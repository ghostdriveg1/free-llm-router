"""
Nancy — Provider Router.

Responsible for selecting which provider handles a given request.
Implements:
  - Circuit breaker (trip after N consecutive failures, cooldown period)
  - RPM rate limiting (sliding window per provider)
  - Fallback chains (try next provider when current is unavailable)
  - Model → provider name resolution
"""

from __future__ import annotations

import logging
from typing import Any

from config import settings
from models.provider import ProviderConfig, ProviderState

logger = logging.getLogger("nancy.router")


# ── Model-to-Provider mapping ────────────────────────────────────────────────

# Maps model name aliases to canonical provider names.
# The extension uses the provider name to know which chatbot tab to target.
MODEL_TO_PROVIDER: dict[str, str] = {
    # ChatGPT
    "chatgpt": "chatgpt",
    "gpt-4": "chatgpt",
    "gpt-4o": "chatgpt",
    "gpt-40": "chatgpt",
    "gpt-4o-mini": "chatgpt",
    "gpt-3.5-turbo": "chatgpt",
    # Gemini
    "gemini": "gemini",
    "gemini-pro": "gemini",
    "gemini-2.0-flash": "gemini",
    "gemini-2.5-pro": "gemini",
    # DeepSeek
    "deepseek": "deepseek",
    "deepseek-chat": "deepseek",
    "deepseek-r1": "deepseek",
    # Kimi
    "kimi": "kimi",
    "moonshot": "kimi",
    # Official Paid API / Hybrid models
    "mistral-large": "api-mistral",
    "nvidia-llama3": "api-nvidia-nim",
    "deepseek-api": "api-deepseek",
    "claude-api": "api-anthropic",
    "z-ai-api": "api-z-ai",
    # Browser relay: NIM Portal (free playground)
    "nim": "nim",
    "nim-llama3": "nim",
    "nim-mistral": "nim",
    # Browser relay: z.ai portal
    "zai": "zai",
    "z-ai": "zai",
    # Claude (browser portal)
    "claude": "claude",
    "claude-3": "claude",
}


class ProviderRouter:
    """
    Selects providers for incoming requests with circuit breaking,
    rate limiting, and fallback chain support.

    Usage::

        router = ProviderRouter()
        provider = router.resolve("gpt-4o")        # → "chatgpt"
        available = router.select_provider("chatgpt")  # checks CB + RPM
        router.record_success("chatgpt")
        router.record_failure("chatgpt")
    """

    def __init__(self) -> None:
        self._states: dict[str, ProviderState] = {}
        self._initialize_providers()

    def _initialize_providers(self) -> None:
        """Build ProviderState objects from configuration."""
        for name, raw_config in settings.providers_config.items():
            config = ProviderConfig(**raw_config) if isinstance(raw_config, dict) else ProviderConfig()
            self._states[name] = ProviderState(name, config)
            logger.info(
                "Provider '%s' initialized (rpm=%d, tpm=%d)",
                name,
                config.rpm,
                config.tpm,
            )

        # Ensure all fallback chain providers exist
        for name in settings.fallback_chain:
            if name not in self._states:
                self._states[name] = ProviderState(name, ProviderConfig())
                logger.info("Provider '%s' added from fallback chain with defaults", name)

    # ── Resolution ────────────────────────────────────────────────────

    def resolve(self, model: str) -> str:
        """
        Resolve a model name to a canonical provider name.

        Falls back to ``settings.default_provider`` if the model is unknown.
        """
        provider = MODEL_TO_PROVIDER.get(model.lower(), model.lower())
        # If the resolved name is a known provider, use it
        if provider in self._states:
            return provider
        # Otherwise fall back to default
        logger.debug(
            "Unknown model '%s' → defaulting to '%s'",
            model,
            settings.default_provider,
        )
        return settings.default_provider

    # ── Provider Selection with Circuit Breaker + Rate Limit ──────────

    def select_provider(
        self,
        preferred: str,
        exclude: set[str] | None = None,
    ) -> str | None:
        """
        Select the best available provider.

        1. Try the preferred provider first.
        2. If it's unavailable (circuit open, rate limited), walk the fallback chain.
        3. Return ``None`` if no provider is available.

        Args:
            preferred: The preferred provider name.
            exclude: Set of provider names to skip (already tried and failed).
        """
        exclude = exclude or set()
        candidates = [preferred] + [
            p for p in settings.fallback_chain if p != preferred
        ]

        for name in candidates:
            if name in exclude:
                continue

            state = self._states.get(name)
            if not state:
                continue

            # Check circuit breaker
            if not state.should_allow_request(
                settings.cb_failure_threshold,
                settings.cb_cooldown_seconds,
            ):
                logger.debug("Provider '%s' circuit is OPEN — skipping", name)
                continue

            # Check rate limit
            if not state.check_rate_limit():
                logger.debug("Provider '%s' rate limited — skipping", name)
                continue

            # Record the request
            state.record_request()
            logger.info("Selected provider: '%s'", name)
            return name

        logger.error(
            "No available provider (preferred=%s, exclude=%s)",
            preferred,
            exclude,
        )
        return None

    # ── Feedback ──────────────────────────────────────────────────────

    def record_success(self, provider: str) -> None:
        """Record a successful completion for the given provider."""
        state = self._states.get(provider)
        if state:
            state.record_success()
            logger.debug("Provider '%s' success recorded", provider)

    def record_failure(self, provider: str) -> None:
        """Record a failure for the given provider (may trip circuit)."""
        state = self._states.get(provider)
        if state:
            state.record_failure(settings.cb_failure_threshold)
            logger.warning(
                "Provider '%s' failure recorded (consecutive=%d, circuit=%s)",
                provider,
                state.consecutive_failures,
                state.circuit_state.value,
            )

    # ── Observability ─────────────────────────────────────────────────

    def get_provider_states(self) -> list[dict[str, Any]]:
        """Return status dicts for all providers."""
        return [state.to_dict() for state in self._states.values()]

    def get_available_models(self) -> list[str]:
        """Return list of all recognized model names."""
        return sorted(MODEL_TO_PROVIDER.keys())

    def get_available_providers(self) -> list[str]:
        """Return list of all configured provider names."""
        return sorted(self._states.keys())

    def is_provider_available(self, provider: str) -> bool:
        """Check if a specific provider is currently available."""
        state = self._states.get(provider)
        if not state:
            return False
        return (
            state.should_allow_request(
                settings.cb_failure_threshold,
                settings.cb_cooldown_seconds,
            )
            and state.check_rate_limit()
        )

    def is_provider_healthy(self, provider: str) -> bool:
        """Alias for is_provider_available for admin dashboard compatibility."""
        return self.is_provider_available(provider)

    @property
    def fallback_chain(self) -> list[str]:
        """Return the active fallback chain of providers."""
        return settings.fallback_chain


# Module-level singleton
provider_router = ProviderRouter()

