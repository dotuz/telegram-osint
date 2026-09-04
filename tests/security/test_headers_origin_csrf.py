import pytest

from tests.security.conftest import auth, token

pytestmark = pytest.mark.security


def test_security_headers_present(secure_client):
    r = secure_client.get("/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert "Referrer-Policy" in r.headers


def test_state_change_with_bad_origin_is_blocked(secure_client):
    h = auth(token(secure_client, "user-a@sec.example.com", "user-a-pass-123"))
    r = secure_client.post(
        "/api/v1/targets",
        json={"kind": "username", "value": "@x"},
        headers={**h, "Origin": "https://evil.example"},
    )
    assert r.status_code == 403


def test_state_change_with_allowed_origin_passes(secure_client):
    h = auth(token(secure_client, "user-a@sec.example.com", "user-a-pass-123"))
    r = secure_client.post(
        "/api/v1/targets",
        json={"kind": "username", "value": "@x"},
        headers={**h, "Origin": "http://localhost:3000"},
    )
    assert r.status_code == 200


def test_state_change_without_origin_passes(secure_client):
    h = auth(token(secure_client, "user-a@sec.example.com", "user-a-pass-123"))
    assert (
        secure_client.post(
            "/api/v1/targets", json={"kind": "username", "value": "@y"}, headers=h
        ).status_code
        == 200
    )


def test_get_with_bad_origin_not_blocked(secure_client):
    h = auth(token(secure_client, "user-a@sec.example.com", "user-a-pass-123"))
    r = secure_client.get("/api/v1/targets", headers={**h, "Origin": "https://evil.example"})
    # GET isn't state-changing; CORS just won't echo the origin back
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") != "https://evil.example"
