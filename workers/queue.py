"""Job queue abstraction.

Production uses Redis (a list for the ready queue, a sorted set for delayed
retries). Tests and single-process dev use :class:`InMemoryJobQueue`.

The process-wide default queue is resolved lazily via :func:`get_default_queue`;
tests override it with :func:`set_default_queue`.
"""

from __future__ import annotations

import time
from collections import deque
from threading import Lock
from typing import Protocol

from security.config import get_settings
from security.logging import get_logger

_log = get_logger("workers.queue")

_READY_KEY = "toi:jobs:ready"
_DELAYED_KEY = "toi:jobs:delayed"


class JobQueue(Protocol):
    def enqueue(self, job_id: str, *, delay: float = 0.0) -> None: ...
    def dequeue(self, *, timeout: float = 5.0) -> str | None: ...
    def size(self) -> int: ...


class InMemoryJobQueue:
    """Deque + delayed list. Single process only."""

    def __init__(self) -> None:
        self._ready: deque[str] = deque()
        self._delayed: list[tuple[float, str]] = []
        self._lock = Lock()

    def enqueue(self, job_id: str, *, delay: float = 0.0) -> None:
        with self._lock:
            if delay > 0:
                self._delayed.append((time.monotonic() + delay, job_id))
            else:
                self._ready.append(job_id)

    def _promote(self) -> None:
        now = time.monotonic()
        due = [j for t, j in self._delayed if t <= now]
        self._delayed = [(t, j) for t, j in self._delayed if t > now]
        self._ready.extend(due)

    def dequeue(self, *, timeout: float = 5.0) -> str | None:
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                self._promote()
                if self._ready:
                    return self._ready.popleft()
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.01)

    def size(self) -> int:
        with self._lock:
            return len(self._ready) + len(self._delayed)


class RedisJobQueue:
    def __init__(self, url: str) -> None:
        import redis

        self._r = redis.from_url(url, decode_responses=True)

    def ping(self) -> None:
        """Force a connection so callers can detect an unreachable Redis."""
        self._r.ping()

    def enqueue(self, job_id: str, *, delay: float = 0.0) -> None:
        if delay > 0:
            self._r.zadd(_DELAYED_KEY, {job_id: time.time() + delay})
        else:
            self._r.lpush(_READY_KEY, job_id)

    def _promote(self) -> None:
        now = time.time()
        due = self._r.zrangebyscore(_DELAYED_KEY, "-inf", now)
        for raw in due:
            job_id = str(raw)
            if self._r.zrem(_DELAYED_KEY, job_id):
                self._r.lpush(_READY_KEY, job_id)

    def dequeue(self, *, timeout: float = 5.0) -> str | None:
        self._promote()
        res = self._r.brpop([_READY_KEY], timeout=int(max(1, timeout)))
        if res is None:
            return None
        return str(res[1])

    def size(self) -> int:
        return int(self._r.llen(_READY_KEY)) + int(self._r.zcard(_DELAYED_KEY))


_default: JobQueue | None = None


def get_default_queue() -> JobQueue:
    global _default
    if _default is None:
        url = get_settings().redis_url
        try:
            candidate = RedisJobQueue(url)
            candidate.ping()  # redis.from_url is lazy; force a real connection
            _default = candidate
            _log.info("job_queue_ready", backend="redis")
        except Exception as exc:  # noqa: BLE001 - fall back so dev without Redis still works
            _log.warning("redis_queue_unavailable_using_memory", error=str(exc))
            _default = InMemoryJobQueue()
    return _default


def set_default_queue(queue: JobQueue | None) -> None:
    global _default
    _default = queue
