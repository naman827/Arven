"""Health and provider status/settings. Never returns key material."""

from typing import Any, Literal

from fastapi import APIRouter, HTTPException

from app.services.container import get_services
from app.services.search.base import SearchError

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/settings/status")
async def status() -> dict[str, Any]:
    s = get_services()
    return {
        "overall": s.router.overall_status(),
        "providers": [s.router.provider_status(p) for p in s.router.providers],
        "search": {"available": s.search.available, "providers": s.search.status()},
        "budgets": {
            "max_search_rounds": s.settings.max_search_rounds,
            "max_unique_sources": s.settings.max_unique_sources,
            "max_report_words": s.settings.max_report_words,
            "job_timeout_seconds": s.settings.job_timeout_seconds,
        },
    }


@router.post("/settings/test/{name}")
async def test_connection(name: Literal["gemini", "nvidia", "tavily", "duckduckgo"]) -> dict[str, Any]:
    s = get_services()
    if name in ("gemini", "nvidia"):
        try:
            return await s.router.test_connection(name)
        except KeyError as exc:
            raise HTTPException(404, "Unknown provider") from exc
    provider = next((p for p in s.search.providers if p.name == name), None)
    if provider is None or not provider.configured:
        return {
            "ok": False,
            "message": "Not configured." + (" Add TAVILY_API_KEY to .env and restart the backend." if name == "tavily" else ""),
        }
    try:
        results = await provider.search("ARVEN AI connection test", max_results=1)
    except SearchError as exc:
        return {"ok": False, "kind": exc.kind, "message": exc.message}
    return {"ok": True, "message": f"Connected. Search returned {len(results)} result(s)."}
