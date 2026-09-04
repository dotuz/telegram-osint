import pytest

from apps.bot.app import build_application
from apps.bot.router import ALL_COMMANDS

pytestmark = pytest.mark.integration


def test_build_application_registers_all_commands():
    app = build_application(token="123456:TEST-TOKEN")

    from telegram.ext import CallbackQueryHandler, CommandHandler, MessageHandler

    handlers = app.handlers[0]
    command_names = {cmd for h in handlers if isinstance(h, CommandHandler) for cmd in h.commands}
    for spec in ALL_COMMANDS:
        assert spec.name in command_names, f"/{spec.name} not registered"

    assert any(isinstance(h, CallbackQueryHandler) for h in handlers)
    assert any(isinstance(h, MessageHandler) for h in handlers)
    assert app.error_handlers


def test_build_application_requires_token(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    from security.config import get_settings

    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
        build_application()
