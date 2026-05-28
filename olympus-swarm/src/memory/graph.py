# graph.py - Neo4j Aura Knowledge Graph Client
import logging
from typing import Any

from neo4j import GraphDatabase

logger = logging.getLogger("olympus.memory.graph")

class KnowledgeGraph:
    """Async Neo4j Aura client handling agent-module dependency mapping and keep-alive cycles."""

    def __init__(self, uri: str, user: str, secret: str):
        self.uri = uri
        self.user = user
        self.secret = secret
        self.driver: Any = None

        if self.uri and self.user and self.secret:
            try:
                # Initialize modern async driver
                self.driver = GraphDatabase.driver(
                    self.uri,
                    auth=(self.user, self.secret)
                )
                logger.info("Neo4j Aura async driver successfully created.")
            except Exception as e:
                logger.critical(f"Failed to create Neo4j driver: {e}")
        else:
            logger.warning("Neo4j Aura credentials missing. Knowledge Graph disabled.")

    async def execute_query(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Executes a Cypher query asynchronously within a read/write session."""
        if not self.driver:
            return []

        try:
            # Open modern async session
            async with self.driver.session() as session:
                result = await session.run(cypher, params or {})
                records = await result.data()
                return records
        except Exception as e:
            logger.error(f"Neo4j Cypher execution failed: {e} | Query: {cypher}")
            return []

    async def save_dependency(self, agent_id: str, module_name: str, path: str, score: float) -> bool:
        """Stores or merges an agent-to-module dependency node mapping."""
        cypher = """
        MERGE (a:Agent {id: $agent_id})
        ON CREATE SET a.created_at = timestamp()
        MERGE (m:Module {name: $module_name})
        ON CREATE SET m.path = $path, m.created_at = timestamp()
        MERGE (a)-[r:BUILT]->(m)
        SET r.timestamp = timestamp(), r.score = $score
        RETURN a.id, m.name
        """
        params = {
            "agent_id": agent_id,
            "module_name": module_name,
            "path": path,
            "score": score
        }
        res = await self.execute_query(cypher, params)
        if res:
            logger.info(f"Committed graph edge: ({agent_id})-[:BUILT]->({module_name}) in Neo4j.")
            return True
        return False

    async def trigger_keep_alive(self) -> bool:
        """Writes a heartbeat node to prevent Aura free tier pausing (runs every 48 hours)."""
        cypher = """
        MERGE (h:Heartbeat {id: "swarm_keepalive"})
        SET h.last_ping = timestamp()
        RETURN h.last_ping
        """
        res = await self.execute_query(cypher)
        if res:
            logger.info("Neo4j Aura keep-alive heartbeat committed successfully.")
            return True
        return False

    async def shutdown(self) -> None:
        """Closes the async driver connection gracefully on app termination."""
        if self.driver:
            await self.driver.close()
            logger.info("Neo4j Aura driver terminated gracefully.")
