"""Authorization decorator for bot handlers.

Wraps a handler so that:
  * unauthorized users get a generic denial and an audit entry;
  * authorized users' handlers receive a resolved :class:`Principal`;
  * any unhandled exception is turned into a generic message (never a stack trace)
    and logged with full detail.
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Coroutine
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

from apps.bot import audit
from apps.bot.adapter import reply
from apps.bot.auth import AccessDenied, Principal, require_admin, resolve_principal
from apps.bot.views import render_denied, render_error
from security.logging import get_logger

_log = get_logger("bot.guard")

Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE, Principal], Coroutine[Any, Any, None]]
PTBHandler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Coroutine[Any, Any, None]]


def authorized(
    *, admin: bool = False, action: str | None = None
) -> Callable[[Handler], PTBHandler]:
    def decorator(fn: Handler) -> PTBHandler:
        act = action or fn.__name__

        @functools.wraps(fn)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            user = update.effective_user
            telegram_id = user.id if user else None
            actor = f"telegram:{telegram_id}"

            try:
                principal = resolve_principal(telegram_id)
                if admin:
                    require_admin(principal)
            except AccessDenied as exc:
                _log.warning(
                    "bot_access_denied", telegram_id=telegram_id, action=act, reason=exc.reason
                )
                audit.record(
                    actor=actor,
                    action="access_denied",
                    resource=f"command:{act}",
                    result="denied",
                    metadata={"reason": exc.reason},
                )
                await reply(update, render_denied())
                return

            try:
                await fn(update, context, principal)
            except Exception:  # noqa: BLE001 - user must never see a traceback
                _log.exception("bot_handler_error", action=act, telegram_id=telegram_id)
                audit.record(actor=actor, action=act, result="error", resource=f"command:{act}")
                await reply(update, render_error())

        return wrapper

    return decorator
