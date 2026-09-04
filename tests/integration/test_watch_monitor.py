from datetime import UTC, datetime, timedelta

import pytest

from collectors.telegram import PublicMessage, TelegramPublicCollector
from database.models import Watchlist
from database.repositories import UserRepository, WatchlistRepository
from database.types import TargetKind
from intelligence.monitoring import WatchMonitor, due_watchlist_ids, mark_scheduled
from tests.telegram_fixtures import seeded_source
from tests.username_fixtures import alice_collector

pytestmark = pytest.mark.integration


@pytest.fixture
def watch(db_session):
    u = UserRepository(db_session).create(email="a@example.com", telegram_user_id=999)
    entry, _ = WatchlistRepository(db_session, u.id).add(
        kind=TargetKind.USERNAME, value="@opsecnews", max_targets=25
    )
    db_session.commit()
    return db_session, entry


async def _poll(session, entry_id, source):
    monitor = WatchMonitor(session, telegram_collector=TelegramPublicCollector(source))
    entry = session.get(Watchlist, entry_id)
    r = await monitor.poll(entry)
    session.commit()
    return r


async def test_first_poll_reports_all_then_dedupes(watch):
    session, entry = watch
    src = seeded_source()

    r1 = await _poll(session, entry.id, src)
    assert len(r1.activities) == 2
    assert all(a.source == "Public Channel" for a in r1.activities)

    r2 = await _poll(session, entry.id, src)
    assert r2.activities == []

    session.refresh(entry)
    assert '"telegram_max_msg_id": 11' in entry.last_seen_marker
    assert entry.last_checked_at is not None


async def test_new_message_is_detected(watch):
    session, entry = watch
    src = seeded_source()
    await _poll(session, entry.id, src)

    src.messages["opsecnews"].append(
        PublicMessage(
            message_id=50,
            chat_username="opsecnews",
            text="fresh drop",
            posted_at=datetime(2026, 5, 1, tzinfo=UTC),
            reference="https://t.me/opsecnews/50",
        )
    )
    r = await _poll(session, entry.id, src)
    assert len(r.activities) == 1
    assert "fresh drop" in r.activities[0].detail


async def test_new_platform_detected(db_session):
    u = UserRepository(db_session).create(email="b@example.com", telegram_user_id=1)
    entry, _ = WatchlistRepository(db_session, u.id).add(
        kind=TargetKind.USERNAME, value="alice", max_targets=25
    )
    db_session.commit()

    monitor = WatchMonitor(
        db_session,
        telegram_collector=TelegramPublicCollector(seeded_source()),
        username_collector=alice_collector(),
    )
    r1 = await monitor.poll(db_session.get(Watchlist, entry.id))
    db_session.commit()
    assert any(a.kind == "account" for a in r1.activities)

    r2 = await monitor.poll(db_session.get(Watchlist, entry.id))
    db_session.commit()
    assert not any(a.kind == "account" for a in r2.activities)


def test_due_and_mark_scheduled(watch):
    session, entry = watch
    assert entry.id in due_watchlist_ids(session, interval_seconds=300)

    mark_scheduled(session, entry.id)
    session.commit()
    session.refresh(entry)
    assert entry.last_checked_at is not None
    assert entry.id not in due_watchlist_ids(session, interval_seconds=300)

    entry.last_checked_at = datetime.now(UTC) - timedelta(seconds=1000)
    session.commit()
    assert entry.id in due_watchlist_ids(session, interval_seconds=300)


def test_inactive_entry_not_due(watch):
    session, entry = watch
    entry.is_active = False
    session.commit()
    assert entry.id not in due_watchlist_ids(session, interval_seconds=0)
