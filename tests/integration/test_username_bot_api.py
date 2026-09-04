from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from apps.bot.handlers import username_osint as handler
from tests.username_fixtures import alice_collector

pytestmark = pytest.mark.integration


@pytest.fixture
def bot_db():
    import database.models  # noqa: F401
    from database.base import Base
    from database.session import get_engine

    engine = get_engine()
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


def _ctx(args, collector=None):
    app = SimpleNamespace(bot_data={"username_collector": collector} if collector else {})
    return SimpleNamespace(args=args, application=app)


def _update(uid=111):
    msg = SimpleNamespace(reply_text=AsyncMock())
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=uid, first_name="A"),
        effective_message=msg,
        effective_chat=SimpleNamespace(send_action=AsyncMock()),
        callback_query=None,
    ), msg


async def test_username_handler_lists_sources_with_disclaimer(bot_db):
    update, msg = _update()
    await handler.username_osint(update, _ctx(["@alice"], alice_collector()))
    text = msg.reply_text.call_args.args[0]
    assert "Username OSINT" in text
    assert "github" in text and "telegram" in text
    assert "potential match" in text
    assert "not proof of a shared identity" in text
    assert "the same person" not in text.lower() or "assume the" in text.lower()


async def test_username_handler_usage(bot_db):
    update, msg = _update()
    await handler.username_osint(update, _ctx([]))
    assert "Usage" in msg.reply_text.call_args.args[0]


async def test_username_handler_denied(bot_db):
    update, msg = _update(uid=999)
    await handler.username_osint(update, _ctx(["@alice"], alice_collector()))
    assert "not authorized" in msg.reply_text.call_args.args[0].lower()


def test_api_username_endpoint(settings):
    from fastapi.testclient import TestClient

    import database.models  # noqa: F401
    from apps.api.deps import get_username_collector
    from apps.api.main import create_app
    from database.base import Base
    from database.session import get_engine

    Base.metadata.create_all(get_engine())
    app = create_app(settings)
    app.dependency_overrides[get_username_collector] = alice_collector
    with TestClient(app) as c:
        resp = c.post("/api/v1/username", json={"username": "@alice"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["found"] is True
        assert {s["platform"] for s in body["sources"]} == {"github", "telegram"}
        assert body["sources"][0]["confidence"] >= 45
        assert body["disclaimer"]
        assert body["same_as_edges"]

        assert c.post("/api/v1/username", json={"username": ""}).status_code == 422
    Base.metadata.drop_all(get_engine())
