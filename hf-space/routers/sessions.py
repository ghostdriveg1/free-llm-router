"""
Nancy HF Space — Session REST API Router.

Provides session management endpoints so agents can:
  - Create new tracked conversation sessions
  - List all sessions (optionally filtered by provider)
  - Get a specific session's state
  - Delete / archive sessions
  - Update a session's conversation URL (called internally after task completion)
"""

from __future__ import annotations

import logging
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from core.auth import require_api_key
from core.sessions import session_store

logger = logging.getLogger("nancy.sessions_router")

router = APIRouter(prefix="/v1/sessions", tags=["Session Management"])


# ── Request / Response Schemas ────────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    """Request body for creating a new conversation session."""
    provider: str = Field(
        ...,
        description="Target provider key (e.g. 'chatgpt', 'gemini', 'nim'). "
                    "Determines which browser tab / official API to use."
    )
    title: str | None = Field(
        default=None,
        description="Optional human-readable title for this session."
    )
    system_prompt: str | None = Field(
        default=None,
        description="Optional system prompt to prepend when starting a new chat."
    )


class UpdateSessionURLRequest(BaseModel):
    """Internal: update a session's conversation URL after a chat."""
    conversation_url: str = Field(
        ...,
        description="The browser tab URL for the active conversation (e.g. chatgpt.com/c/abc123)."
    )
    message_count_delta: int = Field(
        default=1,
        description="How many messages to add to the running total."
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_session(
    body: CreateSessionRequest,
    api_key: str = Depends(require_api_key),
) -> dict[str, Any]:
    """
    Create a new conversation session.

    Returns the session_id and metadata. Use this session_id in subsequent
    chat completion requests (as the `user` field or via custom header) to
    automatically resume the same conversation tab.
    """
    session = await session_store.create_session(
        provider=body.provider,
        title=body.title,
        system_prompt=body.system_prompt,
    )
    logger.info("Created session '%s' for provider '%s'", session.session_id[:8], body.provider)
    return {
        "session_id": session.session_id,
        "message": f"Session created for provider '{body.provider}'.",
        "session": session.to_dict(),
    }


@router.get("")
async def list_sessions(
    provider: str | None = Query(default=None, description="Filter by provider key."),
    api_key: str = Depends(require_api_key),
) -> dict[str, Any]:
    """
    List all tracked sessions, optionally filtered by provider.
    Sessions are sorted by last_used_at (most recent first).
    """
    sessions = await session_store.list_sessions(provider=provider)
    return {
        "total": len(sessions),
        "sessions": [s.to_dict() for s in sessions],
    }


@router.get("/{session_id}")
async def get_session(
    session_id: str,
    api_key: str = Depends(require_api_key),
) -> dict[str, Any]:
    """
    Retrieve a specific session by its ID.
    """
    session = await session_store.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found.",
        )
    return session.to_dict()


@router.patch("/{session_id}/url")
async def update_session_url(
    session_id: str,
    body: UpdateSessionURLRequest,
    api_key: str = Depends(require_api_key),
) -> dict[str, Any]:
    """
    Update a session's conversation URL.

    Called after a task completes to record the browser URL for the conversation,
    enabling future resume operations.
    """
    session = await session_store.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found.",
        )
    await session_store.update_session_url(
        session_id=session_id,
        conversation_url=body.conversation_url,
        message_count_delta=body.message_count_delta,
    )
    updated = await session_store.get_session(session_id)
    return {
        "message": "Session URL updated.",
        "session": updated.to_dict() if updated else {},
    }


@router.delete("/{session_id}", status_code=status.HTTP_200_OK)
async def delete_session(
    session_id: str,
    api_key: str = Depends(require_api_key),
) -> dict[str, Any]:
    """
    Archive / soft-delete a session.
    The session record is kept but marked as archived and excluded from list results.
    """
    deleted = await session_store.delete_session(session_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found.",
        )
    return {"message": f"Session '{session_id[:8]}...' archived successfully."}
