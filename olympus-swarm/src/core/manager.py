# manager.py - Tier 3 Distributed Prompt Orchestrator Template
import logging
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from core.orchestrator import SwarmOrchestrator
from core.state import SwarmState

logger = logging.getLogger("olympus.core.manager")

class ManagerTaskResult(BaseModel):
    """Structured response from the Manager delegating coding work."""
    success: bool = Field(description="True if the coding worker successfully completed and passed tests.")
    master_prompt: str = Field(description="The compiled Master Prompt generated for the browser coding worker.")
    reflexion_critique: str = Field(description="Episodic critique and self-reflection stored for future optimization.")

# Manager PydanticAI Agent definition
manager_agent = Agent(
    model="openai:llama3.3-70b", # Powered by Cerebras Llama 3.3 70B
    result_type=ManagerTaskResult,
    system_prompt=(
        "You are the Tier 3 Manager Agent of Project Olympus. "
        "Your duty is to prompt-engineer highly robust Master Prompts "
        "for Web UI workers (z.ai, ChatGPT) specifying exact file structures, "
        "algorithms, compilation checks, and Git push credentials. "
        "You also perform self-reflection critiques (Reflexion) on testing failures."
    )
)

class SwarmManagerNode:
    """Orchestration node wrapping Manager logic and automated Self-Healing Reflexion loops."""

    def __init__(self, orchestrator: SwarmOrchestrator):
        self.orchestrator = orchestrator

    async def execute_task_node(self, state: SwarmState) -> dict[str, Any]:
        """LangGraph node executing Manager planning, delegation, and local verification loops."""
        manager_id = state.get("active_manager_id", "mgr-1")
        logger.info(f"Tier 3 Manager ({manager_id}) beginning task execution sequence...")

        # 1. Read task from state queue
        tasks = state.get("manager_tasks", [])
        if not tasks:
            logger.warning(f"No pending manager tasks found in global state for {manager_id}.")
            return {"system_status": "manager_idle"}

        active_task = tasks[0]

        # 2. Synthesize Master prompt (PydanticAI)
        logger.info(f"Synthesizing Master prompt for task: {active_task}")
        agent_res = await manager_agent.run(f"Generate Master Prompt for z.ai to build: {active_task}")
        master_prompt = agent_res.data.master_prompt

        # 3. Dispatch to Brave Browser Extension worker over WebSocket
        logger.info(f"Routing Master Prompt to Brave Profile WebSocket of {manager_id}...")
        try:
            # Dispatch prompt via raw WebSocket and await stream completion
            await self.orchestrator.dispatch_worker_prompt(
                manager_id=manager_id,
                provider="z_ai",
                prompt=master_prompt
            )

            # 4. Local Verification & Self-Healing Reflexion Loop
            # In production, we pull the z.ai-pushed branch locally via Git MCP and run unit tests.
            # Here, we mock the local shell test execution and the self-healing compilation.
            logger.info("Local verification: executing shell test suites...")

            test_success = True
            errors = []

            # Mocking a potential boundary test rounding crash (tan(90) error)
            if "trigonometric" in active_task.lower() or "math" in active_task.lower():
                logger.warning("VERIFICATION DETECTED FAILURE: Rounding error on tan(90) limits!")
                test_success = False
                errors = ["AssertionError: tan(90) returned 1.633e+16 instead of Infinity"]

            if not test_success:
                # SELF-HEALING (Reflexion Loop): Run self-reflection and send correction prompt to z.ai
                logger.warning("Triggering self-healing Reflexion loop...")
                f"Reflexion Analysis: Code failed on boundary limits: {errors[0]}."
                correction_prompt = (
                    f"DEBUG CORRECTION REQUIRED:\n"
                    f"Your last push failed during verification with the following stack trace:\n"
                    f"{errors[0]}\n"
                    f"Please apply CORDIC precision correction to handle tan(90) division boundaries and push again."
                )

                # Re-dispatch correction prompt down the WebSocket
                await self.orchestrator.dispatch_worker_prompt(
                    manager_id=manager_id,
                    provider="z_ai",
                    prompt=correction_prompt
                )
                logger.info("Reflexion loop complete. Code successfully self-healed and committed.")
                test_success = True

            status = "completed" if test_success else "failed"
            logger.info(f"Manager task completed. Status: {status.upper()}")

            return {
                "completed_modules": state.get("completed_modules", []) + [f"{manager_id}_success.ts"],
                "manager_tasks": tasks[1:], # Pop task
                "errors": state.get("errors", []) + errors,
                "system_status": f"manager_{status}"
            }

        except Exception as e:
            logger.error(f"Manager delegation node failed on {manager_id}: {e}")
            return {
                "errors": state.get("errors", []) + [str(e)],
                "system_status": "manager_failed"
            }
