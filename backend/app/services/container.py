"""Process-wide service container (wired in main.py lifespan, overridable in tests)."""

from dataclasses import dataclass

from app.config import Settings
from app.services.providers.gemini import GeminiProvider
from app.services.providers.nvidia import NvidiaProvider
from app.services.providers.router import ProviderRouter
from app.services.research.jobs import JobManager
from app.services.research.orchestrator import DeepResearchOrchestrator
from app.services.search.base import SearchProvider
from app.services.search.duckduckgo import DuckDuckGoSearchProvider
from app.services.search.service import SearchService
from app.services.search.tavily import TavilySearchProvider


@dataclass
class Services:
    settings: Settings
    router: ProviderRouter
    search: SearchService
    jobs: JobManager
    orchestrator: DeepResearchOrchestrator


def build_services(settings: Settings) -> Services:
    router = ProviderRouter([GeminiProvider(settings), NvidiaProvider(settings)], settings)
    providers: list[SearchProvider] = [TavilySearchProvider(settings)]
    if settings.enable_duckduckgo_fallback:
        providers.append(DuckDuckGoSearchProvider())
    search = SearchService(providers, settings)
    jobs = JobManager()
    return Services(settings, router, search, jobs, DeepResearchOrchestrator(router, search, jobs, settings))


_services: Services | None = None


def set_services(services: Services | None) -> None:
    global _services
    _services = services


def get_services() -> Services:
    if _services is None:
        raise RuntimeError("services not initialized")
    return _services
