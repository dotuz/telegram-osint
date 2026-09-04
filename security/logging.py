"""Structured logging configuration.

Uses :mod:`structlog` on top of the stdlib logging module. Every log line carries
a ``request_id`` / ``job_id`` when one is bound to the context (see
:func:`bind_context`). In production output is line-delimited JSON; in development
it is a colourised console renderer.

Secrets are never logged: configuration objects expose ``SecretStr`` which
renders as ``**********``.
"""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from typing import Any

import structlog

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_job_id: ContextVar[str | None] = ContextVar("job_id", default=None)

_CONFIGURED = False


def _merge_context(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    rid = _request_id.get()
    jid = _job_id.get()
    if rid is not None:
        event_dict.setdefault("request_id", rid)
    if jid is not None:
        event_dict.setdefault("job_id", jid)
    return event_dict


def configure_logging(*, level: str = "INFO", json_output: bool = False) -> None:
    """Configure structlog + stdlib logging. Idempotent."""
    global _CONFIGURED

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        _merge_context,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer: Any = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=logging.getLevelNamesMapping().get(level.upper(), logging.INFO),
        force=True,
    )
    _CONFIGURED = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound logger, configuring logging with defaults if needed."""
    if not _CONFIGURED:
        configure_logging()
    return structlog.get_logger(name)


def bind_request_id(request_id: str | None) -> None:
    _request_id.set(request_id)


def bind_job_id(job_id: str | None) -> None:
    _job_id.set(job_id)


def clear_context() -> None:
    _request_id.set(None)
    _job_id.set(None)
    structlog.contextvars.clear_contextvars()
