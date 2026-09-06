"""Investigation API: create + queue, list, detail, report download.

Every row is scoped to the caller (``InvestigationRepository`` is a
``ScopedRepository``); a non-owner gets 404, never another user's data.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.deps import Principal, current_user, db_session, resolve_user
from apps.api.security import rate_limit
from database.repositories import InvestigationRepository, JobRepository
from intelligence.investigation import InvalidTarget, parse_target
from workers.queue import get_default_queue

router = APIRouter(
    tags=["investigations"],
    prefix="/investigations",
    dependencies=[Depends(rate_limit("investigate", limit_setting="rate_limit_search_per_minute"))],
)

SessionDep = Annotated[Session, Depends(db_session)]
UserDep = Annotated[Principal, Depends(current_user)]

_MEDIA = {"json": "application/json", "html": "text/html", "pdf": "application/pdf"}


class InvestigateIn(BaseModel):
    target: str = Field(min_length=1, max_length=128)


def _repo(session: Session, principal) -> InvestigationRepository:
    return InvestigationRepository(session, resolve_user(session, principal).id)


def _row(inv, *, observations=None) -> dict:  # noqa: ANN001
    out = {
        "id": inv.id,
        "public_id": inv.public_id,
        "target": inv.target,
        "target_type": inv.target_type,
        "target_normalized": inv.target_normalized,
        "status": inv.status,
        "confidence": inv.confidence,
        "job_id": inv.job_id,
        "report_id": inv.report_id,
        "summary": json.loads(inv.summary_json) if inv.summary_json else None,
        "created_at": inv.created_at.isoformat() if inv.created_at else None,
        "completed_at": inv.completed_at.isoformat() if inv.completed_at else None,
    }
    if observations is not None:
        out["observations"] = [
            {
                "id": o.id,
                "type": o.observation_type,
                "resource_kind": o.resource_kind,
                "resource": o.resource_ref,
                "url": o.resource_url,
                "message_ref": o.message_ref,
                "snippet": o.snippet,
                "observed_at": o.observed_at.isoformat() if o.observed_at else None,
                "source": o.source,
                "confidence": o.confidence,
            }
            for o in observations
        ]
    return out


@router.get("")
async def list_investigations(session: SessionDep, user: UserDep) -> dict:
    return {"investigations": [_row(i) for i in _repo(session, user).list()]}


@router.post("")
async def create_investigation(body: InvestigateIn, session: SessionDep, user: UserDep) -> dict:
    try:
        parsed = parse_target(body.target)
    except InvalidTarget as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    u = resolve_user(session, user)
    inv = InvestigationRepository(session, u.id).create(
        target=parsed.raw, target_normalized=parsed.canonical
    )
    session.flush()

    job = JobRepository(session).create(
        kind="investigation",
        params={"investigation_id": inv.id, "user_id": u.id, "chat_id": None},
        requested_by=f"user:{u.id}",
    )
    inv.job_id = job.id
    session.flush()
    session.commit()
    get_default_queue().enqueue(job.id)

    return {"investigation": _row(inv), "job_id": job.id}


@router.get("/{investigation_id}")
async def get_investigation(investigation_id: str, session: SessionDep, user: UserDep) -> dict:
    repo = _repo(session, user)
    inv = repo.get(investigation_id) or repo.get_by_public_id(investigation_id)
    if inv is None:
        raise HTTPException(status_code=404, detail="investigation not found")
    return _row(inv, observations=list(repo.observations(inv.id)))


@router.get("/{investigation_id}/report/download")
def download_report(
    investigation_id: str,
    session: SessionDep,
    user: UserDep,
    fmt: str = Query(default="json", pattern="^(json|html|pdf)$"),
) -> Response:
    repo = _repo(session, user)
    inv = repo.get(investigation_id) or repo.get_by_public_id(investigation_id)
    if inv is None or inv.report_id is None:
        raise HTTPException(status_code=404, detail="no report for this investigation")

    from database.repositories import ReportRepository

    report = ReportRepository(session, resolve_user(session, user).id).get(inv.report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="report not found")

    artifacts = json.loads(report.artifacts_json) if report.artifacts_json else {}
    path_str = artifacts.get(fmt)
    if path_str and Path(path_str).is_file():
        return FileResponse(path_str, media_type=_MEDIA[fmt], filename=f"{inv.public_id}.{fmt}")
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
