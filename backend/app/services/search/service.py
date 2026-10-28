"""SearchService: provider fallback, normalization, dedupe, and SSRF-safe reading."""

import asyncio
import logging
import re
import time
from html.parser import HTMLParser

import httpx

from app.config import Settings
from app.services.search.base import SearchError, SearchProvider, SearchResult
from app.services.search.url_safety import UnsafeURLError, resolve_and_check, safe_fetch

log = logging.getLogger(__name__)

MIN_READABLE_CHARS = 300
MAX_CONTENT_CHARS = 60_000


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "nav", "footer", "header", "svg", "form", "aside", "template"}
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article", "pre", "blockquote"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP:
            self.skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self.skip_depth:
            self.skip_depth -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif not self.skip_depth:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:
        return ""
    text = "".join(parser.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def _pdf_bytes_to_text(data: bytes) -> str:
    import pymupdf

    with pymupdf.open(stream=data, filetype="pdf") as doc:
        return "\n\n".join(page.get_text() for page in doc)[:MAX_CONTENT_CHARS]


def _shingles(text: str) -> set[str]:
    words = re.findall(r"\w+", text.lower())
    return {" ".join(words[i : i + 4]) for i in range(max(0, len(words) - 3))}


def dedupe(results: list[SearchResult]) -> list[SearchResult]:
    seen: dict[str, SearchResult] = {}
    kept: list[SearchResult] = []
    shingle_cache: list[set[str]] = []
    for r in sorted(results, key=lambda x: -x.score):
        if r.canonical_url in seen:
            continue
        sh = _shingles(r.snippet)
        duplicate = False
        if len(sh) >= 8:
            for other in shingle_cache:
                if other and len(sh & other) / len(sh | other) > 0.85:
                    duplicate = True
                    break
        if duplicate:
            continue
        seen[r.canonical_url] = r
        shingle_cache.append(sh)
        kept.append(r)
    return kept


class SearchService:
    def __init__(self, providers: list[SearchProvider], settings: Settings, http_client: httpx.AsyncClient | None = None) -> None:
        self.providers = providers
        self.settings = settings
        self._http = http_client
        self._sem = asyncio.Semaphore(settings.max_concurrent_requests)
        self._disabled_until: dict[str, float] = {}
        self._last_error: dict[str, str] = {}

    @property
    def http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self.settings.request_timeout_seconds)
        return self._http

    def _usable(self) -> list[SearchProvider]:
        now = time.monotonic()
        return [p for p in self.providers if p.configured and self._disabled_until.get(p.name, 0) <= now]

    @property
    def available(self) -> bool:
        return bool(self._usable())

    def status(self) -> list[dict[str, object]]:
        now = time.monotonic()
        out = []
        for p in self.providers:
            disabled = self._disabled_until.get(p.name, 0) > now
            state = "not_configured" if not p.configured else ("unavailable" if disabled else "ready")
            out.append({"name": p.name, "configured": p.configured, "state": state, "last_error": self._last_error.get(p.name)})
        return out

    def _penalize(self, error: SearchError) -> None:
        self._last_error[error.provider] = error.message
        cooldown = {"auth": 3600, "quota": 1800, "rate_limit": 60}.get(error.kind, 0)
        if cooldown:
            self._disabled_until[error.provider] = time.monotonic() + cooldown

    async def search(self, query: str, *, max_results: int = 5, topic: str = "general") -> list[SearchResult]:
        """Search one query, falling back across providers. Raises SearchError if all fail."""
        errors: list[SearchError] = []
        async with self._sem:
            for provider in self._usable():
                try:
                    results = await provider.search(query, max_results=max_results, topic=topic)
                except SearchError as err:
                    self._penalize(err)
                    errors.append(err)
                    continue
                self._last_error.pop(provider.name, None)
                return results
        if not errors:
            raise SearchError("search", "No web search provider is configured. Add TAVILY_API_KEY to .env.", kind="auth")
        raise SearchError("search", "; ".join(e.message for e in errors))

    async def search_many(
        self, queries: list[str], *, max_results: int = 5, topic: str = "general"
    ) -> tuple[list[SearchResult], list[str]]:
        outcomes = await asyncio.gather(*(self.search(q, max_results=max_results, topic=topic) for q in queries), return_exceptions=True)
        results: list[SearchResult] = []
        errors: list[str] = []
        for q, outcome in zip(queries, outcomes, strict=True):
            if isinstance(outcome, SearchError):
                errors.append(f"{q}: {outcome.message}")
            elif isinstance(outcome, BaseException):
                errors.append(f"{q}: unexpected error ({type(outcome).__name__})")
            else:
                results.extend(outcome)
        return dedupe(results), errors

    async def _fetch_text(self, url: str) -> str:
        async with self._sem:
            fetched = await safe_fetch(url, client=self.http, timeout=self.settings.request_timeout_seconds)
        if fetched.status_code in (401, 402, 403):
            raise UnsafeURLError(f"access denied (HTTP {fetched.status_code}, possibly paywalled or blocked)")
        if fetched.status_code >= 400:
            raise UnsafeURLError(f"HTTP {fetched.status_code}")
        if fetched.content_type == "application/pdf" or fetched.body[:5] == b"%PDF-":
            return await asyncio.to_thread(_pdf_bytes_to_text, fetched.body)
        return html_to_text(fetched.body.decode("utf-8", errors="replace"))

    async def read(self, results: list[SearchResult], *, query: str | None = None) -> list[SearchResult]:
        """Fill `content`; mark unreadable sources honestly. Only SSRF-checked URLs are fetched."""
        safe: list[SearchResult] = []
        for r in results:
            try:
                await resolve_and_check(r.url)
            except UnsafeURLError as exc:
                r.readable, r.error = False, f"blocked: {exc}"
                continue
            safe.append(r)

        extracted: dict[str, str | Exception] = {}
        extractor = next((p for p in self._usable() if type(p).extract is not SearchProvider.extract), None)
        if extractor and safe:
            try:
                extracted = await extractor.extract([r.url for r in safe], query=query)
            except Exception as exc:  # extraction failure falls through to direct fetch
                log.info("extract failed: %s", type(exc).__name__)

        async def finish(r: SearchResult) -> None:
            text = extracted.get(r.url)
            if not isinstance(text, str) or len(text.strip()) < MIN_READABLE_CHARS:
                try:
                    text = await self._fetch_text(r.url)
                except (UnsafeURLError, httpx.HTTPError, OSError, RuntimeError, ValueError) as exc:
                    r.readable, r.error = False, str(exc)[:200] or type(exc).__name__
                    return
            text = (text or "").strip()
            if len(text) < MIN_READABLE_CHARS:
                r.readable, r.error = False, "no readable text (possibly paywalled, blocked, or script-rendered)"
                return
            r.content, r.readable, r.error = text[:MAX_CONTENT_CHARS], True, None

        await asyncio.gather(*(finish(r) for r in safe))
        return results

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
