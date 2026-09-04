"""Global error handler: users get a generic message, logs get the detail."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from apps.bot.adapter import reply
from apps.bot.views import render_error
from security.logging import get_logger

_log = get_logger("bot.errors")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    _log.error(
        "bot_unhandled_error",
        error=repr(context.error),
        update_type=type(update).__name__,
    )
    if isinstance(update, Update):
        try:
            await reply(update, render_error())
        except Exception:  # noqa: BLE001 - nothing more we can do
            _log.warning("bot_error_reply_failed")
