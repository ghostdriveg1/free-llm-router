"""
Nancy HF Space — Health & Status Router.

Provides health checks and detailed status monitoring endpoints for system observability.
"""

from __future__ import annotations

import time
from fastapi import APIRouter, Depends

from core.auth import require_api_key
from core.queue import task_queue
from core.router import provider_router

router = APIRouter(tags=["Health & Monitoring"])


@router.get("/health")
async def health_check():
    """
    Simple Liveness/Readiness Probe.
    Used by keep-alive cron pings to prevent HF Space sleeping.
    """
    return {
        "status": "healthy",
        "timestamp": time.time(),
    }


@router.get("/status")
async def detailed_status(api_key: str = Depends(require_api_key)):
    """
    Detailed System Status.
    Requires Nancy API key authentication. Returns task queue size,
    provider circuit breaker states, and connected extension sessions.
    """
    # Import active_extensions dynamically to avoid circular import
    active_exts = {}
    try:
        from routers.extension import active_extensions
        now = time.time()
        for ext_id, last_seen in list(active_extensions.items()):
            active_exts[ext_id] = {
                "last_seen_ago": round(now - last_seen, 1),
                "online": (now - last_seen) < 30.0,  # 30 seconds threshold
            }
    except Exception:
        pass

    return {
        "status": "running",
        "timestamp": time.time(),
        "queue": task_queue.get_status(),
        "router": {
            "providers": provider_router.get_provider_states(),
            "available_models": provider_router.get_available_models(),
        },
        "active_tasks": task_queue.get_active_tasks(),
        "recent_history": task_queue.get_history(20),
        "connected_extensions": active_exts,
    }
