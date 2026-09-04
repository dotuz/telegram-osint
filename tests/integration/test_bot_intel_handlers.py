from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from apps.bot.handlers import telegram_intel
from tests.telegram_fixtures import fake_collector

pytestmark = pytest.mark.integration


@pytest.fixture
def bot_db():
    import database.models  # noqa: F401
    from database.base import Base
    from database.session import get_engine

    engine = get_engine()
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


def make_ctx(args: list[str], collector=None):
    app = SimpleNamespace(bot_data={"telegram_collector": collector} if collector else {})
    return SimpleNamespace(args=args, application=app)


def make_update(user_id: int = 111):
    msg = SimpleNamespace(reply_text=AsyncMock())
    chat = SimpleNamespace(send_action=AsyncMock())
    return (
        SimpleNamespace(
            effective_user=SimpleNamespace(id=user_id, first_name="A"),
            effective_message=msg,
            effective_chat=chat,
            callback_query=None,
        ),
        msg,
    )


async def test_search_user_replies_with_profile(bot_db):
    update, msg = make_update()
    await telegram_intel.search_user(update, make_ctx(["@alice"], fake_collector()))
    text = msg.reply_text.call_args.args[0]
    assert "TARGET" in text
    assert "Alice Anderson" in text


async def test_search_without_args_shows_usage(bot_db):
    update, msg = make_update()
    await telegram_intel.search_user(update, make_ctx([]))
    assert "Usage" in msg.reply_text.call_args.args[0]


async def test_channel_intel_reply(bot_db):
    update, msg = make_update()
    await telegram_intel.channel_intel(update, make_ctx(["opsecnews"], fake_collector()))
    text = msg.reply_text.call_args.args[0]
    assert "CHANNEL" in text
    assert "OpSec News" in text


async def test_message_search_then_history(bot_db):
    coll = fake_collector()
    update, msg = make_update()
    await telegram_intel.channel_intel(update, make_ctx(["opsecnews"], coll))

    update2, msg2 = make_update()
    await telegram_intel.message_search(update2, make_ctx(['"evil.example"'], coll))
    assert "Message search" in msg2.reply_text.call_args.args[0]

    update3, msg3 = make_update()
    await telegram_intel.history(update3, make_ctx([]))
    assert "Recent searches" in msg3.reply_text.call_args.args[0]


async def test_unauthorized_user_denied(bot_db):
    update, msg = make_update(user_id=999)
    await telegram_intel.search_user(update, make_ctx(["@alice"], fake_collector()))
    assert "not authorized" in msg.reply_text.call_args.args[0].lower()


async def test_search_writes_audit_row(bot_db):
    from database.models import AuditLog
    from database.session import session_scope

    update, _ = make_update()
    await telegram_intel.search_user(update, make_ctx(["@alice"], fake_collector()))
    with session_scope() as s:
        actions = [a.action for a in s.query(AuditLog).all()]
    assert "search" in actions
