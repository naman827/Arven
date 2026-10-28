"""DuckDuckGo fallback via the `ddgs` library. Best effort: unofficial, rate-limited, less reliable."""

import asyncio
from collections.abc import Callable
from typing import Any

from app.services.search.base import SearchError, SearchProvider, SearchResult
from app.services.search.url_safety import canonicalize_url, domain_of


def _default_search(query: str, max_results: int) -> list[dict[str, Any]]:
    from ddgs import DDGS

    return DDGS(timeout=10).text(query, max_results=max_results, backend="duckduckgo")


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
                rows = await asyncio.wait_for(asyncio.to_thread(self._search_fn, query[:300], max_results), timeout=20)
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
