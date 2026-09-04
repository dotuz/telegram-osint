import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def client(settings):
    from fastapi.testclient import TestClient

    import database.models  # noqa: F401
    from apps.api.main import create_app
    from database.base import Base
    from database.repositories import UserRepository
    from database.session import get_engine, session_scope
    from database.types import Role

    Base.metadata.create_all(get_engine())
    with session_scope() as s:
        UserRepository(s).create(email="admin@x.com", role=Role.ADMIN, password="hunter2hunter2")
        UserRepository(s).create(email="analyst@x.com", password="analyst-pass-1")
        s.commit()

    with TestClient(create_app(settings)) as c:
        yield c
    Base.metadata.drop_all(get_engine())


def _token(client, email, password) -> str:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_login_and_me(client):
    tok = _token(client, "admin@x.com", "hunter2hunter2")
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"}).json()
    assert me["email"] == "admin@x.com"
    assert me["role"] == "ADMIN"


def test_bad_credentials_rejected(client):
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": "admin@x.com", "password": "nope"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": "ghost@x.com", "password": "x"}
        ).status_code
        == 401
    )


def test_invalid_bearer_token_rejected(client):
    r = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage.token.here"})
    assert r.status_code == 401


def test_token_auth_scopes_data_to_the_token_user(client):
    a = _token(client, "analyst@x.com", "analyst-pass-1")
    client.post(
        "/api/v1/targets",
        json={"kind": "username", "value": "@x"},
        headers={"Authorization": f"Bearer {a}"},
    )
    admin = _token(client, "admin@x.com", "hunter2hunter2")
    seen = client.get("/api/v1/targets", headers={"Authorization": f"Bearer {admin}"}).json()
    assert seen["targets"] == []


def test_stats_and_audit_rbac(client):
    analyst = _token(client, "analyst@x.com", "analyst-pass-1")
    admin = _token(client, "admin@x.com", "hunter2hunter2")

    assert (
        client.get("/api/v1/stats", headers={"Authorization": f"Bearer {analyst}"}).status_code
        == 200
    )

    # /audit is admin-only
    assert (
        client.get("/api/v1/audit", headers={"Authorization": f"Bearer {analyst}"}).status_code
        == 403
    )
    assert (
        client.get("/api/v1/audit", headers={"Authorization": f"Bearer {admin}"}).status_code == 200
    )


def test_dev_shim_still_works_without_token(client):
    # no Authorization header -> X-User-Email shim (dev only)
    assert client.get("/api/v1/targets").status_code == 200
    assert client.get("/api/v1/audit", headers={"X-User-Role": "ADMIN"}).status_code == 200
