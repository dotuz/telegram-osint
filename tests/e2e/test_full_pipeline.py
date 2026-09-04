"""End-to-end: Telegram command -> job -> worker -> OSINT -> evidence -> report
-> API retrieval -> cross-user isolation.

Uses only synthetic collectors and public-shaped test handles. No network, no
real Telegram, no private data.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from apps.bot.handlers import report as report_handler
from apps.bot.handlers import username_osint as username_handler
from database.repositories import UserRepository
from database.session import session_scope
from security.auth import create_access_token
from tests.username_fixtures import alice_collector
from tests.worker_helpers import CapturingRunner

pytestmark = pytest.mark.e2e


def _update(user_id: int, chat_id: int = 555):
    msg = SimpleNamespace(reply_text=AsyncMock())
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id, first_name="Ann"),
        effective_message=msg,
        effective_chat=SimpleNamespace(id=chat_id, send_action=AsyncMock()),
        callback_query=None,
    ), msg


def _ctx(args, queue):
    app = SimpleNamespace(bot_data={"job_queue": queue})
    return SimpleNamespace(args=args, application=app)


@pytest.fixture
def api(db_session):
    from fastapi.testclient import TestClient

    from apps.api.main import create_app
    from security.config import get_settings

    with TestClient(create_app(get_settings())) as c:
        yield c


def test_bot_to_report_to_api_flow(db_session, api):
    runner = CapturingRunner(username=alice_collector())
    tg_id = 222  # allow-listed analyst (see tests/conftest env)

    # 1. /username alice  ->  job enqueued
    upd, msg = _update(tg_id)
    asyncio.run(username_handler.username_osint(upd, _ctx(["alice"], runner.queue)))
    assert "queued" in msg.reply_text.call_args.args[0].lower()

    # 2. worker runs the username-OSINT job -> evidence persisted, chat notified
    assert runner.drain() == 1
    assert runner.notifications and runner.notifications[0].chat_id == 555
    # non-committal identity phrasing must survive the whole pipeline
    assert "the same person" not in runner.notifications[0].text.lower()

    # 3. /report alice  ->  target + report row + report_generate job
    upd2, _msg2 = _update(tg_id)
    asyncio.run(report_handler.report_cmd(upd2, _ctx(["alice"], runner.queue)))
    assert runner.drain() >= 1

    # resolve the bot user + its report
    with session_scope() as s:
        user = UserRepository(s).get_by_telegram_id(tg_id)
        assert user is not None
        uid, role = user.id, user.role

    # 4. API: the owner sees the generated report and can download every format
    token = create_access_token(user_id=uid, role=role)
    owner = {"Authorization": f"Bearer {token}"}

    listing = api.get("/api/v1/reports", headers=owner).json()["reports"]
    assert len(listing) == 1
    rid = listing[0]["id"]
    assert listing[0]["status"] == "COMPLETED"

    detail = api.get(f"/api/v1/reports/{rid}", headers=owner).json()
    assert detail["content"] is not None
    body = " ".join(str(v) for v in _walk(detail["content"]))
    assert "the same person" not in body.lower()  # confidence phrasing guard

    for fmt, ctype in (
        ("json", "application/json"),
        ("html", "text/html"),
        ("pdf", "application/pdf"),
    ):
        r = api.get(f"/api/v1/reports/{rid}/download?fmt={fmt}", headers=owner)
        assert r.status_code == 200, fmt
        assert r.headers["content-type"].startswith(ctype)

    # 5. target graph reflects the resolved entities from the OSINT run
    tgts = api.get("/api/v1/targets", headers=owner).json()["targets"]
    assert any(t["value"] == "alice" for t in tgts)

    # 6. cross-user isolation: a different user cannot see or download the report
    with session_scope() as s:
        u2 = UserRepository(s).create(email="e2e-other@example.com")
        s.commit()
        other_id = u2.id
    other_h = {"Authorization": f"Bearer {create_access_token(user_id=other_id, role='ANALYST')}"}
    assert api.get("/api/v1/reports", headers=other_h).json()["reports"] == []
    assert api.get(f"/api/v1/reports/{rid}", headers=other_h).status_code == 404
    assert api.get(f"/api/v1/reports/{rid}/download?fmt=json", headers=other_h).status_code == 404


def _walk(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)
    else:
        yield obj
