from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from apps.bot.handlers import watchlist as wl
from database.models import Relationship, Watchlist
from database.session import session_scope
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


def _ctx(args, queue=None):
    data = {"job_queue": queue} if queue is not None else {}
    return SimpleNamespace(args=args, application=SimpleNamespace(bot_data=data))


def _update(uid=111):
    msg = SimpleNamespace(reply_text=AsyncMock())
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=uid, first_name="A"),
        effective_message=msg,
        effective_chat=SimpleNamespace(id=555, send_action=AsyncMock()),
        callback_query=None,
    ), msg


async def test_watch_adds_entry_resolves_target_and_enqueues_poll(bot_db):
    q = InMemoryJobQueue()
    update, msg = _update()
    await wl.watch_cmd(update, _ctx(["@OpSecNews"], queue=q))

    assert "Watching" in msg.reply_text.call_args.args[0]
    assert q.size() == 1  # first poll enqueued

    with session_scope() as s:
        entries = s.query(Watchlist).all()
        assert [e.value_normalized for e in entries] == ["opsecnews"]
        # a target was resolved
        assert s.query(Relationship).filter_by(source_type="target").count() >= 1


async def test_watch_enforces_limit(bot_db, monkeypatch):
    from security.config import get_settings

    monkeypatch.setenv("RATE_LIMIT_WATCH_MAX_TARGETS", "1")
    get_settings.cache_clear()

    q = InMemoryJobQueue()
    await wl.watch_cmd(_update()[0], _ctx(["one"], queue=q))
    update, msg = _update()
    await wl.watch_cmd(update, _ctx(["two"], queue=q))
    assert "limit reached" in msg.reply_text.call_args.args[0].lower()


async def test_unwatch_and_watchlist(bot_db):
    q = InMemoryJobQueue()
    await wl.watch_cmd(_update()[0], _ctx(["@alice"], queue=q))

    update, msg = _update()
    await wl.watchlist_cmd(update, _ctx([]))
    assert "alice" in msg.reply_text.call_args.args[0]

    update2, msg2 = _update()
    await wl.unwatch_cmd(update2, _ctx(["alice"]))
    assert "stopped watching" in msg2.reply_text.call_args.args[0].lower()

    update3, msg3 = _update()
    await wl.unwatch_cmd(update3, _ctx(["alice"]))
    assert "isn't on your watchlist" in msg3.reply_text.call_args.args[0].lower()


async def test_watch_denied_for_unauthorized(bot_db):
    update, msg = _update(uid=999)
    await wl.watch_cmd(update, _ctx(["@alice"], queue=InMemoryJobQueue()))
    assert "not authorized" in msg.reply_text.call_args.args[0].lower()
