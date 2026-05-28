# board.py - Tier 2 Planning Council Debate Graph
import logging
from typing import Any

from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field
from pydantic_ai import Agent

from core.state import SwarmState

logger = logging.getLogger("olympus.core.board")

# ── 1. Structured Director Response Types ─────────────────────────────────────
class ArchitecturePlan(BaseModel):
    plan: str = Field(description="Architectural folder and class design outline.")

class ResearchFindings(BaseModel):
    findings: str = Field(description="Compatibility and library checkup reports.")

class SecurityReview(BaseModel):
    review: str = Field(description="Audit and circular dependency checks.")

class TestSuiteSpec(BaseModel):
    spec: str = Field(description="Target test scripts and criteria details.")

class IntegratedPlan(BaseModel):
    consensus_uip: str = Field(description="Consensus voted master deployment plan.")
    tasks: list[str] = Field(description="Decomposed task checklist for Tier 3 Managers.")

# ── 2. PydanticAI Director Agent Definitions ───────────────────────────────
architect_agent = Agent("google:gemini-2.5-flash", result_type=ArchitecturePlan, system_prompt="You are Chief Architect.")
researcher_agent = Agent("google:gemini-2.5-flash", result_type=ResearchFindings, system_prompt="You are Chief Researcher.")
reviewer_agent = Agent("google:gemini-2.5-flash", result_type=SecurityReview, system_prompt="You are Chief Reviewer.")
tester_agent = Agent("google:gemini-2.5-flash", result_type=TestSuiteSpec, system_prompt="You are Chief Tester.")
integrator_agent = Agent("google:gemini-2.5-flash", result_type=IntegratedPlan, system_prompt="You are Chief Integrator.")

# ── 3. LangGraph Node Implementations ───────────────────────────────────────
async def architect_node(state: SwarmState) -> dict[str, Any]:
    logger.info("Director 1 (Architect) outlining folder structures...")
    res = await architect_agent.run(f"Design plan for: {state['task_description']}")
    return {"board_resolutions": state.get("board_resolutions", []) + [f"Architect: {res.data.plan}"]}

async def researcher_node(state: SwarmState) -> dict[str, Any]:
    logger.info("Director 3 (Researcher) validating dependencies...")
    prev = "\n".join(state.get("board_resolutions", []))
    res = await researcher_agent.run(f"Research requirements for:\n{prev}")
    return {"board_resolutions": state.get("board_resolutions", []) + [f"Researcher: {res.data.findings}"]}

async def reviewer_node(state: SwarmState) -> dict[str, Any]:
    logger.info("Director 2 (Reviewer) checking circular dependencies...")
    prev = "\n".join(state.get("board_resolutions", []))
    res = await reviewer_agent.run(f"Review code safety for:\n{prev}")
    return {"board_resolutions": state.get("board_resolutions", []) + [f"Reviewer: {res.data.review}"]}

async def tester_node(state: SwarmState) -> dict[str, Any]:
    logger.info("Director 5 (Tester) generating test parameters...")
    prev = "\n".join(state.get("board_resolutions", []))
    res = await tester_agent.run(f"Formulate unit tests for:\n{prev}")
    return {"board_resolutions": state.get("board_resolutions", []) + [f"Tester: {res.data.spec}"]}

async def integrator_node(state: SwarmState) -> dict[str, Any]:
    logger.info("Director 4 (Integrator) integrating master plans...")
    prev = "\n".join(state.get("board_resolutions", []))
    res = await integrator_agent.run(f"Synthesize final UIP & task checklist for:\n{prev}")
    return {
        "board_resolutions": state.get("board_resolutions", []) + [f"Integrator Consensus: {res.data.consensus_uip}"],
        "manager_tasks": res.data.tasks,
        "system_status": "board_planning_complete"
    }

# ── 4. Build and Compile the Council StateGraph ─────────────────────────────
builder = StateGraph(SwarmState)

builder.add_node("architect", architect_node)
builder.add_node("researcher", researcher_node)
builder.add_node("reviewer", reviewer_node)
builder.add_node("tester", tester_node)
builder.add_node("integrator", integrator_node)

builder.set_entry_point("architect")
builder.add_edge("architect", "researcher")
builder.add_edge("researcher", "reviewer")
builder.add_edge("reviewer", "tester")
builder.add_edge("tester", "integrator")
builder.add_edge("integrator", END)

board_debate_graph = builder.compile()
