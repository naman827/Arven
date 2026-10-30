"""ProviderRouter: Gemini first, automatic NVIDIA fallback, bounded retries, circuit breakers."""

import asyncio
import logging
import random
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

from app.config import Settings
from app.services.providers.base import ChatMessage, ModelProvider
from app.services.providers.circuit_breaker import CircuitBreaker
from app.services.providers.errors import AllProvidersFailedError, ErrorKind, ProviderError

log = logging.getLogger(__name__)

OverallStatus = Literal["gemini_active", "nvidia_fallback_active", "unavailable", "key_missing_or_invalid"]


@dataclass
class Generation:
    text: str
    provider: str
    model: str


@dataclass
class StreamEvent:
    type: Literal["provider", "token", "reset"]
    text: str = ""
    provider: str = ""
    model: str = ""
    reason: str = ""


class ProviderRouter:
    def __init__(
        self,
        providers: list[ModelProvider],
        settings: Settings,
        *,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
        breakers: dict[str, CircuitBreaker] | None = None,
    ) -> None:
        self.providers = providers
        self.settings = settings
        self._sleep = sleep
        self.breakers = breakers or {
            p.name: CircuitBreaker(
                cooldown_seconds=settings.provider_cooldown_seconds,
                quota_cooldown_seconds=settings.provider_quota_cooldown_seconds,
            )
            for p in providers
        }
        self.last_provider: str | None = None

    # ---- selection -------------------------------------------------------
    def _candidates(self) -> tuple[list[ModelProvider], list[ProviderError]]:
        ready: list[ModelProvider] = []
        skipped: list[ProviderError] = []
        for p in self.providers:
            if not p.configured:
                continue
            breaker = self.breakers[p.name]
            if breaker.allow():
                ready.append(p)
            elif breaker.last_error is not None:
                skipped.append(breaker.last_error)
        return ready, skipped

    def _backoff(self, attempt: int, error: ProviderError) -> float | None:
        """Seconds to wait before retrying the same provider, or None to stop retrying it."""
        if not error.retryable or attempt >= self.settings.max_retry_attempts:
            return None
        if error.kind == ErrorKind.RATE_LIMIT and error.retry_after is not None:
            if error.retry_after > self.settings.max_retry_wait_seconds:
                return None  # waiting too long; fall back instead
            return error.retry_after
        base = min(0.5 * (2**attempt), self.settings.max_retry_wait_seconds)
        return base + random.uniform(0, base / 2)

    def _record(self, provider: ModelProvider, error: ProviderError) -> None:
        self.breakers[provider.name].record_failure(error)
        log.warning("provider %s failed: %s (%s)", provider.name, error.kind.value, error.status_code)

    # ---- non-streaming ---------------------------------------------------
    async def _run[T](self, call: Callable[[ModelProvider], Awaitable[T]]) -> tuple[T, ModelProvider]:
        candidates, errors = self._candidates()
        for provider in candidates:
            attempt = 0
            while True:
                try:
                    result = await call(provider)
                except ProviderError as error:
                    wait = self._backoff(attempt, error)
                    if wait is not None:
                        attempt += 1
                        await self._sleep(wait)
                        continue
                    self._record(provider, error)
                    if not error.fallback_ok:
                        raise
                    errors.append(error)
                    break
                self.breakers[provider.name].record_success()
                self.last_provider = provider.name
                return result, provider
        raise AllProvidersFailedError(errors)

    async def generate(self, messages: list[ChatMessage], **opts: Any) -> Generation:
        text, provider = await self._run(lambda p: p.generate(messages, **opts))
        return Generation(text=text, provider=provider.name, model=provider.model)

    async def generate_structured[T: BaseModel](self, messages: list[ChatMessage], schema: type[T]) -> T:
        result, _ = await self._run(lambda p: p.generate_structured(messages, schema))
        return result

    # ---- streaming -------------------------------------------------------
    async def stream(self, messages: list[ChatMessage], **opts: Any) -> AsyncIterator[StreamEvent]:
        """Yields provider/token/reset events. A `reset` means: discard all text received so far."""
        candidates, errors = self._candidates()
        for index, provider in enumerate(candidates):
            has_backup = index < len(candidates) - 1
            attempt = 0
            while True:
                yield StreamEvent("provider", provider=provider.name, model=provider.model)
                emitted_here = False
                try:
                    async for token in provider.stream(messages, **opts):
                        emitted_here = True
                        yield StreamEvent("token", text=token)
                    if not emitted_here:
                        # A stream that ends without any text is a failure, not an answer: try the backup.
                        raise ProviderError(ErrorKind.INVALID_OUTPUT, provider.name, "empty stream")
                except ProviderError as error:
                    if emitted_here:
                        yield StreamEvent("reset", reason=error.user_message, provider=provider.name)
                    wait = None if (emitted_here and has_backup) else self._backoff(attempt, error)
                    if wait is not None:
                        attempt += 1
                        await self._sleep(wait)
                        continue
                    self._record(provider, error)
                    if not error.fallback_ok:
                        raise
                    errors.append(error)
                    break
                self.breakers[provider.name].record_success()
                self.last_provider = provider.name
                return
        raise AllProvidersFailedError(errors)

    # ---- status ----------------------------------------------------------
    def provider_status(self, provider: ModelProvider) -> dict[str, Any]:
        breaker = self.breakers[provider.name]
        if not provider.configured:
            state = "key_missing_or_invalid"
        elif breaker.needs_credentials:
            state = "key_missing_or_invalid"
        elif not breaker.allow():
            state = "unavailable"
        else:
            state = "ready"
        last = breaker.last_error
        return {
            "name": provider.name,
            "configured": provider.configured,
            "model": provider.model,
            "state": state,
            "circuit": breaker.state.value,
            "retry_in_seconds": round(breaker.seconds_until_retry()),
            "last_error": {"kind": last.kind.value, "message": last.user_message} if last else None,
        }

    def overall_status(self) -> OverallStatus:
        by_name = {p.name: p for p in self.providers}
        gemini, nvidia = by_name.get("gemini"), by_name.get("nvidia")
        if gemini and gemini.configured and self.breakers["gemini"].allow():
            return "gemini_active"
        if nvidia and nvidia.configured and self.breakers["nvidia"].allow():
            return "nvidia_fallback_active"
        if not any(p.configured for p in self.providers) or all(
            self.breakers[p.name].needs_credentials for p in self.providers if p.configured
        ):
            return "key_missing_or_invalid"
        return "unavailable"

    async def test_connection(self, name: str) -> dict[str, Any]:
        provider = next((p for p in self.providers if p.name == name), None)
        if provider is None:
            raise KeyError(name)
        if not provider.configured:
            return {"ok": False, "message": "No API key configured. Add it to .env and restart the backend."}
        try:
            await provider.test_connection()
        except ProviderError as error:
            self.breakers[name].record_failure(error)
            return {"ok": False, "kind": error.kind.value, "message": error.user_message}
        self.breakers[name].record_success()
        return {"ok": True, "message": f"Connected. Model {provider.model} responded."}

    @property
    def any_configured(self) -> bool:
        return any(p.configured for p in self.providers)


def error_message(exc: BaseException) -> str:
    if isinstance(exc, AllProvidersFailedError):
        return exc.message
    if isinstance(exc, ProviderError):
        return f"{exc.provider}: {exc.user_message}"
    return "Unexpected error."
