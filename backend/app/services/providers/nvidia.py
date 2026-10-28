"""NVIDIA API catalog provider via its OpenAI-compatible endpoint."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import openai
from openai import AsyncOpenAI

from app.config import Settings, secret
from app.services.providers.base import ChatMessage, ModelProvider
from app.services.providers.errors import ErrorKind, ProviderError, parse_retry_after


def classify_openai_error(exc: BaseException, provider: str = "nvidia") -> ProviderError:
    if isinstance(exc, ProviderError):
        return exc
    if isinstance(exc, openai.APITimeoutError):
        return ProviderError(ErrorKind.TIMEOUT, provider, "timeout")
    if isinstance(exc, openai.APIConnectionError):
        return ProviderError(ErrorKind.NETWORK, provider, "connection error")
    if isinstance(exc, openai.APIStatusError):
        code = exc.status_code
        text = str(exc.message or "").lower()
        retry_after = parse_retry_after(exc.response.headers.get("retry-after"))
        if code == 401:
            return ProviderError(ErrorKind.AUTH, provider, exc.message, status_code=code)
        if code == 402 or "quota" in text or "credits" in text or "billing" in text:
            return ProviderError(ErrorKind.QUOTA, provider, exc.message, status_code=code, retry_after=retry_after)
        if code == 403:
            return ProviderError(ErrorKind.PERMISSION, provider, exc.message, status_code=code)
        if code == 404:
            return ProviderError(ErrorKind.MODEL_NOT_FOUND, provider, exc.message, status_code=code)
        if code == 429:
            return ProviderError(ErrorKind.RATE_LIMIT, provider, exc.message, status_code=code, retry_after=retry_after)
        if code in (408, 504):
            return ProviderError(ErrorKind.TIMEOUT, provider, exc.message, status_code=code)
        if code >= 500:
            return ProviderError(ErrorKind.SERVER, provider, exc.message, status_code=code)
        if code in (400, 422):
            return ProviderError(ErrorKind.BAD_REQUEST, provider, exc.message, status_code=code)
        return ProviderError(ErrorKind.UNKNOWN, provider, exc.message, status_code=code)
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return ProviderError(ErrorKind.TIMEOUT, provider, "timeout")
    return ProviderError(ErrorKind.UNKNOWN, provider, type(exc).__name__)


class NvidiaProvider(ModelProvider):
    name = "nvidia"

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self._settings = settings
        self._key = secret(settings.nvidia_api_key)
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(self._key)

    @property
    def model(self) -> str:
        return self._settings.nvidia_model

    def _get_client(self) -> Any:
        if not self.configured:
            raise ProviderError(ErrorKind.NOT_CONFIGURED, self.name)
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self._key,
                base_url=self._settings.nvidia_base_url,
                timeout=self._settings.request_timeout_seconds * 3,
                max_retries=0,  # the router owns retries
            )
        return self._client

    @staticmethod
    def _convert(messages: list[ChatMessage]) -> list[dict[str, str]]:
        return [{"role": m.role, "content": m.content} for m in messages]

    async def generate(
        self, messages: list[ChatMessage], *, temperature: float = 0.3, max_tokens: int | None = None, json_mode: bool = False
    ) -> str:
        client = self._get_client()
        kwargs: dict[str, Any] = {"model": self.model, "messages": self._convert(messages), "temperature": temperature}
        kwargs["max_tokens"] = max_tokens or 4096
        try:
            response = await client.chat.completions.create(**kwargs)
        except Exception as exc:
            raise classify_openai_error(exc) from exc
        text = (response.choices[0].message.content or "") if response.choices else ""
        if not text.strip():
            raise ProviderError(ErrorKind.INVALID_OUTPUT, self.name, "empty response")
        return text

    async def stream(self, messages: list[ChatMessage], *, temperature: float = 0.3, max_tokens: int | None = None) -> AsyncIterator[str]:
        client = self._get_client()
        try:
            response = await client.chat.completions.create(
                model=self.model,
                messages=self._convert(messages),
                temperature=temperature,
                max_tokens=max_tokens or 4096,
                stream=True,
            )
            async for chunk in response:
                if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as exc:
            raise classify_openai_error(exc) from exc
