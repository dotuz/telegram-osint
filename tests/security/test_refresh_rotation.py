import pytest

pytestmark = pytest.mark.security


def _login(client, email="user-a@sec.example.com", password="user-a-pass-123"):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200
    return r.json()


def test_refresh_rotates_and_old_token_dies(secure_client):
    first = _login(secure_client)["refresh_token"]

    r1 = secure_client.post("/api/v1/auth/refresh", json={"refresh_token": first})
    assert r1.status_code == 200
    second = r1.json()["refresh_token"]
    assert second != first

    # reusing the first (now revoked) token fails...
    reuse = secure_client.post("/api/v1/auth/refresh", json={"refresh_token": first})
    assert reuse.status_code == 401

    # ...and it also nuked the whole family, so the second no longer works either
    assert (
        secure_client.post("/api/v1/auth/refresh", json={"refresh_token": second}).status_code
        == 401
    )


def test_logout_revokes_refresh_token(secure_client):
    rt = _login(secure_client)["refresh_token"]
    assert secure_client.post("/api/v1/auth/logout", json={"refresh_token": rt}).json()["revoked"]
    assert secure_client.post("/api/v1/auth/refresh", json={"refresh_token": rt}).status_code == 401


def test_refresh_cookie_flags(secure_client):
    r = secure_client.post(
        "/api/v1/auth/login",
        json={"email": "user-a@sec.example.com", "password": "user-a-pass-123"},
    )
    cookie = r.headers.get("set-cookie", "")
    assert "toi_refresh=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie.replace("Strict", "strict")
    assert "Path=/api/v1/auth" in cookie


def test_refresh_without_token_is_401(secure_client):
    assert secure_client.post("/api/v1/auth/refresh", json={}).status_code == 401
