"""Phase-8 API: job status, list, cancel."""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from apps.api.deps import current_user, db_session
from database.models.job import JobState
from database.repositories import IllegalJobStateTransition, JobRepository

router = APIRouter(tags=["jobs"], prefix="/jobs")

SessionDep = Annotated[Session, Depends(db_session)]
UserDep = Annotated[dict, Depends(current_user)]


def _row(job) -> dict:  # noqa: ANN001
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
    rows = JobRepository(session).recent(limit=min(100, max(1, limit)))
    return {"jobs": [_row(j) for j in rows]}


@router.get("/{job_id}")
async def get_job(job_id: str, session: SessionDep, user: UserDep) -> dict:
    job = JobRepository(session).get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _row(job)


@router.post("/{job_id}/cancel")
async def cancel_job(job_id: str, session: SessionDep, user: UserDep) -> dict:
    repo = JobRepository(session)
    job = repo.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if JobState(job.state).is_terminal:
        return {"cancelled": False, "state": job.state}
    try:
        repo.transition(job_id, JobState.CANCELLED)
    except IllegalJobStateTransition:
        return {"cancelled": False, "state": job.state}
    return {"cancelled": True, "state": JobState.CANCELLED.value}
