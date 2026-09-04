"""Phase-8 test helpers: run enqueued jobs synchronously and capture notifications."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import workers.handlers as handlers
from workers.queue import InMemoryJobQueue
from workers.registry import Notification
from workers.runner import JobRunner


class CapturingRunner:
    """A JobRunner over an in-memory queue that records notifications."""

    def __init__(self, *, telegram=None, username=None, retry_base_seconds: float = 0.01) -> None:
        self.queue = InMemoryJobQueue()
        self.notifications: list[Notification] = []
        handlers.set_collector_overrides(telegram=telegram, username=username)
        self._runner = JobRunner(
            self.queue,
            notifier=self.notifications.append,
            retry_base_seconds=retry_base_seconds,
        )

    def drain(self, *, max_jobs: int = 10) -> int:
        done = 0
        for _ in range(max_jobs):
            if self._runner.run_once(poll_timeout=0.05) is None:
                break
            done += 1
        return done


def bot_context(args: list[str], *, queue) -> SimpleNamespace:
    app = SimpleNamespace(bot_data={"job_queue": queue})
    return SimpleNamespace(args=args, application=app)


def bot_message_update(user_id: int = 111):
    msg = SimpleNamespace(reply_text=AsyncMock())
    return (
        SimpleNamespace(
            effective_user=SimpleNamespace(id=user_id, first_name="A"),
            effective_message=msg,
            effective_chat=SimpleNamespace(id=555, send_action=AsyncMock()),
            callback_query=None,
        ),
        msg,
    )
