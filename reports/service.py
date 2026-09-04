"""Report generation orchestration: build content, render artifacts, persist."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from database.models.report import Report
from database.models.target import Target
from database.repositories import ReportRepository
from database.types import TaskStatus
from reports.builder import ReportBuilder
from reports.models import ReportContent
from reports.renderers import PDF_AVAILABLE, render_html, render_json, render_pdf
from security.config import get_settings
from security.logging import get_logger

_log = get_logger("reports.service")

_ALL_FORMATS = ("json", "html", "pdf")


@dataclass
class GenerationResult:
    report_id: str
    status: str
    artifacts: dict[str, str] = field(default_factory=dict)
    summary: str | None = None
    section_count: int = 0
    notes: list[str] = field(default_factory=list)


def generate_report(
    session: Session,
    report_id: str,
    *,
    formats: list[str] | None = None,
) -> GenerationResult:
    report = session.get(Report, report_id)
    if report is None:
        raise LookupError(f"report {report_id} not found")

    repo = ReportRepository(session, report.user_id)
    repo.set_status(report_id, TaskStatus.RUNNING)

    target = session.get(Target, report.target_id) if report.target_id else None
    if target is None:
        repo.set_status(report_id, TaskStatus.FAILED, error="report has no target")
        return GenerationResult(report_id=report_id, status="FAILED", notes=["no target"])

    wanted = [f for f in (formats or list(_ALL_FORMATS)) if f in _ALL_FORMATS]
    content: ReportContent = ReportBuilder(session, report.user_id).build(report_id, target)

    out_dir = Path(get_settings().reports_dir) / report_id
    out_dir.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, str] = {}
    notes: list[str] = []

    json_text = render_json(content)
    if "json" in wanted:
        p = out_dir / "report.json"
        p.write_text(json_text, encoding="utf-8")
        artifacts["json"] = str(p)
    if "html" in wanted:
        p = out_dir / "report.html"
        p.write_text(render_html(content), encoding="utf-8")
        artifacts["html"] = str(p)
    if "pdf" in wanted:
        if PDF_AVAILABLE:
            p = out_dir / "report.pdf"
            p.write_bytes(render_pdf(content))
            artifacts["pdf"] = str(p)
        else:  # pragma: no cover
            notes.append("PDF skipped: fpdf2 not installed")

    report.content_json = json_text
    report.artifacts_json = json.dumps(artifacts)
    report.summary = content.section("executive_summary").data.get("text")
    repo.set_status(report_id, TaskStatus.COMPLETED)

    _log.info("report_generated", report_id=report_id, formats=list(artifacts))
    return GenerationResult(
        report_id=report_id,
        status="COMPLETED",
        artifacts=artifacts,
        summary=report.summary,
        section_count=len(content.sections),
        notes=notes,
    )
