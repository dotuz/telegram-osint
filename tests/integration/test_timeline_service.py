from datetime import UTC, datetime

import pytest

from database.repositories import (
    EvidenceRepository,
    MessageRepository,
    RelationshipRepository,
    TelegramAccountRepository,
    TelegramChannelRepository,
)
from database.types import EntityType, RelationshipType, SourceType
from intelligence.timeline import TimelineService

pytestmark = pytest.mark.integration


@pytest.fixture
def chan(db_session):
    ch, _ = TelegramChannelRepository(db_session).get_or_create(telegram_id=-100, username="news")
    ch.first_observed_at = datetime(2024, 6, 1, tzinfo=UTC)
    db_session.flush()

    EvidenceRepository(db_session).record(
        entity_type=EntityType.TELEGRAM_CHANNEL.value,
        entity_id=ch.id,
        field="title",
        value="News",
        source=SourceType.TELEGRAM_PUBLIC.value,
        source_type="telegram",
        observed_at=datetime(2025, 1, 15, tzinfo=UTC),
        confidence=80,
    )
    MessageRepository(db_session).upsert(
        source_type=EntityType.TELEGRAM_CHANNEL.value,
        source_id=ch.id,
        message_id=1,
        text="hello",
        posted_at=datetime(2026, 3, 3, tzinfo=UTC),
    )
    acc, _ = TelegramAccountRepository(db_session).get_or_create(telegram_id=5, username="poster")
    RelationshipRepository(db_session).observe(
        source_type=EntityType.TELEGRAM_ACCOUNT.value,
        source_id=acc.id,
        target_type=EntityType.TELEGRAM_CHANNEL.value,
        target_id=ch.id,
        rel_type=RelationshipType.ACCOUNT_MEMBER_OF_GROUP.value,
        confidence=40,
    )
    db_session.commit()
    return db_session, ch


def test_timeline_collects_all_event_kinds_in_order(chan):
    session, ch = chan
    tl = TimelineService(session).for_entity(EntityType.TELEGRAM_CHANNEL.value, ch.id)
    kinds = [e.kind for e in tl.events]
    assert set(kinds) == {"account", "evidence", "message", "relationship"}
    whens = [e.when for e in tl.events]
    assert whens == sorted(whens)


def test_timeline_by_year(chan):
    session, ch = chan
    tl = TimelineService(session).for_entity(EntityType.TELEGRAM_CHANNEL.value, ch.id)
    years = tl.by_year()
    assert set(years) == {2024, 2025, 2026}
    assert years[2024][0]["kind"] == "account"


def test_timeline_as_dict_shape(chan):
    session, ch = chan
    d = TimelineService(session).for_entity(EntityType.TELEGRAM_CHANNEL.value, ch.id).as_dict()
    assert d["root"].startswith("telegram_channel:")
    assert "by_year" in d and d["events"]
    assert all("year" in e for e in d["events"])
