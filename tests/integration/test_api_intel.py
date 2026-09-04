import pytest

from tests.telegram_fixtures import fake_collector

pytestmark = pytest.mark.integration


@pytest.fixture
def client(settings):
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
        yield c
    Base.metadata.drop_all(get_engine())


def test_telegram_user_endpoint(client):
    resp = client.post("/api/v1/telegram/user", json={"query": "@alice"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["summary"]["telegram_id"] == 42
    assert body["search_id"]


def test_channel_endpoint_and_history(client):
    assert client.post("/api/v1/telegram/channel", json={"query": "opsecnews"}).json()["found"]

    hist = client.get("/api/v1/searches").json()["searches"]
    assert any(h["kind"] == "channel" for h in hist)


def test_message_search_endpoint(client):
    client.post("/api/v1/telegram/channel", json={"query": "opsecnews"})
    resp = client.post("/api/v1/telegram/messages", json={"query": "evil.example", "limit": 10})
    body = resp.json()
    assert body["found"] is True
    assert len(body["items"]) == 1


def test_query_validation(client):
    resp = client.post("/api/v1/telegram/user", json={"query": ""})
    assert resp.status_code == 422


def test_users_are_isolated_by_header(client):
    client.post(
        "/api/v1/telegram/user", json={"query": "@alice"}, headers={"X-User-Email": "a@x.com"}
    )
    other = client.get("/api/v1/searches", headers={"X-User-Email": "b@x.com"}).json()
    assert other["searches"] == []


def test_sources_health_endpoint(client):
    body = client.get("/api/v1/sources/health").json()
    assert any(s["name"] == "telegram_public" for s in body["sources"])
