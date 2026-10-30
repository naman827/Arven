"""Shared provider interface."""

import json
import re
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ValidationError

from app.services.providers.errors import ErrorKind, ProviderError

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class ChatMessage:
    role: Role
    content: str


class ModelProvider(ABC):
    name: str

    @property
    @abstractmethod
    def configured(self) -> bool: ...

    @property
    @abstractmethod
    def model(self) -> str: ...

    @abstractmethod
    async def generate(
        self, messages: list[ChatMessage], *, temperature: float = 0.3, max_tokens: int | None = None, json_mode: bool = False
    ) -> str: ...

    @abstractmethod
    def stream(self, messages: list[ChatMessage], *, temperature: float = 0.3, max_tokens: int | None = None) -> AsyncIterator[str]: ...

    async def generate_structured[T: BaseModel](self, messages: list[ChatMessage], schema: type[T]) -> T:
        """JSON output validated by Pydantic, with one repair retry."""
        instruction = "Respond with a single JSON object only, no prose or code fences, matching this JSON schema:\n" + json.dumps(
            schema.model_json_schema()
        )
        msgs = [*messages, ChatMessage("user", instruction)]
        raw = await self.generate(msgs, temperature=0.2, json_mode=True)
        try:
            return schema.model_validate(extract_json(raw))
        except (ValidationError, ValueError) as first:
            repair = [
                *msgs,
                ChatMessage("assistant", raw[:4000]),
                ChatMessage("user", f"That output was invalid: {str(first)[:600]}. Return corrected JSON only."),
            ]
            raw2 = await self.generate(repair, temperature=0.0, json_mode=True)
            try:
                return schema.model_validate(extract_json(raw2))
            except (ValidationError, ValueError) as second:
                raise ProviderError(ErrorKind.INVALID_OUTPUT, self.name, str(second)) from second

    async def test_connection(self) -> str:
        # Thinking models spend output tokens on reasoning before answering, so a tiny cap returns nothing.
        reply = await self.generate([ChatMessage("user", "Reply with the single word: ok")], max_tokens=1024)
        return reply.strip()[:40]


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def extract_json(text: str) -> object:
    cleaned = _FENCE.sub("", text.strip()).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("no JSON object found in model output") from None
        return json.loads(cleaned[start : end + 1])
