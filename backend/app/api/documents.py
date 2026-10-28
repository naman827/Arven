"""PDF upload, listing, deletion."""

import asyncio
import uuid

from fastapi import APIRouter, HTTPException, Request, Response, UploadFile
from sqlalchemy import select

from app.db.models import Document, DocumentChunk
from app.db.session import session_factory
from app.schemas.api import DocumentOut
from app.services.container import get_services
from app.services.documents.pdf_reader import InvalidPDFError, extract_pdf, is_pdf

router = APIRouter(prefix="/api/documents", tags=["documents"])


def safe_display_name(name: str | None) -> str:
    base = (name or "document.pdf").replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = "".join(ch for ch in base if ch.isprintable() and ch not in '<>:"|?*').strip() or "document.pdf"
    return cleaned[:200]


@router.post("", response_model=DocumentOut, status_code=201)
async def upload_document(file: UploadFile, request: Request) -> Document:
    settings = get_services().settings
    limit = settings.max_upload_mb * 1024 * 1024
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit + 1024 * 64:
        raise HTTPException(413, f"File too large (max {settings.max_upload_mb} MB)")
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"File too large (max {settings.max_upload_mb} MB)")
    if not data:
        raise HTTPException(422, "File is empty")
    if not is_pdf(data):
        raise HTTPException(415, "Only PDF files are supported (file content is not a PDF)")
    try:
        extracted = await asyncio.to_thread(extract_pdf, data)
    except InvalidPDFError as exc:
        raise HTTPException(422, str(exc)) from exc

    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}.pdf"  # generated name; user filename never touches the filesystem
    (settings.uploads_dir / stored_name).write_bytes(data)

    async with session_factory()() as session:
        doc = Document(
            filename=safe_display_name(file.filename),
            stored_name=stored_name,
            size_bytes=len(data),
            page_count=extracted.page_count,
            has_text=extracted.has_text,
            status="ready" if extracted.has_text else "no_text",
        )
        session.add(doc)
        await session.flush()
        for i, chunk in enumerate(extracted.chunks):
            session.add(DocumentChunk(document_id=doc.id, index=i, page=chunk.page, text=chunk.text))
        await session.commit()
        await session.refresh(doc)
        return doc


@router.get("", response_model=list[DocumentOut])
async def list_documents() -> list[Document]:
    async with session_factory()() as session:
        return list((await session.execute(select(Document).order_by(Document.created_at.desc()))).scalars().all())


@router.delete("/{document_id}", status_code=204)
async def delete_document(document_id: str) -> Response:
    settings = get_services().settings
    async with session_factory()() as session:
        doc = await session.get(Document, document_id)
        if doc is None:
            raise HTTPException(404, "Document not found")
        path = (settings.uploads_dir / doc.stored_name).resolve()
        if path.parent == settings.uploads_dir.resolve() and path.exists():
            path.unlink()
        await session.delete(doc)
        await session.commit()
    return Response(status_code=204)
