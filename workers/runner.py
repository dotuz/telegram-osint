"""Job runner: dequeue -> dispatch -> drive the state machine.

``PENDING`` -> (queue) -> ``RUNNING`` -> ``COMPLETED``; on error ``FAILED``, then
``PENDING`` again (re-enqueued with exponential backoff) until ``max_retries``.

Cancellation: a job set to ``CANCELLED`` (by the API/bot) before it is picked up
is skipped; a job cancelled mid-run still records its terminal state as
``CANCELLED``.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import time
from collections.abc import Callable, Coroutine
from typing import TypeVar

from database.models.job import JobState
from database.repositories import IllegalJobStateTransition, JobRepository
from database.session import session_scope
from security.logging import bind_job_id, clear_context, get_logger
from workers.queue import JobQueue, get_default_queue
from workers.registry import JobContext, JobOutcome, Notification, get_handler

_log = get_logger("workers.runner")

_RETRY_BASE_SECONDS = 5.0
_T = TypeVar("_T")


def _run_sync(coro: Coroutine[object, object, _T]) -> _T:
    """Run a coroutine to completion whether or not a loop is already running in
    this thread (the worker has none; pytest-asyncio does)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


class JobRunner:
    def __init__(
        self,
        queue: JobQueue | None = None,
        *,
        bot_token: str | None = None,
        retry_base_seconds: float = _RETRY_BASE_SECONDS,
        notifier: Callable[[Notification], None] | None = None,
        on_tick: Callable[[], None] | None = None,
        tick_interval: float = 60.0,
    ) -> None:
        self.queue = queue or get_default_queue()
        self.bot_token = bot_token
        self.retry_base_seconds = retry_base_seconds
        self._notifier = notifier or self._send_telegram
        self._on_tick = on_tick
        self._tick_interval = tick_interval
        self._last_tick = 0.0
        self._stop = False

    # ------------------------------------------------------------------ loop
    def run_forever(self, *, poll_timeout: float = 5.0) -> None:  # pragma: no cover - loop
        _log.info("worker_started")
        while not self._stop:
            try:
                self._maybe_tick()
                self.run_once(poll_timeout=poll_timeout)
            except Exception:  # noqa: BLE001 - never let the loop die
                _log.exception("worker_iteration_failed")
                time.sleep(1)
        _log.info("worker_stopped")

    def _maybe_tick(self) -> None:
        if self._on_tick is None:
            return
        now = time.monotonic()
        if now - self._last_tick < self._tick_interval:
            return
        self._last_tick = now
        try:
            self._on_tick()
        except Exception:  # noqa: BLE001 - a bad tick must not stop the loop
            _log.exception("worker_tick_failed")

    def stop(self) -> None:
        self._stop = True

    # ------------------------------------------------------------------ one job
    def run_once(self, *, poll_timeout: float = 1.0) -> str | None:
        job_id = self.queue.dequeue(timeout=poll_timeout)
        if job_id is None:
            return None
        bind_job_id(job_id)
        try:
            self._process(job_id)
        finally:
            clear_context()
        return job_id

    def _process(self, job_id: str) -> None:
        with session_scope() as session:
            repo = JobRepository(session)
            job = repo.get(job_id)
            if job is None:
                _log.warning("job_not_found", job_id=job_id)
                return
            state = JobState(job.state)
            if state.is_terminal:
                _log.info("job_already_terminal", job_id=job_id, state=state.value)
                return
            kind = job.kind
            if get_handler(kind) is None:
                repo.transition(job_id, JobState.FAILED, error=f"no handler for kind {kind!r}")
                return
            try:
                repo.transition(job_id, JobState.RUNNING, progress=0)
            except IllegalJobStateTransition:
                return

        try:
            outcome = _run_sync(self._dispatch(job_id, kind))
        except Exception as exc:  # noqa: BLE001 - convert to FAILED / retry
            self._on_failure(job_id, exc)
            return

        with session_scope() as session:
            repo = JobRepository(session)
            current = repo.get(job_id)
            if current is not None and JobState(current.state) is JobState.CANCELLED:
                _log.info("job_cancelled_before_completion", job_id=job_id)
                return
            repo.transition(job_id, JobState.COMPLETED, progress=100, result=outcome.summary)
        if outcome.notification is not None:
            self._deliver(outcome.notification)

    async def _dispatch(self, job_id: str, kind: str) -> JobOutcome:
        handler = get_handler(kind)
        assert handler is not None
        with session_scope() as session:
            job = JobRepository(session).get(job_id)
            assert job is not None

            def _progress(pct: int) -> None:
                with session_scope() as s:
                    JobRepository(s).transition(job_id, JobState.RUNNING, progress=pct)

            ctx = JobContext(session=session, job=job, _progress=_progress)
            return await handler(ctx)

    def _on_failure(self, job_id: str, exc: Exception) -> None:
        _log.warning("job_failed", job_id=job_id, error=f"{type(exc).__name__}: {exc}")
        with session_scope() as session:
            repo = JobRepository(session)
            job = repo.get(job_id)
            if job is None:
                return
            repo.transition(job_id, JobState.FAILED, error=f"{type(exc).__name__}: {exc}")
            if job.retry_count < job.max_retries:
                repo.transition(job_id, JobState.PENDING)  # bumps retry_count, clears error
                delay = self.retry_base_seconds * (2**job.retry_count)
                session.flush()
                self.queue.enqueue(job_id, delay=delay)
                _log.info(
                    "job_retry_scheduled", job_id=job_id, delay=delay, attempt=job.retry_count
                )
                return
        self._deliver(
            Notification(
                chat_id=self._chat_id(job_id) or 0,
                text="Collection failed. Source unavailable.",
                parse_mode=None,
            )
        )

    # ------------------------------------------------------------------ notify
    def _chat_id(self, job_id: str) -> int | str | None:
        import json

        with session_scope() as session:
            job = JobRepository(session).get(job_id)
            if job is None:
                return None
            return json.loads(job.params_json or "{}").get("chat_id")

    def _deliver(self, notification: Notification) -> None:
        if not notification.chat_id:
            return
        try:
            self._notifier(notification)
        except Exception:  # noqa: BLE001 - a failed notification must not fail the job
            _log.warning("notification_delivery_failed", chat_id=notification.chat_id)

    def _send_telegram(self, notification: Notification) -> None:  # pragma: no cover - network
        token = self.bot_token
        if not token:
            _log.info("notification_skipped_no_token")
            return
        from telegram import Bot

        async def _send() -> None:
            await Bot(token).send_message(
                chat_id=notification.chat_id,
                text=notification.text,
                parse_mode=notification.parse_mode,
            )

        _run_sync(_send())
