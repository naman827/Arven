"""Citation verification pass: checks each cited claim against the stored evidence passages."""

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any

from app.services.providers.base import ChatMessage
from app.services.providers.errors import AllProvidersFailedError, ProviderError
from app.services.providers.router import ProviderRouter
from app.services.research.budget import Budget
from app.services.research.prompts import DATA_GUARD, data_block
from app.services.research.reader import CITATION_RE, SourceRegistry, best_passages_for_claim, strip_invalid_citations
from app.services.research.schemas import VerificationBatch

_PREFIX = re.compile(r"^(\s*(?:(?:[-*+]|\d+\.)\s+)?)")
_SENT_SPLIT = re.compile(r"((?<=[.!?])(?:\s*\[\d{1,3}(?:\s*,\s*\d{1,3})*\])*)\s+(?=\S)")


def split_sentences(line: str) -> list[str]:
    parts = _SENT_SPLIT.split(line)
    sentences: list[str] = []
    for i in range(0, len(parts), 2):
        text = parts[i] + (parts[i + 1] if i + 1 < len(parts) and parts[i + 1] else "")
        if text.strip():
            sentences.append(text)
    return sentences


@dataclass
class Claim:
    id: int
    line: int
    sentence: int
    text: str
    citations: list[int]
    verdict: str | None = None


@dataclass
class VerificationResult:
    markdown: str
    summary: dict[str, Any] = field(default_factory=dict)


def _numbers(text: str) -> list[int]:
    out: list[int] = []
    for m in CITATION_RE.finditer(text):
        out.extend(int(n) for n in m.group(1).split(","))
    return sorted(set(out))


async def verify_report(router: ProviderRouter, markdown: str, registry: SourceRegistry, budget: Budget) -> VerificationResult:
    valid = {r.number for r in registry.readable()}
    markdown, invalid_removed = strip_invalid_citations(markdown, valid)

    lines = markdown.split("\n")
    structure: list[list[str] | None] = []  # None = line kept verbatim
    prefixes: list[str] = []
    claims: list[Claim] = []
    for li, line in enumerate(lines):
        if line.lstrip().startswith("#") or not CITATION_RE.search(line):
            structure.append(None)
            prefixes.append("")
            continue
        if line.lstrip().startswith("|"):
            prefix, sentences = "", [line]
        else:
            match = _PREFIX.match(line)
            prefix = match.group(1) if match else ""
            sentences = split_sentences(line[len(prefix) :])
        structure.append(sentences)
        prefixes.append(prefix)
        for si, sentence in enumerate(sentences):
            nums = _numbers(sentence)
            if nums:
                claims.append(Claim(len(claims) + 1, li, si, sentence.strip(), nums))

    to_check = claims[: budget.max_claims_to_verify]
    batches = [to_check[i : i + budget.verify_batch_size] for i in range(0, len(to_check), budget.verify_batch_size)]
    sem = asyncio.Semaphore(3)
    failed_batches = 0

    async def run_batch(batch: list[Claim]) -> None:
        nonlocal failed_batches
        parts = []
        for c in batch:
            evidence = []
            for n in c.citations:
                rec = registry.get(n)
                if rec:
                    evidence.append(data_block(f"source [{n}]", "\n...\n".join(best_passages_for_claim(rec, c.text)), limit=1800))
            parts.append(f"Claim {c.id}: {CITATION_RE.sub('', c.text).strip()}\nCited evidence:\n" + "\n".join(evidence))
        messages = [
            ChatMessage(
                "system",
                "You verify citations. For each claim decide if the cited evidence supports it: 'supported' if "
                "the evidence clearly states it, 'partial' if only part is supported or it is overstated, "
                "'unsupported' if the evidence does not support it. Judge only against the evidence shown. " + DATA_GUARD,
            ),
            ChatMessage("user", "\n\n".join(parts)),
        ]
        async with sem:
            try:
                result = await router.generate_structured(messages, VerificationBatch)
            except (ProviderError, AllProvidersFailedError):
                failed_batches += 1
                return
        by_id = {v.id: v.verdict for v in result.results}
        for c in batch:
            c.verdict = by_id.get(c.id)

    await asyncio.gather(*(run_batch(b) for b in batches))

    removed = 0
    for c in claims:
        if c.verdict != "unsupported":
            continue
        target = structure[c.line]
        assert target is not None
        if lines[c.line].lstrip().startswith("|"):
            target[c.sentence] = CITATION_RE.sub("", target[c.sentence]).rstrip() + " (unverified)"
        else:
            target[c.sentence] = ""
        removed += 1

    rebuilt: list[str] = []
    for li, kept in enumerate(structure):
        if kept is None:
            rebuilt.append(lines[li])
            continue
        joined = " ".join(s.strip() for s in kept if s.strip())
        if joined:  # a fully removed line is dropped
            rebuilt.append(prefixes[li] + joined)

    checked = [c for c in to_check if c.verdict is not None]
    summary = {
        "ran": True,
        "claims_total": len(claims),
        "claims_checked": len(checked),
        "supported": sum(1 for c in checked if c.verdict == "supported"),
        "partial": sum(1 for c in checked if c.verdict == "partial"),
        "removed": removed,
        "not_checked": len(claims) - len(checked),
        "invalid_citations_removed": invalid_removed,
        "failed_batches": failed_batches,
    }
    return VerificationResult(markdown="\n".join(rebuilt), summary=summary)
