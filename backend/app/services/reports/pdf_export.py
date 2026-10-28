"""Render a stored Markdown report to PDF with ReportLab."""

import io
import re
from datetime import datetime
from html import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    ListFlowable,
    ListItem,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ACCENT = colors.HexColor("#2457d6")
MUTED = colors.HexColor("#5b6472")


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=base["BodyText"], fontName="Helvetica", fontSize=10.5, leading=15, alignment=TA_LEFT, spaceAfter=6)
    return {
        "title": ParagraphStyle(
            "title", parent=base["Title"], fontName="Helvetica-Bold", fontSize=20, leading=25, alignment=TA_LEFT, spaceAfter=4
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=18,
            spaceBefore=12,
            spaceAfter=6,
            textColor=colors.HexColor("#111827"),
        ),
        "h3": ParagraphStyle(
            "h3", parent=base["Heading3"], fontName="Helvetica-Bold", fontSize=12, leading=16, spaceBefore=8, spaceAfter=4
        ),
        "body": body,
        "meta": ParagraphStyle("meta", parent=body, fontSize=9, textColor=MUTED),
        "ref": ParagraphStyle("ref", parent=body, fontSize=9, leading=12.5, leftIndent=14, firstLineIndent=-14),
        "cell": ParagraphStyle("cell", parent=body, fontSize=9, leading=12, spaceAfter=0),
        "code": ParagraphStyle("code", parent=body, fontName="Courier", fontSize=8.5, leading=11, backColor=colors.HexColor("#f3f4f6")),
    }


def inline(text: str, ref_anchors: bool = True) -> str:
    """Escape and convert minimal inline Markdown to ReportLab markup."""
    out = escape(text, quote=False)
    out = re.sub(r"`([^`]+)`", r'<font face="Courier">\1</font>', out)
    out = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", out)
    out = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", out)
    out = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", lambda m: f'<link href="{m.group(2)}" color="#2457d6">{m.group(1)}</link>', out)
    out = re.sub(r"&lt;(https?://\S+?)&gt;", lambda m: f'<link href="{m.group(1)}" color="#2457d6">{m.group(1)}</link>', out)
    if ref_anchors:
        out = re.sub(r"\[(\d{1,3})\]", r'<link href="#ref\1" color="#2457d6">[\1]</link>', out)
    return out


def _table(rows: list[str], styles: dict[str, ParagraphStyle], width: float) -> Table:
    parsed = []
    for row in rows:
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue
        parsed.append(cells)
    ncols = max(len(r) for r in parsed)
    data = [[Paragraph(inline(c), styles["cell"]) for c in r + [""] * (ncols - len(r))] for r in parsed]
    table = Table(data, colWidths=[width / ncols] * ncols, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2fb")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def render_report_pdf(markdown: str, *, title: str, created_at: datetime | None = None) -> bytes:
    styles = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        title=title,
        author="ARVEN AI",
    )
    width = A4[0] - 40 * mm
    story: list = []
    lines = markdown.replace("\r\n", "\n").split("\n")
    in_refs = False
    i = 0
    title_done = False

    def flush_list(items: list[str], ordered: bool) -> None:
        if not items:
            return
        flow = ListFlowable(
            [ListItem(Paragraph(inline(t), styles["body"]), leftIndent=12) for t in items],
            bulletType="1" if ordered else "bullet",
            start="1" if ordered else None,
            leftIndent=14,
            bulletFontSize=9,
        )
        story.append(flow)

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        if stripped.startswith("```"):
            code = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            story.append(Preformatted("\n".join(code), styles["code"]))
            i += 1
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            level, text = len(heading.group(1)), heading.group(2)
            if level == 1 and not title_done:
                story.append(Paragraph(inline(text, False), styles["title"]))
                title_done = True
            else:
                in_refs = text.strip().lower() in ("references", "sources")
                story.append(Paragraph(inline(text, False), styles["h2" if level <= 2 else "h3"]))
            i += 1
            continue
        if stripped.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(lines[i])
                i += 1
            story.append(KeepTogether([_table(rows, styles, width), Spacer(1, 6)]))
            continue
        if in_refs and re.match(r"^\d+\.\s", stripped):
            num = stripped.split(".", 1)[0]
            story.append(Paragraph(f'<a name="ref{num}"/>{inline(stripped, False)}', styles["ref"]))
            i += 1
            continue
        bullet = re.match(r"^([-*+]|\d+\.)\s+(.*)$", stripped)
        if bullet:
            ordered = bullet.group(1)[0].isdigit()
            items = []
            while i < len(lines):
                m = re.match(r"^\s*([-*+]|\d+\.)\s+(.*)$", lines[i])
                if not m or m.group(1)[0].isdigit() != ordered:
                    break
                items.append(m.group(2))
                i += 1
            flush_list(items, ordered)
            continue
        para = [stripped]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r"^(#{1,6}\s|[-*+]\s|\d+\.\s|\||```)", lines[i].strip()):
            para.append(lines[i].strip())
            i += 1
        text = " ".join(para)
        style = styles["meta"] if text.startswith("*Generated") else styles["body"]
        story.append(Paragraph(inline(text), style))

    if not title_done:
        story.insert(0, Paragraph(inline(title, False), styles["title"]))
    if created_at is not None and not any(isinstance(f, Paragraph) and "Generated" in f.text for f in story[:4]):
        story.insert(1, Paragraph(f"Generated {created_at:%Y-%m-%d} by ARVEN AI", styles["meta"]))

    def footer(canvas, document):  # type: ignore[no-untyped-def]
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(20 * mm, 12 * mm, title[:90])
        canvas.drawRightString(A4[0] - 20 * mm, 12 * mm, f"Page {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
