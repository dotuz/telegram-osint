"""Job repository: creation and the state-machine transitions.

The worker layer (Phase 8) drives progress/retries; this repository just owns
the persistence and guards illegal transitions.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from sqlalchemy import select

from database.base import utcnow
from database.models.job import Job, JobState
from database.repositories.base import BaseRepository

_ALLOWED: dict[JobState, set[JobState]] = {
    JobState.PENDING: {JobState.RUNNING, JobState.CANCELLED},
    JobState.RUNNING: {JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED, JobState.PENDING},
    JobState.COMPLETED: set(),
    JobState.FAILED: {JobState.PENDING},  # retry
    JobState.CANCELLED: set(),
}


class IllegalJobStateTransition(RuntimeError):
    """Raised when a job is moved between states the machine does not allow."""


class JobRepository(BaseRepository[Job]):
    model = Job

    def create(
        self,
        *,
        kind: str,
        params: Mapping[str, object] | None = None,
        requested_by: str | None = None,
        max_retries: int = 3,
    ) -> Job:
        job = Job(
            kind=kind,
            params_json=json.dumps(dict(params), default=str) if params else "{}",
            requested_by=requested_by,
            max_retries=max_retries,
        )
        return self.add(job)

    def transition(
        self,
        job_id: str,
        to: JobState,
        *,
        progress: int | None = None,
        error: str | None = None,
        result: Mapping[str, object] | None = None,
    ) -> Job:
        job = self.get(job_id)
        if job is None:
            raise LookupError(f"job {job_id} not found")
        current = JobState(job.state)
        if to != current and to not in _ALLOWED[current]:
            raise IllegalJobStateTransition(f"{current} -> {to}")

        job.state = to.value
        if to is JobState.RUNNING and job.started_at is None:
            job.started_at = utcnow()
        if to is JobState.PENDING and current is JobState.FAILED:
            job.retry_count += 1
            job.error = None
        if to.is_terminal:
            job.completed_at = utcnow()
        if progress is not None:
            job.progress = max(0, min(100, progress))
        if error is not None:
            job.error = error
        if result is not None:
            job.result_json = json.dumps(dict(result), default=str)
        self.session.flush()
        return job

    def pending(self, *, limit: int = 50) -> Sequence[Job]:
        stmt = (
            select(Job)
            .where(Job.state == JobState.PENDING.value)
            .order_by(Job.created_at.asc())
            .limit(limit)
        )
        return self.session.execute(stmt).scalars().all()

    def recent(self, *, limit: int = 50) -> Sequence[Job]:
        stmt = select(Job).order_by(Job.created_at.desc()).limit(limit)
        return self.session.execute(stmt).scalars().all()
