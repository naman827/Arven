"""Embedding-free BM25 ranking of passages."""

import re
from collections.abc import Sequence

from rank_bm25 import BM25Okapi

_STOP = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "of",
    "to",
    "in",
    "on",
    "for",
    "is",
    "are",
    "was",
    "were",
    "be",
    "by",
    "with",
    "as",
    "at",
    "that",
    "this",
    "it",
    "from",
    "what",
    "how",
    "why",
    "which",
    "who",
    "does",
    "do",
    "can",
}


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOP and len(t) > 1]


def rank(query: str, passages: Sequence[str], top_k: int = 5) -> list[tuple[int, float]]:
    """Return [(index, score)] of the best passages, highest first. Falls back to order if query has no terms."""
    if not passages:
        return []
    corpus = [tokenize(p) or ["_empty_"] for p in passages]
    q = tokenize(query)
    if not q:
        return [(i, 0.0) for i in range(min(top_k, len(passages)))]
    scores = BM25Okapi(corpus).get_scores(q)
    order = sorted(range(len(passages)), key=lambda i: -scores[i])
    return [(i, float(scores[i])) for i in order[:top_k]]
