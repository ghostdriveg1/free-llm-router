"""
Nancy HF Space — Extension Relay Router.

Exposes endpoints for the Chrome extension:
  - GET /ext/tasks/stream (SSE) — Extension receives new task assignments
  - POST /ext/heartbeat — Extension reports health and active tasks
  - POST /ext/response — Extension streams chunks and signals completion / error
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import AsyncGenerator
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sse_starlette.sse import EventSourceResponse

from config import settings
from core.auth import require_ext_secret
from core.queue import task_queue
from core.router import provider_router
from core.sessions import session_store
from models.task import ExtensionHeartbeat, ExtensionResponseChunk

logger = logging.getLogger("nancy.extension")

router = APIRouter(prefix="/ext", tags=["Extension Relay"])

# Global dictionary to track connected extension instances: extension_id -> last_seen_timestamp
active_extensions: dict[str, float] = {}


@router.get("/tasks/stream")
async def tasks_stream(
    request: Request,
    secret: str = Depends(require_ext_secret),
):
    """
    Server-Sent Events (SSE) stream for Chrome Extensions.
    Delivers task assignments to connected extensions.
    """
    extension_id = request.query_params.get("extension_id", "default")
    active_extensions[extension_id] = time.time()
    logger.info("Extension client '%s' connected to task stream", extension_id)

    async def event_generator() -> AsyncGenerator[dict, None]:
        try:
            while True:
                # Disconnect check
                if await request.is_disconnected():
                    logger.info("Extension client '%s' disconnected from stream", extension_id)
                    break

                # Update heartbeat timestamp
                active_extensions[extension_id] = time.time()

                # Dequeue a task. We use a 15-second timeout so we can yield a ping if idle.
                task = await task_queue.dequeue_task(timeout=15.0)
                if task:
                    logger.info("Relaying task %s to extension '%s'", task.task_id, extension_id)
                    yield {
                        "event": "task",
                        "data": json.dumps(task.to_extension_payload()),
                        "id": task.task_id,
                    }
                else:
                    # Keep-alive SSE ping
                    yield {
                        "event": "ping",
                        "data": "keep-alive",
                    }
        except asyncio.CancelledError:
            logger.info("Extension client '%s' stream cancelled", extension_id)
        finally:
            active_extensions.pop(extension_id, None)

    return EventSourceResponse(event_generator())


@router.post("/heartbeat")
async def heartbeat(
    payload: ExtensionHeartbeat,
    secret: str = Depends(require_ext_secret),
):
    """
    Extension health check. Pinned every 25s by active extension instances.
    """
    active_extensions[payload.extension_id] = time.time()
    logger.debug(
        "Extension '%s' heartbeat received (active_tasks=%d)",
        payload.extension_id,
        len(payload.active_tasks),
    )
    return {"status": "ok", "timestamp": time.time()}


@router.post("/response")
async def receive_response(
    payload: ExtensionResponseChunk,
    secret: str = Depends(require_ext_secret),
):
    """
    Receive streaming response chunks and completion/error notifications from Chrome Extension.
    """
    task_id = payload.task_id
    handle = task_queue.get_handle(task_id)

    if not handle:
        logger.warning("Received chunk/completion for unknown task %s", task_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found or expired.",
        )

    # 1. Handle error reported by the extension
    if payload.error:
        logger.error("Extension reported failure for task %s: %s", task_id, payload.error)
        task_queue.complete_task(task_id, error=payload.error)
        provider_router.record_failure(handle.task.provider)
        return {"status": "error_registered"}

    # 2. Push text chunk if present
    if payload.chunk:
        task_queue.push_chunk(task_id, payload.chunk)

    # 3. Handle final chunk/completion signal
    if payload.is_done:
        logger.info("Extension completed task %s successfully", task_id)
        task_queue.complete_task(task_id, error=None)
        provider_router.record_success(handle.task.provider)

        # 4. Auto-update session URL if extension reported back the conversation URL
        if payload.conversation_url and handle.task.session_id:
            try:
                await session_store.update_session_url(
                    session_id=handle.task.session_id,
                    conversation_url=payload.conversation_url,
                    message_count_delta=1,
                )
                logger.info(
                    "Session '%s' URL updated to '%s'",
                    handle.task.session_id[:8],
                    payload.conversation_url,
                )
            except Exception as e:
                logger.warning("Failed to update session URL: %s", e)

    return {"status": "accepted"}
