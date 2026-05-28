# working.py - Upstash / Webdis Redis Working Memory Client
import asyncio
import base64
import logging
import os
from typing import Any, Optional

import httpx
from upstash_redis.asyncio import Redis

logger = logging.getLogger("olympus.memory.working")

class WorkingMemory:
    """Async Redis Working Memory client with dynamic Upstash and Webdis compatibility."""
    
    def __init__(self, url: Optional[str] = None, token: Optional[str] = None):
        self.url = url or os.getenv("UPSTASH_REDIS_REST_URL", "")
        self.token = token or os.getenv("UPSTASH_REDIS_REST_TOKEN", "")
        self.redis_secret = os.getenv("NANCY_REDIS_SECRET", "")
        self.webdis_url = os.getenv("NANCY_REDIS_URL", "") or self.url
        
        self.redis_online = False
        self.redis: Optional[Redis] = None
        self.webdis_client: Optional[httpx.AsyncClient] = None
        self.local_shadow: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        
        if self.token:
            # Traditional Upstash setup
            self.redis = Redis(url=self.url, token=self.token)
            self.redis_online = True
            logger.info("Upstash Redis client initialized and marked online.")
        elif self.redis_secret and self.webdis_url:
            # Self-hosted Webdis setup
            auth_str = f"nancy_admin:{self.redis_secret}"
            b64_auth = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")
            headers = {"Authorization": f"Basic {b64_auth}"}
            self.webdis_client = httpx.AsyncClient(
                base_url=self.webdis_url.rstrip("/"),
                headers=headers,
                timeout=httpx.Timeout(10.0, connect=5.0),
            )
            self.redis_online = True
            logger.info("Self-Hosted Webdis client initialized and marked online.")
        else:
            logger.warning("No Redis credentials found. Using local RAM shadow only.")
            
    async def set(self, key: str, value: str, ex: Optional[int] = None) -> None:
        """Set cache value with automated fallback to RAM shadow if offline."""
        if self.redis_online:
            if self.redis:
                try:
                    await self.redis.set(key, value, ex=ex)
                    return
                except Exception as e:
                    logger.error(f"Upstash Redis set error: {e}. Switching to RAM shadow.")
                    self.redis_online = False
                    asyncio.create_task(self._start_reconnection_poll())
            elif self.webdis_client:
                try:
                    # Using PUT to pass value in request body for safety with special chars
                    path = f"/SET/{key}"
                    resp = await self.webdis_client.put(path, content=value)
                    resp.raise_for_status()
                    
                    if ex is not None:
                        # Webdis expiration set via separate EXPIRE command
                        expire_resp = await self.webdis_client.post(f"/EXPIRE/{key}/{ex}")
                        expire_resp.raise_for_status()
                    return
                except Exception as e:
                    logger.error(f"Webdis Redis set error: {e}. Switching to RAM shadow.")
                    self.redis_online = False
                    asyncio.create_task(self._start_reconnection_poll())
                
        async with self._lock:
            self.local_shadow[key] = {"value": value, "ttl": ex}
            
    async def get(self, key: str) -> Optional[str]:
        """Get cache value with automated fallback to RAM shadow."""
        if self.redis_online:
            if self.redis:
                try:
                    val = await self.redis.get(key)
                    return str(val) if val is not None else None
                except Exception as e:
                    logger.error(f"Upstash Redis get error: {e}. Switching to RAM shadow.")
                    self.redis_online = False
                    asyncio.create_task(self._start_reconnection_poll())
            elif self.webdis_client:
                try:
                    resp = await self.webdis_client.get(f"/GET/{key}")
                    resp.raise_for_status()
                    data = resp.json()
                    val = data.get("GET")
                    return str(val) if val is not None else None
                except Exception as e:
                    logger.error(f"Webdis Redis get error: {e}. Switching to RAM shadow.")
                    self.redis_online = False
                    asyncio.create_task(self._start_reconnection_poll())
                    
        async with self._lock:
            data = self.local_shadow.get(key)
            if data:
                return str(data["value"])
            return None
            
    async def delete(self, key: str) -> None:
        """Delete cache key."""
        if self.redis_online:
            if self.redis:
                try:
                    await self.redis.delete(key)
                    return
                except Exception as e:
                    logger.error(f"Upstash Redis delete error: {e}. Switching to RAM shadow.")
                    self.redis_online = False
                    asyncio.create_task(self._start_reconnection_poll())
            elif self.webdis_client:
                try:
                    resp = await self.webdis_client.get(f"/DEL/{key}")
                    resp.raise_for_status()
                    return
                except Exception as e:
                    logger.error(f"Webdis Redis delete error: {e}. Switching to RAM shadow.")
                    self.redis_online = False
                    asyncio.create_task(self._start_reconnection_poll())
                    
        async with self._lock:
            if key in self.local_shadow:
                del self.local_shadow[key]
                
    async def _start_reconnection_poll(self) -> None:
        """Background poll task to restore Redis and sync shadow data."""
        if self.redis_online:
            return
            
        logger.info("Starting Redis reconnection poll...")
        while not self.redis_online:
            try:
                if self.redis:
                    await self.redis.ping()
                elif self.webdis_client:
                    resp = await self.webdis_client.get("/PING")
                    resp.raise_for_status()
                else:
                    break
                    
                logger.info("Redis connection restored! Syncing shadow RAM...")
                async with self._lock:
                    for k, v in self.local_shadow.items():
                        await self.set(k, v["value"], ex=v["ttl"])
                    self.local_shadow.clear()
                self.redis_online = True
                logger.info("Working Memory sync complete. Redis is back online.")
                break
            except Exception:
                await asyncio.sleep(10)
