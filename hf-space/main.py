"""
Nancy HF Space — FastAPI Main Entry Point.

Initializes the FastAPI application, registers routers (API, Extension, Health),
manages startup/shutdown hooks (Redis, logging), and configures CORS middleware.
"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import settings
from core.redis_client import redis_client
from models.openai import ErrorDetail, ErrorResponse
from routers.api import router as api_router
from routers.extension import router as extension_router
from routers.health import router as health_router
from routers.sessions import router as sessions_router
from routers.admin import router as admin_router

# ── Logging Configuration ─────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("nancy.main")


# ── Lifespan Context Manager ──────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handles startup and shutdown hooks for Nancy."""
    logger.info("Initializing Nancy HF Space backend...")

    # Startup Upstash Redis if configured
    await redis_client.startup()

    yield

    logger.info("Shutting down Nancy HF Space backend...")
    # Shutdown Upstash Redis
    await redis_client.shutdown()


# ── FastAPI App Initialization ────────────────────────────────────────────────
app = FastAPI(
    title="Nancy",
    description="Free Chatbot to OpenAI-Compatible API Orchestrator",
    version="0.1.0",
    lifespan=lifespan,
)

# ── CORS Middleware ───────────────────────────────────────────────────────────
# Allow access from Chrome extension environment (chrome-extension://*)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Router Registration ───────────────────────────────────────────────────────
app.include_router(health_router)
app.include_router(extension_router)
app.include_router(api_router)
app.include_router(sessions_router)
app.include_router(admin_router)


# ── Global Exception Handlers ─────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch-all standard OpenAI-compatible error response for internal errors."""
    logger.error("Unhandled error at %s: %s", request.url.path, exc, exc_info=True)
    error_detail = ErrorDetail(
        message=f"Nancy server internal error: {str(exc)}",
        type="internal_server_error",
        code="500",
    )
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(error=error_detail).model_dump(),
    )


@app.get("/")
async def root_index():
    """Welcome index page for browser landing."""
    return {
        "name": "Nancy",
        "description": "API Orchestrator for converting free chatbot interfaces into structured APIs.",
        "version": "0.1.0",
        "docs_url": "/docs",
        "health_check": "/health",
    }
