"""Reports: list, view, PDF export."""

import asyncio
import re

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select

from app.db.models import Report, Source
from app.db.session import session_factory
from app.schemas.api import ReportOut, ReportSummary, SourceOut
from app.services.reports.pdf_export import render_report_pdf

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("", response_model=list[ReportSummary])
async def list_reports() -> list[Report]:
    async with session_factory()() as session:
        return list((await session.execute(select(Report).order_by(Report.created_at.desc()))).scalars().all())


@router.get("/{report_id}", response_model=ReportOut)
async def get_report(report_id: str) -> ReportOut:
    async with session_factory()() as session:
        report = await session.get(Report, report_id)
        if report is None:
            raise HTTPException(404, "Report not found")
        sources = []
        if report.job_id:
            rows = await session.execute(select(Source).where(Source.job_id == report.job_id).order_by(Source.number))
            sources = [SourceOut.model_validate(s) for s in rows.scalars().all()]
        return ReportOut(
            **ReportSummary.model_validate(report).model_dump(),
            markdown=report.markdown,
            verification=report.verification,
            provider=report.provider,
            sources=sources,
        )


@router.get("/{report_id}/pdf")
async def report_pdf(report_id: str) -> Response:
    async with session_factory()() as session:
        report = await session.get(Report, report_id)
        if report is None:
            raise HTTPException(404, "Report not found")
        markdown, title, created = report.markdown, report.title, report.created_at
    pdf = await asyncio.to_thread(render_report_pdf, markdown, title=title, created_at=created)
    slug = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-")[:60] or "report"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{slug}.pdf"'},
    )
