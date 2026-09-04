"""Worker process entrypoint."""

from __future__ import annotations

from collectors.bootstrap import register_default_collectors
from security.config import get_settings
from security.logging import configure_logging, get_logger
from workers.runner import JobRunner

_log = get_logger("workers")


def run_worker() -> None:  # pragma: no cover - process entrypoint
    settings = get_settings()
    configure_logging(level=settings.log_level, json_output=settings.log_json)
    settings.require_production_secrets()
    register_default_collectors()

    import workers.handlers  # noqa: F401 - registers job handlers
    from workers.queue import get_default_queue
    from workers.scheduler import schedule_due_watches_tick

    token = settings.telegram_bot_token.get_secret_value() or None
    queue = get_default_queue()
    _log.info("worker_booting", env=settings.app_env)
    JobRunner(
        queue,
        bot_token=token,
        on_tick=lambda: schedule_due_watches_tick(queue),
        tick_interval=min(60.0, float(settings.watch_poll_interval_seconds)),
    ).run_forever()
