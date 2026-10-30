"""API contract tests: chat/research streaming, history, documents, reports/PDF, settings, SSE resume."""

import asyncio
import json

import httpx
import pymupdf
import pytest
from sqlalchemy import select

from app.db.models import Report, Source
from app.db.session import session_factory
from app.main import create_app
from tests.conftest import FakeProvider, FakeSearchProvider, provider_error, research_handler


def parse_sse(text: str) -> list[dict]:
    events = []
    for block in text.strip().split("\n\n"):
        ev: dict = {}
        for line in block.splitlines():
            if line.startswith("event: "):
                ev["type"] = line[7:]
            elif line.startswith("data: "):
                ev["data"] = json.loads(line[6:])
            elif line.startswith("id: "):
                ev["id"] = int(line[4:])
        if "type" in ev:
            events.append(ev)
    return events


@pytest.fixture
async def client(db, settings):
    app = create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_chat_streams_persists_and_history_survives(client, make_router, build_services):
    build_services(make_router(FakeProvider("gemini"), FakeProvider("nvidia")))
    r = await client.post("/api/chat", json={"message": "Hello there", "mode": "chat"})
    events = parse_sse(r.text)
    types = [e["type"] for e in events]
    assert types[0] == "meta" and "provider" in types and "token" in types and types[-1] == "done"
    conv_id = events[0]["data"]["conversation_id"]
    assert events[-1]["data"]["provider"] == "gemini"

    # second turn in same conversation, then "refresh": reload from API
    await client.post("/api/chat", json={"conversation_id": conv_id, "message": "More", "mode": "chat"})
    detail = (await client.get(f"/api/conversations/{conv_id}")).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant", "user", "assistant"]
    assert detail["messages"][1]["content"] == "streamed from gemini" and detail["messages"][1]["provider"] == "gemini"
    assert detail["title"] == "Hello there" and detail["mode"] == "chat"

    listing = (await client.get("/api/conversations", params={"q": "More"})).json()
    assert [c["id"] for c in listing] == [conv_id]

    renamed = (await client.patch(f"/api/conversations/{conv_id}", json={"title": "Renamed"})).json()
    assert renamed["title"] == "Renamed"
    assert (await client.delete(f"/api/conversations/{conv_id}")).status_code == 204
    assert (await client.get(f"/api/conversations/{conv_id}")).status_code == 404


async def test_chat_falls_back_to_nvidia_mid_stream(client, make_router, build_services):
    g = FakeProvider("gemini", stream_script=[["partial ", provider_error("server")]])
    build_services(make_router(g, FakeProvider("nvidia")))
    events = parse_sse((await client.post("/api/chat", json={"message": "hi"})).text)
    types = [e["type"] for e in events]
    assert "reset" in types
    done = events[-1]["data"]
    assert done["provider"] == "nvidia" and done["content"] == "streamed from nvidia"


async def test_regenerate_replaces_last_answer(client, make_router, build_services):
    build_services(make_router(FakeProvider("gemini")))
    conv = parse_sse((await client.post("/api/chat", json={"message": "hi"})).text)[0]["data"]["conversation_id"]
    await client.post("/api/chat", json={"conversation_id": conv, "regenerate": True})
    msgs = (await client.get(f"/api/conversations/{conv}")).json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]


async def test_chat_error_when_no_provider(client, make_router, build_services):
    build_services(make_router(FakeProvider("gemini", configured=False), FakeProvider("nvidia", configured=False)))
    events = parse_sse((await client.post("/api/chat", json={"message": "hi"})).text)
    err = next(e for e in events if e["type"] == "error")
    assert "GEMINI_API_KEY" in err["data"]["message"]


async def test_research_mode_cites_stored_sources(client, make_router, build_services, allow_all_urls):
    build_services(make_router(FakeProvider("gemini", handler=research_handler)), [FakeSearchProvider()])
    events = parse_sse((await client.post("/api/chat", json={"message": "solar adoption", "mode": "research"})).text)
    types = [e["type"] for e in events]
    assert "query" in types and "source_found" in types and "source_read" in types
    done = events[-1]["data"]
    assert "[42]" not in done["content"] and "[1]" in done["content"] and done["invalid_citations_removed"] == 1
    async with session_factory()() as s:
        sources = list((await s.execute(select(Source).where(Source.message_id == done["message_id"]))).scalars())
    assert {1, 2} <= {src.number for src in sources}


async def test_research_mode_without_search_says_unavailable_but_chat_works(client, make_router, build_services):
    build_services(make_router(FakeProvider("gemini")), [FakeSearchProvider(configured=False)])
    events = parse_sse((await client.post("/api/chat", json={"message": "x", "mode": "research"})).text)
    assert any(e["type"] == "error" and "unavailable" in e["data"]["message"] for e in events)
    events = parse_sse((await client.post("/api/chat", json={"message": "x", "mode": "chat"})).text)
    assert events[-1]["data"]["content"] == "streamed from gemini"


async def test_deep_research_endpoints_and_sse_resume(client, make_router, build_services, allow_all_urls):
    services = build_services(make_router(FakeProvider("gemini", handler=research_handler)), [FakeSearchProvider()])
    started = (await client.post("/api/research", json={"question": "Solar energy adoption?"})).json()
    job_id = started["job_id"]
    task = services.jobs._tasks.get(job_id)
    if task:
        await task
    events = parse_sse((await client.get(f"/api/research/{job_id}/events")).text)
    assert events[-1]["type"] == "done"
    mid = events[len(events) // 2]["id"]
    resumed = parse_sse((await client.get(f"/api/research/{job_id}/events", headers={"Last-Event-ID": str(mid)})).text)
    assert resumed[0]["id"] > mid and resumed[-1]["type"] == "done"

    job = (await client.get(f"/api/research/{job_id}")).json()
    assert job["status"] == "completed"
    report = (await client.get(f"/api/reports/{job['report_id']}")).json()
    assert report["sources"] and report["verification"]["ran"]
    assert (await client.get("/api/reports")).json()[0]["id"] == report["id"]
    conv = (await client.get(f"/api/conversations/{started['conversation_id']}")).json()
    assert conv["mode"] == "deep_research" and conv["messages"][-1]["meta"]["report_id"] == report["id"]


async def test_report_pdf_export_is_valid(client, make_router, build_services):
    build_services(make_router(FakeProvider("gemini")))
    md = (
        "# Test Report Title\n\n*Generated 2026-10-29 by ARVEN AI Deep Research*\n\n## Executive summary\n\n"
        "Solar works **well** [1].\n\n- item one [1]\n- item two\n\n| Option | Cost |\n|---|---|\n| A | low |\n\n"
        "## References\n\n1. Example source. example.org. Retrieved 2026-10-29. <https://example.org/a?x=1&y=2>\n"
    )
    async with session_factory()() as s:
        rep = Report(title="Test Report Title", markdown=md)
        s.add(rep)
        await s.commit()
        rid = rep.id
    r = await client.get(f"/api/reports/{rid}/pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content[:5] == b"%PDF-"
    with pymupdf.open(stream=r.content, filetype="pdf") as doc:
        text = "".join(p.get_text() for p in doc)
        links = [lnk.get("uri") for p in doc for lnk in p.get_links() if lnk.get("uri")]
    assert "Test Report Title" in text and "Executive summary" in text and "References" in text and "low" in text
    assert "https://example.org/a?x=1&y=2" in links


def _make_pdf(text_pages: list[str]) -> bytes:
    doc = pymupdf.open()
    for t in text_pages:
        page = doc.new_page()
        if t:
            page.insert_textbox(pymupdf.Rect(50, 50, 550, 800), t)
    data = doc.tobytes()
    doc.close()
    return data


async def test_pdf_upload_extraction_and_chat_context(client, make_router, build_services):
    captured = {}

    def handler(messages, json_mode):
        captured["system"] = messages[0].content
        return "answer"

    build_services(make_router(FakeProvider("gemini", handler=handler)))
    pdf = _make_pdf(["Intro page about nothing in particular. " * 5, "The photosynthesis rate doubles at noon. " * 5])
    r = await client.post("/api/documents", files={"file": ("../../evil name.pdf", pdf, "application/pdf")})
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["page_count"] == 2 and doc["has_text"] and doc["filename"] == "evil name.pdf"
    await client.post("/api/chat", json={"message": "What about photosynthesis rate?", "document_ids": [doc["id"]]})
    assert "page 2" in captured["system"] and "photosynthesis" in captured["system"]
    assert (await client.delete(f"/api/documents/{doc['id']}")).status_code == 204


async def test_scanned_pdf_and_invalid_upload(client, make_router, build_services):
    build_services(make_router(FakeProvider("gemini")))
    r = await client.post("/api/documents", files={"file": ("scan.pdf", _make_pdf(["", ""]), "application/pdf")})
    assert r.status_code == 201 and r.json()["has_text"] is False and r.json()["status"] == "no_text"
    r = await client.post("/api/documents", files={"file": ("fake.pdf", b"MZ not a pdf", "application/pdf")})
    assert r.status_code == 415


async def test_settings_status_and_connection_tests(client, make_router, build_services, monkeypatch):
    g = FakeProvider("gemini", script=[provider_error("auth")])
    build_services(make_router(g, FakeProvider("nvidia", configured=False)), [FakeSearchProvider(configured=False)])
    res = (await client.post("/api/settings/test/gemini")).json()
    assert res["ok"] is False and res["kind"] == "auth"
    assert (await client.post("/api/settings/test/nvidia")).json()["ok"] is False
    assert (await client.post("/api/settings/test/tavily")).json()["ok"] is False
    status = (await client.get("/api/settings/status")).json()
    assert status["overall"] == "key_missing_or_invalid"
    assert status["search"]["available"] is False
    assert {p["name"]: p["state"] for p in status["providers"]}["gemini"] == "key_missing_or_invalid"
    assert (await client.post("/api/settings/test/unknown")).status_code == 422


async def test_cors_only_allows_local_frontend(client, make_router, build_services):
    build_services(make_router(FakeProvider("gemini")))
    ok = await client.options("/api/health", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    bad = await client.options("/api/health", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-origin" not in bad.headers


async def test_rejects_foreign_host_and_origin(client, make_router, build_services):
    build_services(make_router(FakeProvider("gemini"), FakeProvider("nvidia")))
    # DNS rebinding: a page on attacker.example resolving to 127.0.0.1 sends its own Host header.
    r = await client.get("/api/conversations", headers={"Host": "attacker.example"})
    assert r.status_code == 400
    r = await client.delete("/api/conversations/x", headers={"Origin": "https://attacker.example"})
    assert r.status_code == 403
    r = await client.get("/api/health")
    assert r.status_code == 200


async def test_access_password_gates_api(monkeypatch, db, make_router, build_services):
    from app.api import auth
    from app.config import get_settings

    monkeypatch.setenv("ACCESS_PASSWORD", "correct horse")
    get_settings.cache_clear()
    real_sleep = asyncio.sleep
    monkeypatch.setattr(auth.asyncio, "sleep", lambda _s: real_sleep(0))
    auth._failures.clear()
    build_services(make_router(FakeProvider("gemini"), FakeProvider("nvidia")))
    app = create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.get("/api/health")).status_code == 200
        assert (await c.get("/api/conversations")).status_code == 401
        assert (await c.get("/api/auth/status")).json() == {"required": True, "authenticated": False}
        assert (await c.post("/api/auth/login", json={"password": "wrong"})).status_code == 401
        token = (await c.post("/api/auth/login", json={"password": "correct horse"})).json()["token"]
        h = {"Authorization": f"Bearer {token}"}
        assert (await c.get("/api/conversations", headers=h)).status_code == 200
        assert (await c.get(f"/api/conversations?access_token={token}")).status_code == 200
        # query tokens are only accepted on GET
        assert (await c.delete(f"/api/conversations/x?access_token={token}")).status_code == 401
        assert (await c.get("/api/conversations", headers={"Authorization": "Bearer 1.bad"})).status_code == 401
        assert (await c.get("/api/auth/status", headers=h)).json()["authenticated"] is True
    get_settings.cache_clear()


def test_tokens_expire_and_rotate_with_password():
    from app.api.auth import TOKEN_TTL_SECONDS, issue_token, token_valid

    t = issue_token("pw", now=1000)
    assert token_valid(t, "pw", now=1001)
    assert not token_valid(t, "pw", now=1000 + TOKEN_TTL_SECONDS + 1)
    assert not token_valid(t, "other", now=1001)
