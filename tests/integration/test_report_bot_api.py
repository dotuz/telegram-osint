from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from apps.bot.handlers import report as report_handler
from database.models import Job, Report, Target
from database.session import session_scope
from tests.report_fixtures import make_report, seed_target
from tests.telegram_fixtures import fake_collector
from tests.username_fixtures import alice_collector
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


def _ctx(args, queue=None):
    data = {"job_queue": queue} if queue is not None else {}
    return SimpleNamespace(args=args, application=SimpleNamespace(bot_data=data))


def _update(uid=111):
    msg = SimpleNamespace(reply_text=AsyncMock())
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=uid, first_name="A"),
        effective_message=msg,
        effective_chat=SimpleNamespace(id=42, send_action=AsyncMock()),
        callback_query=None,
    ), msg


async def test_report_command_creates_report_and_enqueues(bot_db):
    q = InMemoryJobQueue()
    update, msg = _update()
    await report_handler.report_cmd(update, _ctx(["@alice"], queue=q))

    assert "queued" in msg.reply_text.call_args.args[0].lower()
    assert q.size() == 1
    with session_scope() as s:
        assert s.query(Report).count() == 1
        assert s.query(Target).filter_by(value_normalized="alice").count() == 1
        assert s.query(Job).one().kind == "report_generate"


async def test_report_worker_generates_and_notifies(bot_db):
    runner = CapturingRunner()

    # seed data + a report, then enqueue the job
    with session_scope() as s:
        from database.repositories import UserRepository

        u = UserRepository(s).get_or_create_for_telegram(111)[0]
        tid = await seed_target(s, u.id)
        rid = make_report(s, u.id, tid)
        s.commit()

    from database.repositories import JobRepository

    with session_scope() as s:
        job = JobRepository(s).create(
            kind="report_generate", params={"report_id": rid, "chat_id": 42, "formats": ["json"]}
        )
        s.commit()
        jid = job.id
    runner.queue.enqueue(jid)
    runner.drain()

    assert runner.notifications
    assert "Report ready" in runner.notifications[0].text
    with session_scope() as s:
        assert s.get(Report, rid).status == "COMPLETED"


async def test_report_list_subcommand(bot_db):
    with session_scope() as s:
        from database.repositories import UserRepository

        u = UserRepository(s).get_or_create_for_telegram(111)[0]
        tid = await seed_target(s, u.id)
        make_report(s, u.id, tid, title="Alpha")
        s.commit()

    update, msg = _update()
    await report_handler.report_cmd(update, _ctx(["list"]))
    assert "Alpha" in msg.reply_text.call_args.args[0]


async def test_report_usage_and_denial(bot_db):
    update, msg = _update()
    await report_handler.report_cmd(update, _ctx([], queue=InMemoryJobQueue()))
    assert "Usage" in msg.reply_text.call_args.args[0]

    update2, msg2 = _update(uid=999)
    await report_handler.report_cmd(update2, _ctx(["@alice"], queue=InMemoryJobQueue()))
    assert "not authorized" in msg2.reply_text.call_args.args[0].lower()


def test_api_report_lifecycle(settings):
    from fastapi.testclient import TestClient

    import database.models  # noqa: F401
    from apps.api.deps import get_collector, get_username_collector
    from apps.api.main import create_app
    from database.base import Base
    from database.session import get_engine

    Base.metadata.create_all(get_engine())
    app = create_app(settings)
    app.dependency_overrides[get_collector] = lambda: fake_collector()
    app.dependency_overrides[get_username_collector] = alice_collector

    with TestClient(app) as c:
        c.post("/api/v1/telegram/user", json={"query": "@alice"})
        created = c.post("/api/v1/reports", json={"value": "@alice"}).json()
        rid = created["report"]["id"]
        assert created["report"]["status"] == "COMPLETED"
        assert set(created["report"]["artifacts"]) == {"json", "html", "pdf"}

        assert any(r["id"] == rid for r in c.get("/api/v1/reports").json()["reports"])

        detail = c.get(f"/api/v1/reports/{rid}").json()
        assert detail["content"]["report_id"] == rid
        assert len(detail["content"]["sections"]) == 15

        assert c.get(f"/api/v1/reports/{rid}/download?fmt=json").status_code == 200
        html = c.get(f"/api/v1/reports/{rid}/download?fmt=html")
        assert html.status_code == 200 and "text/html" in html.headers["content-type"]
        pdf = c.get(f"/api/v1/reports/{rid}/download?fmt=pdf")
        assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"

        assert c.get("/api/v1/reports/nope").status_code == 404
        assert c.post("/api/v1/reports", json={}).status_code == 422

        other = c.get("/api/v1/reports", headers={"X-User-Email": "other@x"}).json()
        assert other["reports"] == []
    Base.metadata.drop_all(get_engine())
