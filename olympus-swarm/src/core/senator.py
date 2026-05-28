# senator.py - Tier 1 Global Executive Auditor Agent
import logging
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from core.state import SwarmState

logger = logging.getLogger("olympus.core.senator")

class MilestoneAudit(BaseModel):
    """Structured response from the Senator auditing Board plans."""
    approved: bool = Field(description="True if the Board plan meets all safety and architectural requirements.")
    audit_summary: str = Field(description="A detailed summary of the architectural and budget audit results.")
    budget_estimate_usd: float = Field(description="The estimated token financial budget required for the milestone.")

# Senator PydanticAI Agent definition
senator_agent = Agent(
    model="google:gemini-2.5-pro",
    result_type=MilestoneAudit,
    system_prompt=(
        "You are the Tier 1 Senator of Project Olympus. "
        "Your duty is to act as the supreme auditor. Analyze Board planning resolutions "
        "and enforce standard architecture guidelines, strict token budget boundaries, "
        "and security constraints. Reject plans with circular dependencies or excessive risk."
    )
)

async def senator_audit_node(state: SwarmState) -> dict[str, Any]:
    """LangGraph node wrapping the Senator PydanticAI agent's execution."""
    logger.info("Tier 1 Senator auditing the active Board Planning Resolution...")

    # Formulate prompt from state resolutions
    resolutions_text = "\n".join(state.get("board_resolutions", []))
    prompt = (
        f"Audit the following Board planning resolutions for task: {state.get('task_description')}\n"
        f"Resolutions:\n{resolutions_text}"
    )

    try:
        # Run PydanticAI agent
        result = await senator_agent.run(prompt)
        audit_data = result.data

        status = "approved" if audit_data.approved else "rejected"
        ledger_entry = (
            f"Senator Audit: {status.upper()} | Budget: ${audit_data.budget_estimate_usd:.4f} | "
            f"Summary: {audit_data.audit_summary}"
        )

        logger.info(f"Senator audit complete. Status: {status.upper()}")
        return {
            "board_resolutions": state.get("board_resolutions", []) + [ledger_entry],
            "milestone_spec": audit_data.audit_summary if audit_data.approved else "",
            "system_status": f"senator_{status}"
        }
    except Exception as e:
        logger.error(f"Senator audit node failed: {e}")
        return {
            "system_status": "senator_failed"
        }
