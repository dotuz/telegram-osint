from datetime import UTC

import pytest

from database.models import EvidenceImmutableError
from database.repositories import EvidenceRepository
from database.types import EntityType, SourceType

pytestmark = pytest.mark.unit


def _record(session, **overrides):
    repo = EvidenceRepository(session)
    kwargs = dict(
        entity_type=EntityType.TELEGRAM_ACCOUNT,
        entity_id="acc-1",
        source=SourceType.TELEGRAM_PUBLIC.value,
        source_type="telegram",
        field="bio",
        value="hello world",
        confidence=70,
    )
    kwargs.update(overrides)
    ev, created = repo.record(**kwargs)
    return ev, created


def test_record_is_deduplicated_on_content(db_session):
    a, created_a = _record(db_session)
    b, created_b = _record(db_session)
    db_session.commit()
    assert created_a is True and created_b is False
    assert a.id == b.id


def test_new_value_creates_new_observation(db_session):
    a, _ = _record(db_session, value="bio v1")
    b, created = _record(db_session, value="bio v2")
    db_session.commit()
    assert created is True
    assert a.id != b.id

    rows = EvidenceRepository(db_session).for_entity(EntityType.TELEGRAM_ACCOUNT, "acc-1")
    assert len(rows) == 2


def test_updating_persisted_evidence_raises(db_session):
    ev, _ = _record(db_session)
    db_session.commit()

    ev.confidence = 10
    with pytest.raises(EvidenceImmutableError):
        db_session.flush()
    db_session.rollback()


def test_deleting_evidence_raises(db_session):
    ev, _ = _record(db_session)
    db_session.commit()

    db_session.delete(ev)
    with pytest.raises(EvidenceImmutableError):
        db_session.flush()
    db_session.rollback()


def test_confidence_is_clamped(db_session):
    ev, _ = _record(db_session, confidence=999)
    db_session.commit()
    assert ev.confidence == 100


def test_latest_value_prefers_most_recent_observation(db_session):
    from datetime import datetime

    _record(db_session, value="old", observed_at=datetime(2024, 1, 1, tzinfo=UTC))
    _record(db_session, value="new", observed_at=datetime(2026, 1, 1, tzinfo=UTC))
    db_session.commit()

    latest = EvidenceRepository(db_session).latest_value(
        EntityType.TELEGRAM_ACCOUNT, "acc-1", "bio"
    )
    assert latest is not None
    assert "new" in (latest.value_json or "")
