"""Free-action quota + referral unlock for the public (non-allow-listed) bot tier.

Only consulted for ``Principal.is_public`` (``Role.USER``) -- allow-listed
ANALYST/ADMIN users are always unlimited. A public user gets
``FREE_OSINT_ACTIONS`` collection actions; beyond that they need
``REFERRAL_UNLOCK_COUNT`` distinct people to have started the bot via their
referral link (``/start ref_<telegram_id>``). Referral count is computed live
(count of users with ``invited_by_telegram_id`` set to this id), so it never
needs a separate "unlocked" flag and never regresses.
"""

from __future__ import annotations

from dataclasses import dataclass

from database.repositories import UserRepository
from database.session import session_scope
from database.types import Role


@dataclass(frozen=True)
class QuotaStatus:
    allowed: bool
    used: int
    limit: int
    referrals: int
    required_referrals: int

    @property
    def unlocked_by_referral(self) -> bool:
        return self.referrals >= self.required_referrals


def check_and_consume(telegram_id: int) -> QuotaStatus:
    """Consult (and, if a free action is spent, update) the quota for one user.

    Idempotent with respect to being called more than the enforced limit: once
    blocked, repeated calls keep returning ``allowed=False`` without further
    decrementing anything.
    """
    from security.config import get_settings

    settings = get_settings()
    with session_scope() as session:
        repo = UserRepository(session)
        user, _ = repo.get_or_create_for_telegram(telegram_id, role=Role.USER)
        referrals = repo.count_referrals(telegram_id)

        if referrals >= settings.referral_unlock_count:
            return QuotaStatus(
                True,
                user.free_actions_used,
                settings.free_osint_actions,
                referrals,
                settings.referral_unlock_count,
            )
        if user.free_actions_used < settings.free_osint_actions:
            repo.consume_free_action(user)
            return QuotaStatus(
                True,
                user.free_actions_used,
                settings.free_osint_actions,
                referrals,
                settings.referral_unlock_count,
            )
        return QuotaStatus(
            False,
            user.free_actions_used,
            settings.free_osint_actions,
            referrals,
            settings.referral_unlock_count,
        )


def referral_link(bot_username: str | None, telegram_id: int) -> str | None:
    if not bot_username:
        return None
    return f"https://t.me/{bot_username}?start=ref_{telegram_id}"
