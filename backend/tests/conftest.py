"""Shared fixtures: isolated settings/DB, scripted fake providers, fake search."""

import json
import re
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.config import Settings, get_settings
from app.db import session as db_session
from app.services.container import Services, set_services
from app.services.providers.base import ChatMessage, ModelProvider
from app.services.providers.errors import ProviderError
from app.services.providers.router import ProviderRouter
from app.services.research.jobs import JobManager
from app.services.research.orchestrator import DeepResearchOrchestrator
from app.services.search import service as search_service_mod
from app.services.search.base import SearchProvider, SearchResult
from app.services.search.service import SearchService
from app.services.search.url_safety import canonicalize_url, domain_of


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    for key in ("GEMINI_API_KEY", "NVIDIA_API_KEY", "TAVILY_API_KEY"):
        monkeypatch.setenv(key, "")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MAX_RETRY_ATTEMPTS", "2")
    monkeypatch.setenv("ALLOWED_HOSTS", "127.0.0.1,localhost,test")
    get_settings.cache_clear()
    s = get_settings()
    yield s
    get_settings.cache_clear()


@pytest.fixture
async def db(settings: Settings) -> AsyncIterator[None]:
    await db_session.dispose_engine()
    await db_session.init_db()
    yield
    await db_session.dispose_engine()


Handler = Callable[[list[ChatMessage], bool], str]


class FakeProvider(ModelProvider):
    """Scripted provider. `script` items are str (reply) or Exception (raised). Falls back to `handler`."""

    def __init__(
        self,
        name: str,
        *,
        configured: bool = True,
        script: list[Any] | None = None,
        handler: Handler | None = None,
        stream_script: list[Any] | None = None,
        model: str = "fake-model",
    ) -> None:
        self.name = name
        self._configured = configured
        self.script = list(script or [])
        self.handler = handler
        self.stream_script = list(stream_script or [])
        self._model = model
        self.calls = 0
        self.stream_calls = 0

    @property
    def configured(self) -> bool:
        return self._configured

    @property
    def model(self) -> str:
        return self._model

    async def generate(self, messages, *, temperature=0.3, max_tokens=None, json_mode=False):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.script:
            item = self.script.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item
        if self.handler:
            return self.handler(messages, json_mode)
        return f"reply from {self.name}"

    async def stream(self, messages, *, temperature=0.3, max_tokens=None):  # type: ignore[no-untyped-def]
        self.stream_calls += 1
        if self.stream_script:
            plan = self.stream_script.pop(0)
            if isinstance(plan, BaseException):
                raise plan
            for piece in plan:
                if isinstance(piece, BaseException):
                    raise piece
                yield piece
            return
        text = self.handler(messages, False) if self.handler else f"streamed from {self.name}"
        for i in range(0, len(text), 40):
            yield text[i : i + 40]


async def no_sleep(_seconds: float) -> None:
    return None


@pytest.fixture
def make_router(settings: Settings) -> Callable[..., ProviderRouter]:
    def _make(*providers: ModelProvider) -> ProviderRouter:
        return ProviderRouter(list(providers), settings, sleep=no_sleep)

    return _make


# ---------------------------------------------------------------------------
# Deep-research script: replies chosen by inspecting the system prompt.


def research_handler(messages: list[ChatMessage], json_mode: bool) -> str:
    system = messages[0].content if messages else ""
    user = "\n".join(m.content for m in messages if m.role == "user")
    if "planning step" in system:
        return json.dumps(
            {
                "main_question": "What is solar energy adoption like?",
                "deliverable_type": "research report",
                "subquestions": [
                    {"question": "What drives solar adoption?", "evidence_needed": "drivers"},
                    {"question": "What does solar cost?", "evidence_needed": "costs"},
                    {"question": "What are solar limitations?", "evidence_needed": "limits"},
                ],
                "time_sensitive_claims": ["current prices"],
                "stop_conditions": ["coverage"],
            }
        )
    if "web search queries" in system:
        sub = re.search(r"Subquestion: (.+)", user)
        base = (sub.group(1) if sub else "solar")[:40]
        return json.dumps({"queries": [f"{base} official data", f"{base} critique"]})
    if "analysis step" in system:
        nums = sorted({int(n) for n in re.findall(r'label="\[(\d+)\]', user)})
        return json.dumps(
            {
                "findings": [{"statement": "Solar panels convert sunlight to electricity.", "citations": nums[:2]}],
                "coverage": 0.9,
                "gaps": [],
                "conflicts": [],
                "follow_up_queries": [],
            }
        )
    if "verify citations" in system:
        ids = [(int(m.group(1)), m.group(2)) for m in re.finditer(r"Claim (\d+): (.+)", user)]
        return json.dumps({"results": [{"id": i, "verdict": "unsupported" if "UNSUPPORTED" in text else "supported"} for i, text in ids]})
    if "writing step" in system:
        return (
            "# Solar Energy Adoption\n\n## Executive summary\n\nSolar panels convert sunlight to electricity [1]. "
            "This UNSUPPORTED claim says solar is free forever [2].\n\n## Findings\n\n"
            "- Costs have fallen sharply [2].\n- A fabricated claim cites a missing source [99].\n\n"
            "## References\n\n1. Should be stripped\n"
        )
    if "Research mode" in system:
        return "Solar is growing quickly [1]. Costs fell [2]. Bogus [42]."
    return "ok"


class FakeSearchProvider(SearchProvider):
    name = "fakesearch"

    def __init__(self, *, configured: bool = True, fail: Exception | None = None, readable: bool = True) -> None:
        self._configured = configured
        self.fail = fail
        self.readable = readable
        self.queries: list[str] = []

    @property
    def configured(self) -> bool:
        return self._configured

    async def search(self, query: str, *, max_results: int = 5, topic: str = "general") -> list[SearchResult]:
        if self.fail:
            raise self.fail
        self.queries.append(query)
        slug = re.sub(r"\W+", "-", query.lower()).strip("-")[:30]
        out = []
        for i in range(min(max_results, 3)):
            url = f"https://source{i}.example.org/{slug}"
            out.append(
                SearchResult(
                    title=f"{query} result {i}",
                    url=url,
                    canonical_url=canonicalize_url(url),
                    domain=domain_of(url),
                    snippet=f"Snippet about {query} number {i} with distinct words {slug} {i}",
                    score=1.0 - i * 0.1,
                    provider=self.name,
                )
            )
        return out

    async def extract(self, urls: list[str], *, query: str | None = None) -> dict[str, str | Exception]:
        if not self.readable:
            return {u: "" for u in urls}
        body = (
            "Solar panels convert sunlight to electricity using photovoltaic cells. "
            "Costs have fallen sharply over the past decade according to industry data. "
        ) * 8
        return {u: body for u in urls}


@pytest.fixture
def allow_all_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    async def ok(_url: str) -> None:
        return None

    from app.services.search import url_safety

    monkeypatch.setattr(search_service_mod, "resolve_and_check", ok)
    monkeypatch.setattr(url_safety, "resolve_and_check", ok)


@pytest.fixture
def build_services(settings: Settings) -> Callable[..., Services]:
    def _build(router: ProviderRouter, search_providers: list[SearchProvider] | None = None) -> Services:
        search = SearchService(
            search_providers or [], settings, http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(403)))
        )
        jobs = JobManager()
        services = Services(settings, router, search, jobs, DeepResearchOrchestrator(router, search, jobs, settings))
        set_services(services)
        return services

    yield _build
    set_services(None)


def provider_error(kind: str, provider: str = "gemini", **kw: Any) -> ProviderError:
    from app.services.providers.errors import ErrorKind

    return ProviderError(ErrorKind(kind), provider, "test", **kw)
