"""Phase-1 security regression tests: CORS config + secret hygiene.

Expanded in Phase 12 with IDOR/BOLA, CSRF, SSRF, rate-limit, and auth-bypass suites.
"""

import pytest

from apps.api.main import create_app
from security.config import Settings

pytestmark = pytest.mark.security


def test_app_refuses_wildcard_cors_via_settings():
    with pytest.raises(ValueError):
        Settings(cors_allowed_origins="*", _env_file=None)


def test_cors_preflight_allows_configured_origin(settings):
    from fastapi.testclient import TestClient

    with TestClient(create_app(settings)) as client:
        resp = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_cors_rejects_unlisted_origin(settings):
    from fastapi.testclient import TestClient

    with TestClient(create_app(settings)) as client:
        resp = client.get("/health", headers={"Origin": "https://evil.example"})
    # Starlette omits the ACAO header entirely for disallowed origins.
    assert resp.headers.get("access-control-allow-origin") != "https://evil.example"


def test_openapi_docs_disabled_in_production():
    prod = Settings(
        app_env="production",
        app_debug=False,
        secret_key="x" * 48,
        telegram_bot_token="1:2",
        cors_allowed_origins="https://dash.example",
        redis_url="redis://localhost:6379/0",
        database_url="sqlite+pysqlite:///:memory:",
        _env_file=None,
    )
    app = create_app(prod)
    assert app.docs_url is None
