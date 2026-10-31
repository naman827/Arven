"""Chat and Research-mode turn execution. Yields typed events for SSE."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from app.services.documents.retrieval import rank
from app.services.providers.base import ChatMessage
from app.services.providers.errors import AllProvidersFailedError, ProviderError
from app.services.providers.router import ProviderRouter, error_message
from app.services.research.planner import make_queries
from app.services.research.prompts import CHAT_SYSTEM, RESEARCH_ANSWER_SYSTEM, data_block, today
from app.services.research.reader import SourceRegistry, extract_passages, strip_invalid_citations
from app.services.search.service import SearchService

HISTORY_MESSAGES = 20
HISTORY_CHARS = 6000
RESEARCH_SOURCES = 8


@dataclass
class DocContext:
    filename: str
    has_text: bool
    chunks: list[tuple[int, str]]  # (page, text)


@dataclass
class TurnResult:
    content: str = ""
    provider: str | None = None
    model: str | None = None
    sources: list[dict[str, Any]] = field(default_factory=list)
    passages: dict[int, list[str]] = field(default_factory=dict)
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


def history_messages(history: list[tuple[str, str]]) -> list[ChatMessage]:
    out = []
    for role, content in history[-HISTORY_MESSAGES:]:
        if role in ("user", "assistant") and content.strip():
            out.append(ChatMessage(role, content[:HISTORY_CHARS]))  # type: ignore[arg-type]
    return out


def document_context(question: str, docs: list[DocContext], top_k: int = 6) -> tuple[str, list[str]]:
    notes: list[str] = []
    blocks: list[str] = []
    for doc in docs:
        if not doc.has_text:
            notes.append(
                f"The attached file '{doc.filename}' appears to be a scanned PDF with no extractable text layer. "
                "Tell the user its text could not be read (OCR is not supported yet)."
            )
            continue
        texts = [t for _, t in doc.chunks]
        for idx, _ in rank(question, texts, top_k=top_k):
            page, text = doc.chunks[idx]
            blocks.append(data_block(f"{doc.filename}, page {page}", text, limit=1500))
    if blocks:
        notes.append(
            "Relevant excerpts from the user's attached PDF(s) follow. Use them when relevant and cite pages like "
            "(filename, p. N). Do not claim content the excerpts do not show.\n\n" + "\n\n".join(blocks)
        )
    return "\n\n".join(notes), blocks


async def _stream_answer(router: ProviderRouter, messages: list[ChatMessage], result: TurnResult) -> AsyncIterator[dict[str, Any]]:
    parts: list[str] = []
    async for event in router.stream(messages, temperature=0.4):
        if event.type == "provider":
            result.provider, result.model = event.provider, event.model
            yield {"type": "provider", "data": {"provider": event.provider, "model": event.model}}
        elif event.type == "reset":
            parts.clear()
            yield {"type": "reset", "data": {"reason": event.reason}}
        else:
            parts.append(event.text)
            yield {"type": "token", "data": {"text": event.text}}
    result.content = "".join(parts)


async def run_chat(
    router: ProviderRouter,
    question: str,
    history: list[tuple[str, str]],
    docs: list[DocContext],
    result: TurnResult,
    memory: str = "",
) -> AsyncIterator[dict[str, Any]]:
    system = CHAT_SYSTEM.format(date=today())
    if memory:
        system += "\n\n" + memory
    context, _ = document_context(question, docs)
    if context:
        system += "\n\n" + context
    messages = [ChatMessage("system", system), *history_messages(history), ChatMessage("user", question)]
    try:
        async for event in _stream_answer(router, messages, result):
            yield event
    except (ProviderError, AllProvidersFailedError) as exc:
        result.error = error_message(exc)
        yield {"type": "error", "data": {"message": result.error}}


async def run_research(
    router: ProviderRouter,
    search: SearchService,
    question: str,
    history: list[tuple[str, str]],
    docs: list[DocContext],
    result: TurnResult,
    memory: str = "",
) -> AsyncIterator[dict[str, Any]]:
    if not search.available:
        result.error = "Web research is unavailable: no working search provider. Add TAVILY_API_KEY to .env and restart the backend. Chat mode still works."
        yield {"type": "error", "data": {"message": result.error}}
        return
    try:
        yield {"type": "status", "data": {"status": "searching"}}
        try:
            queries = await make_queries(router, question, main_question=question, count=3)
        except ProviderError as exc:
            if not exc.fallback_ok and exc.kind.value != "invalid_output":
                raise
            queries = [question[:300]]
        for q in queries:
            yield {"type": "query", "data": {"query": q}}
        results, errors = await search.search_many(queries, max_results=5)
        for err in errors:
            yield {"type": "search_error", "data": {"message": err[:300]}}
        if not results:
            result.error = "Web search returned no results" + (f" ({errors[0][:200]})" if errors else "") + "."
            yield {"type": "error", "data": {"message": result.error}}
            return

        registry = SourceRegistry(RESEARCH_SOURCES)
        for r in results:
            record = registry.add(r, None)
            if record is not None:
                yield {"type": "source_found", "data": record.to_public()}

        yield {"type": "status", "data": {"status": "reading"}}
        await search.read([r.result for r in registry.records], query=question)
        for record in registry.records:
            if record.readable:
                record.passages = extract_passages(record, question, k=3)
                if not record.passages:
                    record.result.readable, record.result.error = False, "no relevant passages found"
            yield {"type": "source_read", "data": {"number": record.number, "readable": record.readable, "error": record.result.error}}

        readable = registry.readable()
        result.sources = [r.to_public() for r in registry.records]
        result.passages = {r.number: r.passages for r in registry.records}
        if not readable:
            result.error = "Sources were found but none could be read (blocked, paywalled, or empty), so no cited answer can be given."
            yield {"type": "error", "data": {"message": result.error}}
            return

        yield {"type": "status", "data": {"status": "synthesizing"}}
        evidence = "\n\n".join(
            data_block(f"[{r.number}] {r.result.title} ({r.result.domain})", "\n...\n".join(r.passages), limit=2400) for r in readable
        )
        system = RESEARCH_ANSWER_SYSTEM.format(date=today())
        if memory:
            system += "\n\n" + memory
        context, _ = document_context(question, docs)
        if context:
            system += "\n\n" + context
        messages = [
            ChatMessage("system", system),
            *history_messages(history),
            ChatMessage("user", f"Question: {question}\n\nSources:\n{evidence}"),
        ]
        async for event in _stream_answer(router, messages, result):
            yield event
        cleaned, removed = strip_invalid_citations(result.content, {r.number for r in readable})
        result.content = cleaned
        result.meta["invalid_citations_removed"] = removed
        result.meta["queries"] = queries
    except (ProviderError, AllProvidersFailedError) as exc:
        result.error = error_message(exc)
        yield {"type": "error", "data": {"message": result.error}}
