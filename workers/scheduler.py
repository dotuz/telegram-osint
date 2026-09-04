"""Periodic scheduling for watchlist polls.

Called on a timer by the worker loop (and directly by tests). Finds active
watchlist entries that are due for a check, enqueues one ``watch_poll`` job per
entry, and optimistically stamps ``last_checked_at`` so a slow poll isn't
re-enqueued before it finishes.
"""

from __future__ import annotations

from database.repositories import JobRepository
from database.session import session_scope
from intelligence.monitoring import due_watchlist_ids, mark_scheduled
from security.config import get_settings
from security.logging import get_logger
from workers.queue import JobQueue, get_default_queue

_log = get_logger("workers.scheduler")


def schedule_due_watches_tick(queue: JobQueue | None = None) -> None:
    """No-return wrapper for use as a ``JobRunner`` tick callback."""
    schedule_due_watches(queue)


def schedule_due_watches(
    queue: JobQueue | None = None, *, interval_seconds: int | None = None
) -> int:
    q = queue or get_default_queue()
    interval = interval_seconds or get_settings().watch_poll_interval_seconds

    job_ids: list[str] = []
    with session_scope() as session:
        due = due_watchlist_ids(session, interval_seconds=interval)
        repo = JobRepository(session)
        for wid in due:
            job = repo.create(kind="watch_poll", params={"watchlist_id": wid})
            mark_scheduled(session, wid)
            job_ids.append(job.id)
        session.commit()

    for jid in job_ids:
        q.enqueue(jid)
    if job_ids:
        _log.info("watch_polls_scheduled", count=len(job_ids))
    return len(job_ids)
