"""
Nancy — Task Queue.

Manages the lifecycle of tasks using ``asyncio.Queue`` for the pending
work queue and a dict of ``TaskHandle`` objects for in-flight coordination.

The queue bridges two sides:
  - **API side** (producer): creates a task, enqueues it, waits for chunks.
  - **Extension side** (consumer): dequeues tasks via SSE, pushes response chunks.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import AsyncIterator

from config import settings
from models.task import Task, TaskHandle, TaskStatus

logger = logging.getLogger("nancy.queue")


class TaskQueue:
    """
    Central task queue and handle registry.

    This is a singleton that coordinates between the API router
    (which creates tasks) and the extension router (which fulfills them).

    Attributes:
        _pending: asyncio.Queue of Task objects waiting for an extension.
        _handles: dict mapping ``task_id`` → ``TaskHandle`` for in-flight tasks.
        _history: bounded list of recently completed task summaries.
    """

    def __init__(self, max_size: int | None = None) -> None:
        self._max_size = max_size or settings.task_queue_max_size
        self._pending: asyncio.Queue[Task] = asyncio.Queue(maxsize=self._max_size)
        self._handles: dict[str, TaskHandle] = {}
        self._history: list[dict] = []
        self._max_history = 100
        # Event fired whenever a new task is enqueued — used to wake the
        # extension SSE stream.
        self._new_task_event = asyncio.Event()

    # ── API-side operations ───────────────────────────────────────────

    async def submit_task(self, task: Task) -> TaskHandle:
        """
        Submit a new task and return its handle.

        The handle's ``chunk_queue`` and ``done_event`` are used by the
        API router to stream chunks back to the caller.

        Raises:
            asyncio.QueueFull: If the pending queue is at capacity.
        """
        handle = TaskHandle(task)
        self._handles[task.task_id] = handle

        try:
            self._pending.put_nowait(task)
        except asyncio.QueueFull:
            # Clean up the handle
            self._handles.pop(task.task_id, None)
            logger.error("Task queue full — rejecting task %s", task.task_id)
            raise

        self._new_task_event.set()
        logger.info(
            "Task %s submitted (provider=%s, model=%s, queue_size=%d)",
            task.task_id,
            task.provider,
            task.model,
            self._pending.qsize(),
        )
        return handle

    def get_handle(self, task_id: str) -> TaskHandle | None:
        """Retrieve a handle by task ID, or None if not found."""
        return self._handles.get(task_id)

    async def wait_for_completion(
        self,
        handle: TaskHandle,
        timeout: float | None = None,
    ) -> None:
        """
        Block until the task is done or timeout expires.

        This is used for *non-streaming* requests that need the full response.

        Raises:
            asyncio.TimeoutError: If the task does not complete in time.
        """
        timeout = timeout or settings.task_timeout_seconds
        try:
            await asyncio.wait_for(handle.done_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            handle.task.status = TaskStatus.TIMED_OUT
            handle.task.error = f"Task timed out after {timeout}s"
            handle.finish(error=handle.task.error)
            raise

    async def stream_chunks(
        self,
        handle: TaskHandle,
        timeout: float | None = None,
    ) -> AsyncIterator[str]:
        """
        Async generator that yields text chunks from the extension.

        Yields chunks until a ``None`` sentinel is received (end of stream)
        or the timeout expires.
        """
        timeout = timeout or settings.task_timeout_seconds
        deadline = time.time() + timeout

        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                handle.task.status = TaskStatus.TIMED_OUT
                handle.task.error = "Streaming timed out"
                logger.warning("Task %s stream timed out", handle.task_id)
                break

            try:
                chunk = await asyncio.wait_for(
                    handle.chunk_queue.get(),
                    timeout=min(remaining, 30.0),
                )
            except asyncio.TimeoutError:
                # Check if there's still time left
                if time.time() >= deadline:
                    handle.task.status = TaskStatus.TIMED_OUT
                    handle.task.error = "Streaming timed out"
                    logger.warning("Task %s stream timed out", handle.task_id)
                    break
                continue

            if chunk is None:
                # End-of-stream sentinel
                break

            yield chunk

    # ── Extension-side operations ─────────────────────────────────────

    async def dequeue_task(self, timeout: float = 30.0) -> Task | None:
        """
        Dequeue the next pending task.

        Returns ``None`` if no task is available within ``timeout`` seconds.
        Used by the extension SSE stream.
        """
        try:
            task = await asyncio.wait_for(self._pending.get(), timeout=timeout)
            task.status = TaskStatus.ASSIGNED
            task.assigned_at = time.time()
            logger.info("Task %s dequeued (provider=%s)", task.task_id, task.provider)
            return task
        except asyncio.TimeoutError:
            return None

    def push_chunk(self, task_id: str, chunk: str) -> bool:
        """
        Push a response chunk for a task. Returns False if task not found.
        """
        handle = self._handles.get(task_id)
        if not handle:
            logger.warning("Chunk received for unknown task %s", task_id)
            return False
        if handle.task.status == TaskStatus.ASSIGNED:
            handle.task.status = TaskStatus.STREAMING
        handle.push_chunk(chunk)
        return True

    def complete_task(self, task_id: str, error: str | None = None) -> bool:
        """
        Mark a task as complete. Returns False if task not found.
        """
        handle = self._handles.get(task_id)
        if not handle:
            logger.warning("Completion signal for unknown task %s", task_id)
            return False
        handle.finish(error=error)

        # Archive to history
        self._history.append(handle.task.to_status_dict())
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        logger.info(
            "Task %s completed (status=%s, error=%s)",
            task_id,
            handle.task.status.value,
            error,
        )
        return True

    def cleanup_task(self, task_id: str) -> None:
        """Remove a task handle from the registry."""
        self._handles.pop(task_id, None)

    # ── Observability ─────────────────────────────────────────────────

    @property
    def pending_count(self) -> int:
        """Number of tasks waiting in the queue."""
        return self._pending.qsize()

    @property
    def active_count(self) -> int:
        """Number of in-flight task handles."""
        return len(self._handles)

    @property
    def new_task_event(self) -> asyncio.Event:
        """Event that fires when a new task is enqueued."""
        return self._new_task_event

    def get_status(self) -> dict:
        """Return queue status for health endpoints."""
        return {
            "pending": self.pending_count,
            "active": self.active_count,
            "max_size": self._max_size,
            "recent_history": len(self._history),
        }

    def get_active_tasks(self) -> list[dict]:
        """Return status dicts for all active tasks."""
        return [h.task.to_status_dict() for h in self._handles.values()]

    def get_history(self, limit: int = 20) -> list[dict]:
        """Return recent task history."""
        return self._history[-limit:]

    def is_extension_active(self) -> bool:
        """Check if there is at least one active extension connection."""
        try:
            from routers.extension import active_extensions
            now = time.time()
            return any((now - last_seen) < 45.0 for last_seen in active_extensions.values())
        except Exception:
            return False


# Module-level singleton
task_queue = TaskQueue()

