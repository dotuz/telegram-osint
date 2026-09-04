import os

import pytest

from security.config import Settings

pytestmark = pytest.mark.unit


def test_settings_load_from_env(settings):
    assert settings.app_env == "development"
    assert settings.telegram_allowed_user_ids == [111, 222]
    assert settings.telegram_admin_user_ids == [111]
    assert settings.cors_allowed_origins == ["http://localhost:3000"]
    # Default hermetic run is SQLite; a QA/CI run may point at another engine via
    # TOI_TEST_DATABASE_URL -- assert is_sqlite tracks the actual URL either way.
    assert settings.is_sqlite is settings.database_url.startswith("sqlite")
    if not os.environ.get("TOI_TEST_DATABASE_URL"):
        assert settings.is_sqlite is True


def test_secrets_are_not_printed(settings):
    assert "test-secret" not in repr(settings)
    assert "123456:TEST" not in str(settings)
    assert settings.secret_key.get_secret_value().startswith("test-secret")


def test_wildcard_cors_origin_rejected():
    with pytest.raises(ValueError, match="must not contain"):
        Settings(cors_allowed_origins="*", _env_file=None)


def test_csv_origins_parsed():
    s = Settings(
        cors_allowed_origins="https://a.example, https://b.example",
        _env_file=None,
    )
    assert s.cors_allowed_origins == ["https://a.example", "https://b.example"]


def test_production_secret_gate_blocks_empty_secret():
    s = Settings(
        app_env="production",
        app_debug=False,
        secret_key="",
        telegram_bot_token="",
        cors_allowed_origins="https://dash.example",
        _env_file=None,
    )
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        s.require_production_secrets()


def test_production_secret_gate_passes_when_configured():
    s = Settings(
        app_env="production",
        app_debug=False,
        secret_key="x" * 48,
        telegram_bot_token="123:abc",
        cors_allowed_origins="https://dash.example",
        _env_file=None,
    )
    s.require_production_secrets()  # must not raise
