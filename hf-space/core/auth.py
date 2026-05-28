"""
Nancy — Authentication & Authorization.

Provides FastAPI dependency functions for bearer token validation.
Two separate tokens are used:
  - ``NANCY_API_KEY``  → for agent-facing ``/v1/*`` endpoints
  - ``NANCY_EXT_SECRET`` → for extension-facing ``/ext/*`` endpoints
"""

from __future__ import annotations

import logging
import hashlib
import time
import asyncio
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config import settings
from core.redis_client import redis_client


logger = logging.getLogger("nancy.auth")

# Reusable security scheme — auto_error=False lets us return a nicer message
_bearer_scheme = HTTPBearer(auto_error=False)


def _extract_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
) -> str:
    """
    Extract the bearer token from the Authorization header.

    Falls back to the ``authorization`` query parameter for SSE connections
    where some clients cannot set custom headers.

    Raises:
        HTTPException(401): If no token is present.
    """
    if credentials and credentials.credentials:
        return credentials.credentials

    # Fallback: query param (useful for EventSource which can't set headers)
    query_token = request.query_params.get("authorization") or request.query_params.get("token")
    if query_token:
        # Strip "Bearer " prefix if present
        if query_token.lower().startswith("bearer "):
            return query_token[7:]
        return query_token

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing authorization header. Provide 'Authorization: Bearer <token>'.",
        headers={"WWW-Authenticate": "Bearer"},
    )
async def require_api_key(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)
    ] = None,
) -> str:
    """
    FastAPI dependency: validates the bearer token against either NANCY_API_KEY
    or a SHA-256 hashed token cached dynamically in Upstash Redis.

    Returns the validated token string on success.
    """
    token = _extract_token(request, credentials)
    
    # 1. Master Key Local Bypass
    if token == settings.nancy_api_key:
        return token

    # 2. Dynamic Redis Hashed Key validation
    hashed = hashlib.sha256(token.encode("utf-8")).hexdigest()
    try:
        key_meta = await redis_client.get_json(f"nancy:api_keys:{hashed}")
        if key_meta:
            # Asynchronously update key metadata (fire-and-forget to keep requests fast)
            key_meta["last_used"] = int(time.time())
            key_meta["request_count"] = key_meta.get("request_count", 0) + 1
            asyncio.create_task(redis_client.set_json(f"nancy:api_keys:{hashed}", key_meta))
            return token
    except Exception as exc:
        logger.error("Error validating dynamic hashed token in Redis: %s", exc)

    logger.warning("Invalid API key attempt from %s", request.client.host if request.client else "unknown")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid API key.",
        headers={"WWW-Authenticate": "Bearer"},
    )



async def require_ext_secret(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)
    ] = None,
) -> str:
    """
    FastAPI dependency: validates the bearer token against ``NANCY_EXT_SECRET``.

    Used for all ``/ext/*`` endpoints.
    """
    token = _extract_token(request, credentials)
    if token != settings.nancy_ext_secret:
        logger.warning(
            "Invalid extension secret attempt from %s",
            request.client.host if request.client else "unknown",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid extension secret.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token
