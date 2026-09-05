"""Public-tier free-action quota + referral unlock."""

import pytest

from apps.bot.quota import check_and_consume, referral_link
from database.repositories import UserRepository
from database.session import session_scope

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _quota_settings(monkeypatch):
    monkeypatch.setenv("FREE_OSINT_ACTIONS", "3")
    monkeypatch.setenv("REFERRAL_UNLOCK_COUNT", "5")
    from security.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_free_actions_are_consumed_then_blocked(db_session):
    tg_id = 42
    for _ in range(3):
        assert check_and_consume(tg_id).allowed
    blocked = check_and_consume(tg_id)
    assert not blocked.allowed
    assert blocked.used == 3
    assert blocked.limit == 3
    # repeated calls after blocked don't keep decrementing / erroring
    assert not check_and_consume(tg_id).allowed


def test_referrals_unlock_unlimited_use(db_session):
    inviter = 100
    for _ in range(3):
        check_and_consume(inviter)
    assert not check_and_consume(inviter).allowed

    with session_scope() as s:
        repo = UserRepository(s)
        for referred_id in range(1, 6):
            new_row, _ = repo.get_or_create_for_telegram(1000 + referred_id)
            repo.record_referral(new_row, inviter_telegram_id=inviter)

    status = check_and_consume(inviter)
    assert status.allowed
    assert status.unlocked_by_referral
    # still allowed on further calls -- referral count never regresses
    assert check_and_consume(inviter).allowed


def test_self_referral_is_rejected(db_session):
    with session_scope() as s:
        repo = UserRepository(s)
        row, _ = repo.get_or_create_for_telegram(7)
        assert repo.record_referral(row, inviter_telegram_id=7) is False
        assert repo.count_referrals(7) == 0


def test_referral_is_recorded_only_once(db_session):
    with session_scope() as s:
        repo = UserRepository(s)
        row, _ = repo.get_or_create_for_telegram(8)
        assert repo.record_referral(row, inviter_telegram_id=1) is True
        assert repo.record_referral(row, inviter_telegram_id=2) is False
        assert repo.count_referrals(1) == 1
        assert repo.count_referrals(2) == 0


def test_referral_link_format():
    assert referral_link("MyOsintBot", 555) == "https://t.me/MyOsintBot?start=ref_555"
    assert referral_link(None, 555) is None
