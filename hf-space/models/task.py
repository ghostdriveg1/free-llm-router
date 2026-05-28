"""
Nancy — Task models.

A *task* is the unit of work that flows through the system:
  1. API receives a chat completion request → creates a Task
  2. Task enters the queue → extension picks it up via SSE
  3. Extension sends response chunks back → routed to the waiting API caller
"""

from __future__ import annotations

import asyncio
import time
import uuid
try:
    from enum import StrEnum
except ImportError:
    import enum
    class StrEnum(str, enum.Enum):
        pass
from typing import Any

from pydantic import BaseModel, Field


class TaskStatus(StrEnum):
    """Lifecycle states of a task."""

    PENDING = "pending"
    ASSIGNED = "assigned"
    STREAMING = "streaming"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class Task(BaseModel):
    """
    Represents a single chat completion request flowing through the relay.

    The ``completion_id`` is the OpenAI-format ``chatcmpl-*`` ID that will be
    used across all SSE chunks for this task.
    """

    task_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    completion_id: str = Field(
        default_factory=lambda: f"chatcmpl-{uuid.uuid4().hex[:29]}"
    )
    provider: str = Field(..., description="Target provider, e.g. 'chatgpt'.")
    model: str = Field(..., description="Original model name from the request.")
    messages: list[dict[str, Any]] = Field(
        ..., description="Chat messages to send to the provider."
    )
    temperature: float | None = None
    max_tokens: int | None = None
    stream: bool = True
    status: TaskStatus = TaskStatus.PENDING
    created_at: float = Field(default_factory=time.time)
    assigned_at: float | None = None
    completed_at: float | None = None
    error: str | None = None

    # ── Session-aware routing fields ──────────────────────────────────
    session_id: str | None = Field(
        default=None,
        description="Optional session ID for conversation tracking."
    )
    conversation_url: str | None = Field(
        default=None,
        description="URL to navigate to when resuming a session (e.g. chatgpt.com/c/<id>)."
    )
    action: str = Field(
        default="continue",
        description="'new_chat' = open fresh conversation, 'resume_chat' = navigate to URL, 'continue' = send to current tab."
    )

    # These fields are NOT serialized — they are runtime-only handles.
    model_config = {"arbitrary_types_allowed": True}

    def to_extension_payload(self) -> dict[str, Any]:
        """
        Serialize the task for delivery to the Chrome extension via SSE.

        Includes session navigation fields so the extension knows whether to
        open a new chat, resume a specific conversation, or continue in the current tab.
        """
        return {
            "task_id": self.task_id,
            "provider": self.provider,
            "model": self.model,
            "messages": self.messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            # Session navigation
            "session_id": self.session_id,
            "conversation_url": self.conversation_url,
            "action": self.action,
        }

    def to_status_dict(self) -> dict[str, Any]:
        """Compact status representation for health / debug endpoints."""
        return {
            "task_id": self.task_id,
            "provider": self.provider,
            "model": self.model,
            "status": self.status.value,
            "created_at": self.created_at,
            "assigned_at": self.assigned_at,
            "completed_at": self.completed_at,
            "error": self.error,
        }


class TaskHandle:
    """
    Runtime handle for an in-flight task.

    Bundles the ``Task`` data model with the asyncio primitives needed
    to coordinate between the API caller and the extension relay.

    Attributes:
        task: The Task data model.
        chunk_queue: Queue where the extension pushes response chunks.
        done_event: Event set when the extension signals completion.
    """

    __slots__ = ("task", "chunk_queue", "done_event", "created_at")

    def __init__(self, task: Task) -> None:
        self.task = task
        self.chunk_queue: asyncio.Queue[str | None] = asyncio.Queue()
        self.done_event = asyncio.Event()
        self.created_at = time.time()

    @property
    def task_id(self) -> str:
        return self.task.task_id

    def push_chunk(self, chunk: str) -> None:
        """
        Enqueue a text chunk from the extension.

        A ``None`` sentinel signals end-of-stream.
        """
        self.chunk_queue.put_nowait(chunk)

    def finish(self, error: str | None = None) -> None:
        """
        Mark the task as done.

        Pushes a ``None`` sentinel into the chunk queue and sets the
        done event so the API handler can stop waiting.
        """
        if error:
            self.task.status = TaskStatus.FAILED
            self.task.error = error
        else:
            self.task.status = TaskStatus.COMPLETED
        self.task.completed_at = time.time()
        self.chunk_queue.put_nowait(None)  # sentinel
        self.done_event.set()


class ExtensionResponseChunk(BaseModel):
    """
    Payload sent by the Chrome extension via ``POST /ext/response``.
    """

    task_id: str = Field(..., description="ID of the task this chunk belongs to.")
    chunk: str = Field(default="", description="Text fragment (may be empty on final).")
    is_done: bool = Field(
        default=False, description="True on the final chunk."
    )
    error: str | None = Field(
        default=None, description="Error message if the extension failed."
    )
    # Session URL reporting: extension reports back the current tab URL after task completes
    conversation_url: str | None = Field(
        default=None,
        description="Current browser tab URL after task completes. Used to update session records."
    )


class ExtensionHeartbeat(BaseModel):
    """
    Payload sent by the Chrome extension via ``POST /ext/heartbeat``.
    """

    extension_id: str = Field(
        default="default",
        description="Unique extension instance identifier.",
    )
    timestamp: float = Field(
        default_factory=time.time,
        description="Client-side UTC Unix timestamp.",
    )
    active_tasks: list[str] = Field(
        default_factory=list,
        description="Task IDs currently being processed by this extension.",
    )
