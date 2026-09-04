"""Telegram bot application.

Only data legitimately delivered by the Telegram Bot API is used here. The bot
never requests or handles sessions, tokens, passwords, OTP codes, cookies, or
device credentials -- not in ``/start`` and not anywhere else.

Run with ``python -m apps.bot``.
"""

from apps.bot.app import build_application, run

__all__ = ["build_application", "run"]
