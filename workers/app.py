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

    token = settings.telegram_bot_token.get_secret_value() or None
    _log.info("worker_booting", env=settings.app_env)
    JobRunner(bot_token=token).run_forever()
