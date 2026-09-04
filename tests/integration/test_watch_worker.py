import pytest

from database.models import Job, JobState, Watchlist
from database.repositories import UserRepository, WatchlistRepository
from database.session import session_scope
from database.types import TargetKind
from tests.telegram_fixtures import seeded_source
from tests.worker_helpers import CapturingRunner
from workers.scheduler import schedule_due_watches

pytestmark = pytest.mark.integration


@pytest.fixture
def watched(db_session):
    u = UserRepository(db_session).create(email="a@example.com", telegram_user_id=42)
    e1, _ = WatchlistRepository(db_session, u.id).add(
        kind=TargetKind.USERNAME, value="@opsecnews", max_targets=25
    )
    e2, _ = WatchlistRepository(db_session, u.id).add(
        kind=TargetKind.USERNAME, value="@leakclub", max_targets=25
    )
    db_session.commit()
    return db_session, [e1.id, e2.id]


def test_scheduler_enqueues_one_job_per_due_entry(watched):
    session, ids = watched
    runner = CapturingRunner()

    n = schedule_due_watches(runner.queue, interval_seconds=300)
    assert n == 2
    assert runner.queue.size() == 2

    # marked scheduled -> a second immediate call enqueues nothing
    assert schedule_due_watches(runner.queue, interval_seconds=300) == 0

    with session_scope() as s:
        kinds = {j.kind for j in s.query(Job).all()}
    assert kinds == {"watch_poll"}


def test_watch_poll_job_notifies_on_new_activity(watched):
    session, ids = watched
    runner = CapturingRunner()
    runner._runner  # noqa: B018 - ensure constructed
    from workers.handlers import set_collector_overrides

    set_collector_overrides(telegram=None, username=None)

    # inject the fake source via the module-level override the handler reads
    import workers.handlers as h
    from collectors.telegram.collector import TelegramPublicCollector

    h._TG_COLLECTOR = TelegramPublicCollector(seeded_source())

    schedule_due_watches(runner.queue, interval_seconds=300)
    runner.drain()

    # opsecnews has 2 messages -> a NEW PUBLIC ACTIVITY notification to chat 42
    texts = [n.text for n in runner.notifications]
    assert any("NEW PUBLIC ACTIVITY" in t for t in texts)
    assert all(n.chat_id == 42 for n in runner.notifications)

    with session_scope() as s:
        states = {j.state for j in s.query(Job).all()}
    assert states == {JobState.COMPLETED.value}


def test_watch_poll_skips_inactive_entry(watched):
    session, ids = watched
    with session_scope() as s:
        s.get(Watchlist, ids[0]).is_active = False
        s.commit()

    runner = CapturingRunner()
    import workers.handlers as h
    from collectors.telegram.collector import TelegramPublicCollector

    h._TG_COLLECTOR = TelegramPublicCollector(seeded_source())

    # enqueue a poll for the now-inactive entry directly
    from database.repositories import JobRepository

    with session_scope() as s:
        job = JobRepository(s).create(kind="watch_poll", params={"watchlist_id": ids[0]})
        s.commit()
        jid = job.id
    runner.queue.enqueue(jid)
    runner.drain()

    with session_scope() as s:
        job = s.get(Job, jid)
        assert job.state == JobState.COMPLETED.value
        assert '"skipped": true' in job.result_json
