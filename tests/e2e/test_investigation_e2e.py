"""E2E: /investigate -> job -> worker -> collector -> observations -> report ->
bot summary -> API retrieval -> cross-user isolation.

Synthetic collectors only; no network, no real Telegram, no private data.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import workers.handlers as handlers
from apps.bot.handlers import investigate
from collectors.telegram import FakeTelegramSource, PublicMessage, PublicProfile
from collectors.telegram.collector import TelegramPublicCollector
from database.repositories import UserRepository
from database.session import session_scope
from security.auth import create_access_token
from tests.username_fixtures import alice_collector
from tests.worker_helpers import CapturingRunner

pytestmark = pytest.mark.e2e

TG_ID = 222  # allow-listed analyst per tests/conftest env


def _source() -> FakeTelegramSource:
    src = FakeTelegramSource()
    src.profiles["alice"] = PublicProfile(username="alice", display_name="Alice", telegram_id=42)
    src.messages["opsecnews"] = [
        PublicMessage(
            message_id=1,
            chat_username="opsecnews",
            author_username="alice",
            text="alice posting publicly",
            posted_at=datetime(2026, 4, 1, tzinfo=UTC),
            reference="https://t.me/opsecnews/1",
        ),
        PublicMessage(
            message_id=2,
            chat_username="opsecnews",
            author_username="mallory",
            text="looking for @alice",
            posted_at=datetime(2026, 4, 2, tzinfo=UTC),
            reference="https://t.me/opsecnews/2",
        ),
    ]
    return src


def _update(chat_id: int = 555):
    msg = SimpleNamespace(reply_text=AsyncMock())
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=TG_ID, first_name="Op"),
        effective_message=msg,
        effective_chat=SimpleNamespace(id=chat_id, send_action=AsyncMock()),
        callback_query=None,
    ), msg


def _ctx(args, queue):
    return SimpleNamespace(
        args=args,
        user_data={},
        application=SimpleNamespace(bot_data={"job_queue": queue, "bot_username": "TOIBot"}),
    )


@pytest.fixture
def api(db_session):
    from fastapi.testclient import TestClient

    from apps.api.main import create_app
    from security.config import get_settings

    with TestClient(create_app(get_settings())) as c:
        yield c


def test_investigate_end_to_end(db_session, api):
    runner = CapturingRunner()
    handlers.set_collector_overrides(
        telegram=TelegramPublicCollector(_source()), username=alice_collector()
    )
    try:
        # 1. /investigate @alice
        upd, msg = _update()
        asyncio.run(investigate.investigate_cmd(upd, _ctx(["@alice"], runner.queue)))
        assert "Investigation started" in msg.reply_text.call_args.args[0]

        # 2. worker runs the investigation job
        assert runner.drain() == 1
        assert runner.notifications
        note = runner.notifications[0].text
        assert "Investigation `INV-" in note
        assert "Mentions: 1" in note
        assert "Likely authored: 1" in note

        # 3. resolve the investigation + report via the API
        with session_scope() as s:
            user = UserRepository(s).get_by_telegram_id(TG_ID)
            uid, role = user.id, user.role
        h = {"Authorization": f"Bearer {create_access_token(user_id=uid, role=role)}"}

        listing = api.get("/api/v1/investigations", headers=h).json()["investigations"]
        assert len(listing) == 1
        inv = listing[0]
        assert inv["status"] == "COMPLETED"
        assert inv["public_id"].startswith("INV-")

        detail = api.get(f"/api/v1/investigations/{inv['id']}", headers=h).json()
        types = {o["type"] for o in detail["observations"]}
        assert "AUTHOR" in types and "MENTION" in types
        body = " ".join(str(v) for v in _walk(detail))
        assert "the same person" not in body.lower()

        for fmt, ctype in (("json", "application/json"), ("html", "text/html")):
            r = api.get(f"/api/v1/investigations/{inv['id']}/report/download?fmt={fmt}", headers=h)
            assert r.status_code == 200, fmt
            assert r.headers["content-type"].startswith(ctype)
        # the report must carry the visibility-limitations section
        rj = api.get(
            f"/api/v1/investigations/{inv['id']}/report/download?fmt=json", headers=h
        ).json()
        keys = {s["key"] for s in rj["sections"]}
        assert "limitations" in keys and "methodology" in keys

        # 4. cross-user isolation
        with session_scope() as s:
            other = UserRepository(s).create(email="e2e-other-inv@example.com")
            s.commit()
            other_id = other.id
        oh = {"Authorization": f"Bearer {create_access_token(user_id=other_id, role='ANALYST')}"}
        assert api.get("/api/v1/investigations", headers=oh).json()["investigations"] == []
        assert api.get(f"/api/v1/investigations/{inv['id']}", headers=oh).status_code == 404
        assert (
            api.get(
                f"/api/v1/investigations/{inv['id']}/report/download?fmt=json", headers=oh
            ).status_code
            == 404
        )
    finally:
        handlers.set_collector_overrides(telegram=None, username=None)


def _walk(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)
    else:
        yield obj
