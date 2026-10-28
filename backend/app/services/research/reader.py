"""Source registry and evidence extraction (relevant passages only, never whole pages)."""

import re
from dataclasses import dataclass, field
from datetime import datetime

from app.services.documents.chunking import split_passages
from app.services.documents.retrieval import rank
from app.services.search.base import SearchResult

_ACADEMIC_DOMAINS = (
    "arxiv.org",
    "doi.org",
    "nature.com",
    "sciencedirect.com",
    "springer.com",
    "ieee.org",
    "acm.org",
    "nih.gov",
    "ncbi.nlm.nih.gov",
    "pubmed",
    "jstor.org",
    "wiley.com",
    "plos.org",
    "ssrn.com",
    "biorxiv.org",
    "medrxiv.org",
    "semanticscholar.org",
    "researchgate.net",
    "frontiersin.org",
    "mdpi.com",
)
_PREPRINT = ("arxiv.org", "biorxiv.org", "medrxiv.org", "ssrn.com", "researchgate.net")


def classify_source(domain: str) -> str:
    if any(d in domain for d in _PREPRINT):
        return "preprint"
    if any(d in domain for d in _ACADEMIC_DOMAINS):
        return "academic"
    if domain.endswith((".gov", ".gov.uk", ".europa.eu", ".int")) or ".gov." in domain:
        return "government"
    if domain.endswith(".edu") or ".ac." in domain or ".edu." in domain:
        return "institution"
    if any(n in domain for n in ("wikipedia.org",)):
        return "encyclopedia"
    return "web"


@dataclass
class SourceRecord:
    number: int
    result: SearchResult
    subquestion: str | None
    passages: list[str] = field(default_factory=list)
    source_type: str = "web"
    db_id: str | None = None

    @property
    def readable(self) -> bool:
        return bool(self.result.readable)

    def to_public(self) -> dict[str, object]:
        r = self.result
        return {
            "number": self.number,
            "url": r.url,
            "title": r.title,
            "domain": r.domain,
            "published_date": r.published_date,
            "retrieved_at": r.retrieved_at.isoformat() if isinstance(r.retrieved_at, datetime) else None,
            "snippet": r.snippet[:300],
            "readable": r.readable,
            "error": r.error,
            "source_type": self.source_type,
            "subquestion": self.subquestion,
            "provider": r.provider,
        }


class SourceRegistry:
    """Assigns stable citation numbers 1..N; caps unique sources."""

    def __init__(self, max_sources: int) -> None:
        self.max_sources = max_sources
        self.records: list[SourceRecord] = []
        self._by_url: dict[str, SourceRecord] = {}

    def add(self, result: SearchResult, subquestion: str | None) -> SourceRecord | None:
        existing = self._by_url.get(result.canonical_url)
        if existing is not None:
            return None
        if len(self.records) >= self.max_sources:
            return None
        record = SourceRecord(len(self.records) + 1, result, subquestion, source_type=classify_source(result.domain))
        self.records.append(record)
        self._by_url[result.canonical_url] = record
        return record

    def get(self, number: int) -> SourceRecord | None:
        return self.records[number - 1] if 1 <= number <= len(self.records) else None

    @property
    def full(self) -> bool:
        return len(self.records) >= self.max_sources

    def readable(self) -> list[SourceRecord]:
        return [r for r in self.records if r.readable]


def extract_passages(record: SourceRecord, query: str, k: int = 3) -> list[str]:
    content = record.result.content
    if not content:
        return []
    passages = split_passages(content, size=900, overlap=100)
    if not passages:
        return []
    best = rank(query, passages, top_k=k)
    # keep document order for readability
    return [passages[i] for i, _ in sorted(best, key=lambda t: t[0])]


def best_passages_for_claim(record: SourceRecord, claim: str, k: int = 2) -> list[str]:
    if not record.passages:
        return []
    return [record.passages[i] for i, _ in rank(claim, record.passages, top_k=k)]


CITATION_RE = re.compile(r"\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]")


def cited_numbers(text: str) -> list[int]:
    nums: list[int] = []
    for m in CITATION_RE.finditer(text):
        nums.extend(int(n) for n in m.group(1).split(","))
    return nums


def strip_invalid_citations(text: str, valid: set[int]) -> tuple[str, int]:
    """Remove citation numbers that do not map to a stored source. Returns (text, removed_count)."""
    removed = 0

    def repl(m: re.Match[str]) -> str:
        nonlocal removed
        nums = [int(n) for n in m.group(2).split(",")]
        keep = [n for n in nums if n in valid]
        removed += len(nums) - len(keep)
        return (m.group(1) + "".join(f"[{n}]" for n in keep)) if keep else ""

    return _CITATION_WS_RE.sub(repl, text), removed


_CITATION_WS_RE = re.compile(r"([ 	]*)\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]")
