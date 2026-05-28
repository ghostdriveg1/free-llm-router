"""
Nancy HF Space — Configuration Module.

All settings are loaded from environment variables with sensible defaults.
Provider configuration can be supplied as a JSON string via PROVIDERS_CONFIG.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings

logger = logging.getLogger("nancy.config")


class Settings(BaseSettings):
    """Application settings sourced from environment variables."""

    # ── Auth ──────────────────────────────────────────────────────────
    nancy_api_key: str = Field(
        default="nancy-dev-key",
        description="Bearer token required for /v1/* API endpoints.",
    )
    nancy_ext_secret: str = Field(
        default="nancy-ext-dev-secret",
        description="Bearer token required for /ext/* extension endpoints.",
    )

    # ── Upstash Redis (optional) ──────────────────────────────────────
    upstash_redis_rest_url: str = Field(
        default="",
        description="Upstash Redis REST URL. Leave empty to use in-memory fallback.",
    )
    upstash_redis_rest_token: str = Field(
        default="",
        description="Upstash Redis REST bearer token.",
    )

    # ── Official Paid APIs / Hybrid Keys (optional) ───────────────────
    mistral_api_key: str = Field(default="", description="Official Mistral API Key.")
    nvidia_nim_api_key: str = Field(default="", description="Official NVIDIA NIM API Key.")
    deepseek_api_key: str = Field(default="", description="Official DeepSeek API Key.")
    anthropic_api_key: str = Field(default="", description="Official Anthropic/Claude API Key.")
    z_ai_api_key: str = Field(default="", description="Official Z.ai API Key.")

    # ── Provider Routing ──────────────────────────────────────────────
    default_provider: str = Field(
        default="chatgpt",
        description="Default provider when the model name is not recognized.",
    )
    fallback_chain: list[str] = Field(
        default=["chatgpt", "gemini", "deepseek", "kimi", "claude", "nim", "zai"],
        description="Ordered list of providers to try on failure.",
    )
    providers_config: dict[str, Any] = Field(
        default_factory=lambda: {
            "chatgpt":  {"rpm": 10, "tpm": 40000, "url_pattern": "https://chatgpt.com"},
            "gemini":   {"rpm": 15, "tpm": 60000, "url_pattern": "https://gemini.google.com"},
            "deepseek": {"rpm": 10, "tpm": 40000, "url_pattern": "https://chat.deepseek.com"},
            "kimi":     {"rpm": 10, "tpm": 40000, "url_pattern": "https://kimi.moonshot.cn"},
            "claude":   {"rpm": 5,  "tpm": 30000, "url_pattern": "https://claude.ai"},
            "nim":      {"rpm": 5,  "tpm": 20000, "url_pattern": "https://build.nvidia.com/nim"},
            "zai":      {"rpm": 5,  "tpm": 20000, "url_pattern": "https://chat.z.ai"},
        },
        description="Per-provider configuration. Supply as JSON string via env var.",
    )


    # ── Circuit Breaker ───────────────────────────────────────────────
    cb_failure_threshold: int = Field(
        default=3,
        description="Consecutive failures before tripping the circuit breaker.",
    )
    cb_cooldown_seconds: float = Field(
        default=60.0,
        description="Seconds to wait before retrying a tripped provider.",
    )

    # ── Task Queue ────────────────────────────────────────────────────
    task_timeout_seconds: float = Field(
        default=120.0,
        description="Max seconds to wait for extension to complete a task.",
    )
    task_queue_max_size: int = Field(
        default=100,
        description="Maximum number of pending tasks in the queue.",
    )

    # ── Extension ─────────────────────────────────────────────────────
    ext_heartbeat_timeout_seconds: float = Field(
        default=30.0,
        description="Seconds after last heartbeat before extension is considered offline.",
    )
    ext_sse_keepalive_seconds: float = Field(
        default=15.0,
        description="Interval for SSE keepalive pings to the extension.",
    )

    # ── Server ────────────────────────────────────────────────────────
    log_level: str = Field(default="INFO", description="Logging level.")
    cors_origins: list[str] = Field(
        default=["*"],
        description="Allowed CORS origins.",
    )

    # ── Validators ────────────────────────────────────────────────────
    @field_validator("providers_config", mode="before")
    @classmethod
    def parse_providers_json(cls, v: Any) -> dict[str, Any]:
        """Accept a JSON string or dict for providers_config."""
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError as exc:
                logger.error("Invalid PROVIDERS_CONFIG JSON: %s", exc)
                raise ValueError(f"PROVIDERS_CONFIG is not valid JSON: {exc}") from exc
        return v

    @field_validator("fallback_chain", mode="before")
    @classmethod
    def parse_fallback_chain(cls, v: Any) -> list[str]:
        """Accept a comma-separated string or list."""
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: Any) -> list[str]:
        """Accept a comma-separated string or list."""
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    @property
    def redis_enabled(self) -> bool:
        """Return True if Upstash Redis is configured."""
        return bool(self.upstash_redis_rest_url and self.upstash_redis_rest_token)

    model_config = {"env_prefix": "", "case_sensitive": False}


# Module-level singleton
settings = Settings()
