"""Conversation history CRUD."""

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import delete, or_, select

from app.db.models import Conversation, Message, Report, ResearchJob, Source
from app.db.session import ACTIVE_JOB_STATES, session_factory
from app.schemas.api import ConversationDetail, ConversationOut, ConversationUpdate, MessageOut, SourceOut

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationOut])
async def list_conversations(
    q: str | None = Query(default=None, max_length=200), limit: int = Query(default=200, le=500)
) -> list[Conversation]:
    async with session_factory()() as session:
        stmt = select(Conversation).order_by(Conversation.updated_at.desc()).limit(limit)
        if q and q.strip():
            like = f"%{q.strip()}%"
            matching = select(Message.conversation_id).where(Message.content.ilike(like))
            stmt = stmt.where(or_(Conversation.title.ilike(like), Conversation.id.in_(matching)))
        return list((await session.execute(stmt)).scalars().all())


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: str) -> ConversationDetail:
    async with session_factory()() as session:
        conv = await session.get(Conversation, conversation_id)
        if conv is None:
            raise HTTPException(404, "Conversation not found")
        messages = (
            (await session.execute(select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at)))
            .scalars()
            .all()
        )
        active = (
            await session.execute(
                select(ResearchJob.id)
                .where(
                    ResearchJob.conversation_id == conversation_id, ResearchJob.status.in_((*ACTIVE_JOB_STATES, "awaiting_plan_approval"))
                )
                .order_by(ResearchJob.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return ConversationDetail(
            **ConversationOut.model_validate(conv).model_dump(),
            messages=[MessageOut.model_validate(m) for m in messages],
            active_job_id=active,
        )


@router.patch("/{conversation_id}", response_model=ConversationOut)
async def update_conversation(conversation_id: str, body: ConversationUpdate) -> Conversation:
    async with session_factory()() as session:
        conv = await session.get(Conversation, conversation_id)
        if conv is None:
            raise HTTPException(404, "Conversation not found")
        if body.title is not None:
            conv.title = body.title.strip()
        if body.mode is not None:
            conv.mode = body.mode
        await session.commit()
        await session.refresh(conv)
        return conv


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: str) -> Response:
    from app.services.container import get_services

    async with session_factory()() as session:
        conv = await session.get(Conversation, conversation_id)
        if conv is None:
            raise HTTPException(404, "Conversation not found")
        job_ids = (await session.execute(select(ResearchJob.id).where(ResearchJob.conversation_id == conversation_id))).scalars().all()
        for job_id in job_ids:
            await get_services().jobs.cancel(job_id)
        message_ids = select(Message.id).where(Message.conversation_id == conversation_id)
        await session.execute(delete(Source).where(or_(Source.message_id.in_(message_ids), Source.job_id.in_(job_ids))))
        await session.execute(delete(Report).where(Report.conversation_id == conversation_id))
        await session.delete(conv)
        await session.commit()
    return Response(status_code=204)


@router.get("/{conversation_id}/messages/{message_id}/sources", response_model=list[SourceOut])
async def message_sources(conversation_id: str, message_id: str) -> list[Source]:
    async with session_factory()() as session:
        msg = await session.get(Message, message_id)
        if msg is None or msg.conversation_id != conversation_id:
            raise HTTPException(404, "Message not found")
        if msg.research_job_id:
            stmt = select(Source).where(Source.job_id == msg.research_job_id)
        else:
            stmt = select(Source).where(Source.message_id == message_id)
        return list((await session.execute(stmt.order_by(Source.number))).scalars().all())
