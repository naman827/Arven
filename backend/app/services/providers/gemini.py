"""Google Gemini provider using the official google-genai SDK."""

import asyncio
import re
from collections.abc import AsyncIterator
from typing import Any

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.config import Settings, secret
from app.services.providers.base import ChatMessage, ModelProvider
from app.services.providers.errors import ErrorKind, ProviderError

_RETRY_DELAY = re.compile(r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)s")


def classify_gemini_error(exc: BaseException) -> ProviderError:
    if isinstance(exc, ProviderError):
        return exc
    if isinstance(exc, genai_errors.APIError):
        code = int(exc.code or 0)
        status = (exc.status or "").upper()
        text = f"{exc.message or ''} {exc.details!s}"
        lowered = text.lower()
        if code == 401 or status == "UNAUTHENTICATED" or "api key not valid" in lowered or "api_key_invalid" in lowered:
            return ProviderError(ErrorKind.AUTH, "gemini", exc.message or "", status_code=code)
        if code == 403 or status == "PERMISSION_DENIED":
            return ProviderError(ErrorKind.PERMISSION, "gemini", exc.message or "", status_code=code)
        if code == 429 or status == "RESOURCE_EXHAUSTED":
            match = _RETRY_DELAY.search(text)
            retry_after = float(match.group(1)) if match else None
            if exc.response is not None and retry_after is None:
                header = getattr(exc.response, "headers", {}).get("retry-after")
                retry_after = float(header) if header and header.replace(".", "", 1).isdigit() else None
            if "perday" in lowered or "billing" in lowered or "limit: 0" in lowered:
                return ProviderError(ErrorKind.QUOTA, "gemini", exc.message or "", status_code=code, retry_after=retry_after)
            return ProviderError(ErrorKind.RATE_LIMIT, "gemini", exc.message or "", status_code=code, retry_after=retry_after)
        if code == 404 or status == "NOT_FOUND":
            return ProviderError(ErrorKind.MODEL_NOT_FOUND, "gemini", exc.message or "", status_code=code)
        if code == 400 and ("api key" in lowered or "api_key" in lowered):
            return ProviderError(ErrorKind.AUTH, "gemini", exc.message or "", status_code=code)
        if code in (400, 422) or status == "INVALID_ARGUMENT":
            if "not supported" in lowered or "unsupported" in lowered:
                return ProviderError(ErrorKind.MODEL_NOT_FOUND, "gemini", exc.message or "", status_code=code)
            return ProviderError(ErrorKind.BAD_REQUEST, "gemini", exc.message or "", status_code=code)
        if code == 504 or status == "DEADLINE_EXCEEDED":
            return ProviderError(ErrorKind.TIMEOUT, "gemini", exc.message or "", status_code=code)
        if code >= 500:
            return ProviderError(ErrorKind.SERVER, "gemini", exc.message or "", status_code=code)
        return ProviderError(ErrorKind.UNKNOWN, "gemini", exc.message or "", status_code=code)
    if isinstance(exc, (httpx.TimeoutException, asyncio.TimeoutError, TimeoutError)):
        return ProviderError(ErrorKind.TIMEOUT, "gemini", type(exc).__name__)
    if isinstance(exc, (httpx.TransportError, ConnectionError, OSError)):
        return ProviderError(ErrorKind.NETWORK, "gemini", type(exc).__name__)
    return ProviderError(ErrorKind.UNKNOWN, "gemini", type(exc).__name__)


class GeminiProvider(ModelProvider):
    name = "gemini"

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self._settings = settings
        self._key = secret(settings.gemini_api_key)
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(self._key)

    @property
    def model(self) -> str:
        return self._settings.gemini_default_model

    def _get_client(self) -> Any:
        if not self.configured:
            raise ProviderError(ErrorKind.NOT_CONFIGURED, self.name)
        if self._client is None:
            timeout_ms = int(self._settings.request_timeout_seconds * 1000 * 3)
            self._client = genai.Client(api_key=self._key, http_options=types.HttpOptions(timeout=timeout_ms))
        return self._client

    @staticmethod
    def _convert(messages: list[ChatMessage]) -> tuple[str | None, list[types.Content]]:
        system = "\n\n".join(m.content for m in messages if m.role == "system") or None
        contents: list[types.Content] = []
        for m in messages:
            if m.role == "system":
                continue
            role = "model" if m.role == "assistant" else "user"
            if contents and contents[-1].role == role and contents[-1].parts:
                contents[-1].parts.append(types.Part.from_text(text=m.content))
            else:
                contents.append(types.Content(role=role, parts=[types.Part.from_text(text=m.content)]))
        return system, contents

    def _config(self, system: str | None, temperature: float, max_tokens: int | None, json_mode: bool) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            max_output_tokens=max_tokens,
            response_mime_type="application/json" if json_mode else None,
        )

    async def generate(
        self, messages: list[ChatMessage], *, temperature: float = 0.3, max_tokens: int | None = None, json_mode: bool = False
    ) -> str:
        client = self._get_client()
        system, contents = self._convert(messages)
        try:
            response = await client.aio.models.generate_content(
                model=self.model, contents=contents, config=self._config(system, temperature, max_tokens, json_mode)
            )
        except Exception as exc:
            raise classify_gemini_error(exc) from exc
        text = response.text or ""
        if not text.strip():
            raise ProviderError(ErrorKind.INVALID_OUTPUT, self.name, "empty response (possibly blocked by safety filters)")
        return text

    async def stream(self, messages: list[ChatMessage], *, temperature: float = 0.3, max_tokens: int | None = None) -> AsyncIterator[str]:
        client = self._get_client()
        system, contents = self._convert(messages)
        try:
            iterator = await client.aio.models.generate_content_stream(
                model=self.model, contents=contents, config=self._config(system, temperature, max_tokens, False)
            )
            async for chunk in iterator:
                if chunk.text:
                    yield chunk.text
        except Exception as exc:
            raise classify_gemini_error(exc) from exc
