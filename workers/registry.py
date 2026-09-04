"""Job-handler registry.

A handler is ``async (JobContext) -> JobOutcome``. It does the work for one
``Job.kind``, using the session and progress callback the runner provides, and
returns a result summary plus an optional user notification.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from database.models.job import Job


@dataclass
class JobContext:
    session: Session
    job: Job
    _progress: Callable[[int], None]

    def progress(self, percent: int) -> None:
        self._progress(max(0, min(100, percent)))

    @property
    def params(self) -> dict[str, Any]:
        return json.loads(self.job.params_json or "{}")


@dataclass
class Notification:
    chat_id: int | str
    text: str
    parse_mode: str | None = "Markdown"


@dataclass
class JobOutcome:
    summary: dict[str, Any] = field(default_factory=dict)
    notification: Notification | None = None


JobHandler = Callable[[JobContext], Awaitable[JobOutcome]]

_HANDLERS: dict[str, JobHandler] = {}


def register(kind: str) -> Callable[[JobHandler], JobHandler]:
    def deco(fn: JobHandler) -> JobHandler:
        _HANDLERS[kind] = fn
        return fn

    return deco


def get_handler(kind: str) -> JobHandler | None:
    return _HANDLERS.get(kind)


def known_kinds() -> list[str]:
    return sorted(_HANDLERS)
