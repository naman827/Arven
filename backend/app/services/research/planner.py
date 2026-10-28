"""Planning and query generation."""

from app.services.providers.base import ChatMessage
from app.services.providers.router import ProviderRouter
from app.services.research.prompts import DATA_GUARD, today
from app.services.research.schemas import QuerySet, ResearchPlan, SubQuestion


async def make_plan(router: ProviderRouter, question: str, *, focus: str = "general") -> ResearchPlan:
    focus_note = (
        "Academic focus: favor peer-reviewed papers, institutions, and DOIs; note preprints separately."
        if focus == "academic"
        else "General focus: favor primary and authoritative sources."
    )
    messages = [
        ChatMessage(
            "system",
            "You are the planning step of a deep research system. Break the user's question into 3-7 distinct, "
            "non-overlapping subquestions that together answer it. For each, state what evidence would answer it. "
            f"List claims that are time-sensitive (may have changed recently). Today's date is {today()}. "
            f"{focus_note} {DATA_GUARD}",
        ),
        ChatMessage("user", f"Research question:\n{question[:4000]}"),
    ]
    plan = await router.generate_structured(messages, ResearchPlan)
    if len(plan.subquestions) < 3 and len(question) > 0:
        # Pad very small plans with a neutral background subquestion so coverage is not trivially thin.
        plan.subquestions.append(
            SubQuestion(question=f"Background and key context: {question[:300]}", evidence_needed="Overview from authoritative sources")
        )
    return plan


async def make_queries(
    router: ProviderRouter, subquestion: str, *, main_question: str, count: int, focus: str = "general", avoid: list[str] | None = None
) -> list[str]:
    avoid_text = ("\nAlready tried (do not repeat):\n- " + "\n- ".join(avoid[:12])) if avoid else ""
    academic = (
        " Include at least one query aimed at scholarly sources (e.g. adding 'study', 'paper', or 'doi')." if focus == "academic" else ""
    )
    messages = [
        ChatMessage(
            "system",
            f"Write {count} web search queries for the subquestion. Each query must take a DIFFERENT angle "
            "(e.g. definitions/official sources, data/statistics, critiques/limitations, recent developments), not a "
            f"rewording. Keep each under 12 words. Today's date is {today()}.{academic}",
        ),
        ChatMessage("user", f"Main question: {main_question[:800]}\nSubquestion: {subquestion[:400]}{avoid_text}"),
    ]
    result = await router.generate_structured(messages, QuerySet)
    return result.queries[:count]
