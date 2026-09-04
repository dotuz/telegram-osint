"""Bot authorization.

Only numeric Telegram user IDs listed in ``TELEGRAM_ALLOWED_USER_IDS`` (plus
``TELEGRAM_ADMIN_USER_IDS``) may use the bot. This is an allow-list: if no IDs
are configured, **every** user is denied (secure default) and a warning is
logged at startup.

Authorization decisions here are advisory for UX; the API/worker layers
re-check authorization server-side for every resource (Phase 12).
"""

from __future__ import annotations

from dataclasses import dataclass

from database.types import Role
from security.config import Settings, get_settings
from security.logging import get_logger

_log = get_logger("bot.auth")

__all__ = ["AccessDenied", "Principal", "Role", "require_admin", "resolve_principal"]


@dataclass(frozen=True)
class Principal:
    telegram_id: int
    role: Role

    @property
    def is_admin(self) -> bool:
        return self.role is Role.ADMIN

    @property
    def actor(self) -> str:
        return f"telegram:{self.telegram_id}"


class AccessDenied(Exception):
    """Raised when a Telegram user is not on the allow-list or lacks a role."""

    def __init__(self, telegram_id: int | None, *, reason: str) -> None:
        super().__init__(reason)
        self.telegram_id = telegram_id
        self.reason = reason


def _allowed_ids(settings: Settings) -> set[int]:
    return set(settings.telegram_allowed_user_ids) | set(settings.telegram_admin_user_ids)


def warn_if_open_or_closed(settings: Settings | None = None) -> None:
    """Startup sanity check for the allow-list configuration."""
    settings = settings or get_settings()
    if not _allowed_ids(settings):
        _log.warning(
            "bot_allowlist_empty",
            detail="No TELEGRAM_ALLOWED_USER_IDS / TELEGRAM_ADMIN_USER_IDS set; "
            "the bot will reject every user until IDs are configured.",
        )


def resolve_principal(telegram_id: int | None, settings: Settings | None = None) -> Principal:
    """Return the :class:`Principal` for a Telegram user id or raise :class:`AccessDenied`."""
    settings = settings or get_settings()
    if telegram_id is None:
        raise AccessDenied(None, reason="missing telegram user id")

    if telegram_id in set(settings.telegram_admin_user_ids):
        return Principal(telegram_id=telegram_id, role=Role.ADMIN)

    if telegram_id in set(settings.telegram_allowed_user_ids):
        return Principal(telegram_id=telegram_id, role=Role.ANALYST)

    raise AccessDenied(telegram_id, reason="not on allow-list")


def require_admin(principal: Principal) -> Principal:
    if not principal.is_admin:
        raise AccessDenied(principal.telegram_id, reason="admin role required")
    return principal
