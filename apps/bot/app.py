"""Telegram bot application wiring.

``build_application`` assembles the handler graph from the command registry and
is import-safe (no network). ``run`` configures logging and starts long polling.
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from apps.bot.auth import warn_if_open_or_closed
from apps.bot.errors import on_error
from apps.bot.handlers import admin, common, telegram_intel
from apps.bot.handlers.stubs import make_stub_handler
from apps.bot.router import ALL_COMMANDS, public_command_menu
from security.config import Settings, get_settings
from security.logging import configure_logging, get_logger

_log = get_logger("bot.app")

# Commands with real Phase-2 implementations; everything else gets a stub handler.
_LIVE_HANDLERS = {
    "start": common.start,
    "help": common.help_cmd,
    "whoami": common.whoami,
    "admin": admin.admin_overview,
    "health": admin.health_cmd,
    # Phase 4: public Telegram intelligence
    "search": telegram_intel.search_user,
    "user": telegram_intel.user_alias,
    "group": telegram_intel.group_intel,
    "channel": telegram_intel.channel_intel,
    "message": telegram_intel.message_search,
    "history": telegram_intel.history,
}


async def _post_init(application: Application) -> None:
    try:
        await application.bot.set_my_commands(public_command_menu())
    except Exception as exc:  # noqa: BLE001 - non-fatal
        _log.warning("set_my_commands_failed", error=str(exc))


def build_application(*, token: str | None = None, settings: Settings | None = None) -> Application:
    settings = settings or get_settings()
    warn_if_open_or_closed(settings)

    token = token or settings.telegram_bot_token.get_secret_value()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

    application = ApplicationBuilder().token(token).post_init(_post_init).build()

    for spec in ALL_COMMANDS:
        handler = _LIVE_HANDLERS.get(spec.name) or make_stub_handler(spec)
        application.add_handler(CommandHandler(spec.name, handler))

    application.add_handler(CallbackQueryHandler(common.menu_callback, pattern=r"^menu:"))
    # Any other /command -> generic "unknown command".
    application.add_handler(MessageHandler(filters.COMMAND, common.unknown_command))

    application.add_error_handler(on_error)
    return application


def run() -> None:  # pragma: no cover - process entrypoint
    settings = get_settings()
    configure_logging(level=settings.log_level, json_output=settings.log_json)
    settings.require_production_secrets()
    _log.info("bot_starting", env=settings.app_env)
    build_application(settings=settings).run_polling(allowed_updates=Update.ALL_TYPES)
