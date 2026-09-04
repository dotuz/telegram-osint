import pytest

from security.auth import create_access_token
from tests.security.conftest import auth, token

pytestmark = pytest.mark.security


def test_forged_and_tampered_tokens_rejected(secure_client):
    assert secure_client.get("/api/v1/auth/me", headers=auth("a.b.c")).status_code == 401
    good = token(secure_client, "user-a@sec.example.com", "user-a-pass-123")
    h, p, s = good.split(".")
    forged = f"{h}.{p}AAAA.{s}"
    assert secure_client.get("/api/v1/auth/me", headers=auth(forged)).status_code == 401


def test_expired_token_rejected(secure_client):
    from database.repositories import UserRepository
    from database.session import session_scope

    with session_scope() as sess:
        uid = UserRepository(sess).get_by_email("user-a@sec.example.com").id
    expired = create_access_token(user_id=uid, role="ANALYST", ttl_seconds=-5)
    assert secure_client.get("/api/v1/auth/me", headers=auth(expired)).status_code == 401


def test_role_claim_cannot_be_self_elevated(secure_client):
    # a token minted for an ANALYST cannot be edited to ADMIN (signature breaks)
    from database.repositories import UserRepository
    from database.session import session_scope

    with session_scope() as sess:
        uid = UserRepository(sess).get_by_email("user-a@sec.example.com").id
    tok = create_access_token(user_id=uid, role="ANALYST", ttl_seconds=60)
    # naive tamper: flip a payload char
    h, p, s = tok.split(".")
    assert secure_client.get("/api/v1/audit", headers=auth(f"{h}.{p[:-1]}X.{s}")).status_code == 401


def test_dev_shim_disabled_in_production(monkeypatch):
    from fastapi.testclient import TestClient

    import database.models  # noqa: F401
    from apps.api.main import create_app
    from database.base import Base
    from database.session import get_engine
    from security.config import get_settings

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_DEBUG", "false")
    monkeypatch.setenv("SECRET_KEY", "x" * 48)
    get_settings.cache_clear()
    prod = get_settings()

    Base.metadata.create_all(get_engine())
    try:
        with TestClient(create_app(prod)) as c:
            # no Authorization header -> shim would resolve a user in dev; prod = 401
            assert c.get("/api/v1/targets").status_code == 401
            assert c.get("/api/v1/targets", headers={"X-User-Email": "x@y.z"}).status_code == 401
    finally:
        Base.metadata.drop_all(get_engine())
        get_settings.cache_clear()
