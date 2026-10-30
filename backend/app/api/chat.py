"""POST /api/chat: Chat and Research modes, streamed as SSE over the POST response."""

from collections.abc import AsyncIterator
from typing import Any

import anyio
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.sse import SSE_HEADERS, format_sse
from app.db.models import Conversation, Document, Message, Source
from app.db.session import session_factory
from app.schemas.api import ChatRequest
from app.services.chat import DocContext, TurnResult, run_chat, run_research
from app.services.container import get_services

router = APIRouter(prefix="/api", tags=["chat"])


def title_from(text: str) -> str:
    words = " ".join(text.split())
    return (words[:60] + "...") if len(words) > 60 else (words or "New conversation")


async def _prepare(req: ChatRequest) -> tuple[str, str, str, list[tuple[str, str]], list[DocContext]]:
    async with session_factory()() as session:
        if req.conversation_id:
            conv = await session.get(Conversation, req.conversation_id)
            if conv is None:
                raise HTTPException(404, "Conversation not found")
        else:
            if not req.message.strip():
                raise HTTPException(422, "Message is empty")
            conv = Conversation(title=title_from(req.message), mode=req.mode)
            session.add(conv)
            await session.flush()
        rows = (
            (await session.execute(select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at))).scalars().all()
        )
        messages = list(rows)

        if req.regenerate:
            while messages and messages[-1].role == "assistant":
                await session.delete(messages.pop())
            if not messages or messages[-1].role != "user":
                raise HTTPException(409, "Nothing to regenerate")
            user_msg = messages[-1]
            question = user_msg.content
            prior = messages[:-1]
            document_ids = list(user_msg.meta.get("document_ids", [])) or req.document_ids
        else:
            question = req.message.strip()
            if not question:
                raise HTTPException(422, "Message is empty")
            document_ids = req.document_ids
            # Reject unknown attachments up front instead of answering without them (nothing is committed yet).
            for doc_id in document_ids[:5]:
                if await session.get(Document, doc_id) is None:
                    raise HTTPException(404, "Attached document not found. It may have been deleted.")
            user_msg = Message(conversation_id=conv.id, role="user", content=question, mode=req.mode, meta={"document_ids": document_ids})
            session.add(user_msg)
            prior = messages
        conv.mode = req.mode

        docs: list[DocContext] = []
        for doc_id in document_ids[:5]:
            doc = await session.get(Document, doc_id)
            if doc is None:
                continue
            await session.refresh(doc, ["chunks"])
            docs.append(DocContext(doc.filename, doc.has_text, [(c.page, c.text) for c in doc.chunks]))
        await session.commit()
        history = [(m.role, m.content) for m in prior if m.status in ("complete", "stopped")]
        return conv.id, user_msg.id, question, history, docs


async def _save(conversation_id: str, mode: str, result: TurnResult, status: str) -> str | None:
    if not result.content.strip() and not result.error:
        if status != "stopped":
            return None
    async with session_factory()() as session:
        content = result.content if result.content.strip() else (result.error or "")
        msg = Message(
            conversation_id=conversation_id,
            role="assistant",
            content=content,
            mode=mode,
            provider=result.provider,
            model=result.model,
            status="error" if (result.error and not result.content.strip()) else status,
            meta={**result.meta, "sources": result.sources, **({"error": result.error} if result.error else {})},
        )
        session.add(msg)
        await session.flush()
        for s in result.sources:
            session.add(
                Source(
                    message_id=msg.id,
                    number=int(s["number"]),
                    url=str(s["url"]),
                    title=str(s.get("title") or ""),
                    domain=str(s.get("domain") or ""),
                    published_date=s.get("published_date"),
                    snippet=str(s.get("snippet") or ""),
                    passages=result.passages.get(int(s["number"]), []),
                    source_type=s.get("source_type"),
                    readable=bool(s.get("readable")),
                    error=s.get("error"),
                    search_provider=s.get("provider"),
                )
            )
        conv = await session.get(Conversation, conversation_id)
        if conv is not None:
            conv.updated_at = msg.created_at
        await session.commit()
        return msg.id


@router.post("/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    services = get_services()
    conversation_id, user_message_id, question, history, docs = await _prepare(req)

    async def stream() -> AsyncIterator[str]:
        result = TurnResult()
        status = "stopped"
        yield format_sse(
            {"type": "meta", "data": {"conversation_id": conversation_id, "user_message_id": user_message_id, "mode": req.mode}}
        )
        try:
            if req.mode == "research":
                events = run_research(services.router, services.search, question, history, docs, result)
            else:
                events = run_chat(services.router, question, history, docs, result)
            async for event in events:
                yield format_sse(event)
            status = "complete"
        finally:
            with anyio.CancelScope(shield=True):
                message_id = await _save(conversation_id, req.mode, result, status)
        done: dict[str, Any] = {"message_id": message_id, "provider": result.provider, "model": result.model}
        if result.meta.get("invalid_citations_removed"):
            done["invalid_citations_removed"] = result.meta["invalid_citations_removed"]
        done["content"] = result.content  # final text (citations validated) replaces the streamed draft
        yield format_sse({"type": "done", "data": done})

    return StreamingResponse(stream(), media_type="text/event-stream", headers=SSE_HEADERS)
