"""Phase-8 API: job status, list, cancel. Scoped to the caller (admins see all)."""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.deps import Principal, current_user, db_session, resolve_user
from database.models.job import Job, JobState
from database.repositories import IllegalJobStateTransition, JobRepository

router = APIRouter(tags=["jobs"], prefix="/jobs")

SessionDep = Annotated[Session, Depends(db_session)]
UserDep = Annotated[Principal, Depends(current_user)]


def _requesters(session: Session, principal: Principal) -> list[str]:
    """The ``requested_by`` values this principal is allowed to see."""
    user = resolve_user(session, principal)
    ids = [f"user:{user.id}"]
    if user.telegram_user_id is not None:
        ids.append(f"telegram:{user.telegram_user_id}")
    return ids


def _visible_job(session: Session, principal: Principal, job_id: str) -> Job | None:
    job = JobRepository(session).get(job_id)
    if job is None:
        return None
    if principal.is_admin or job.requested_by in _requesters(session, principal):
        return job
    return None


def _row(job: Job) -> dict:
    return {
        "id": job.id,
        "kind": job.kind,
        "state": job.state,
        "progress": job.progress,
        "retry_count": job.retry_count,
        "error": job.error,
        "requested_by": job.requested_by,
        "params": json.loads(job.params_json or "{}"),
        "result": json.loads(job.result_json) if job.result_json else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


@router.get("")
async def list_jobs(session: SessionDep, user: UserDep, limit: int = 25) -> dict:
    limit = min(100, max(1, limit))
    if user.is_admin:
        rows = JobRepository(session).recent(limit=limit)
    else:
        rows = list(
            session.execute(
                select(Job)
                .where(Job.requested_by.in_(_requesters(session, user)))
                .order_by(Job.created_at.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )
    return {"jobs": [_row(j) for j in rows]}


@router.get("/{job_id}")
async def get_job(job_id: str, session: SessionDep, user: UserDep) -> dict:
    job = _visible_job(session, user, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _row(job)


@router.post("/{job_id}/cancel")
async def cancel_job(job_id: str, session: SessionDep, user: UserDep) -> dict:
    job = _visible_job(session, user, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if JobState(job.state).is_terminal:
        return {"cancelled": False, "state": job.state}
    try:
        JobRepository(session).transition(job.id, JobState.CANCELLED)
    except IllegalJobStateTransition:
        return {"cancelled": False, "state": job.state}
    return {"cancelled": True, "state": JobState.CANCELLED.value}
