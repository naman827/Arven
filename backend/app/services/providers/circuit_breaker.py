"""Per-provider half-open circuit breaker."""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from app.services.providers.errors import ErrorKind, ProviderError


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    cooldown_seconds: float = 60.0
    quota_cooldown_seconds: float = 1800.0
    failure_threshold: int = 3
    clock: Callable[[], float] = field(default=time.monotonic)

    failures: int = 0
    open_until: float = 0.0
    needs_credentials: bool = False
    last_error: ProviderError | None = None
    _state: CircuitState = CircuitState.CLOSED

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN and self.clock() >= self.open_until:
            self._state = CircuitState.HALF_OPEN
        return self._state

    def allow(self) -> bool:
        if self.needs_credentials:
            return False
        return self.state in (CircuitState.CLOSED, CircuitState.HALF_OPEN)

    def record_success(self) -> None:
        self.failures = 0
        self.needs_credentials = False
        self.last_error = None
        self._state = CircuitState.CLOSED

    def record_failure(self, error: ProviderError) -> None:
        self.last_error = error
        if error.kind == ErrorKind.AUTH:
            self.needs_credentials = True
            self._open(self.quota_cooldown_seconds)
            return
        if error.kind == ErrorKind.QUOTA:
            self._open(max(self.quota_cooldown_seconds, error.retry_after or 0))
            return
        if error.kind == ErrorKind.RATE_LIMIT:
            self._open(max(error.retry_after or self.cooldown_seconds, 1.0))
            return
        if error.kind in (ErrorKind.PERMISSION, ErrorKind.MODEL_NOT_FOUND):
            self._open(self.cooldown_seconds * 5)
            return
        if error.kind in (ErrorKind.BAD_REQUEST, ErrorKind.INVALID_OUTPUT):
            return  # request-specific, not a provider health problem
        self.failures += 1
        if self.failures >= self.failure_threshold or self._state == CircuitState.HALF_OPEN:
            self._open(self.cooldown_seconds)

    def _open(self, seconds: float) -> None:
        self._state = CircuitState.OPEN
        self.open_until = self.clock() + seconds

    def reset(self) -> None:
        self.failures = 0
        self.needs_credentials = False
        self.open_until = 0.0
        self.last_error = None
        self._state = CircuitState.CLOSED

    def seconds_until_retry(self) -> float:
        return max(0.0, self.open_until - self.clock()) if self._state == CircuitState.OPEN else 0.0
