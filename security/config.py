"""Central application configuration.

All configuration is loaded from environment variables (or a local ``.env`` file
during development). Secrets are wrapped in :class:`pydantic.SecretStr` so they are
never accidentally logged or serialised.

Import the singleton via :func:`get_settings` -- it is cached for the process
lifetime, so tests override it with ``get_settings.cache_clear()`` + monkeypatched
environment, or by constructing :class:`Settings` directly.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["development", "staging", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


def _split_csv(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [item.strip() for item in value.split(",") if item.strip()]


class Settings(BaseSettings):
    """Typed, validated application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        # Do not attempt JSON-decoding of complex fields from env; our own
        # ``mode="before"`` validators parse comma-separated strings instead.
        enable_decoding=False,
    )

    # --- Runtime ---
    app_env: AppEnv = "development"
    app_debug: bool = True
    log_level: LogLevel = "INFO"
    log_json: bool = False

    # --- API ---
    api_host: str = "0.0.0.0"  # noqa: S104 - bind inside container network
    api_port: int = 8000
    cors_allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # --- Security / crypto ---
    secret_key: SecretStr = SecretStr("")
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_seconds: int = 1_209_600

    # --- Database / Redis ---
    database_url: str = "postgresql+psycopg://osint:osint@localhost:5432/telegram_osint"
    redis_url: str = "redis://localhost:6379/0"

    # --- Telegram Bot API ---
    telegram_bot_token: SecretStr = SecretStr("")
    telegram_allowed_user_ids: list[int] = Field(default_factory=list)
    telegram_admin_user_ids: list[int] = Field(default_factory=list)

    # --- Optional authorized operator account ---
    telegram_operator_api_id: str | None = None
    telegram_operator_api_hash: SecretStr | None = None
    telegram_operator_session: SecretStr | None = None

    # --- External OSINT source credentials ---
    github_token: SecretStr | None = None
    reddit_client_id: SecretStr | None = None
    reddit_client_secret: SecretStr | None = None
    reddit_user_agent: str = "telegram-osint-research/1.0"

    # --- Outbound fetcher / SSRF guard ---
    http_fetch_timeout_seconds: float = 10.0
    http_fetch_max_bytes: int = 5_242_880
    http_fetch_max_redirects: int = 3
    http_fetch_allow_private: bool = False

    # --- Rate limits ---
    rate_limit_enabled: bool = True
    rate_limit_search_per_minute: int = 10
    rate_limit_reports_per_hour: int = 5
    rate_limit_watch_max_targets: int = 25
    rate_limit_api_per_minute: int = 120
    rate_limit_login_per_minute: int = 8
    # Per-IP backstop = per-principal limit * this factor (so a shared NAT / proxy
    # does not let one user's quota starve everyone else behind the same address).
    rate_limit_ip_burst_multiplier: int = 20
    # Per-Telegram-user, per-command sliding window for the bot (0 disables).
    rate_limit_bot_per_minute: int = 20

    # --- Browser security ---
    # State-changing requests whose Origin is set must match an allowed origin.
    enforce_origin_check: bool = True

    # --- Monitoring / watchlist ---
    watch_poll_interval_seconds: int = 300

    # --- Reports ---
    reports_dir: str = "./reports_output"

    # ------------------------------------------------------------------
    # validators / normalisation
    # ------------------------------------------------------------------
    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _parse_origins(cls, v: object) -> list[str]:
        return _split_csv(v)  # type: ignore[arg-type]

    @field_validator("telegram_allowed_user_ids", "telegram_admin_user_ids", mode="before")
    @classmethod
    def _parse_id_list(cls, v: object) -> list[int]:
        return [int(item) for item in _split_csv(v)]  # type: ignore[arg-type]

    @field_validator("cors_allowed_origins")
    @classmethod
    def _reject_wildcard_origin(cls, v: list[str]) -> list[str]:
        if "*" in v:
            raise ValueError(
                "cors_allowed_origins must not contain '*': wildcard origins are "
                "incompatible with credentialed requests. List explicit origins."
            )
        return v

    # ------------------------------------------------------------------
    # convenience
    # ------------------------------------------------------------------
    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    def require_production_secrets(self) -> None:
        """Fail fast if the process is production but critical secrets are unset."""
        if not self.is_production:
            return
        missing: list[str] = []
        if not self.secret_key.get_secret_value():
            missing.append("SECRET_KEY")
        if not self.telegram_bot_token.get_secret_value():
            missing.append("TELEGRAM_BOT_TOKEN")
        if self.app_debug:
            missing.append("APP_DEBUG must be false in production")
        if "*" in self.cors_allowed_origins:
            missing.append("CORS_ALLOWED_ORIGINS must not be '*'")
        if missing:
            raise RuntimeError(f"Refusing to start in production; fix: {', '.join(missing)}")


@lru_cache
def get_settings() -> Settings:
    """Return the cached process-wide settings instance."""
    return Settings()
