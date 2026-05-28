# state.py - Global Swarm State Definition
from typing import Any, TypedDict


class SwarmState(TypedDict):
    """The unified global state dictionary mapped across all LangGraph subgraphs."""
    task_id: str
    task_description: str
    milestone_spec: str
    board_resolutions: list[str]
    manager_tasks: list[str]
    completed_modules: list[str]
    active_manager_id: str
    active_profile_id: str
    errors: list[str]
    system_status: str
    metadata: dict[str, Any]
