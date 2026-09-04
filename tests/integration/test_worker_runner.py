import pytest

from database.models import Job, JobState
from database.repositories import JobRepository, UserRepository
from database.session import session_scope
from tests.telegram_fixtures import fake_collector
from tests.username_fixtures import alice_collector
from tests.worker_helpers import CapturingRunner
from workers.registry import JobOutcome, register
from workers.runner import JobRunner

pytestmark = pytest.mark.integration


@pytest.fixture
def user(db_session):
    u = UserRepository(db_session).create(email="a@example.com")
    db_session.commit()
    return u


def _submit(queue, kind, params):
    with session_scope() as s:
        job = JobRepository(s).create(kind=kind, params=params)
        s.commit()
        jid = job.id
    queue.enqueue(jid)
    return jid


def test_telegram_user_job_completes_with_notification(db_session, user):
    runner = CapturingRunner(telegram=fake_collector())
    jid = _submit(
        runner.queue, "telegram_user", {"query": "@alice", "user_id": user.id, "chat_id": 9}
    )

    assert runner.drain() == 1
    job = db_session.get(Job, jid)
    db_session.refresh(job)
    assert job.state == JobState.COMPLETED.value
    assert job.progress == 100
    assert '"found": true' in job.result_json
    assert runner.notifications[0].chat_id == 9


def test_username_job_completes(db_session, user):
    runner = CapturingRunner(username=alice_collector())
    jid = _submit(
        runner.queue, "username_osint", {"query": "alice", "user_id": user.id, "chat_id": 1}
    )
    runner.drain()
    job = db_session.get(Job, jid)
    db_session.refresh(job)
    assert job.state == JobState.COMPLETED.value


def test_unknown_kind_fails(db_session):
    runner = CapturingRunner()
    jid = _submit(runner.queue, "does_not_exist", {})
    runner.drain()
    job = db_session.get(Job, jid)
    db_session.refresh(job)
    assert job.state == JobState.FAILED.value
    assert "no handler" in job.error


def test_retry_with_backoff_then_success(db_session):
    attempts = {"n": 0}

    @register("flaky_test")
    async def _flaky(ctx):  # noqa: ANN001
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("transient")
        return JobOutcome(summary={"ok": True})

    runner = CapturingRunner(retry_base_seconds=0.001)
    jid = _submit(runner.queue, "flaky_test", {})

    # 3 dequeues: fail, fail, succeed (delayed re-enqueue promotes quickly)
    import time

    for _ in range(6):
        runner.drain()
        time.sleep(0.005)
        with session_scope() as s:
            if JobState(s.get(Job, jid).state).is_terminal:
                break

    job = db_session.get(Job, jid)
    db_session.refresh(job)
    assert job.state == JobState.COMPLETED.value
    assert job.retry_count == 2
    assert attempts["n"] == 3


def test_exhausted_retries_end_failed(db_session):
    @register("always_fail")
    async def _fail(ctx):  # noqa: ANN001
        raise RuntimeError("nope")

    runner = CapturingRunner(retry_base_seconds=0.001)
    with session_scope() as s:
        job = JobRepository(s).create(kind="always_fail", params={}, max_retries=2)
        s.commit()
        jid = job.id
    runner.queue.enqueue(jid)

    import time

    for _ in range(8):
        runner.drain()
        time.sleep(0.004)
        with session_scope() as s:
            if JobState(s.get(Job, jid).state).is_terminal:
                break

    job = db_session.get(Job, jid)
    db_session.refresh(job)
    assert job.state == JobState.FAILED.value
    assert job.retry_count == 2


def test_cancelled_job_is_skipped(db_session):
    runner = CapturingRunner(telegram=fake_collector())
    with session_scope() as s:
        repo = JobRepository(s)
        job = repo.create(kind="telegram_user", params={"query": "x", "user_id": "u"})
        repo.transition(job.id, JobState.CANCELLED)
        s.commit()
        jid = job.id
    runner.queue.enqueue(jid)

    runner.drain()
    job = db_session.get(Job, jid)
    db_session.refresh(job)
    assert job.state == JobState.CANCELLED.value
    assert not runner.notifications


def test_run_once_returns_none_when_empty():
    runner = JobRunner(CapturingRunner().queue, notifier=lambda n: None)
    assert runner.run_once(poll_timeout=0.02) is None
