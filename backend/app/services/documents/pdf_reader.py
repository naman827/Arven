"""PDF validation and page-aware text extraction (PyMuPDF)."""

from dataclasses import dataclass

import pymupdf

from app.services.documents.chunking import split_passages

PDF_MAGIC = b"%PDF-"


class InvalidPDFError(ValueError):
    pass


@dataclass
class PageChunk:
    page: int
    text: str


@dataclass
class ExtractedPDF:
    page_count: int
    chunks: list[PageChunk]
    has_text: bool


def is_pdf(data: bytes) -> bool:
    return data[:1024].lstrip().startswith(PDF_MAGIC)


def extract_pdf(data: bytes) -> ExtractedPDF:
    if not is_pdf(data):
        raise InvalidPDFError("File is not a PDF (missing %PDF header).")
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise InvalidPDFError("PDF could not be opened (corrupt or unsupported).") from exc
    with doc:
        if doc.needs_pass:
            raise InvalidPDFError("PDF is password-protected.")
        chunks: list[PageChunk] = []
        total_chars = 0
        for number in range(1, doc.page_count + 1):
            text = doc[number - 1].get_text()
            total_chars += len(text.strip())
            for passage in split_passages(text, size=1000, overlap=120):
                chunks.append(PageChunk(page=number, text=passage))
        page_count = doc.page_count
    # Scanned PDFs have (almost) no text layer.
    has_text = total_chars >= max(80, 25 * page_count)
    return ExtractedPDF(page_count=page_count, chunks=chunks if has_text else [], has_text=has_text)
