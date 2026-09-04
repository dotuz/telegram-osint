"""Telegram <-> :class:`BotMessage` adapter.

The only module (besides ``app.py``) that touches ``telegram.*`` runtime objects
for sending. Handlers build a :class:`BotMessage` and call :func:`reply`.
"""

from __future__ import annotations

from telegram import Message, Update

from apps.bot.responses import BotMessage


async def reply(update: Update, message: BotMessage) -> None:
    """Send ``message`` as a reply, editing in place for callback-query updates."""
    markup = message.to_reply_markup()
    kwargs = {
        "reply_markup": markup,
        "parse_mode": message.parse_mode,
        "disable_web_page_preview": message.disable_web_page_preview,
    }

    if update.callback_query is not None:
        await update.callback_query.answer()
        try:
            await update.callback_query.edit_message_text(message.text, **kwargs)
        except Exception:  # noqa: BLE001 - "message is not modified" etc. are harmless
            fallback = update.callback_query.message
            if isinstance(fallback, Message):
                await fallback.reply_text(message.text, **kwargs)
        return

    if update.effective_message is not None:
        await update.effective_message.reply_text(message.text, **kwargs)
