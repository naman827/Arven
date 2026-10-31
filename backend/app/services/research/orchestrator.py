"""Deep Research workflow: plan -> search -> read -> cross-check (bounded rounds) -> write -> verify -> persist."""

import asyncio
import logging
from typing import Any

from sqlalchemy import select

from app.config import Settings
from app.db.models import Conversation, Message, Report, ResearchJob, Source
from app.db.session import session_factory
from app.services.memory import memory_context
from app.services.providers.errors import AllProvidersFailedError, ProviderError
from app.services.providers.router import ProviderRouter, error_message
from app.services.research.analyst import analyze_subquestion
from app.services.research.budget import Budget
from app.services.research.jobs import JobManager
from app.services.research.planner import make_plan, make_queries
from app.services.research.reader import SourceRecord, SourceRegistry, extract_passages
from app.services.research.schemas import ResearchPlan, SubQuestion, SubQuestionAnalysis
from app.services.research.verifier import verify_report
from app.services.research.writer import (
    ensure_title_and_date,
    extract_title,
    references_section,
    strip_model_references,
    writer_messages,
)
from app.services.search.base import SearchResult
from app.services.search.service import SearchService

log = logging.getLogger(__name__)


class ResearchUnavailableError(Exception):
    pass


class DeepResearchOrchestrator:
    def __init__(self, router: ProviderRouter, search: SearchService, jobs: JobManager, settings: Settings) -> None:
        self.router = router
        self.search = search
        self.jobs = jobs
        self.settings = settings
        self.budget = Budget.from_settings(settings)
        self._llm_sem = asyncio.Semaphore(3)

    async def run(self, job_id: str) -> None:
        try:
            async with asyncio.timeout(self.settings.job_timeout_seconds):
                await self._run(job_id)
        except asyncio.CancelledError:
            if self.jobs.cancelled_by_user(job_id):
                await self.jobs.set_status(job_id, "cancelled")
                await self._add_message(job_id, "Deep research was cancelled. Collected sources were kept.", status="cancelled")
                return
            await self.jobs.set_status(job_id, "failed", error="interrupted: the server stopped while this job was running")
            raise
        except TimeoutError:
            await self._fail(job_id, f"Job exceeded the time budget (JOB_TIMEOUT_SECONDS={self.settings.job_timeout_seconds}).")
        except (ProviderError, AllProvidersFailedError) as exc:
            await self._fail(job_id, error_message(exc))
        except ResearchUnavailableError as exc:
            await self._fail(job_id, str(exc))
        except Exception:
            log.exception("deep research job %s crashed", job_id)
            await self._fail(job_id, "Unexpected internal error during research. See backend logs.")

    async def _fail(self, job_id: str, message: str) -> None:
        await self.jobs.set_status(job_id, "failed", error=message)
        await self.jobs.emit(job_id, "error", {"message": message})
        await self._add_message(job_id, f"Deep research failed: {message}", status="error")

    async def _add_message(self, job_id: str, content: str, *, status: str, meta: dict[str, Any] | None = None) -> str | None:
        async with session_factory()() as session:
            job = await session.get(ResearchJob, job_id)
            if job is None:
                return None
            msg = Message(
                conversation_id=job.conversation_id,
                role="assistant",
                content=content,
                mode="deep_research",
                status=status,
                research_job_id=job_id,
                provider=self.router.last_provider,
                meta=meta or {},
            )
            session.add(msg)
            conv = await session.get(Conversation, job.conversation_id)
            if conv is not None:
                conv.updated_at = msg.created_at
            await session.commit()
            return msg.id

    # ------------------------------------------------------------------------
    async def _run(self, job_id: str) -> None:
        async with session_factory()() as session:
            job = await session.get(ResearchJob, job_id)
            if job is None:
                return
            question, options = job.question, dict(job.options or {})
        focus = options.get("focus", "general")

        if not self.router.any_configured:
            raise ResearchUnavailableError("No model provider is configured. Add GEMINI_API_KEY or NVIDIA_API_KEY to .env.")
        if not self.search.available:
            raise ResearchUnavailableError(
                "Web research is unavailable: no working search provider. Add TAVILY_API_KEY to .env and restart the backend."
            )

        # A. Plan
        await self.jobs.set_status(job_id, "planning")
        memory = await memory_context()
        plan = await make_plan(self.router, question, focus=focus, memory=memory)
        await self.jobs.emit(job_id, "plan", plan.model_dump())
        await self.jobs.set_status(job_id, "planning", plan=plan.model_dump())
        if options.get("review_plan"):
            await self.jobs.set_status(job_id, "awaiting_plan_approval")
            approval = await self.jobs.wait_for_approval(job_id)
            edited = [q.strip() for q in approval.get("subquestions", []) if isinstance(q, str) and q.strip()]
            if edited:
                plan.subquestions = [SubQuestion(question=q[:400]) for q in edited[:7]]
                await self.jobs.emit(job_id, "plan", plan.model_dump())
                await self.jobs.set_status(job_id, "planning", plan=plan.model_dump())

        registry = SourceRegistry(self.budget.max_unique_sources)
        by_subq: dict[str, list[SourceRecord]] = {sq.question: [] for sq in plan.subquestions}
        tried: dict[str, list[str]] = {sq.question: [] for sq in plan.subquestions}
        analyses: dict[str, SubQuestionAnalysis] = {}

        # B-D. Bounded search rounds
        pending: dict[str, list[str] | None] = {sq.question: None for sq in plan.subquestions}  # None => generate queries
        for round_no in range(1, self.budget.max_search_rounds + 1):
            if not pending or registry.full and round_no > 1:
                break
            await self.jobs.set_status(job_id, "searching")
            new_records = await self._search_round(job_id, plan, pending, registry, by_subq, tried, focus, round_no)

            await self.jobs.set_status(job_id, "reading")
            await self._read(job_id, new_records)

            await self.jobs.set_status(job_id, "cross_checking")
            targets = list(pending.keys())
            results = await asyncio.gather(*(self._analyze(sq, by_subq[sq]) for sq in targets))
            analyses.update(dict(zip(targets, results, strict=True)))

            pending = {}
            if round_no < self.budget.max_search_rounds:
                for sq, analysis in analyses.items():
                    weak = analysis.coverage < self.budget.coverage_threshold or analysis.conflicts
                    if weak and (analysis.gaps or analysis.conflicts):
                        follow = [q for q in analysis.follow_up_queries if q not in tried[sq]][:2]
                        pending[sq] = follow or None
                        await self.jobs.emit(
                            job_id,
                            "gap_found",
                            {
                                "subquestion": sq,
                                "coverage": round(analysis.coverage, 2),
                                "gaps": analysis.gaps[:3],
                                "conflicts": analysis.conflicts[:3],
                            },
                        )

        if not registry.readable():
            raise ResearchUnavailableError(
                "None of the sources found could be read, so no evidence-based report can be written. Try rephrasing the question."
            )

        # E. Write
        await self.jobs.set_status(job_id, "synthesizing")
        method_note = (
            f"{len(plan.subquestions)} subquestions; {sum(len(v) for v in tried.values())} search queries; "
            f"{len(registry.records)} sources found, {len(registry.readable())} read; up to {self.budget.max_search_rounds} search rounds; "
            "findings cross-checked across sources and every citation verified against stored evidence after drafting."
        )
        messages = writer_messages(
            question, plan, analyses, registry, max_words=self.budget.max_report_words, method_note=method_note, memory=memory
        )
        draft = await self._stream_draft(job_id, messages)

        # F. Verify citations
        await self.jobs.emit(job_id, "status", {"status": "synthesizing", "stage": "verifying_citations"})
        body = strip_model_references(draft)
        verified = await verify_report(self.router, body, registry, self.budget)
        title = extract_title(verified.markdown, question[:120])
        final = ensure_title_and_date(verified.markdown, title) + "\n\n" + references_section(verified.markdown, registry)
        await self.jobs.emit(job_id, "verification", verified.summary)

        # G. Persist
        async with session_factory()() as session:
            report = Report(
                job_id=job_id,
                title=title,
                markdown=final,
                verification=verified.summary,
                provider=self.router.last_provider,
            )
            job_row = await session.get(ResearchJob, job_id)
            if job_row is not None:
                report.conversation_id = job_row.conversation_id
            session.add(report)
            await session.commit()
            report_id = report.id
        message_id = await self._add_message(
            job_id, final, status="complete", meta={"report_id": report_id, "verification": verified.summary, "title": title}
        )
        await self.jobs.set_status(job_id, "completed", report_id=report_id)
        await self.jobs.emit(
            job_id, "done", {"report_id": report_id, "message_id": message_id, "title": title, "verification": verified.summary}
        )

    # ------------------------------------------------------------------------
    async def _search_round(
        self,
        job_id: str,
        plan: ResearchPlan,
        pending: dict[str, list[str] | None],
        registry: SourceRegistry,
        by_subq: dict[str, list[SourceRecord]],
        tried: dict[str, list[str]],
        focus: str,
        round_no: int,
    ) -> list[SourceRecord]:
        async def queries_for(sq: str) -> list[str]:
            given = pending[sq]
            if given:
                return given
            async with self._llm_sem:
                try:
                    return await make_queries(
                        self.router,
                        sq,
                        main_question=plan.main_question,
                        count=self.budget.queries_per_subquestion if round_no == 1 else 2,
                        focus=focus,
                        avoid=tried[sq],
                    )
                except ProviderError:
                    return [sq[:200]]  # malformed structured output: fall back to the subquestion itself

        subqs = list(pending.keys())
        query_lists = await asyncio.gather(*(queries_for(sq) for sq in subqs))
        new_records: list[SourceRecord] = []
        for sq, queries in zip(subqs, query_lists, strict=True):
            tried[sq].extend(queries)
            for q in queries:
                await self.jobs.emit(job_id, "query", {"subquestion": sq, "query": q, "round": round_no})
            results, errors = await self.search.search_many(queries, max_results=self.budget.results_per_query)
            for err in errors:
                await self.jobs.emit(job_id, "search_error", {"subquestion": sq, "message": err[:300]})
            if not results and errors and not self.search.available:
                raise ResearchUnavailableError("Web search stopped working during research: " + errors[0][:200])
            added = 0
            for result in self._prefer(results, focus):
                if added >= self.budget.sources_per_subquestion or registry.full:
                    break
                record = registry.add(result, sq)
                if record is None:
                    continue
                added += 1
                by_subq[sq].append(record)
                new_records.append(record)
                await self.jobs.emit(job_id, "source_found", record.to_public())
        return new_records

    @staticmethod
    def _prefer(results: list[SearchResult], focus: str) -> list[SearchResult]:
        from app.services.research.reader import classify_source

        weight = {"academic": 0.3, "preprint": 0.15, "government": 0.25, "institution": 0.2, "encyclopedia": 0.05, "web": 0.0}
        if focus != "academic":
            weight = {k: v / 2 for k, v in weight.items()}
        return sorted(results, key=lambda r: -(r.score + weight.get(classify_source(r.domain), 0.0)))

    async def _read(self, job_id: str, records: list[SourceRecord]) -> None:
        if not records:
            return
        await self.search.read([r.result for r in records])
        for r in records:
            if r.readable:
                r.passages = extract_passages(r, r.subquestion or "", k=self.budget.passages_per_source)
                if not r.passages:
                    r.result.readable, r.result.error = False, "no relevant passages found"
            await self.jobs.emit(
                job_id, "source_read", {"number": r.number, "readable": r.readable, "error": r.result.error, "passages": len(r.passages)}
            )
        async with session_factory()() as session:
            for r in records:
                row = Source(
                    job_id=job_id,
                    number=r.number,
                    url=r.result.url,
                    title=r.result.title,
                    domain=r.result.domain,
                    published_date=r.result.published_date,
                    retrieved_at=r.result.retrieved_at,
                    snippet=r.result.snippet[:1000],
                    passages=r.passages,
                    subquestion=r.subquestion,
                    source_type=r.source_type,
                    readable=r.readable,
                    error=r.result.error,
                    search_provider=r.result.provider,
                )
                session.add(row)
            await session.commit()

    async def _analyze(self, sq: str, records: list[SourceRecord]) -> SubQuestionAnalysis:
        async with self._llm_sem:
            try:
                return await analyze_subquestion(self.router, sq, records)
            except ProviderError as exc:
                if exc.kind.value == "invalid_output":
                    return SubQuestionAnalysis(findings=[], coverage=0.0, gaps=["Analysis output was malformed for this subquestion."])
                raise

    async def _stream_draft(self, job_id: str, messages: list[Any]) -> str:
        text: list[str] = []
        buffer = ""
        async for event in self.router.stream(messages, temperature=0.3, max_tokens=8192):
            if event.type == "provider":
                await self.jobs.emit(job_id, "provider", {"provider": event.provider, "model": event.model})
            elif event.type == "reset":
                text.clear()
                buffer = ""
                await self.jobs.emit(job_id, "reset", {"reason": event.reason})
            elif event.type == "token":
                text.append(event.text)
                buffer += event.text
                if len(buffer) >= 240:
                    await self.jobs.emit(job_id, "token", {"text": buffer})
                    buffer = ""
        if buffer:
            await self.jobs.emit(job_id, "token", {"text": buffer})
        draft = "".join(text).strip()
        if not draft:
            raise ResearchUnavailableError("The model returned an empty report.")
        return draft


async def load_job_sources(job_id: str) -> list[Source]:
    async with session_factory()() as session:
        rows = await session.execute(select(Source).where(Source.job_id == job_id).order_by(Source.number))
        return list(rows.scalars().all())
