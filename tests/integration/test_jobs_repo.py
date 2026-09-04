import pytest

from database.models import JobState
from database.repositories import IllegalJobStateTransition, JobRepository

pytestmark = pytest.mark.integration


def test_job_lifecycle(db_session):
    repo = JobRepository(db_session)
    job = repo.create(
        kind="username_osint", params={"username": "alice"}, requested_by="telegram:1"
    )
    db_session.commit()
    assert job.state == JobState.PENDING.value

    repo.transition(job.id, JobState.RUNNING, progress=10)
    assert job.started_at is not None

    repo.transition(job.id, JobState.COMPLETED, progress=100, result={"hits": 3})
    db_session.commit()
    assert job.state == JobState.COMPLETED.value
    assert job.completed_at is not None
    assert '"hits": 3' in job.result_json


def test_illegal_transition_rejected(db_session):
    repo = JobRepository(db_session)
    job = repo.create(kind="x")
    db_session.commit()
    with pytest.raises(IllegalJobStateTransition):
        repo.transition(job.id, JobState.COMPLETED)  # PENDING -> COMPLETED not allowed


def test_failed_job_can_retry_to_pending(db_session):
    repo = JobRepository(db_session)
    job = repo.create(kind="x")
    repo.transition(job.id, JobState.RUNNING)
    repo.transition(job.id, JobState.FAILED, error="boom")
    repo.transition(job.id, JobState.PENDING)
    db_session.commit()
    assert job.state == JobState.PENDING.value
    assert job.retry_count == 1
    assert job.error is None


def test_pending_queue_order(db_session):
    repo = JobRepository(db_session)
    j1 = repo.create(kind="a")
    j2 = repo.create(kind="b")
    db_session.commit()
    pending = list(repo.pending())
    assert [j.id for j in pending] == [j1.id, j2.id]
