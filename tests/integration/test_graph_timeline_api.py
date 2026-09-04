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


def test_target_crud_and_graph_timeline(client):
    # collect something first so resolution has an entity to link
    client.post("/api/v1/telegram/user", json={"query": "@alice"})

    created = client.post(
        "/api/v1/targets", json={"kind": "telegram_user", "value": "@alice"}
    ).json()
    tid = created["id"]
    assert any("telegram_account" in r for r in created["resolved_entities"])

    assert any(t["id"] == tid for t in client.get("/api/v1/targets").json()["targets"])

    got = client.get(f"/api/v1/targets/{tid}").json()
    assert got["resolved_entities"]

    graph = client.get(f"/api/v1/targets/{tid}/graph?depth=2").json()
    assert graph["root"].startswith("target:")
    assert any(n["type"] == "target" for n in graph["nodes"])

    tl = client.get(f"/api/v1/targets/{tid}/timeline").json()
    assert "by_year" in tl


def test_entity_graph_and_timeline(client):
    body = client.post("/api/v1/telegram/user", json={"query": "@alice"}).json()
    eid = body["entity_id"]
    g = client.get(f"/api/v1/entities/telegram_account/{eid}/graph").json()
    assert g["nodes"]
    t = client.get(f"/api/v1/entities/telegram_account/{eid}/timeline").json()
    assert "events" in t


def test_target_404(client):
    assert client.get("/api/v1/targets/nope/graph").status_code == 404
    assert client.post("/api/v1/targets", json={"kind": "bogus", "value": "x"}).status_code == 422


def test_targets_isolated_by_user(client):
    client.post("/api/v1/telegram/user", json={"query": "@alice"}, headers={"X-User-Email": "a@x"})
    client.post(
        "/api/v1/targets",
        json={"kind": "telegram_user", "value": "@alice"},
        headers={"X-User-Email": "a@x"},
    )
    other = client.get("/api/v1/targets", headers={"X-User-Email": "b@x"}).json()
    assert other["targets"] == []
