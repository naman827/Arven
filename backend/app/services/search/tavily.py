"""Tavily search + extract (primary)."""

from typing import Any

from tavily import AsyncTavilyClient
from tavily import errors as tavily_errors

from app.config import Settings, secret
from app.services.search.base import SearchError, SearchProvider, SearchResult
from app.services.search.url_safety import canonicalize_url, domain_of


def _classify(exc: Exception) -> SearchError:
    if isinstance(exc, (tavily_errors.InvalidAPIKeyError, tavily_errors.MissingAPIKeyError)):
        return SearchError("tavily", "Tavily API key is missing or invalid.", kind="auth")
    if isinstance(exc, tavily_errors.UsageLimitExceededError):
        return SearchError("tavily", "Tavily usage limit exceeded.", kind="quota")
    if isinstance(exc, tavily_errors.ForbiddenError):
        return SearchError("tavily", "Tavily denied the request (forbidden).", kind="auth")
    if isinstance(exc, tavily_errors.TimeoutError):
        return SearchError("tavily", "Tavily timed out.", kind="network")
    if isinstance(exc, tavily_errors.BadRequestError):
        return SearchError("tavily", "Tavily rejected the request.", kind="error")
    return SearchError("tavily", f"Tavily request failed ({type(exc).__name__}).", kind="network")


class TavilySearchProvider(SearchProvider):
    name = "tavily"

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self._key = secret(settings.tavily_api_key)
        self._timeout = settings.request_timeout_seconds
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(self._key)

    def _get_client(self) -> Any:
        if not self.configured:
            raise SearchError("tavily", "Tavily API key is not configured.", kind="auth")
        if self._client is None:
            self._client = AsyncTavilyClient(self._key)
        return self._client

    async def search(self, query: str, *, max_results: int = 5, topic: str = "general") -> list[SearchResult]:
        client = self._get_client()
        try:
            data = await client.search(
                query=query[:400],
                search_depth="basic",
                topic=topic if topic in ("general", "news", "finance") else "general",
                max_results=max_results,
                timeout=self._timeout,
            )
        except Exception as exc:
            raise _classify(exc) from exc
        results = []
        for item in data.get("results", []) or []:
            url = item.get("url") or ""
            if not url.startswith(("http://", "https://")):
                continue
            results.append(
                SearchResult(
                    title=(item.get("title") or url)[:300],
                    url=url,
                    canonical_url=canonicalize_url(url),
                    domain=domain_of(url),
                    snippet=(item.get("content") or "")[:1200],
                    score=float(item.get("score") or 0.0),
                    published_date=item.get("published_date"),
                    provider=self.name,
                )
            )
        return results

    async def extract(self, urls: list[str], *, query: str | None = None) -> dict[str, str | Exception]:
        client = self._get_client()
        out: dict[str, str | Exception] = {}
        try:
            data = await client.extract(urls=urls[:20], extract_depth="basic", format="text", timeout=min(self._timeout * 2, 60))
        except Exception as exc:
            err = _classify(exc)
            return {u: err for u in urls}
        for item in data.get("results", []) or []:
            if item.get("url"):
                out[item["url"]] = item.get("raw_content") or ""
        for item in data.get("failed_results", []) or []:
            if item.get("url"):
                out[item["url"]] = SearchError("tavily", str(item.get("error") or "extraction failed")[:200])
        for u in urls:
            out.setdefault(u, SearchError("tavily", "no extraction result returned"))
        return out
