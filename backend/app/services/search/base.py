"""Search provider interface and normalized result types."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class SearchResult:
    title: str
    url: str
    canonical_url: str
    domain: str
    snippet: str
    score: float = 0.0
    published_date: str | None = None
    content: str = ""  # extracted text, filled by extract()
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    provider: str = ""
    readable: bool | None = None  # None = not read yet
    error: str | None = None


class SearchError(Exception):
    def __init__(self, provider: str, message: str, *, kind: str = "error") -> None:
        self.provider = provider
        self.kind = kind  # auth | quota | rate_limit | network | error
        self.message = message
        super().__init__(f"{provider}: {message}")


class SearchProvider(ABC):
    name: str

    @property
    @abstractmethod
    def configured(self) -> bool: ...

    @abstractmethod
    async def search(self, query: str, *, max_results: int = 5, topic: str = "general") -> list[SearchResult]: ...

    async def extract(self, urls: list[str], *, query: str | None = None) -> dict[str, str | Exception]:
        """Return {url: text or exception}. Default: unsupported."""
        return {u: NotImplementedError("extract not supported") for u in urls}
