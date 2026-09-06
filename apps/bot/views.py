"""Pure view functions: build :class:`BotMessage` objects from plain inputs.

No ``telegram.*`` imports, no I/O -> fully unit-testable.
"""

from __future__ import annotations

from apps.bot.keyboards import BACK_TO_MENU, MAIN_MENU
from apps.bot.responses import BotMessage, Button

START_TITLE = "Telegram Public OSINT Investigator"
START_BODY = (
    "Send /investigate @username (or a numeric Telegram ID) and I'll collect the "
    "target's *publicly observable* Telegram presence — public mentions, public "
    "messages, replies, references, a timeline, correlated entities and an "
    "evidence-backed report.\n\n"
    "_Public data only. This bot never touches private groups, private chats, or "
    "any account you do not control._"
)

# Generic, non-leaking failure text shown to users.
GENERIC_ERROR = "Something went wrong handling that request. Please try again later."
GENERIC_DENIED = (
    "You are not authorized to use this bot. If you believe this is a mistake, "
    "contact the operator."
)
SOURCE_UNAVAILABLE = "Collection failed. Source unavailable."
GENERIC_RATE_LIMITED = "You're sending commands too quickly. Please wait a moment and try again."


def render_start(*, first_name: str | None = None) -> BotMessage:
    greeting = f"Hi {first_name},\n\n" if first_name else ""
    text = (
        f"{greeting}*{START_TITLE}*\n\n"
        f"{START_BODY}\n\n"
        "Choose an action below, or send /help for the command list."
    )
    return BotMessage(text=text, keyboard=MAIN_MENU, parse_mode="Markdown")


def render_menu_home() -> BotMessage:
    return BotMessage(
        text=f"*{START_TITLE}*\n\nChoose an action:",
        keyboard=MAIN_MENU,
        parse_mode="Markdown",
    )


def render_help(*, commands: list[tuple[str, str]], is_admin: bool) -> BotMessage:
    lines = ["*Available commands*", ""]
    for name, summary in commands:
        lines.append(f"/{name} — {summary}")
    if is_admin:
        lines += ["", "_Admin commands are included above._"]
    lines += [
        "",
        "This platform only uses public data and Telegram Bot API data. "
        "It never handles passwords, login codes, or sessions.",
    ]
    return BotMessage(text="\n".join(lines), parse_mode="Markdown", keyboard=BACK_TO_MENU)


def render_stub(*, feature: str, phase: int, usage: str | None = None) -> BotMessage:
    body = [
        f"*{feature}* is not available yet.",
        f"It is scheduled for phase {phase} of the build.",
    ]
    if usage:
        body += ["", f"Planned usage:\n`{usage}`"]
    return BotMessage(text="\n".join(body), parse_mode="Markdown", keyboard=BACK_TO_MENU)


def render_denied() -> BotMessage:
    return BotMessage(text=GENERIC_DENIED)


def render_error() -> BotMessage:
    return BotMessage(text=GENERIC_ERROR)


def render_rate_limited() -> BotMessage:
    return BotMessage(text=GENERIC_RATE_LIMITED)


def render_quota_exceeded(
    *, used: int, limit: int, referrals: int, required_referrals: int, link: str | None
) -> BotMessage:
    remaining = max(0, required_referrals - referrals)
    lines = [
        f"🔒 Bepul limit tugadi ({used}/{limit} ta bepul OSINT amal ishlatildi).",
        "",
        "Cheklovsiz foydalanish uchun:",
        f"• {required_referrals} ta do'stingizni botga taklif qiling "
        f"(hozircha {referrals}/{required_referrals}, yana {remaining} kishi kerak)",
        "• Obuna: tez orada",
    ]
    if link:
        lines += ["", f"Taklif havolangiz:\n{link}"]
    return BotMessage(text="\n".join(lines), keyboard=BACK_TO_MENU)


def render_whoami(*, telegram_id: int, role: str) -> BotMessage:
    return BotMessage(
        text=f"*You*\n\nTelegram ID: `{telegram_id}`\nRole: `{role}`",
        parse_mode="Markdown",
        keyboard=BACK_TO_MENU,
    )


def render_health(*, checks: dict[str, str], env: str) -> BotMessage:
    icon = {"ok": "🟢", "error": "🔴"}
    lines = [f"*Health* (env: `{env}`)", ""]
    for name, status in checks.items():
        lines.append(f"{icon.get(status, '⚪')} {name}: {status}")
    return BotMessage(text="\n".join(lines), parse_mode="Markdown", keyboard=BACK_TO_MENU)


def render_unknown_command() -> BotMessage:
    return BotMessage(
        text="Unknown command. Send /help for the list of commands.",
        keyboard=BACK_TO_MENU,
    )


# Maps a main-menu callback action to the command it corresponds to.
MENU_ACTION_TO_COMMAND: dict[str, str] = {
    "search_user": "search",
    "username": "username",
    "messages": "message",
    "group": "group",
    "channel": "channel",
    "watchlist": "watch",
    "report": "report",
    "history": "history",
    "settings": "settings",
}


def menu_button_for(action: str) -> Button:  # pragma: no cover - convenience
    return Button(action, callback_data=f"menu:{action}")
