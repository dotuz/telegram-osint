"""Phase-10 handler: /report @username -> async report generation."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from apps.bot import audit
from apps.bot.adapter import reply
from apps.bot.auth import Principal, Role
from apps.bot.guard import authorized
from apps.bot.intel_views import render_job_queued, render_usage
from apps.bot.jobs import submit_job
from apps.bot.responses import BotMessage
from database.normalize import normalize_username
from database.repositories import ReportRepository, TargetRepository, UserRepository
from database.session import session_scope
from database.types import TargetKind
from intelligence.entity_resolution import TargetResolver


def _args(context: ContextTypes.DEFAULT_TYPE) -> list[str]:
    return list(getattr(context, "args", None) or [])


def _queue(context: ContextTypes.DEFAULT_TYPE):  # noqa: ANN202
    app = getattr(context, "application", None)
    return (getattr(app, "bot_data", None) or {}).get("job_queue")


@authorized(action="report", quota=True)
async def report_cmd(
    update: Update, context: ContextTypes.DEFAULT_TYPE, principal: Principal
) -> None:
    args = _args(context)
    if not args:
        await reply(update, render_usage("report", "/report @username"))
        return

    if args[0].lower() == "list":
        await _list(update, principal)
        return

    handle = normalize_username(args[0])
    with session_scope() as session:
        user, _ = UserRepository(session).get_or_create_for_telegram(
            principal.telegram_id,
            role=Role.ADMIN if principal.is_admin else Role.ANALYST,
        )
        target, _ = TargetRepository(session, user.id).get_or_create(
            kind=TargetKind.USERNAME, value=handle
        )
        session.flush()
        TargetResolver(session).resolve(target)
        report = ReportRepository(session, user.id).create(
            title=f"OSINT report — @{handle}", target_id=target.id
        )
        session.commit()
        report_id = report.id

    chat = update.effective_chat
    submit_job(
        kind="report_generate",
        params={
            "report_id": report_id,
            "chat_id": chat.id if chat is not None else None,
            "formats": ["json", "html", "pdf"],
        },
        requested_by=principal.actor,
        queue=_queue(context),
    )
    audit.record(
        actor=principal.actor,
        action="report",
        resource=f"report:{report_id}",
        metadata={"target": handle},
    )
    await reply(update, render_job_queued(report_id, f"report for @{handle}"))


async def _list(update: Update, principal: Principal) -> None:
    with session_scope() as session:
        user, _ = UserRepository(session).get_or_create_for_telegram(
            principal.telegram_id,
            role=Role.ADMIN if principal.is_admin else Role.ANALYST,
        )
        rows = ReportRepository(session, user.id).list(limit=15)
        lines = ["*Your reports*", ""]
        for r in rows:
            lines.append(
                f"• `{r.id[:8]}` {r.title} — {r.status}"
                + (f" · {r.generated_at:%Y-%m-%d %H:%M}" if r.generated_at else "")
            )
        text = "\n".join(lines) if rows else "No reports yet. Try /report @username."
    await reply(update, BotMessage(text=text, parse_mode="Markdown"))
