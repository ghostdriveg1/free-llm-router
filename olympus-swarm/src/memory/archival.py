# archival.py - Xata Postgres Archival & Semantic Memory Client
import logging
from typing import Any

import asyncpg
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger("olympus.memory.archival")

class ArchivalMemory:
    """Async Xata Postgres client utilizing PgBouncer and pgvector for unified storage."""

    def __init__(self, dsn: str):
        self.dsn = dsn
        self.pool: asyncpg.Pool | None = None
        if self.dsn:
            logger.info("Xata Postgres Archival client configuration stored.")
        else:
            logger.warning("Xata DSN missing. Archival memory disabled.")

    async def initialize(self) -> None:
        """Initializes the database connection pool with pre-ping health checks."""
        if not self.dsn:
            return

        try:
            self.pool = await asyncpg.create_pool(
                self.dsn,
                min_size=1,
                max_size=5,
                command_timeout=10.0,
                server_settings={"statement_timeout": "10000"}  # 10s
            )
            logger.info("Xata Postgres connection pool successfully created.")
        except Exception as e:
            logger.critical(f"Failed to create Xata Postgres connection pool: {e}")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def _get_connection(self) -> asyncpg.Connection:
        """Acquires a connection from pool and runs a pre-ping health check."""
        if not self.pool:
            raise ConnectionError("Connection pool is not initialized.")
        conn = await self.pool.acquire()
        try:
            await conn.execute("SELECT 1")
            return conn
        except Exception as e:
            await self.pool.release(conn)
            logger.warning(f"Connection pre-ping failed, retrying: {e}")
            raise

    async def execute(self, query: str, *args: Any) -> str:
        """Executes an SQL command (INSERT, UPDATE, DELETE)."""
        if not self.pool:
            return ""
        conn = await self._get_connection()
        try:
            return await conn.execute(query, *args)
        finally:
            await self.pool.release(conn)

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        """Fetches multiple rows from the database."""
        if not self.pool:
            return []
        conn = await self._get_connection()
        try:
            records = await conn.fetch(query, *args)
            return [dict(r) for r in records]
        finally:
            await self.pool.release(conn)

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        """Fetches a single row from the database."""
        if not self.pool:
            return None
        conn = await self._get_connection()
        try:
            record = await conn.fetchrow(query, *args)
            return dict(record) if record else None
        finally:
            await self.pool.release(conn)

    async def save_ledger_entry(self, milestone_id: str, phase: str, author: str, entry: str) -> bool:
        """Writes an entry to the append-only global project ledger (Senator's ledger)."""
        query = """
        INSERT INTO global_project_ledger (milestone_id, phase, author, ledger_entry)
        VALUES ($1, $2, $3, $4)
        """
        try:
            await self.execute(query, milestone_id, phase, author, entry)
            logger.info("Ledger entry committed successfully to Xata.")
            return True
        except Exception as e:
            logger.error(f"Failed to commit ledger entry: {e}")
            return False

    async def save_embedding(self, collection: str, key_signature: str, content: str, vector: list[float]) -> bool:
        """Stores a semantic memory vector embedding (pgvector) in Xata."""
        query = """
        INSERT INTO semantic_memory (collection, key_signature, content, embedding)
        VALUES ($1, $2, $3, $4)
        """
        try:
            await self.execute(query, collection, key_signature, content, vector)
            logger.info(f"Vector embedding stored successfully in collection {collection}.")
            return True
        except Exception as e:
            logger.error(f"Failed to store vector embedding: {e}")
            return False

    async def search_semantic_memory(self, collection: str, vector: list[float], limit: int = 3) -> list[dict[str, Any]]:
        """Queries pgvector semantic embeddings based on cosine distance similarity."""
        query = """
        SELECT id, key_signature, content, 1 - (embedding <=> $1) as similarity
        FROM semantic_memory
        WHERE collection = $2
        ORDER BY embedding <=> $1
        LIMIT $3
        """
        try:
            return await self.fetch(query, vector, collection, limit)
        except Exception as e:
            logger.error(f"Semantic vector search failed: {e}")
            return []

    async def shutdown(self) -> None:
        """Closes the connection pool gracefully on app termination."""
        if self.pool:
            await self.pool.close()
            logger.info("Xata Postgres connection pool terminated gracefully.")
