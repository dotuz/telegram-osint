import time

import pytest

from workers.queue import InMemoryJobQueue

pytestmark = pytest.mark.integration


def test_in_memory_queue_fifo_and_delay():
    q = InMemoryJobQueue()
    q.enqueue("a")
    q.enqueue("b")
    q.enqueue("c", delay=0.05)
    assert q.dequeue(timeout=0.1) == "a"
    assert q.dequeue(timeout=0.1) == "b"
    assert q.dequeue(timeout=0.02) is None  # c not ready
    time.sleep(0.06)
    assert q.dequeue(timeout=0.1) == "c"
    assert q.size() == 0


def test_queue_dequeue_times_out():
    assert InMemoryJobQueue().dequeue(timeout=0.02) is None


@pytest.fixture
def client(settings):
    from fastapi.testclient import TestClient

    import database.models  # noqa: F401
    from apps.api.main import create_app
    from database.base import Base
    from database.session import get_engine

    Base.metadata.create_all(get_engine())
    with TestClient(create_app(settings)) as c:
        yield c
    Base.metadata.drop_all(get_engine())


def _make_job(kind="telegram_user"):
    from database.repositories import JobRepository
    from database.session import session_scope

    with session_scope() as s:
        job = JobRepository(s).create(kind=kind, params={"query": "x"}, requested_by="telegram:1")
        s.commit()
        return job.id


def test_jobs_api_list_get_cancel(client):
    jid = _make_job()

    listing = client.get("/api/v1/jobs").json()["jobs"]
    assert any(j["id"] == jid for j in listing)

    detail = client.get(f"/api/v1/jobs/{jid}").json()
    assert detail["kind"] == "telegram_user"
    assert detail["state"] == "PENDING"
    assert detail["params"]["query"] == "x"

    cancelled = client.post(f"/api/v1/jobs/{jid}/cancel").json()
    assert cancelled == {"cancelled": True, "state": "CANCELLED"}

    again = client.post(f"/api/v1/jobs/{jid}/cancel").json()
    assert again["cancelled"] is False

    assert client.get("/api/v1/jobs/nope").status_code == 404
