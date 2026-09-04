import pytest

from collectors.telegram import NullTelegramSource, TelegramPublicCollector
from database.models import Search, SearchResult
from database.repositories import UserRepository
from database.types import TaskStatus
from intelligence.search import TelegramIntelService
from tests.telegram_fixtures import fake_collector

pytestmark = pytest.mark.integration


@pytest.fixture
def user(db_session):
    u = UserRepository(db_session).create(email="analyst@example.com")
    db_session.commit()
    return u


@pytest.fixture
def svc(db_session, user):
    return TelegramIntelService(db_session, user.id, collector=fake_collector())


async def test_search_user_found(svc, db_session):
    r = await svc.search_user("@alice")
    db_session.commit()
    assert r.found
    assert r.summary["telegram_id"] == 42
    assert r.summary["display_name"] == "Alice Anderson"
    assert r.search_id

    search = db_session.get(Search, r.search_id)
    assert search.status == TaskStatus.COMPLETED.value
    assert db_session.query(SearchResult).filter_by(search_id=r.search_id).count() == 1


async def test_search_user_not_found(svc):
    r = await svc.search_user("@ghost")
    assert r.found is False
    assert any("no public" in n for n in r.notes)


async def test_channel_intel_reports_public_presence(svc, db_session):
    r = await svc.channel_intel("opsecnews")
    db_session.commit()
    assert r.found
    assert r.summary["participants_count"] == 12345
    assert r.summary["observed_messages"] == 2


async def test_message_search_over_corpus(svc, db_session):
    await svc.channel_intel("opsecnews")  # populate corpus
    db_session.commit()
    r = await svc.search_messages("evil.example")
    assert r.found
    assert len(r.items) == 1
    assert "evil.example" in r.items[0]["text"]


async def test_history_lists_searches(svc, db_session):
    await svc.search_user("@alice")
    await svc.channel_intel("opsecnews")
    db_session.commit()
    hist = svc.history()
    assert {h["kind"] for h in hist} == {"username", "channel"}


async def test_source_unavailable_still_returns_gracefully(db_session, user):
    svc = TelegramIntelService(
        db_session, user.id, collector=TelegramPublicCollector(NullTelegramSource())
    )
    r = await svc.search_user("@alice")
    db_session.commit()
    assert r.found is False
    assert r.source_available is False
