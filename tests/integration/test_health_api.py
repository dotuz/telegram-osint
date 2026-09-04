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


def test_ready_reports_db_ok_redis_error(api_client):
    # No Redis in the unit environment -> readiness degraded, DB healthy.
    resp = api_client.get("/ready")
    body = resp.json()
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["redis"] == "error"
    assert resp.status_code == 503
    assert body["ready"] is False
