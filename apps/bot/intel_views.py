"""Pure view functions for Phase-4 Telegram intelligence results.

Kept separate from ``views.py`` to keep files small. No ``telegram.*``, no I/O.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from apps.bot.keyboards import BACK_TO_MENU
from apps.bot.responses import BotMessage, Button

_MAX_ITEMS = 10


def _labelled(summary: Mapping[str, object], keys: Sequence[tuple[str, str]]) -> list[str]:
    lines = []
    for key, label in keys:
        if summary.get(key) not in (None, ""):
            lines.append(f"{label}: {summary[key]}")
    return lines


def render_usage(command: str, usage: str) -> BotMessage:
    return BotMessage(
        text=f"Usage:\n`{usage}`",
        parse_mode="Markdown",
        keyboard=BACK_TO_MENU,
    )


def render_source_unavailable() -> BotMessage:
    return BotMessage(
        text=(
            "No public Telegram source is configured, so live collection is off. "
            "Showing anything already in the database.\n\n"
            "_The operator can enable the Bot API or an authorized account._"
        ),
        parse_mode="Markdown",
        keyboard=BACK_TO_MENU,
    )


def render_user_intel(
    *,
    query: str,
    found: bool,
    summary: Mapping[str, object],
    notes: Sequence[str],
    entity_id: str | None,
) -> BotMessage:
    if not found:
        body = [f"*User:* `{query}`", "", "No public data found for this identifier."]
        body += [f"_{n}_" for n in notes]
        return BotMessage(text="\n".join(body), parse_mode="Markdown", keyboard=BACK_TO_MENU)

    lines = ["*TARGET*", ""]
    lines += _labelled(
        summary,
        [
            ("display_name", "Name"),
            ("username", "Username"),
            ("telegram_id", "Telegram ID"),
            ("bio", "Bio"),
            ("is_verified", "Verified"),
            ("is_scam", "Flagged scam"),
            ("evidence_count", "Evidence items"),
        ],
    )
    lines += [
        "",
        "_Only public profile data is shown. Private groups/chats are not "
        "accessible from a Telegram ID alone._",
    ]
    for n in notes:
        lines.append(f"_{n}_")

    buttons: tuple[tuple[Button, ...], ...] = ()
    if entity_id:
        buttons = (
            (
                Button("View Timeline", callback_data=f"intel:timeline:{entity_id}"),
                Button("View Graph", callback_data=f"intel:graph:{entity_id}"),
            ),
            (Button("Generate Report", callback_data=f"intel:report:{entity_id}"),),
        ) + BACK_TO_MENU
    return BotMessage(
        text="\n".join(lines), parse_mode="Markdown", keyboard=buttons or BACK_TO_MENU
    )


def render_chat_intel(
    *, kind: str, query: str, found: bool, summary: Mapping[str, object], notes: Sequence[str]
) -> BotMessage:
    heading = "CHANNEL" if kind == "telegram_channel" else "GROUP"
    if not found:
        body = [f"*{heading}:* `{query}`", "", "No public data available for this chat."]
        body += [f"_{n}_" for n in notes]
        return BotMessage(text="\n".join(body), parse_mode="Markdown", keyboard=BACK_TO_MENU)

    lines = [f"*{heading}*", ""]
    lines += _labelled(
        summary,
        [
            ("title", "Title"),
            ("username", "Username"),
            ("telegram_id", "Telegram ID"),
            ("description", "Description"),
            ("participants_count", "Members"),
            ("observed_messages", "Public messages collected"),
            ("evidence_count", "Evidence items"),
        ],
    )
    for n in notes:
        lines.append(f"\n_{n}_")
    return BotMessage(text="\n".join(lines), parse_mode="Markdown", keyboard=BACK_TO_MENU)


def render_message_hits(
    *, query: str, items: Sequence[Mapping[str, object]], notes: Sequence[str], page: int = 1
) -> BotMessage:
    total = len(items)
    if total == 0:
        body = [f"*Message search:* `{query}`", "", "No matching public messages."]
        body += [f"_{n}_" for n in notes]
        return BotMessage(text="\n".join(body), parse_mode="Markdown", keyboard=BACK_TO_MENU)

    shown = list(items)[:_MAX_ITEMS]
    lines = [f"*Message search:* `{query}`  ({total} hit{'s' if total != 1 else ''})", ""]
    for i, m in enumerate(shown, 1):
        text = str(m.get("text", "")).replace("\n", " ")
        if len(text) > 160:
            text = text[:157] + "..."
        meta = []
        if m.get("author_username"):
            meta.append(f"@{m['author_username']}")
        if m.get("posted_at"):
            meta.append(str(m["posted_at"])[:10])
        prefix = f"{i}. "
        lines.append(f"{prefix}{text}")
        if meta:
            lines.append(f"   _{' · '.join(meta)}_")
        if m.get("source_url"):
            lines.append(f"   {m['source_url']}")
    if total > _MAX_ITEMS:
        lines.append(f"\n_Showing {_MAX_ITEMS} of {total}._")
    return BotMessage(text="\n".join(lines), parse_mode="Markdown", keyboard=BACK_TO_MENU)


def render_history(rows: Sequence[Mapping[str, object]]) -> BotMessage:
    if not rows:
        return BotMessage(
            text="No searches yet. Try /search, /group, /channel or /message.",
            keyboard=BACK_TO_MENU,
        )
    lines = ["*Recent searches*", ""]
    for r in rows:
        when = str(r.get("created_at", ""))[:16].replace("T", " ")
        count = r.get("result_count", 0)
        lines.append(f"• `{r.get('query')}` — {r.get('kind')} · {count} result(s) · {when}")
    return BotMessage(text="\n".join(lines), parse_mode="Markdown", keyboard=BACK_TO_MENU)
