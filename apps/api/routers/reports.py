"""Phase-10 API: report generation + download."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.deps import Principal, current_user, db_session, resolve_user
from database.repositories import ReportRepository, TargetRepository
from database.types import TargetKind
from intelligence.entity_resolution import TargetResolver
from reports.service import generate_report

router = APIRouter(tags=["reports"], prefix="/reports")

SessionDep = Annotated[Session, Depends(db_session)]
UserDep = Annotated[Principal, Depends(current_user)]

_MEDIA = {"json": "application/json", "html": "text/html", "pdf": "application/pdf"}


class ReportIn(BaseModel):
    value: str | None = Field(default=None, max_length=190)
    target_id: str | None = None
    title: str | None = None
    formats: list[str] | None = None


def _repo(session: Session, principal) -> ReportRepository:
    return ReportRepository(session, resolve_user(session, principal).id)


def _row(r) -> dict:  # noqa: ANN001
    return {
        "id": r.id,
        "title": r.title,
        "status": r.status,
        "target_id": r.target_id,
        "summary": r.summary,
        "artifacts": json.loads(r.artifacts_json) if r.artifacts_json else {},
        "generated_at": r.generated_at.isoformat() if r.generated_at else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.get("")
async def list_reports(session: SessionDep, user: UserDep) -> dict:
    return {"reports": [_row(r) for r in _repo(session, user).list()]}


@router.post("")
async def create_report(body: ReportIn, session: SessionDep, user: UserDep) -> dict:
    u = resolve_user(session, user)
    treports = TargetRepository(session, u.id)

    if body.target_id:
        target = treports.get(body.target_id)
        if target is None:
            raise HTTPException(status_code=404, detail="target not found")
    elif body.value:
        target, _ = treports.get_or_create(kind=TargetKind.USERNAME, value=body.value)
        session.flush()
        TargetResolver(session).resolve(target)
    else:
        raise HTTPException(status_code=422, detail="value or target_id is required")

    report = ReportRepository(session, u.id).create(
        title=body.title or f"OSINT report — {target.value}", target_id=target.id
    )
    session.flush()
    result = generate_report(session, report.id, formats=body.formats)
    return {"report": _row(session.get(type(report), report.id)), "generation": result.__dict__}


@router.get("/{report_id}")
async def get_report(report_id: str, session: SessionDep, user: UserDep) -> dict:
    report = _repo(session, user).get(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="report not found")
    row = _row(report)
    row["content"] = json.loads(report.content_json) if report.content_json else None
    return row


@router.get("/{report_id}/download")
def download_report(
    report_id: str,
    session: SessionDep,
    user: UserDep,
    fmt: str = Query(default="json", pattern="^(json|html|pdf)$"),
) -> Response:
    report = _repo(session, user).get(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="report not found")

    artifacts = json.loads(report.artifacts_json) if report.artifacts_json else {}
    path_str = artifacts.get(fmt)
    if path_str and Path(path_str).is_file():
        return FileResponse(
            path_str, media_type=_MEDIA[fmt], filename=f"report-{report_id[:8]}.{fmt}"
        )

    # fall back to the stored JSON content when the file isn't on disk
    if fmt == "json" and report.content_json:
        return JSONResponse(content=json.loads(report.content_json))
    if fmt == "html" and report.content_json:
        from reports.models import Claim, ReportContent, Section
        from reports.renderers import render_html

        d = json.loads(report.content_json)
        content = ReportContent(
            report_id=d["report_id"],
            title=d["title"],
            target=d["target"],
            generated_at=__import__("datetime").datetime.fromisoformat(d["generated_at"]),
            sections={
                s["key"]: Section(
                    key=s["key"],
                    claims=[Claim(**c) for c in s["claims"]],
                    data=s["data"],
                )
                for s in d["sections"]
            },
        )
        return PlainTextResponse(render_html(content), media_type="text/html")

    raise HTTPException(status_code=404, detail=f"{fmt} artifact not available")
