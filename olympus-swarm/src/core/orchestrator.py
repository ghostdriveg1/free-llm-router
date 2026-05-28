# orchestrator.py - Central System Loop & Swarm State Machine
import asyncio
import json
import logging

from fastapi import WebSocket, WebSocketDisconnect

from memory.working import WorkingMemory

logger = logging.getLogger("olympus.core.orchestrator")

class SwarmOrchestrator:
    """Manages the perpetual event loop, Brave WebSocket routing, and Day/Night shifts."""

    def __init__(self, working_memory: WorkingMemory):
        self.working_memory = working_memory
        self.connected_profiles: dict[str, WebSocket] = {}
        self.swarm_mode = "LEGIT_API_STANDBY"
        self.concurrency_semaphore = asyncio.Semaphore(5)  # Default Balanced
        self._lock = asyncio.Lock()

    async def register_profile(self, manager_id: str, websocket: WebSocket) -> None:
        """Registers an active Brave profile WebSocket connection and handles state acceleration."""
        async with self._lock:
            self.connected_profiles[manager_id] = websocket
            logger.info(f"Brave Profile registered for {manager_id}. WebSocket connected.")

            # Day acceleration trigger: ULTRON_MAX
            if len(self.connected_profiles) > 0 and self.swarm_mode == "LEGIT_API_STANDBY":
                self.swarm_mode = "ULTRON_MAX"
                await self.working_memory.set("swarm:state:mode", "ULTRON_MAX")
                logger.info("STATE MACHINE CHANGE: Connected Brave profiles detected. Entering day shift [ULTRON_MAX]!")

    async def unregister_profile(self, manager_id: str) -> None:
        """Unregisters Brave profile WebSocket and handles standby deceleration."""
        async with self._lock:
            if manager_id in self.connected_profiles:
                del self.connected_profiles[manager_id]
                logger.info(f"Brave Profile {manager_id} unregistered.")

            # Night shift standby trigger: LEGIT_API_STANDBY
            if len(self.connected_profiles) == 0 and self.swarm_mode == "ULTRON_MAX":
                self.swarm_mode = "LEGIT_API_STANDBY"
                await self.working_memory.set("swarm:state:mode", "LEGIT_API_STANDBY")
                logger.info("STATE MACHINE CHANGE: All profiles disconnected. Entering night shift [LEGIT_API_STANDBY]!")

    async def update_concurrency_limit(self, limit_type: str) -> None:
        """Dynamically adjusts the concurrency slider limit (Eco, Balanced, Quantum)."""
        limit_mappings = {
            "eco": 2,
            "balanced": 5,
            "quantum": 10
        }
        limit_val = limit_mappings.get(limit_type.lower(), 5)
        async with self._lock:
            self.concurrency_semaphore = asyncio.Semaphore(limit_val)
            await self.working_memory.set("swarm:concurrency:limit", str(limit_val))
            logger.info(f"Swarm concurrency adjusted to: {limit_type.upper()} (Max {limit_val} parallel managers).")

    async def dispatch_worker_prompt(self, manager_id: str, provider: str, prompt: str) -> str:
        """Acquires a concurrency slot and routes a prompt down the active WebSocket client."""
        # Dynamic hardware load throttle slider
        async with self.concurrency_semaphore:
            if manager_id not in self.connected_profiles:
                raise ConnectionError(f"No active Brave WebSocket connection available for {manager_id}")

            ws = self.connected_profiles[manager_id]
            tx_id = f"tx_{int(asyncio.get_event_loop().time())}"

            payload = {
                "event": "dispatch_prompt",
                "transaction_id": tx_id,
                "provider": provider,
                "prompt": prompt
            }

            await ws.send_text(json.dumps(payload))
            logger.info(f"Dispatched prompt down Brave Profile WS for transaction: {tx_id} | Provider: {provider}")

            # Wait loop for streamed result completion
            try:
                async for message in ws:
                    data = json.loads(message)
                    if data.get("transaction_id") == tx_id:
                        if data.get("event") == "stream_chunk" and data.get("status") == "completed":
                            logger.info(f"Transaction completed successfully: {tx_id}")
                            return str(data.get("chunk", ""))
                        elif data.get("event") == "error":
                            raise RuntimeError(f"Brave UI extension execution error: {data.get('error')}")
            except WebSocketDisconnect:
                logger.error(f"WebSocket disconnected during transaction: {tx_id}")
                raise ConnectionError(f"Brave Profile {manager_id} connection lost.")
            return ""
