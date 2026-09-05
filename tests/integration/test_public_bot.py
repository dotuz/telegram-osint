"""Public bot tier: open access with a free-action quota + referral unlock.

Regression coverage for the PUBLIC_BOT_ENABLED feature: a non-allow-listed
Telegram user can use the bot up to FREE_OSINT_ACTIONS times, after which they
are blocked until REFERRAL_UNLOCK_COUNT distinct people start the bot via
their referral link. Allow-listed users are never subject to this.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from apps.bot.handlers import common, telegram_intel
from database.repositories import UserRepository
from database.session import session_scope
from tests.telegram_fixtures import fake_collector
from tests.worker_helpers import CapturingRunner

pytestmark = pytest.mark.integration

PUBLIC_USER = 999999  # not in TELEGRAM_ALLOWED_USER_IDS / TELEGRAM_ADMIN_USER_IDS


@pytest.fixture
def bot_db():
    import database.models  # noqa: F401
    from database.base import Base
    from database.session import get_engine

    engine = get_engine()
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture
def public_mode(monkeypatch):
    monkeypatch.setenv("PUBLIC_BOT_ENABLED", "true")
    monkeypatch.setenv("FREE_OSINT_ACTIONS", "2")
    monkeypatch.setenv("REFERRAL_UNLOCK_COUNT", "2")
    from security.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _ctx(args, queue, bot_username=None):
    data = {"job_queue": queue}
    if bot_username:
        data["bot_username"] = bot_username
    return SimpleNamespace(args=args, application=SimpleNamespace(bot_data=data))


def _update(user_id):
    msg = SimpleNamespace(reply_text=AsyncMock())
    chat = SimpleNamespace(id=555, send_action=AsyncMock())
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id, first_name="Pub"),
        effective_message=msg,
        effective_chat=chat,
        callback_query=None,
    ), msg


async def test_public_user_blocked_after_free_actions(bot_db, public_mode):
    runner = CapturingRunner(telegram=fake_collector())

    for _ in range(2):
        upd, msg = _update(PUBLIC_USER)
        await telegram_intel.search_user(upd, _ctx(["@alice"], runner.queue))
        assert "queued" in msg.reply_text.call_args.args[0].lower()

    upd, msg = _update(PUBLIC_USER)
    await telegram_intel.search_user(upd, _ctx(["@alice"], runner.queue, bot_username="TOIBot"))
    text = msg.reply_text.call_args.args[0]
    assert "limit" in text.lower()
    assert "t.me/TOIBot?start=ref_" in text
    assert runner.queue.size() == 2  # the 3rd call never enqueued a job


async def test_allowlisted_user_is_never_quota_limited(bot_db, public_mode):
    runner = CapturingRunner(telegram=fake_collector())
    for _ in range(5):  # well past FREE_OSINT_ACTIONS=2
        upd, msg = _update(111)  # admin id from the test env allow-list
        await telegram_intel.search_user(upd, _ctx(["@alice"], runner.queue))
        assert "queued" in msg.reply_text.call_args.args[0].lower()
    assert runner.queue.size() == 5


async def test_start_captures_referral_and_unlocks_inviter(bot_db, public_mode):
    inviter = 777777
    runner = CapturingRunner(telegram=fake_collector())

    # inviter burns their free actions first
    for _ in range(2):
        upd, _msg = _update(inviter)
        await telegram_intel.search_user(upd, _ctx(["@alice"], runner.queue))
    upd, msg = _update(inviter)
    await telegram_intel.search_user(upd, _ctx(["@alice"], runner.queue))
    assert "limit" in msg.reply_text.call_args.args[0].lower()

    # two new users /start via the inviter's referral link
    for referred in (888001, 888002):
        upd, _msg = _update(referred)
        await common.start(upd, _ctx([f"ref_{inviter}"], runner.queue))

    with session_scope() as s:
        assert UserRepository(s).count_referrals(inviter) == 2

    # inviter is now unlocked (REFERRAL_UNLOCK_COUNT=2)
    upd, msg = _update(inviter)
    await telegram_intel.search_user(upd, _ctx(["@alice"], runner.queue))
    assert "queued" in msg.reply_text.call_args.args[0].lower()


async def test_self_referral_via_start_does_not_count(bot_db, public_mode):
    runner = CapturingRunner()
    upd, _msg = _update(PUBLIC_USER)
    await common.start(upd, _ctx([f"ref_{PUBLIC_USER}"], runner.queue))

    with session_scope() as s:
        assert UserRepository(s).count_referrals(PUBLIC_USER) == 0
