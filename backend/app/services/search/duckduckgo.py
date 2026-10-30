"""Free search fallback via the `ddgs` library (DuckDuckGo plus other engines). Best effort: unofficial, rate-limited."""

import asyncio
import time
from collections.abc import Callable
from typing import Any

from app.services.search.base import SearchError, SearchProvider, SearchResult
from app.services.search.url_safety import canonicalize_url, domain_of

# The DuckDuckGo engine alone often answers "No results found." when it rate-limits a client. ddgs can query
# other engines too; a second pass in a different order recovers most remaining failures.
_ENGINE_ORDERS = ("duckduckgo,yahoo,brave,mojeek", "yahoo,mojeek,brave,duckduckgo")
_RETRY_DELAY_SECONDS = 1.5


def _default_search(query: str, max_results: int) -> list[dict[str, Any]]:
    from ddgs import DDGS

    last: Exception | None = None
    for attempt, engines in enumerate(_ENGINE_ORDERS):
        if attempt:
            time.sleep(_RETRY_DELAY_SECONDS)
        try:
            return DDGS(timeout=10).text(query, max_results=max_results, backend=engines)
        except Exception as exc:  # ddgs raises DDGSException / TimeoutException / RatelimitException
            last = exc
    assert last is not None
    raise last


class DuckDuckGoSearchProvider(SearchProvider):
    name = "duckduckgo"

    def __init__(self, enabled: bool = True, search_fn: Callable[[str, int], list[dict[str, Any]]] | None = None) -> None:
        self._enabled = enabled
        self._search_fn = search_fn or _default_search
        self._lock = asyncio.Semaphore(1)  # be gentle; DDG rate-limits aggressively

    @property
    def configured(self) -> bool:
        return self._enabled

    async def search(self, query: str, *, max_results: int = 5, topic: str = "general") -> list[SearchResult]:
        if not self._enabled:
            raise SearchError(self.name, "DuckDuckGo fallback is disabled.", kind="auth")
        async with self._lock:
            try:
                rows = await asyncio.wait_for(asyncio.to_thread(self._search_fn, query[:300], max_results), timeout=30)
            except Exception as exc:
                kind = "rate_limit" if "ratelimit" in type(exc).__name__.lower() else "network"
                raise SearchError(self.name, f"DuckDuckGo search failed ({type(exc).__name__}).", kind=kind) from exc
        results = []
        for row in rows or []:
            url = row.get("href") or row.get("url") or ""
            if not url.startswith(("http://", "https://")):
                continue
            results.append(
                SearchResult(
                    title=(row.get("title") or url)[:300],
                    url=url,
                    canonical_url=canonicalize_url(url),
                    domain=domain_of(url),
                    snippet=(row.get("body") or "")[:1200],
                    provider=self.name,
                )
            )
        return results
