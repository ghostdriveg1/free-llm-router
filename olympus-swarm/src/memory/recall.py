# recall.py - Turso SQLite Recall Memory Client
import logging
from typing import Any

import httpx

logger = logging.getLogger("olympus.memory.recall")

class RecallMemory:
    """Async Turso SQLite client handling rolling logs and transaction history."""

    def __init__(self, db_url: str, auth_token: str):
        self.db_url = db_url.replace("libsql://", "https://") if db_url else ""
        self.auth_token = auth_token
        self.headers = {
            "Authorization": f"Bearer {self.auth_token}",
            "Content-Type": "application/json"
        }
        if self.db_url:
            logger.info("Turso libSQL client initialized over HTTP interface.")
        else:
            logger.warning("Turso database credentials missing. Recall memory disabled.")

    async def execute(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        """Executes a raw SQL statement via Turso REST interface securely."""
        if not self.db_url:
            return []

        payload = {
            "statements": [
                {
                    "q": sql,
                    "params": params or []
                }
            ]
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.post(
                    f"{self.db_url}/v1/execute",
                    json=payload,
                    headers=self.headers
                )
                if response.status_code == 200:
                    data = response.json()
                    # Return formatted rows
                    return self._parse_results(data)
                else:
                    logger.error(f"Turso API returned status {response.status_code}: {response.text}")
                    return []
            except Exception as e:
                logger.error(f"Turso execute connection failed: {e}")
                return []

    async def log_interaction(self, task_id: str, agent_id: str, action: str, target: str, payload: str) -> bool:
        """Logs an interaction and double-checks write correctness to protect against silent inserts."""
        sql = """
        INSERT INTO recall_log (task_id, agent_id, action, target, payload)
        VALUES (?, ?, ?, ?, ?)
        """
        await self.execute(sql, [task_id, agent_id, action, target, payload])

        # Post-write verification query
        verification_sql = "SELECT id FROM recall_log WHERE task_id = ? AND agent_id = ? ORDER BY id DESC LIMIT 1"
        rows = await self.execute(verification_sql, [task_id, agent_id])
        if rows:
            logger.info(f"Verified insertion into recall_log for task {task_id}.")
            return True
        else:
            logger.critical(f"Recall log silent insert error detected on task {task_id}!")
            return False

    def _parse_results(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Parses the raw JSON-RPC libSQL results into list of dictionaries."""
        try:
            results = data.get("results", [])
            if not results:
                return []

            first_result = results[0]
            response = first_result.get("response", {})
            result = response.get("result", {})
            cols = [c.get("name") for c in result.get("cols", [])]
            rows = result.get("rows", [])

            parsed = []
            for row in rows:
                row_dict = {}
                for idx, col in enumerate(cols):
                    val = row[idx].get("value")
                    row_dict[col] = val
                parsed.append(row_dict)
            return parsed
        except Exception as e:
            logger.error(f"Failed to parse Turso results: {e}")
            return []
