import pytest

from collectors.common.interfaces import CollectRequest
from collectors.telegram.collector import KIND_CHANNEL
from database.types import EntityType
from intelligence.ingest import IngestionService
from intelligence.ioc import IocService
from tests.telegram_fixtures import fake_collector

pytestmark = pytest.mark.integration


@pytest.fixture
async def populated(db_session):
    result = await fake_collector().run(CollectRequest(query="opsecnews", kind=KIND_CHANNEL))
    IngestionService(db_session).ingest(result)
    db_session.commit()
    from database.models import Message, TelegramChannel

    chan = db_session.query(TelegramChannel).one()
    msg = db_session.query(Message).filter_by(message_id=10).one()
    return chan, msg


async def test_for_message(db_session, populated):
    _chan, msg = populated
    iocs = IocService(db_session).for_message(msg.id)
    values = {i["value_normalized"] for i in iocs}
    assert "evil.example" in values
    assert any(i["ioc_type"] == "url" for i in iocs)


async def test_for_container_aggregates_and_resolves_typed(db_session, populated):
    chan, _msg = populated
    iocs = IocService(db_session).for_container(EntityType.TELEGRAM_CHANNEL.value, chan.id)
    assert {i["ioc_type"] for i in iocs} >= {"domain", "url"}
    # message 11 has no indicators -> only message 10's IOCs
    assert len(iocs) >= 3


async def test_recent_and_type_filter(db_session, populated):
    svc = IocService(db_session)
    assert svc.recent(limit=100)
    only_urls = svc.recent(limit=100, ioc_type="url")
    assert only_urls and all(i["ioc_type"] == "url" for i in only_urls)


def test_api_iocs_endpoints(settings):
    from fastapi.testclient import TestClient

    import database.models  # noqa: F401
    from apps.api.deps import get_collector
    from apps.api.main import create_app
    from database.base import Base
    from database.session import get_engine

    Base.metadata.create_all(get_engine())
    app = create_app(settings)
    app.dependency_overrides[get_collector] = lambda: fake_collector()
    with TestClient(app) as c:
        assert c.post("/api/v1/telegram/channel", json={"query": "opsecnews"}).json()["found"]

        recent = c.get("/api/v1/iocs").json()["iocs"]
        assert any(i["ioc_type"] == "domain" for i in recent)

        msg_search = c.post(
            "/api/v1/telegram/messages", json={"query": "breach dump", "limit": 5}
        ).json()
        mid = msg_search["items"][0]["entity_id"]
        per_msg = c.get(f"/api/v1/iocs?message_id={mid}").json()["iocs"]
        assert per_msg

        bad = c.get("/api/v1/iocs?ioc_type=nope").json()
        assert bad["iocs"] == [] and "unknown" in bad["note"]
    Base.metadata.drop_all(get_engine())
