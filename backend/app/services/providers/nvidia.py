"""NVIDIA API catalog provider via its OpenAI-compatible endpoint."""

import asyncio
import re
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


_OPEN, _CLOSE = "<think>", "</think>"
_THINK_RE = re.compile(r"<think>.*?(?:</think>|\Z)", re.DOTALL)


def strip_reasoning(text: str) -> str:
    """Remove inline <think> blocks that reasoning models emit before the answer."""
    if _CLOSE in text and _OPEN not in text:
        # Some models omit the opening tag and start directly with reasoning.
        text = text.split(_CLOSE, 1)[1]
    return _THINK_RE.sub("", text).lstrip()


class ReasoningFilter:
    """Streaming counterpart of strip_reasoning; handles tags split across chunks."""

    def __init__(self) -> None:
        self._buf = ""
        self._thinking = False
        self._started = False  # leading whitespace before the answer is dropped

    def feed(self, chunk: str) -> str:
        self._buf += chunk
        out: list[str] = []
        while True:
            tag = _CLOSE if self._thinking else _OPEN
            idx = self._buf.find(tag)
            if idx >= 0:
                if not self._thinking:
                    out.append(self._buf[:idx])
                self._buf = self._buf[idx + len(tag) :]
                self._thinking = not self._thinking
                continue
            # Keep a possible partial tag at the end for the next chunk.
            keep = next((k for k in range(min(len(tag) - 1, len(self._buf)), 0, -1) if tag.startswith(self._buf[-k:])), 0)
            if not self._thinking:
                out.append(self._buf[: len(self._buf) - keep])
            self._buf = self._buf[len(self._buf) - keep :]
            break
        return self._emit("".join(out))

    def flush(self) -> str:
        rest, self._buf = ("" if self._thinking else self._buf), ""
        return self._emit(rest)

    def _emit(self, text: str) -> str:
        if not self._started:
            text = text.lstrip()
            self._started = bool(text)
        return text


class NvidiaProvider(ModelProvider):
    name = "nvidia"

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self._settings = settings
        self._key = secret(settings.nvidia_api_key)
        self._client = client
        self._thinking_option_supported = True

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

    def _thinking_args(self) -> dict[str, Any]:
        # Thinking models (e.g. Nemotron) otherwise spend thousands of hidden reasoning tokens first; on long
        # report prompts that can use the whole max_tokens budget and return an empty answer.
        if self._settings.nvidia_thinking or not self._thinking_option_supported:
            return {}
        return {"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}}

    async def _create(self, client: Any, **kwargs: Any) -> Any:
        try:
            return await client.chat.completions.create(**kwargs, **self._thinking_args())
        except openai.BadRequestError:
            if not self._thinking_args():
                raise
            # A model that rejects the option: stop sending it and retry once.
            self._thinking_option_supported = False
            return await client.chat.completions.create(**kwargs)

    async def generate(
        self, messages: list[ChatMessage], *, temperature: float = 0.3, max_tokens: int | None = None, json_mode: bool = False
    ) -> str:
        client = self._get_client()
        kwargs: dict[str, Any] = {"model": self.model, "messages": self._convert(messages), "temperature": temperature}
        kwargs["max_tokens"] = max_tokens or 4096
        try:
            response = await self._create(client, **kwargs)
        except Exception as exc:
            raise classify_openai_error(exc) from exc
        text = strip_reasoning((response.choices[0].message.content or "") if response.choices else "")
        if not text.strip():
            raise ProviderError(ErrorKind.INVALID_OUTPUT, self.name, "empty response")
        return text

    async def stream(self, messages: list[ChatMessage], *, temperature: float = 0.3, max_tokens: int | None = None) -> AsyncIterator[str]:
        client = self._get_client()
        try:
            response = await self._create(
                client,
                model=self.model,
                messages=self._convert(messages),
                temperature=temperature,
                max_tokens=max_tokens or 4096,
                stream=True,
            )
            reasoning = ReasoningFilter()
            async for chunk in response:
                if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                    if text := reasoning.feed(chunk.choices[0].delta.content):
                        yield text
            if text := reasoning.flush():
                yield text
        except Exception as exc:
            raise classify_openai_error(exc) from exc
