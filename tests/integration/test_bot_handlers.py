from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from apps.bot.handlers import admin, common
from apps.bot.handlers.stubs import make_stub_handler
from apps.bot.router import get_command

pytestmark = pytest.mark.integration


@pytest.fixture
def bot_db():
    """Create the operational schema on the shared in-memory engine."""
    import database.models  # noqa: F401
    from database.base import Base
    from database.session import get_engine

    engine = get_engine()
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


def message_update(user_id: int, first_name: str = "Ann"):
    msg = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id, first_name=first_name),
        effective_message=msg,
        callback_query=None,
    )
    return update, msg


def callback_update(user_id: int, data: str):
    inner = SimpleNamespace(reply_text=AsyncMock())
    cq = SimpleNamespace(
        data=data,
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
        message=inner,
    )
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id, first_name="Ann"),
        effective_message=None,
        callback_query=cq,
    )
    return update, cq


async def test_start_shows_menu_for_authorized_user(bot_db):
    update, msg = message_update(222)
    await common.start(update, None)

    msg.reply_text.assert_awaited_once()
    text = msg.reply_text.call_args.args[0]
    assert "Telegram Public OSINT Investigator" in text
    assert "/investigate" in text
    assert msg.reply_text.call_args.kwargs["reply_markup"] is not None


async def test_unauthorized_user_is_denied(bot_db):
    update, msg = message_update(999)
    await common.start(update, None)

    text = msg.reply_text.call_args.args[0]
    assert "not authorized" in text.lower()
    # No keyboard leaked to an unauthorized user.
    assert msg.reply_text.call_args.kwargs["reply_markup"] is None


async def test_start_writes_audit_row(bot_db):
    from database.models import AuditLog
    from database.session import session_scope

    update, _ = message_update(222)
    await common.start(update, None)

    with session_scope() as s:
        actions = {a.action for a in s.query(AuditLog).all()}
    assert "start" in actions


async def test_denied_user_writes_denied_audit_row(bot_db):
    from database.models import AuditLog
    from database.session import session_scope

    update, _ = message_update(999)
    await common.start(update, None)

    with session_scope() as s:
        rows = s.query(AuditLog).all()
    assert any(r.action == "access_denied" and r.result == "denied" for r in rows)


async def test_health_requires_admin(bot_db):
    update, msg = message_update(222)  # analyst
    await admin.health_cmd(update, None)
    assert "not authorized" in msg.reply_text.call_args.args[0].lower()


async def test_health_ok_for_admin(bot_db):
    update, msg = message_update(111)  # admin
    await admin.health_cmd(update, None)
    text = msg.reply_text.call_args.args[0]
    assert "Health" in text
    assert "database" in text


async def test_stub_handler_reports_phase(bot_db):
    handler = make_stub_handler(get_command("report"))
    update, msg = message_update(222)
    await handler(update, None)
    assert "phase 10" in msg.reply_text.call_args.args[0]


async def test_menu_callback_routes_to_stub(bot_db):
    update, cq = callback_update(222, "menu:username")
    await common.menu_callback(update, None)

    cq.answer.assert_awaited_once()
    cq.edit_message_text.assert_awaited_once()
    assert "phase 6" in cq.edit_message_text.call_args.args[0]


async def test_menu_callback_home_shows_menu(bot_db):
    update, cq = callback_update(222, "menu:home")
    await common.menu_callback(update, None)
    assert cq.edit_message_text.call_args.kwargs["reply_markup"] is not None


async def test_unknown_command_handler(bot_db):
    update, msg = message_update(222)
    await common.unknown_command(update, None)
    assert "/help" in msg.reply_text.call_args.args[0]


async def test_handler_exception_becomes_generic_message(bot_db, monkeypatch):
    # Force the view to raise; the guard must swallow it and reply generically.
    monkeypatch.setattr(
        "apps.bot.handlers.common.render_start",
        lambda **_: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    update, msg = message_update(222)
    await common.start(update, None)
    assert "went wrong" in msg.reply_text.call_args.args[0].lower()
