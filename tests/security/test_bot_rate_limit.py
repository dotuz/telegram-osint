"""The bot must throttle a single Telegram user hammering one command.

Regression for Phase 13 finding: bot handlers created jobs with no per-user
rate limit, so an allow-listed user could flood the job queue / OSINT sources.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from apps.bot.guard import authorized
from security.ratelimit import InMemoryRateLimiter, set_rate_limiter

pytestmark = pytest.mark.security


@pytest.fixture
def limited(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_BOT_PER_MINUTE", "3")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "222")
    monkeypatch.setenv("TELEGRAM_ADMIN_USER_IDS", "111")
    from security.config import get_settings

    get_settings.cache_clear()
    set_rate_limiter(InMemoryRateLimiter())
    yield
    set_rate_limiter(None)
    get_settings.cache_clear()


def _update(user_id: int):
    msg = SimpleNamespace(reply_text=AsyncMock())
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id, first_name="Ann"),
        effective_message=msg,
        callback_query=None,
    ), msg


async def test_bot_command_is_rate_limited_per_user(limited):
    calls = {"n": 0}

    @authorized(action="search")
    async def handler(update, context, principal):  # noqa: ANN001
        calls["n"] += 1

    # limit = 3/min -> 3 pass, the rest are throttled
    for _ in range(6):
        update, msg = _update(222)
        await handler(update, None)

    assert calls["n"] == 3
    last_text = msg.reply_text.call_args.args[0]
    assert "too quickly" in last_text.lower()


async def test_rate_limit_is_per_command_and_per_user(limited):
    seen = []

    @authorized(action="a")
    async def handler_a(update, context, principal):  # noqa: ANN001
        seen.append("a")

    @authorized(action="b")
    async def handler_b(update, context, principal):  # noqa: ANN001
        seen.append("b")

    for _ in range(3):
        await handler_a(_update(222)[0], None)
    # command "a" now exhausted for user 222...
    await handler_a(_update(222)[0], None)
    assert seen.count("a") == 3
    # ...but a different command still works
    await handler_b(_update(222)[0], None)
    assert "b" in seen
    # ...and a different user is unaffected on command "a"
    await handler_a(_update(111)[0], None)
    assert seen.count("a") == 4
