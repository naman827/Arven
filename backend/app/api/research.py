"""Deep Research jobs: create, inspect, live events (SSE with resume), cancel, plan approval."""

from collections.abc import AsyncIterator

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.chat import title_from
from app.api.sse import SSE_HEADERS, format_sse
from app.db.models import Conversation, Message, ResearchJob, Source
from app.db.session import session_factory
from app.schemas.api import JobOut, PlanApproval, ResearchRequest, SourceOut
from app.services.container import get_services

router = APIRouter(prefix="/api/research", tags=["research"])


@router.post("", status_code=202)
async def start_research(req: ResearchRequest) -> dict[str, str]:
    services = get_services()
    async with session_factory()() as session:
        if req.conversation_id:
            conv = await session.get(Conversation, req.conversation_id)
            if conv is None:
                raise HTTPException(404, "Conversation not found")
            conv.mode = "deep_research"
        else:
            conv = Conversation(title=title_from(req.question), mode="deep_research")
            session.add(conv)
            await session.flush()
        job = ResearchJob(
            conversation_id=conv.id,
            question=req.question.strip(),
            options={"review_plan": req.review_plan, "focus": req.focus},
        )
        session.add(job)
        await session.flush()
        session.add(
            Message(conversation_id=conv.id, role="user", content=req.question.strip(), mode="deep_research", research_job_id=job.id)
        )
        await session.commit()
        job_id, conversation_id = job.id, conv.id
    await services.jobs.emit(job_id, "status", {"status": "queued"})
    services.jobs.start(job_id, lambda: services.orchestrator.run(job_id))
    return {"job_id": job_id, "conversation_id": conversation_id}


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: str) -> ResearchJob:
    async with session_factory()() as session:
        job = await session.get(ResearchJob, job_id)
        if job is None:
            raise HTTPException(404, "Job not found")
        return job


@router.get("/{job_id}/sources", response_model=list[SourceOut])
async def job_sources(job_id: str) -> list[Source]:
    async with session_factory()() as session:
        rows = await session.execute(select(Source).where(Source.job_id == job_id).order_by(Source.number))
        return list(rows.scalars().all())


@router.get("/{job_id}/events")
async def job_events(
    job_id: str,
    request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    after: int = Query(default=0, ge=0),
) -> StreamingResponse:
    async with session_factory()() as session:
        if await session.get(ResearchJob, job_id) is None:
            raise HTTPException(404, "Job not found")
    start = after
    if last_event_id and last_event_id.isdigit():
        start = max(start, int(last_event_id))
    jobs = get_services().jobs

    async def stream() -> AsyncIterator[str]:
        yield "retry: 3000\n\n"
        async for event in jobs.subscribe(job_id, start):
            if await request.is_disconnected():
                break
            if event["type"] == "ping":
                yield ": ping\n\n"
                continue
            yield format_sse(event)

    return StreamingResponse(stream(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post("/{job_id}/cancel")
async def cancel_job(job_id: str) -> dict[str, object]:
    services = get_services()
    async with session_factory()() as session:
        job = await session.get(ResearchJob, job_id)
        if job is None:
            raise HTTPException(404, "Job not found")
    cancelled = await services.jobs.cancel(job_id)
    return {"cancelled": cancelled}


@router.post("/{job_id}/approve")
async def approve_plan(job_id: str, body: PlanApproval) -> dict[str, bool]:
    async with session_factory()() as session:
        if await session.get(ResearchJob, job_id) is None:
            raise HTTPException(404, "Job not found")
    if not get_services().jobs.approve(job_id, body.model_dump()):
        raise HTTPException(409, "This job is not waiting for plan approval")
    return {"approved": True}
