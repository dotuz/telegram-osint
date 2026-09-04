"""Transport-agnostic bot response model.

Handlers (and the pure view functions they call) build :class:`BotMessage`
objects. The thin Telegram adapter layer turns these into actual
``bot.send_message`` / ``callback_query.edit_message_text`` calls. Keeping the
view logic free of ``telegram.*` objects makes it trivially unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Button:
    text: str
    callback_data: str | None = None
    url: str | None = None


@dataclass(frozen=True)
class BotMessage:
    text: str
    # Rows of buttons -> inline keyboard.
    keyboard: tuple[tuple[Button, ...], ...] = field(default_factory=tuple)
    parse_mode: str | None = None
    disable_web_page_preview: bool = True

    def to_reply_markup(self):  # noqa: ANN201 - telegram type, imported lazily
        if not self.keyboard:
            return None
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        rows = [
            [InlineKeyboardButton(b.text, callback_data=b.callback_data, url=b.url) for b in row]
            for row in self.keyboard
        ]
        return InlineKeyboardMarkup(rows)
