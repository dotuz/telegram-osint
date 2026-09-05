import pytest

pytestmark = pytest.mark.integration


def test_health_ok(api_client):
    resp = api_client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["env"] == "development"


def test_request_id_header_roundtrip(api_client):
    resp = api_client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert resp.headers["X-Request-ID"] == "abc-123"


def test_ready_reports_db_ok_redis_error(monkeypatch):
    # Point REDIS_URL at a port nothing listens on -- unlike the ambient test
    # REDIS_URL, this is unreachable even when a real Redis happens to be
    # running nearby (a CI service container, a stray local redis-server),
    # which previously made this test flaky/environment-dependent.
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    from fastapi.testclient import TestClient

    from apps.api.main import create_app
    from security.config import get_settings

    get_settings.cache_clear()
    try:
        with TestClient(create_app(get_settings())) as client:
            resp = client.get("/ready")
            body = resp.json()
    finally:
        get_settings.cache_clear()

    assert body["checks"]["database"] == "ok"
    assert body["checks"]["redis"] == "error"
    assert resp.status_code == 503
    assert body["ready"] is False
