import pytest

from database.models import AuditLog, Job, JobState
from database.repositories import AuditRepository

pytestmark = pytest.mark.unit


def test_job_defaults_and_state_machine(db_session):
    job = Job(kind="username_osint", params_json='{"username": "example"}')
    db_session.add(job)
    db_session.commit()

    assert job.id
    assert job.state == JobState.PENDING.value
    assert job.progress == 0
    assert job.retry_count == 0
    assert JobState.PENDING.is_terminal is False
    assert JobState.COMPLETED.is_terminal is True


def test_job_progress_check_constraint(db_session):
    from sqlalchemy.exc import IntegrityError

    db_session.add(Job(kind="x", params_json="{}", progress=150))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_audit_repository_scrubs_secrets(db_session):
    repo = AuditRepository(db_session)
    entry = repo.record(
        actor="telegram:111",
        action="search",
        resource="target:abc",
        metadata={"query": "example.com", "token": "SHOULD_NOT_PERSIST"},
    )
    db_session.commit()

    stored = db_session.get(AuditLog, entry.id)
    assert "SHOULD_NOT_PERSIST" not in (stored.metadata_json or "")
    assert "example.com" in stored.metadata_json
    assert "<redacted>" in stored.metadata_json


def test_audit_recent_filter(db_session):
    repo = AuditRepository(db_session)
    repo.record(actor="telegram:111", action="login")
    repo.record(actor="telegram:222", action="login")
    db_session.commit()

    assert len(repo.recent(limit=10)) == 2
    assert len(repo.recent(limit=10, actor="telegram:111")) == 1
