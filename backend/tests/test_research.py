"""Deep research flow, verifier, citation integrity, budgets, cancellation, failures."""

import asyncio
import json

from sqlalchemy import select

from app.db import session as db_session
from app.db.models import Conversation, Message, Report, ResearchEvent, ResearchJob, Source
from app.db.session import session_factory
from app.services.providers.base import ChatMessage
from app.services.research.budget import Budget
from app.services.research.reader import SourceRegistry, cited_numbers, strip_invalid_citations
from app.services.research.verifier import split_sentences, verify_report
from app.services.search.base import SearchResult
from app.services.search.url_safety import canonicalize_url
from tests.conftest import FakeProvider, FakeSearchProvider, research_handler


async def _make_job(question: str = "How is solar energy adoption going?", **options) -> str:
    async with session_factory()() as s:
        conv = Conversation(title="t", mode="deep_research")
        s.add(conv)
        await s.flush()
        job = ResearchJob(conversation_id=conv.id, question=question, options=options)
        s.add(job)
        await s.commit()
        return job.id


async def _events(job_id: str) -> list[ResearchEvent]:
    async with session_factory()() as s:
        return list((await s.execute(select(ResearchEvent).where(ResearchEvent.job_id == job_id).order_by(ResearchEvent.id))).scalars())


async def test_full_deep_research_flow(db, make_router, build_services, allow_all_urls):
    router = make_router(FakeProvider("gemini", handler=research_handler), FakeProvider("nvidia"))
    search = FakeSearchProvider()
    services = build_services(router, [search])
    job_id = await _make_job()
    await services.orchestrator.run(job_id)

    async with session_factory()() as s:
        job = await s.get(ResearchJob, job_id)
        assert job.status == "completed", job.error
        report = await s.get(Report, job.report_id)
        sources = list((await s.execute(select(Source).where(Source.job_id == job_id))).scalars())
        msgs = list((await s.execute(select(Message).where(Message.conversation_id == job.conversation_id))).scalars())

    statuses = [e.data.get("status") for e in await _events(job_id) if e.type == "status"]
    for expected in ("planning", "searching", "reading", "cross_checking", "synthesizing", "completed"):
        assert expected in statuses
    assert statuses.index("planning") < statuses.index("searching") < statuses.index("reading") < statuses.index("synthesizing")

    md = report.markdown
    body, refs = md.split("## References")
    stored = {src.number: src for src in sources}
    # every citation maps 1:1 to a stored, readable source
    for n in cited_numbers(body):
        assert n in stored and stored[n].readable
    assert "[99]" not in md, "citations to non-existent sources must be removed"
    assert "UNSUPPORTED" not in md, "verifier must remove unsupported claims"
    assert "Should be stripped" not in md, "model-written reference lists are replaced"
    for n in set(cited_numbers(body)):
        assert stored[n].url in refs
    v = report.verification
    assert v["ran"] and v["removed"] == 2 and v["invalid_citations_removed"] == 1 and v["claims_checked"] >= 2
    assert "fabricated claim" not in md, "a sentence citing only non-existent sources is removed"
    assert any(m.meta.get("report_id") == report.id for m in msgs)
    # distinct queries were generated per subquestion (not rewordings of one query)
    assert len(set(search.queries)) >= 6


async def test_budget_caps_sources_and_rounds(db, make_router, build_services, allow_all_urls, settings):
    router = make_router(FakeProvider("gemini", handler=research_handler))
    services = build_services(router, [FakeSearchProvider()])
    services.orchestrator.budget = Budget(max_search_rounds=1, max_unique_sources=4, max_report_words=500)
    job_id = await _make_job()
    await services.orchestrator.run(job_id)
    async with session_factory()() as s:
        sources = list((await s.execute(select(Source).where(Source.job_id == job_id))).scalars())
    assert len(sources) <= 4
    rounds = {e.data.get("round") for e in await _events(job_id) if e.type == "query"}
    assert rounds == {1}


def _gap_handler(messages, json_mode):
    system = messages[0].content
    if "analysis step" in system:
        return json.dumps(
            {"findings": [], "coverage": 0.1, "gaps": ["missing data"], "conflicts": [], "follow_up_queries": ["targeted follow up"]}
        )
    return research_handler(messages, json_mode)


async def test_gap_triggers_bounded_extra_round(db, make_router, build_services, allow_all_urls):
    router = make_router(FakeProvider("gemini", handler=_gap_handler))
    services = build_services(router, [FakeSearchProvider()])
    services.orchestrator.budget = Budget(max_search_rounds=2, max_unique_sources=40, max_report_words=500)
    job_id = await _make_job()
    await services.orchestrator.run(job_id)
    events = await _events(job_id)
    assert any(e.type == "gap_found" for e in events)
    assert {e.data.get("round") for e in events if e.type == "query"} == {1, 2}


async def test_research_fails_clearly_without_search(db, make_router, build_services):
    router = make_router(FakeProvider("gemini", handler=research_handler))
    services = build_services(router, [FakeSearchProvider(configured=False)])
    job_id = await _make_job()
    await services.orchestrator.run(job_id)
    async with session_factory()() as s:
        job = await s.get(ResearchJob, job_id)
    assert job.status == "failed" and "TAVILY_API_KEY" in job.error
    assert any(e.type == "error" for e in await _events(job_id))


async def test_all_sources_unreadable_fails_honestly(db, make_router, build_services, allow_all_urls):
    router = make_router(FakeProvider("gemini", handler=research_handler))
    services = build_services(router, [FakeSearchProvider(readable=False)])
    job_id = await _make_job()
    await services.orchestrator.run(job_id)
    async with session_factory()() as s:
        job = await s.get(ResearchJob, job_id)
    assert job.status == "failed" and "could be read" in job.error


async def test_cancellation(db, make_router, build_services, allow_all_urls):
    gate = asyncio.Event()

    class Slow(FakeProvider):
        async def generate(self, messages, **kw):  # type: ignore[override]
            await gate.wait()
            return await super().generate(messages, **kw)

    router = make_router(Slow("gemini", handler=research_handler))
    services = build_services(router, [FakeSearchProvider()])
    job_id = await _make_job()
    services.jobs.start(job_id, lambda: services.orchestrator.run(job_id))
    await asyncio.sleep(0.05)
    assert await services.jobs.cancel(job_id)
    async with session_factory()() as s:
        job = await s.get(ResearchJob, job_id)
    assert job.status == "cancelled"
    assert not services.jobs.is_running(job_id)


async def test_plan_review_waits_for_approval(db, make_router, build_services, allow_all_urls):
    router = make_router(FakeProvider("gemini", handler=research_handler))
    services = build_services(router, [FakeSearchProvider()])
    job_id = await _make_job(review_plan=True)
    services.jobs.start(job_id, lambda: services.orchestrator.run(job_id))
    for _ in range(50):
        await asyncio.sleep(0.02)
        async with session_factory()() as s:
            if (await s.get(ResearchJob, job_id)).status == "awaiting_plan_approval":
                break
    assert services.jobs.approve(job_id, {"subquestions": ["Only this one?"]})
    for _ in range(200):
        await asyncio.sleep(0.02)
        if not services.jobs.is_running(job_id):
            break
    async with session_factory()() as s:
        job = await s.get(ResearchJob, job_id)
    assert job.status == "completed" and [q["question"] for q in job.plan["subquestions"]] == ["Only this one?"]


async def test_interrupted_jobs_marked_failed_on_startup(db):
    job_id = await _make_job()
    async with session_factory()() as s:
        (await s.get(ResearchJob, job_id)).status = "searching"
        await s.commit()
    assert await db_session.mark_interrupted_jobs() == 1
    async with session_factory()() as s:
        job = await s.get(ResearchJob, job_id)
    assert job.status == "failed" and "interrupted" in job.error


async def test_event_replay_after_last_event_id(db, make_router, build_services, allow_all_urls):
    router = make_router(FakeProvider("gemini", handler=research_handler))
    services = build_services(router, [FakeSearchProvider()])
    job_id = await _make_job()
    await services.orchestrator.run(job_id)
    all_events = [e async for e in services.jobs.subscribe(job_id, 0)]
    assert all_events[-1]["type"] == "done"
    middle = all_events[len(all_events) // 2]["id"]
    resumed = [e async for e in services.jobs.subscribe(job_id, middle)]
    assert resumed and all(e["id"] > middle for e in resumed) and resumed[-1]["type"] == "done"


# ---- unit pieces -------------------------------------------------------------


def test_strip_invalid_citations():
    text, removed = strip_invalid_citations("A [1]. B [2, 7]. C [9].", {1, 2})
    assert text == "A [1]. B [2]. C." and removed == 2


def test_split_sentences_keeps_trailing_citations():
    assert split_sentences("One fact. [1] Two facts [2]. Three.") == ["One fact. [1]", "Two facts [2].", "Three."]


async def test_verifier_removes_only_unsupported(make_router):
    registry = SourceRegistry(5)
    for i in (1, 2):
        url = f"https://s{i}.org/"
        rec = registry.add(
            SearchResult(title=f"S{i}", url=url, canonical_url=canonicalize_url(url), domain=f"s{i}.org", snippet="", readable=True), None
        )
        rec.passages = ["Solar panels convert sunlight to electricity."]

    def handler(messages: list[ChatMessage], json_mode: bool) -> str:
        return research_handler(messages, json_mode)

    router = make_router(FakeProvider("gemini", handler=handler))
    md = "## Findings\n\n- Good claim [1].\n- UNSUPPORTED claim [2].\n\nPara one [1]. UNSUPPORTED para [2]. Plain sentence."
    result = await verify_report(router, md, registry, Budget(2, 5, 500))
    assert "Good claim [1]." in result.markdown and "UNSUPPORTED" not in result.markdown
    assert "- Good claim" in result.markdown and "Plain sentence." in result.markdown
    assert result.summary["removed"] == 2 and result.summary["supported"] == 2
