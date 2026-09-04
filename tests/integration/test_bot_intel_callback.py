from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from apps.bot.handlers import graph_views, telegram_intel
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


def _cb_update(data: str, uid: int = 111):
    inner = SimpleNamespace(reply_text=AsyncMock())
    cq = SimpleNamespace(
        data=data, answer=AsyncMock(), edit_message_text=AsyncMock(), message=inner
    )
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=uid, first_name="A"),
        effective_message=None,
        effective_chat=SimpleNamespace(send_action=AsyncMock()),
        callback_query=cq,
    ), cq


async def _seed_account(bot_db):
    """Enqueue a search and drain the worker so an account entity exists."""
    from tests.worker_helpers import CapturingRunner

    runner = CapturingRunner(telegram=fake_collector())
    msg = SimpleNamespace(reply_text=AsyncMock())
    upd = SimpleNamespace(
        effective_user=SimpleNamespace(id=111, first_name="A"),
        effective_message=msg,
        effective_chat=SimpleNamespace(id=1, send_action=AsyncMock()),
        callback_query=None,
    )
    ctx = SimpleNamespace(
        args=["@alice"],
        application=SimpleNamespace(bot_data={"job_queue": runner.queue}),
    )
    await telegram_intel.search_user(upd, ctx)
    runner.drain()

    from database.models import TelegramAccount
    from database.session import session_scope

    with session_scope() as s:
        return s.query(TelegramAccount).one().id


async def test_timeline_callback(bot_db):
    eid = await _seed_account(bot_db)
    update, cq = _cb_update(f"intel:timeline:{eid}")
    await graph_views.intel_callback(update, None)
    cq.answer.assert_awaited()
    assert "Timeline" in cq.edit_message_text.call_args.args[0]


async def test_graph_callback(bot_db):
    eid = await _seed_account(bot_db)
    update, cq = _cb_update(f"intel:graph:{eid}")
    await graph_views.intel_callback(update, None)
    assert "Graph" in cq.edit_message_text.call_args.args[0]


async def test_report_callback_is_stub(bot_db):
    update, cq = _cb_update("intel:report:abc")
    await graph_views.intel_callback(update, None)
    assert "phase 10" in cq.edit_message_text.call_args.args[0]


async def test_callback_denied_for_unauthorized(bot_db):
    update, cq = _cb_update("intel:graph:abc", uid=999)
    await graph_views.intel_callback(update, None)
    assert "not authorized" in cq.edit_message_text.call_args.args[0].lower()
