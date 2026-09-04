import pytest

from database.repositories import UserRepository
from intelligence.search import TelegramIntelService
from tests.telegram_fixtures import fake_collector

pytestmark = pytest.mark.integration


@pytest.fixture
def svc(db_session):
    u = UserRepository(db_session).create(email="a@example.com")
    db_session.commit()
    return TelegramIntelService(db_session, u.id, collector=fake_collector())


async def test_channel_summary_includes_ioc_count(svc, db_session):
    r = await svc.channel_intel("opsecnews")
    db_session.commit()
    assert r.summary["ioc_count"] >= 3


async def test_message_search_items_carry_iocs(svc, db_session):
    await svc.channel_intel("opsecnews")
    db_session.commit()
    r = await svc.search_messages("breach dump")
    assert r.items
    iocs = r.items[0]["iocs"]
    assert any(i["ioc_type"] == "url" for i in iocs)
    assert any(i["ioc_type"] == "domain" for i in iocs)
