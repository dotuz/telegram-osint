from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from apps.bot.handlers import telegram_intel
from tests.telegram_fixtures import fake_collector
from tests.worker_helpers import CapturingRunner
from workers.queue import InMemoryJobQueue

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


def make_ctx(args: list[str], collector=None, queue=None):
    data: dict = {}
    if collector:
        data["telegram_collector"] = collector
    if queue is not None:
        data["job_queue"] = queue
    return SimpleNamespace(args=args, application=SimpleNamespace(bot_data=data))


def make_update(user_id: int = 111):
    msg = SimpleNamespace(reply_text=AsyncMock())
    chat = SimpleNamespace(id=555, send_action=AsyncMock())
    return (
        SimpleNamespace(
            effective_user=SimpleNamespace(id=user_id, first_name="A"),
            effective_message=msg,
            effective_chat=chat,
            callback_query=None,
        ),
        msg,
    )


async def test_search_enqueues_and_worker_delivers_profile(bot_db):
    runner = CapturingRunner(telegram=fake_collector())
    update, msg = make_update()

    await telegram_intel.search_user(update, make_ctx(["@alice"], queue=runner.queue))
    queued = msg.reply_text.call_args.args[0]
    assert "queued" in queued.lower()
    assert runner.queue.size() == 1

    assert runner.drain() == 1
    assert runner.notifications
    note = runner.notifications[0]
    assert note.chat_id == 555
    assert "TARGET" in note.text and "Alice Anderson" in note.text


async def test_search_without_args_shows_usage(bot_db):
    update, msg = make_update()
    await telegram_intel.search_user(update, make_ctx([], queue=InMemoryJobQueue()))
    assert "Usage" in msg.reply_text.call_args.args[0]


async def test_channel_enqueues_and_delivers(bot_db):
    runner = CapturingRunner(telegram=fake_collector())
    update, msg = make_update()
    await telegram_intel.channel_intel(update, make_ctx(["opsecnews"], queue=runner.queue))
    assert "queued" in msg.reply_text.call_args.args[0].lower()
    runner.drain()
    assert "CHANNEL" in runner.notifications[0].text
    assert "OpSec News" in runner.notifications[0].text


async def test_message_search_stays_synchronous(bot_db):
    runner = CapturingRunner(telegram=fake_collector())
    update, _ = make_update()
    await telegram_intel.channel_intel(update, make_ctx(["opsecnews"], queue=runner.queue))
    runner.drain()  # populate corpus

    update2, msg2 = make_update()
    await telegram_intel.message_search(
        update2, make_ctx(['"evil.example"'], fake_collector(), queue=runner.queue)
    )
    text = msg2.reply_text.call_args.args[0]
    assert "Message search" in text and "queued" not in text.lower()


async def test_history_lists_completed_searches(bot_db):
    runner = CapturingRunner(telegram=fake_collector())
    update, _ = make_update()
    await telegram_intel.search_user(update, make_ctx(["@alice"], queue=runner.queue))
    runner.drain()

    update2, msg2 = make_update()
    await telegram_intel.history(update2, make_ctx([]))
    assert "Recent searches" in msg2.reply_text.call_args.args[0]


async def test_unauthorized_user_denied(bot_db):
    update, msg = make_update(user_id=999)
    await telegram_intel.search_user(update, make_ctx(["@alice"], queue=InMemoryJobQueue()))
    assert "not authorized" in msg.reply_text.call_args.args[0].lower()


async def test_search_writes_audit_row(bot_db):
    from database.models import AuditLog
    from database.session import session_scope

    update, _ = make_update()
    await telegram_intel.search_user(update, make_ctx(["@alice"], queue=InMemoryJobQueue()))
    with session_scope() as s:
        actions = [a.action for a in s.query(AuditLog).all()]
    assert "search" in actions


async def test_cancel_command(bot_db):
    q = InMemoryJobQueue()
    update, _ = make_update()
    await telegram_intel.search_user(update, make_ctx(["@alice"], queue=q))

    from database.models import Job
    from database.session import session_scope

    with session_scope() as s:
        job_id = s.query(Job).one().id

    update2, msg2 = make_update()
    await telegram_intel.cancel_cmd(update2, make_ctx([job_id[:8]]))
    assert "cancelled" in msg2.reply_text.call_args.args[0].lower()

    with session_scope() as s:
        assert s.get(Job, job_id).state == "CANCELLED"
