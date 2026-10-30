"""Search normalization, dedupe, SSRF protection, unreadable reporting, provider fallback."""

import httpx
import pytest
import respx

from app.services.search.base import SearchError, SearchResult
from app.services.search.duckduckgo import DuckDuckGoSearchProvider
from app.services.search.service import SearchService, dedupe, html_to_text
from app.services.search.tavily import TavilySearchProvider
from app.services.search.url_safety import UnsafeURLError, canonicalize_url, resolve_and_check, safe_fetch
from tests.conftest import FakeSearchProvider


def test_canonicalize_strips_tracking_and_normalizes():
    a = canonicalize_url("HTTP://www.Example.com/path/?utm_source=x&b=2&a=1&fbclid=zzz#frag")
    b = canonicalize_url("https://example.com/path?a=1&b=2")
    assert a == b == "https://example.com/path?a=1&b=2"


def _r(url: str, snippet: str, score: float = 0.5) -> SearchResult:
    return SearchResult(title=url, url=url, canonical_url=canonicalize_url(url), domain="d", snippet=snippet, score=score)


def test_dedupe_by_url_and_near_duplicate_content():
    text = "the quick brown fox jumps over the lazy dog near the river bank today and tomorrow"
    results = [
        _r("https://a.com/x?utm_campaign=1", "unique one about cats and many other words in here", 0.9),
        _r("https://a.com/x", "duplicate url", 0.5),
        _r("https://b.com/1", text, 0.8),
        _r("https://c.com/2", text + " extra", 0.7),
    ]
    out = dedupe(results)
    assert [r.url for r in out] == ["https://a.com/x?utm_campaign=1", "https://b.com/1"]


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://localhost:8000/",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://100.64.0.1/",
        "file:///etc/passwd",
        "ftp://example.com/file",
        "http://user:pass@example.com/",
        "http://metadata.google.internal/",
    ],
)
async def test_ssrf_blocked(url):
    with pytest.raises(UnsafeURLError):
        await resolve_and_check(url)


async def test_public_ip_literal_allowed():
    await resolve_and_check("https://93.184.216.34/")


@respx.mock
async def test_redirect_to_private_address_is_blocked():
    respx.get("https://93.184.216.34/start").mock(return_value=httpx.Response(302, headers={"location": "http://127.0.0.1/secret"}))
    async with httpx.AsyncClient() as client:
        with pytest.raises(UnsafeURLError):
            await safe_fetch("https://93.184.216.34/start", client=client)


@respx.mock
async def test_disallowed_content_type_and_size_cap():
    respx.get("https://93.184.216.34/bin").mock(
        return_value=httpx.Response(200, headers={"content-type": "application/octet-stream"}, content=b"x")
    )
    respx.get("https://93.184.216.34/big").mock(
        return_value=httpx.Response(200, headers={"content-type": "text/html"}, content=b"a" * (4 * 1024 * 1024))
    )
    async with httpx.AsyncClient() as client:
        with pytest.raises(UnsafeURLError, match="content type"):
            await safe_fetch("https://93.184.216.34/bin", client=client)
        with pytest.raises(UnsafeURLError, match="too large"):
            await safe_fetch("https://93.184.216.34/big", client=client)


def test_html_to_text_drops_scripts():
    html = "<html><head><title>T</title><script>evil()</script></head><body><nav>menu</nav><p>Hello <b>world</b></p></body></html>"
    assert html_to_text(html) == "Hello world"


async def test_unreadable_sources_are_reported_honestly(settings, allow_all_urls):
    transport = httpx.MockTransport(lambda r: httpx.Response(403, headers={"content-type": "text/html"}))
    svc = SearchService([FakeSearchProvider(readable=False)], settings, http_client=httpx.AsyncClient(transport=transport))
    results = await svc.search("solar")
    await svc.read(results)
    assert all(r.readable is False for r in results)
    assert all("403" in (r.error or "") for r in results)


async def test_blocked_urls_never_fetched(settings):
    calls = []
    transport = httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(200))
    svc = SearchService([], settings, http_client=httpx.AsyncClient(transport=transport))
    r = _r("http://127.0.0.1/x", "s")
    await svc.read([r])
    assert r.readable is False and r.error and r.error.startswith("blocked") and not calls


async def test_readable_via_direct_fetch(settings, allow_all_urls):
    page = "<html><body><p>" + ("Solar evidence sentence. " * 40) + "</p></body></html>"
    transport = httpx.MockTransport(lambda r: httpx.Response(200, headers={"content-type": "text/html"}, text=page))
    svc = SearchService([FakeSearchProvider(readable=False)], settings, http_client=httpx.AsyncClient(transport=transport))
    results = await svc.search("solar")
    await svc.read(results)
    assert all(r.readable for r in results) and "Solar evidence" in results[0].content


async def test_search_provider_fallback_and_status(settings):
    primary = FakeSearchProvider(fail=SearchError("fakesearch", "Tavily usage limit exceeded.", kind="quota"))
    calls = []
    ddg = DuckDuckGoSearchProvider(search_fn=lambda q, n: calls.append(q) or [{"title": "T", "href": "https://x.org/a", "body": "b"}])
    svc = SearchService([primary, ddg], settings)
    out = await svc.search("query")
    assert out[0].provider == "duckduckgo" and calls == ["query"]
    states = {s["name"]: s["state"] for s in svc.status()}
    assert states == {"fakesearch": "unavailable", "duckduckgo": "ready"}


async def test_no_search_provider_means_unavailable(settings):
    svc = SearchService([TavilySearchProvider(settings), DuckDuckGoSearchProvider(enabled=False)], settings)
    assert svc.available is False
    with pytest.raises(SearchError, match="TAVILY_API_KEY"):
        await svc.search("x")
    assert {s["state"] for s in svc.status()} == {"not_configured"}


class _FakeTavilyClient:
    async def search(self, **kw):
        return {
            "results": [
                {"title": "A", "url": "https://www.a.com/p?utm_source=z", "content": "c", "score": 0.7, "published_date": "2026-01-02"},
                {"title": "bad", "url": "javascript:alert(1)", "content": "x", "score": 0.9},
            ]
        }

    async def extract(self, **kw):
        return {"results": [{"url": kw["urls"][0], "raw_content": "text"}], "failed_results": [{"url": kw["urls"][1], "error": "blocked"}]}


async def test_tavily_normalization_and_extract(settings, monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    from app.config import Settings

    t = TavilySearchProvider(Settings(), client=_FakeTavilyClient())
    out = await t.search("q")
    assert len(out) == 1 and out[0].canonical_url == "https://a.com/p" and out[0].published_date == "2026-01-02"
    ext = await t.extract(["https://a.com/1", "https://b.com/2"])
    assert ext["https://a.com/1"] == "text" and isinstance(ext["https://b.com/2"], SearchError)


def test_check_peer_blocks_rebinding_to_private_address():
    import httpx

    from app.services.search.url_safety import UnsafeURLError, check_peer

    class Stream:
        def __init__(self, ip: str) -> None:
            self.ip = ip

        def get_extra_info(self, name: str):
            return (self.ip, 443) if name == "server_addr" else None

    with pytest.raises(UnsafeURLError):
        check_peer(httpx.Response(200, extensions={"network_stream": Stream("127.0.0.1")}))
    with pytest.raises(UnsafeURLError):
        check_peer(httpx.Response(200, extensions={"network_stream": Stream("169.254.169.254")}))
    check_peer(httpx.Response(200, extensions={"network_stream": Stream("93.184.215.14")}))
    check_peer(httpx.Response(200))  # mock transport: nothing to check
