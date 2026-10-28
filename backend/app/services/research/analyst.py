"""Evidence compression, coverage scoring, gap and conflict detection per subquestion."""

from app.services.providers.base import ChatMessage
from app.services.providers.router import ProviderRouter
from app.services.research.prompts import DATA_GUARD, data_block
from app.services.research.reader import SourceRecord
from app.services.research.schemas import SubQuestionAnalysis


def evidence_blocks(records: list[SourceRecord], per_source_chars: int = 2400) -> str:
    blocks = []
    for r in records:
        if not r.passages:
            continue
        date = f", published {r.result.published_date}" if r.result.published_date else ""
        label = f"[{r.number}] {r.result.title} ({r.result.domain}{date}; type: {r.source_type})"
        blocks.append(data_block(label, "\n...\n".join(r.passages), limit=per_source_chars))
    return "\n\n".join(blocks)


async def analyze_subquestion(router: ProviderRouter, subquestion: str, records: list[SourceRecord]) -> SubQuestionAnalysis:
    usable = [r for r in records if r.passages]
    if not usable:
        return SubQuestionAnalysis(findings=[], coverage=0.0, gaps=["No readable sources were found for this subquestion."])
    valid = {r.number for r in usable}
    messages = [
        ChatMessage(
            "system",
            "You are the analysis step of a research system. From the evidence passages, extract the key findings "
            "that answer the subquestion. Each finding must cite the source numbers (from the block labels) that "
            "directly support it. Only state what the passages actually say. Then score coverage from 0 to 1, list "
            "remaining gaps, list conflicts where sources disagree, flag claims that rest on a single weak source as "
            "gaps, and suggest up to 3 targeted follow-up search queries for the gaps. " + DATA_GUARD,
        ),
        ChatMessage("user", f"Subquestion: {subquestion}\n\nEvidence:\n{evidence_blocks(usable)}"),
    ]
    analysis = await router.generate_structured(messages, SubQuestionAnalysis)
    for finding in analysis.findings:
        finding.citations = [n for n in finding.citations if n in valid]
    analysis.findings = [f for f in analysis.findings if f.citations]
    return analysis
