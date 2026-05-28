"""
Nancy HF Space — Session Manager.

Manages multi-conversation sessions so agents can:
  - Start fresh conversations (new chat)
  - Resume specific past conversations by navigating to their saved URLs
  - Track conversation URLs per provider and session
  - Persist sessions in Upstash Redis (with in-memory fallback)
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from core.redis_client import redis_client

logger = logging.getLogger("nancy.sessions")

# ── Session Data Structure ─────────────────────────────────────────────────────

class SessionRecord:
    """Represents a tracked conversation session."""

    def __init__(
        self,
        session_id: str,
        provider: str,
        title: str | None = None,
        conversation_url: str | None = None,
        system_prompt: str | None = None,
    ) -> None:
        self.session_id = session_id
        self.provider = provider
        self.title = title or f"Session {session_id[:8]}"
        self.conversation_url = conversation_url
        self.system_prompt = system_prompt
        self.created_at: float = time.time()
        self.last_used_at: float = time.time()
        self.message_count: int = 0
        self.status: str = "active"  # active | archived | error

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for Redis storage and API responses."""
        return {
            "session_id": self.session_id,
            "provider": self.provider,
            "title": self.title,
            "conversation_url": self.conversation_url,
            "system_prompt": self.system_prompt,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
            "message_count": self.message_count,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionRecord":
        """Deserialize from dictionary (from Redis)."""
        session = cls(
            session_id=data["session_id"],
            provider=data["provider"],
            title=data.get("title"),
            conversation_url=data.get("conversation_url"),
            system_prompt=data.get("system_prompt"),
        )
        session.created_at = data.get("created_at", time.time())
        session.last_used_at = data.get("last_used_at", time.time())
        session.message_count = data.get("message_count", 0)
        session.status = data.get("status", "active")
        return session


# ── Session Store ──────────────────────────────────────────────────────────────

class SessionStore:
    """
    Manages conversation sessions.
    Uses Upstash Redis for persistence if available, in-memory dict otherwise.
    """

    REDIS_PREFIX = "nancy:session:"
    REDIS_INDEX_KEY = "nancy:sessions:index"
    SESSION_TTL = 60 * 60 * 24 * 30  # 30 days in seconds

    def __init__(self) -> None:
        # In-memory fallback when Redis is not configured
        self._sessions: dict[str, SessionRecord] = {}

    # ── CRUD ───────────────────────────────────────────────────────────

    async def create_session(
        self,
        provider: str,
        title: str | None = None,
        system_prompt: str | None = None,
    ) -> SessionRecord:
        """
        Create a new session and persist it.

        Args:
            provider: Target provider key (e.g. "chatgpt", "gemini")
            title: Optional human-readable title for the session
            system_prompt: Optional system prompt to prepend in new chat

        Returns:
            The newly created SessionRecord
        """
        session_id = str(uuid.uuid4())
        session = SessionRecord(
            session_id=session_id,
            provider=provider,
            title=title,
            system_prompt=system_prompt,
        )

        await self._save(session)
        logger.info("Created session '%s' for provider '%s'", session_id[:8], provider)
        return session

    async def get_session(self, session_id: str) -> SessionRecord | None:
        """Fetch a session by ID."""
        # Try Redis first
        data = await redis_client.get(f"{self.REDIS_PREFIX}{session_id}")
        if data:
            try:
                import json
                return SessionRecord.from_dict(json.loads(data))
            except Exception as e:
                logger.warning("Failed to deserialize session '%s': %s", session_id[:8], e)

        # Fall back to in-memory
        return self._sessions.get(session_id)

    async def list_sessions(self, provider: str | None = None) -> list[SessionRecord]:
        """
        List all known sessions, optionally filtered by provider.

        Returns sessions sorted by last_used_at descending.
        """
        sessions: list[SessionRecord] = []

        # Try Redis
        if redis_client.is_enabled:
            try:
                import json
                index = await redis_client.get(self.REDIS_INDEX_KEY)
                if index:
                    session_ids: list[str] = json.loads(index)
                    for sid in session_ids:
                        session = await self.get_session(sid)
                        if session and session.status != "archived":
                            sessions.append(session)
            except Exception as e:
                logger.warning("Redis session list failed, using in-memory: %s", e)

        if not sessions:
            sessions = [s for s in self._sessions.values() if s.status != "archived"]

        if provider:
            sessions = [s for s in sessions if s.provider == provider]

        sessions.sort(key=lambda s: s.last_used_at, reverse=True)
        return sessions

    async def update_session_url(
        self,
        session_id: str,
        conversation_url: str,
        message_count_delta: int = 1,
    ) -> None:
        """
        Update a session's conversation URL after a task completes.
        Called by the extension via the server when it reports back the active tab URL.

        Args:
            session_id: The session to update
            conversation_url: The current browser tab URL (e.g. chatgpt.com/c/abc123)
            message_count_delta: How many messages to add to the count
        """
        session = await self.get_session(session_id)
        if not session:
            logger.warning("Cannot update URL: session '%s' not found", session_id[:8])
            return

        session.conversation_url = conversation_url
        session.last_used_at = time.time()
        session.message_count += message_count_delta

        await self._save(session)
        logger.info(
            "Session '%s' URL updated → %s (total messages: %d)",
            session_id[:8], conversation_url, session.message_count
        )

    async def delete_session(self, session_id: str) -> bool:
        """
        Soft-delete (archive) a session.

        Returns True if the session was found and archived.
        """
        session = await self.get_session(session_id)
        if not session:
            return False

        session.status = "archived"
        await self._save(session)
        logger.info("Session '%s' archived", session_id[:8])
        return True

    # ── Internal helpers ───────────────────────────────────────────────

    async def _save(self, session: SessionRecord) -> None:
        """Persist session to Redis and in-memory."""
        import json
        data = json.dumps(session.to_dict())

        # Always keep in-memory
        self._sessions[session.session_id] = session

        # Persist to Redis if available
        if redis_client.is_enabled:
            try:
                await redis_client.set(
                    f"{self.REDIS_PREFIX}{session.session_id}",
                    data,
                    ex=self.SESSION_TTL,
                )
                # Update the index
                index_data = await redis_client.get(self.REDIS_INDEX_KEY)
                session_ids: list[str] = json.loads(index_data) if index_data else []
                if session.session_id not in session_ids:
                    session_ids.append(session.session_id)
                    await redis_client.set(
                        self.REDIS_INDEX_KEY,
                        json.dumps(session_ids),
                        ex=self.SESSION_TTL,
                    )
            except Exception as e:
                logger.warning("Failed to persist session to Redis: %s", e)


# Module-level singleton
session_store = SessionStore()
