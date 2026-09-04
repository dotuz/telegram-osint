"""Bot-side job submission helpers.

The bot never runs collection inline. A command validates input, creates a
``Job`` row, enqueues it, and returns immediately. The worker delivers the
result back to the originating chat.
"""

from __future__ import annotations

from collections.abc import Mapping

from database.models.job import JobState
from database.repositories import IllegalJobStateTransition, JobRepository
from database.session import session_scope
from security.logging import get_logger
from workers.queue import JobQueue, get_default_queue

_log = get_logger("bot.jobs")


def submit_job(
    *,
    kind: str,
    params: Mapping[str, object],
    requested_by: str | None = None,
    queue: JobQueue | None = None,
) -> str:
    q = queue or get_default_queue()
    with session_scope() as session:
        job = JobRepository(session).create(
            kind=kind, params=dict(params), requested_by=requested_by
        )
        session.commit()
        job_id = job.id
    q.enqueue(job_id)
    _log.info("job_submitted", job_id=job_id, kind=kind)
    return job_id


def find_job_id(prefix: str, *, requested_by: str | None = None) -> str | None:
    """Resolve a short id prefix to a full job id, optionally scoped to a requester."""
    from sqlalchemy import select

    from database.models.job import Job

    with session_scope() as session:
        stmt = select(Job.id).where(Job.id.like(f"{prefix}%"))
        if requested_by is not None:
            stmt = stmt.where(Job.requested_by == requested_by)
        rows = session.execute(stmt.limit(2)).scalars().all()
        return rows[0] if len(rows) == 1 else None


def cancel_job(job_id: str) -> bool:
    with session_scope() as session:
        repo = JobRepository(session)
        job = repo.get(job_id)
        if job is None or JobState(job.state).is_terminal:
            return False
        try:
            repo.transition(job_id, JobState.CANCELLED)
        except IllegalJobStateTransition:
            return False
        return True
