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
            ("ioc_count", "IOCs extracted"),
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
        iocs = m.get("iocs")
        if isinstance(iocs, list) and iocs:
            shown_iocs = ", ".join(f"{d['ioc_type']}:{d['value']}" for d in iocs[:5])
            more = f" (+{len(iocs) - 5})" if len(iocs) > 5 else ""
            lines.append(f"   IOC: {shown_iocs}{more}")
        if m.get("source_url"):
            lines.append(f"   {m['source_url']}")
    if total > _MAX_ITEMS:
        lines.append(f"\n_Showing {_MAX_ITEMS} of {total}._")
    return BotMessage(text="\n".join(lines), parse_mode="Markdown", keyboard=BACK_TO_MENU)


def render_username_osint(
    *,
    username: str,
    found: bool,
    sources: Sequence[Mapping[str, object]],
    notes: Sequence[str],
    disclaimer: str,
) -> BotMessage:
    if not found:
        body = [f"*Username OSINT:* `{username}`", "", "No public accounts found for this handle."]
        body += [f"_{n}_" for n in notes]
        return BotMessage(text="\n".join(body), parse_mode="Markdown", keyboard=BACK_TO_MENU)

    lines = [f"*Username OSINT:* `{username}`", ""]
    for s in sources:
        raw_conf = s.get("confidence", 0)
        conf = int(raw_conf) if isinstance(raw_conf, int | float | str) else 0
        icon = "🟢" if conf >= 75 else "🟡" if conf >= 45 else "🟠" if conf >= 20 else "⚪"
        lines.append(f"{icon} *{s.get('platform')}* — {conf}% potential match")
        if s.get("url"):
            lines.append(f"   {s['url']}")
        raw_ev = s.get("evidence")
        ev = [e for e in raw_ev if isinstance(e, str)][:3] if isinstance(raw_ev, list) else []
        for e in ev:
            lines.append(f"   • {e}")
        lines.append("")

    lines.append(f"_{disclaimer}_")
    for n in notes:
        lines.append(f"_{n}_")
    return BotMessage(text="\n".join(lines), parse_mode="Markdown", keyboard=BACK_TO_MENU)


def render_watch_activity(*, target: str, activities: Sequence[Mapping[str, object]]) -> BotMessage:
    lines = ["*NEW PUBLIC ACTIVITY*", "", f"Target: `{target}`", ""]
    for a in activities:
        when = str(a.get("when") or "")[11:16] or "—"
        lines.append(f"Source: {a.get('source')}")
        lines.append(f"Time: {when}")
        lines.append(f"{a.get('detail')}")
        if a.get("reference"):
            lines.append(f"{a['reference']}")
        lines.append("")
    lines.append("_Only public activity is monitored._")
    return BotMessage(text="\n".join(lines).rstrip(), parse_mode="Markdown")


def render_watchlist(rows: Sequence[Mapping[str, object]]) -> BotMessage:
    if not rows:
        return BotMessage(
            text="Your watchlist is empty. Add one with `/watch @username`.",
            parse_mode="Markdown",
            keyboard=BACK_TO_MENU,
        )
    lines = ["*Watchlist*", ""]
    for r in rows:
        state = "active" if r.get("is_active") else "paused"
        checked = str(r.get("last_checked_at") or "never")[:16].replace("T", " ")
        lines.append(f"• `{r.get('value')}` — {state} · last check: {checked}")
    lines.append("")
    lines.append("_/unwatch <handle> to stop monitoring._")
    return BotMessage(text="\n".join(lines), parse_mode="Markdown", keyboard=BACK_TO_MENU)


def render_watch_added(*, value: str, count: int, limit: int) -> BotMessage:
    return BotMessage(
        text=(
            f"👁 Watching `{value}` for new public activity.\n\n"
            f"_{count}/{limit} watch slots used. I'll notify you here on new public messages "
            f"or newly discovered public accounts._"
        ),
        parse_mode="Markdown",
        keyboard=BACK_TO_MENU,
    )


def render_job_queued(job_id: str, what: str) -> BotMessage:
    return BotMessage(
        text=(
            f"⏳ *{what}* queued.\n\n"
            f"Job `{job_id[:8]}` is running in the background — I'll send the "
            f"results here when it finishes.\n\n"
            f"_Cancel with_ `/cancel {job_id[:8]}` _(admins: /jobs to inspect)._"
        ),
        parse_mode="Markdown",
        keyboard=BACK_TO_MENU,
    )


def render_jobs(rows: Sequence[Mapping[str, object]]) -> BotMessage:
    if not rows:
        return BotMessage(text="No jobs recorded.", keyboard=BACK_TO_MENU)
    icon = {
        "PENDING": "⏳",
        "RUNNING": "▶️",
        "COMPLETED": "✅",
        "FAILED": "❌",
        "CANCELLED": "🚫",
    }
    lines = ["*Recent jobs*", ""]
    for r in rows:
        state = str(r.get("state", ""))
        prog = r.get("progress", 0)
        lines.append(
            f"{icon.get(state, '•')} `{str(r.get('id'))[:8]}` {r.get('kind')} — "
            f"{state} {prog}%"
            + (f" (retry {r.get('retry_count')})" if r.get("retry_count") else "")
        )
    return BotMessage(text="\n".join(lines), parse_mode="Markdown", keyboard=BACK_TO_MENU)


def render_stats(stats: Mapping[str, object]) -> BotMessage:
    lines = ["*Usage statistics*", ""]
    by_state = stats.get("jobs_by_state", {})
    if isinstance(by_state, Mapping):
        lines.append("Jobs by state:")
        for k, v in by_state.items():
            lines.append(f"  {k}: {v}")
    lines.append("")
    lines.append(f"Users: {stats.get('users', 0)}")
    lines.append(f"Targets: {stats.get('targets', 0)}")
    lines.append(f"Searches: {stats.get('searches', 0)}")
    lines.append(f"Queue depth: {stats.get('queue_depth', 'n/a')}")
    return BotMessage(text="\n".join(lines), parse_mode="Markdown", keyboard=BACK_TO_MENU)


def render_timeline(
    *, root_label: str, by_year: Mapping[str, Sequence[Mapping[str, object]]], truncated: bool
) -> BotMessage:
    if not by_year:
        return BotMessage(
            text=f"*Timeline:* {root_label}\n\nNo dated events observed yet.",
            parse_mode="Markdown",
            keyboard=BACK_TO_MENU,
        )
    lines = [f"*Timeline:* {root_label}", ""]
    for year in sorted(by_year, key=str):
        lines.append(f"*{year}*")
        for ev in list(by_year[year])[:12]:
            when = str(ev.get("when", ""))[:10]
            lines.append(f"  {when} — {ev.get('title')}")
        lines.append("")
    if truncated:
        lines.append("_Timeline truncated._")
    return BotMessage(text="\n".join(lines), parse_mode="Markdown", keyboard=BACK_TO_MENU)


def render_graph(
    *,
    root_label: str,
    nodes: Sequence[Mapping[str, object]],
    edges: Sequence[Mapping[str, object]],
    truncated: bool,
) -> BotMessage:
    lines = [
        f"*Graph:* {root_label}",
        f"_{len(nodes)} node(s), {len(edges)} edge(s)_",
        "",
    ]
    for e in list(edges)[:20]:
        src = str(e.get("source", "")).split(":", 1)[0]
        tgt = str(e.get("target", "")).split(":", 1)[0]
        lines.append(f"  {src} —[{e.get('type')} · {e.get('confidence')}%]→ {tgt}")
    if truncated:
        lines.append("\n_Graph truncated at the node cap._")
    lines.append("\n_Open the dashboard for the interactive graph._")
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
