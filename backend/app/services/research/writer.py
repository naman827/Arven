"""Report writer: prompt construction and deterministic references section."""

import re

from app.services.providers.base import ChatMessage
from app.services.research.prompts import DATA_GUARD, today
from app.services.research.reader import SourceRegistry, cited_numbers
from app.services.research.schemas import ResearchPlan, SubQuestionAnalysis

SECTIONS = [
    "Executive summary",
    "Scope and method",
    "Background",
    "Findings (one subsection per subtopic)",
    "Comparisons and trade-offs",
    "Conflicts, uncertainties, and limitations",
    "Practical conclusions",
]


def writer_messages(
    question: str,
    plan: ResearchPlan,
    analyses: dict[str, SubQuestionAnalysis],
    registry: SourceRegistry,
    *,
    max_words: int,
    method_note: str,
) -> list[ChatMessage]:
    findings_text = []
    for sq in plan.subquestions:
        a = analyses.get(sq.question)
        if a is None:
            continue
        lines = [f"### {sq.question} (coverage {a.coverage:.1f})"]
        lines += [f"- {f.statement} " + "".join(f"[{n}]" for n in f.citations) for f in a.findings]
        if a.conflicts:
            lines.append("Conflicts: " + "; ".join(a.conflicts))
        if a.gaps:
            lines.append("Gaps: " + "; ".join(a.gaps))
        findings_text.append("\n".join(lines))
    sources = "\n".join(
        f"[{r.number}] {r.result.title} - {r.result.domain} ({r.source_type}"
        + (f", {r.result.published_date}" if r.result.published_date else "")
        + ")"
        for r in registry.readable()
    )
    system = (
        "You are the writing step of a deep research system. Write a well-structured Markdown research report "
        "using ONLY the verified findings below. Rules:\n"
        "- Start with a level-1 title line (# Title).\n"
        f"- Then these level-2 sections in order: {', '.join(SECTIONS)}.\n"
        "- Cite every factual sentence inline with source numbers in square brackets like [3] or [2][5], using only "
        "the numbers given. Never invent sources, authors, dates, DOIs, or statistics.\n"
        "- Present disagreements between sources explicitly in the conflicts section.\n"
        "- Note when evidence is thin, a single source, a preprint, or possibly outdated.\n"
        "- Do NOT write a References section; it is added automatically.\n"
        f"- Stay under {max_words} words. Tables are allowed where they help comparison.\n"
        f"Today's date is {today()}. {DATA_GUARD}"
    )
    user = (
        f"Research question: {question[:2000]}\n\nMethod used: {method_note}\n\n"
        f"Findings by subquestion:\n\n" + "\n\n".join(findings_text) + f"\n\nAvailable sources:\n{sources}"
    )
    return [ChatMessage("system", system), ChatMessage("user", user)]


_REF_HEADING = re.compile(r"(?im)^#{1,3}\s*(references|sources|bibliography)\s*$")


def strip_model_references(markdown: str) -> str:
    m = _REF_HEADING.search(markdown)
    return markdown[: m.start()].rstrip() if m else markdown.rstrip()


def extract_title(markdown: str, fallback: str) -> str:
    m = re.search(r"(?m)^#\s+(.+)$", markdown)
    return (m.group(1).strip() if m else fallback)[:200]


def ensure_title_and_date(markdown: str, title: str) -> str:
    body = markdown.strip()
    if not re.match(r"^#\s", body):
        body = f"# {title}\n\n{body}"
    lines = body.split("\n", 1)
    rest = lines[1] if len(lines) > 1 else ""
    return f"{lines[0]}\n\n*Generated {today()} by ARVEN AI Deep Research*\n{rest}"


def references_section(markdown: str, registry: SourceRegistry) -> str:
    used = sorted(set(cited_numbers(markdown)))
    lines = ["## References", ""]
    for n in used:
        r = registry.get(n)
        if r is None:
            continue
        res = r.result
        date = f" Published {res.published_date}." if res.published_date else ""
        kind = f" ({r.source_type})" if r.source_type != "web" else ""
        lines.append(f"{n}. {res.title}{kind}. {res.domain}.{date} Retrieved {res.retrieved_at.astimezone():%Y-%m-%d}. <{res.url}>")
    if len(lines) == 2:
        lines.append("No sources were cited.")
    return "\n".join(lines)
