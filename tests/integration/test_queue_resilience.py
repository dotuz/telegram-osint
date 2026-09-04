"""Redis-outage behaviour for the job queue.

Phase 13 finding: ``get_default_queue`` used ``redis.from_url`` (lazy) without a
connection probe, so an unreachable Redis returned a broken RedisJobQueue instead
of falling back, and ``submit_job`` then left an orphaned PENDING row.
"""

import pytest

from apps.bot.jobs import submit_job
from database.models.job import Job, JobState
from database.repositories import JobRepository
from database.session import session_scope
from workers.queue import InMemoryJobQueue, get_default_queue, set_default_queue

pytestmark = pytest.mark.integration


@pytest.fixture
def _reset_queue():
    set_default_queue(None)
    yield
    set_default_queue(None)


def test_unreachable_redis_falls_back_to_memory(monkeypatch, _reset_queue):
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")  # nothing listening
    from security.config import get_settings

    get_settings.cache_clear()
    q = get_default_queue()
    assert isinstance(q, InMemoryJobQueue)
    # and it still works
    q.enqueue("job-x")
    assert q.dequeue(timeout=0.1) == "job-x"


class _BrokenQueue:
    def enqueue(self, job_id, *, delay=0.0):  # noqa: ANN001
        raise ConnectionError("redis down")

    def dequeue(self, *, timeout=5.0):  # noqa: ANN001
        return None

    def size(self):
        return 0


def test_submit_job_marks_failed_when_enqueue_raises(db_session, _reset_queue):
    with pytest.raises(ConnectionError):
        submit_job(kind="telegram_user", params={"query": "x"}, queue=_BrokenQueue())

    with session_scope() as s:
        rows = s.query(Job).all()
        assert len(rows) == 1
        assert rows[0].state == JobState.FAILED.value
        assert "queue unavailable" in (rows[0].error or "")
    # no PENDING orphan left behind
    with session_scope() as s:
        assert JobRepository(s).pending() == []
