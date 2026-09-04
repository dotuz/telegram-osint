"""Shared pytest fixtures.

Tests run fully offline against an in-memory SQLite database. No Postgres, Redis,
or network access is required for the unit suite. Integration tests that need
real services are marked ``@pytest.mark.integration`` and skipped unless the
services are configured.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

# Force a hermetic environment BEFORE any application module imports settings.
os.environ.update(
    APP_ENV="development",
    APP_DEBUG="true",
    LOG_LEVEL="WARNING",
    LOG_JSON="false",
    DATABASE_URL="sqlite+pysqlite:///:memory:",
    REDIS_URL="redis://localhost:6379/15",
    SECRET_KEY="test-secret-not-for-production-000000000000000000000000",
    TELEGRAM_BOT_TOKEN="123456:TEST",
    CORS_ALLOWED_ORIGINS="http://localhost:3000",
    TELEGRAM_ALLOWED_USER_IDS="111,222",
    TELEGRAM_ADMIN_USER_IDS="111",
)


@pytest.fixture(autouse=True)
def _reset_caches() -> Iterator[None]:
    """Clear cached settings/engine between tests so env overrides take effect."""
    from database.session import reset_engine_cache
    from security.config import get_settings

    get_settings.cache_clear()
    reset_engine_cache()
    yield
    get_settings.cache_clear()
    reset_engine_cache()


@pytest.fixture
def settings():
    from security.config import get_settings

    return get_settings()


@pytest.fixture
def db_session(settings) -> Iterator[Session]:  # noqa: F821
    """A session bound to a freshly-created in-memory schema."""
    import database.models  # noqa: F401 - register models
    from database.base import Base
    from database.session import get_engine, get_sessionmaker

    engine = get_engine()
    Base.metadata.create_all(engine)
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture
def api_client(settings) -> Iterator[TestClient]:  # noqa: F821
    from fastapi.testclient import TestClient

    import database.models  # noqa: F401
    from apps.api.main import create_app
    from database.base import Base
    from database.session import get_engine

    Base.metadata.create_all(get_engine())
    app = create_app(settings)
    with TestClient(app) as client:
        yield client
    Base.metadata.drop_all(get_engine())
