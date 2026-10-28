"""Text chunking into overlapping passages."""

import re


def split_passages(text: str, *, size: int = 900, overlap: int = 150) -> list[str]:
    text = re.sub(r"[ \t]+", " ", text).strip()
    if not text:
        return []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        while len(para) > size:
            cut = para.rfind(". ", 0, size)
            cut = cut + 1 if cut > size // 2 else size
            if current:
                chunks.append(current)
                current = ""
            chunks.append(para[:cut].strip())
            para = para[max(0, cut - overlap) :].strip()
        if len(current) + len(para) + 2 <= size:
            current = f"{current}\n\n{para}" if current else para
        else:
            if current:
                chunks.append(current)
            tail = current[-overlap:] if current else ""
            current = f"{tail} {para}".strip() if tail else para
    if current:
        chunks.append(current)
    return [c for c in chunks if len(c) > 40]
