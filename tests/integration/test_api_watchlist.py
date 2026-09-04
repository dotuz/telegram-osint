import pytest

from tests.telegram_fixtures import fake_collector

pytestmark = pytest.mark.integration


@pytest.fixture
def client(settings, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_WATCH_MAX_TARGETS", "2")
    from security.config import get_settings

    get_settings.cache_clear()

    from fastapi.testclient import TestClient

    import database.models  # noqa: F401
    from apps.api.deps import get_collector
    from apps.api.main import create_app
    from database.base import Base
    from database.session import get_engine

    Base.metadata.create_all(get_engine())
    app = create_app(get_settings())
    app.dependency_overrides[get_collector] = lambda: fake_collector()
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(get_engine())


def test_watchlist_crud_and_limit(client):
    assert client.get("/api/v1/watchlist").json()["watchlist"] == []

    r = client.post("/api/v1/watchlist", json={"value": "@opsecnews"}).json()
    assert r["created"] is True
    assert r["watch"]["value"] == "@opsecnews"

    client.post("/api/v1/watchlist", json={"value": "leakclub"})
    over = client.post("/api/v1/watchlist", json={"value": "third"})
    assert over.status_code == 429

    assert len(client.get("/api/v1/watchlist").json()["watchlist"]) == 2

    assert client.request("DELETE", "/api/v1/watchlist/opsecnews").json() == {"removed": True}
    assert client.request("DELETE", "/api/v1/watchlist/nope").json() == {"removed": False}


def test_manual_poll(client):
    wid = client.post("/api/v1/watchlist", json={"value": "@opsecnews"}).json()["watch"]["id"]
    poll = client.post(f"/api/v1/watchlist/{wid}/poll").json()
    assert poll["target"] == "@opsecnews"
    assert any(a["kind"] == "message" for a in poll["activities"])

    # second poll -> deduped
    poll2 = client.post(f"/api/v1/watchlist/{wid}/poll").json()
    assert poll2["activities"] == []

    assert client.post("/api/v1/watchlist/nope/poll").status_code == 404


def test_watchlist_isolated_by_user(client):
    client.post("/api/v1/watchlist", json={"value": "@x"}, headers={"X-User-Email": "a@x"})
    assert (
        client.get("/api/v1/watchlist", headers={"X-User-Email": "b@x"}).json()["watchlist"] == []
    )
