"""
Nancy — Upstash Redis REST API client.

Uses ``httpx`` to communicate with Upstash Redis via its REST interface.
All operations are optional — if Redis is not configured, methods are
no-ops that return sensible defaults.

This allows the HF Space to work without any external dependencies while
supporting persistence when Upstash credentials are provided.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from config import settings

logger = logging.getLogger("nancy.redis")


class RedisClient:
    """
    Async client for the Upstash Redis REST API.

    All public methods are safe to call even when Redis is not configured —
    they will log a debug message and return ``None`` / empty defaults.

    Usage::

        redis = RedisClient()
        await redis.set("key", "value", ex=300)
        val = await redis.get("key")
    """

    def __init__(self) -> None:
        self._enabled = settings.redis_enabled
        self._base_url = settings.upstash_redis_rest_url.rstrip("/")
        self._token = settings.upstash_redis_rest_token
        self._client: httpx.AsyncClient | None = None

    @property
    def is_enabled(self) -> bool:
        """Return True if Redis is configured and the client is initialized."""
        return self._enabled and self._client is not None


    async def startup(self) -> None:
        """Initialize the HTTP client. Call during app startup."""
        if not self._enabled:
            logger.info("Redis not configured — using in-memory fallbacks.")
            return
        import base64
        import os

        # Determine authentication headers (Upstash Bearer vs Self-hosted Webdis Basic Auth)
        redis_secret = os.getenv("NANCY_REDIS_SECRET", "")
        if self._token:
            headers = {"Authorization": f"Bearer {self._token}"}
            logger.info("Configuring REST client using Upstash Bearer token.")
        elif redis_secret:
            auth_str = f"nancy_admin:{redis_secret}"
            b64_auth = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")
            headers = {"Authorization": f"Basic {b64_auth}"}
            logger.info("Configuring REST client using Self-Hosted Webdis Basic Auth.")
        else:
            headers = {}
            logger.warning("No authentication credentials found for REST client.")

        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=httpx.Timeout(10.0, connect=5.0),
        )
        # Verify connectivity
        try:
            resp = await self._client.post("/", json=["PING"])
            resp.raise_for_status()
            logger.info("Redis connected: %s", resp.json())
        except Exception as exc:
            logger.warning("Redis PING failed (non-fatal): %s", exc)

    async def shutdown(self) -> None:
        """Close the HTTP client. Call during app shutdown."""
        if self._client:
            await self._client.aclose()
            self._client = None

    # ── Low-level command execution ───────────────────────────────────

    async def _execute(self, *args: str) -> Any:
        """
        Execute a raw Redis command via the REST API.

        Returns the ``result`` field from the Upstash response, or ``None``
        on error / when Redis is disabled.
        """
        if not self._enabled or not self._client:
            return None

        import os
        is_webdis = os.getenv("NANCY_REDIS_SECRET", "") and not settings.upstash_redis_rest_token

        if not is_webdis:
            # Traditional Upstash REST API call
            try:
                resp = await self._client.post("/", json=list(args))
                resp.raise_for_status()
                data = resp.json()
                return data.get("result")
            except httpx.HTTPStatusError as exc:
                logger.error("Redis HTTP error: %s %s", exc.response.status_code, exc.response.text)
                return None
            except Exception as exc:
                logger.error("Redis error: %s", exc)
                return None

        # Webdis REST API Translation logic
        try:
            if not args:
                return None

            cmd = args[0].upper()

            # Special case: SET with or without EX
            if cmd == "SET":
                key = args[1]
                value = args[2]
                ex = None
                if len(args) > 4 and args[3].upper() == "EX":
                    ex = args[4]

                # Use PUT to pass large/complex value safely in the body
                resp = await self._client.put(f"/SET/{key}", content=value)
                resp.raise_for_status()

                if ex is not None:
                    # Set expire separately
                    exp_resp = await self._client.post(f"/EXPIRE/{key}/{ex}")
                    exp_resp.raise_for_status()

                return "OK"

            # Special case: HSET
            elif cmd == "HSET":
                key = args[1]
                field = args[2]
                value = args[3]
                import urllib.parse
                safe_field = urllib.parse.quote(field, safe="")
                resp = await self._client.put(f"/HSET/{key}/{safe_field}", content=value)
                resp.raise_for_status()
                return 1

            # Special case: LPUSH / RPUSH
            elif cmd in ("LPUSH", "RPUSH"):
                key = args[1]
                value = args[2]
                resp = await self._client.put(f"/{cmd}/{key}", content=value)
                resp.raise_for_status()
                data = resp.json()
                return data.get(cmd)

            # Special case: SADD / SREM / SISMEMBER
            elif cmd in ("SADD", "SREM", "SISMEMBER"):
                key = args[1]
                value = args[2]
                resp = await self._client.put(f"/{cmd}/{key}", content=value)
                resp.raise_for_status()
                data = resp.json()
                res = data.get(cmd)
                if res is None:
                    res = data.get(cmd.lower())
                return res

            else:
                # Fallback for standard commands: urlencode arguments in the path
                import urllib.parse
                encoded_args = [urllib.parse.quote(str(arg), safe="") for arg in args[1:]]
                if encoded_args:
                    path = f"/{cmd}/" + "/".join(encoded_args)
                else:
                    path = f"/{cmd}"

                # Execute via GET
                resp = await self._client.get(path)
                resp.raise_for_status()
                data = resp.json()

                res = data.get(cmd)
                if res is None:
                    res = data.get(cmd.lower())
                return res

        except httpx.HTTPStatusError as exc:
            logger.error("Webdis Redis HTTP error: %s %s", exc.response.status_code, exc.response.text)
            return None
        except Exception as exc:
            logger.error("Webdis Redis error: %s", exc)
            return None

    # ── High-level operations ─────────────────────────────────────────

    async def get(self, key: str) -> str | None:
        """Get a string value by key."""
        return await self._execute("GET", key)

    async def set(
        self,
        key: str,
        value: str,
        ex: int | None = None,
    ) -> bool:
        """
        Set a string value, optionally with expiration in seconds.

        Returns True on success.
        """
        if ex is not None:
            result = await self._execute("SET", key, value, "EX", str(ex))
        else:
            result = await self._execute("SET", key, value)
        return result == "OK"

    async def delete(self, key: str) -> bool:
        """Delete a key. Returns True if the key existed."""
        result = await self._execute("DEL", key)
        return result is not None and int(result) > 0

    async def incr(self, key: str) -> int | None:
        """Increment an integer key. Returns the new value."""
        result = await self._execute("INCR", key)
        return int(result) if result is not None else None

    async def expire(self, key: str, seconds: int) -> bool:
        """Set expiration on an existing key."""
        result = await self._execute("EXPIRE", key, str(seconds))
        return result is not None and int(result) == 1

    async def lpush(self, key: str, value: str) -> int | None:
        """Push a value to the head of a list."""
        result = await self._execute("LPUSH", key, value)
        return int(result) if result is not None else None

    async def lrange(self, key: str, start: int, stop: int) -> list[str]:
        """Return a range of elements from a list."""
        result = await self._execute("LRANGE", key, str(start), str(stop))
        return result if isinstance(result, list) else []

    async def hset(self, key: str, field: str, value: str) -> bool:
        """Set a hash field."""
        result = await self._execute("HSET", key, field, value)
        return result is not None

    async def hget(self, key: str, field: str) -> str | None:
        """Get a hash field value."""
        return await self._execute("HGET", key, field)

    async def hgetall(self, key: str) -> dict[str, str]:
        """Get all fields and values in a hash."""
        result = await self._execute("HGETALL", key)
        if not result or not isinstance(result, list):
            return {}
        # Upstash returns [field1, val1, field2, val2, ...]
        it = iter(result)
        return dict(zip(it, it))

    # ── JSON helpers ──────────────────────────────────────────────────

    async def set_json(
        self,
        key: str,
        value: Any,
        ex: int | None = None,
    ) -> bool:
        """Serialize ``value`` as JSON and store it."""
        return await self.set(key, json.dumps(value, default=str), ex=ex)

    async def get_json(self, key: str) -> Any | None:
        """Retrieve and deserialize a JSON value."""
        raw = await self.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Failed to parse JSON for key '%s'", key)
            return None


# Module-level singleton
redis_client = RedisClient()
