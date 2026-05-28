"""
Nancy — Provider models.

Tracks per-provider runtime state: rate limits, circuit breaker status,
and routing metadata.
"""

from __future__ import annotations

import time
try:
    from enum import StrEnum
except ImportError:
    import enum
    class StrEnum(str, enum.Enum):
        pass
from typing import Any

from pydantic import BaseModel, Field


class CircuitState(StrEnum):
    """Circuit breaker states."""

    CLOSED = "closed"        # healthy — requests flow through
    OPEN = "open"            # tripped — requests are blocked
    HALF_OPEN = "half_open"  # cooldown expired — next request is a probe


class ProviderConfig(BaseModel):
    """
    Static configuration for a single provider.

    Loaded from the ``PROVIDERS_CONFIG`` environment variable or defaults.
    """

    rpm: int = Field(default=10, description="Requests per minute limit.")
    tpm: int = Field(default=40000, description="Tokens per minute limit.")
    url_pattern: str = Field(
        default="", description="Base URL pattern for the chatbot UI."
    )


class ProviderState:
    """
    Mutable runtime state for a single provider.

    This is NOT a Pydantic model because it holds mutable counters and
    timestamps that change on every request.

    Attributes:
        name: Provider identifier (e.g. ``"chatgpt"``).
        config: Static provider configuration.
        circuit_state: Current circuit breaker state.
        consecutive_failures: Count of back-to-back failures.
        last_failure_time: Timestamp of the most recent failure.
        last_success_time: Timestamp of the most recent success.
        request_timestamps: Rolling window of request timestamps for RPM.
    """

    __slots__ = (
        "name",
        "config",
        "circuit_state",
        "consecutive_failures",
        "last_failure_time",
        "last_success_time",
        "request_timestamps",
    )

    def __init__(self, name: str, config: ProviderConfig) -> None:
        self.name = name
        self.config = config
        self.circuit_state = CircuitState.CLOSED
        self.consecutive_failures: int = 0
        self.last_failure_time: float = 0.0
        self.last_success_time: float = 0.0
        self.request_timestamps: list[float] = []

    # ── Circuit Breaker ───────────────────────────────────────────────

    def record_success(self) -> None:
        """Reset failure counter and close the circuit."""
        self.consecutive_failures = 0
        self.last_success_time = time.time()
        self.circuit_state = CircuitState.CLOSED

    def record_failure(self, threshold: int) -> None:
        """Increment failure counter; trip if threshold is reached."""
        self.consecutive_failures += 1
        self.last_failure_time = time.time()
        if self.consecutive_failures >= threshold:
            self.circuit_state = CircuitState.OPEN

    def should_allow_request(self, threshold: int, cooldown: float) -> bool:
        """
        Check whether the circuit breaker allows a request.

        - CLOSED → always allow.
        - OPEN → allow only if cooldown has elapsed (transition to HALF_OPEN).
        - HALF_OPEN → allow (it's a probe request).
        """
        if self.circuit_state == CircuitState.CLOSED:
            return True
        if self.circuit_state == CircuitState.OPEN:
            elapsed = time.time() - self.last_failure_time
            if elapsed >= cooldown:
                self.circuit_state = CircuitState.HALF_OPEN
                return True
            return False
        # HALF_OPEN — allow the probe
        return True

    # ── Rate Limiting (sliding window) ────────────────────────────────

    def check_rate_limit(self) -> bool:
        """
        Return True if the provider is within its RPM budget.

        Prunes timestamps older than 60 seconds.
        """
        now = time.time()
        cutoff = now - 60.0
        self.request_timestamps = [
            ts for ts in self.request_timestamps if ts > cutoff
        ]
        return len(self.request_timestamps) < self.config.rpm

    def record_request(self) -> None:
        """Record a request timestamp for RPM tracking."""
        self.request_timestamps.append(time.time())

    # ── Serialization ─────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialize for health / debug endpoints."""
        now = time.time()
        cutoff = now - 60.0
        active_rpm = len([ts for ts in self.request_timestamps if ts > cutoff])
        return {
            "name": self.name,
            "circuit_state": self.circuit_state.value,
            "consecutive_failures": self.consecutive_failures,
            "rpm_current": active_rpm,
            "rpm_limit": self.config.rpm,
            "last_failure_ago": (
                round(now - self.last_failure_time, 1)
                if self.last_failure_time
                else None
            ),
            "last_success_ago": (
                round(now - self.last_success_time, 1)
                if self.last_success_time
                else None
            ),
        }
