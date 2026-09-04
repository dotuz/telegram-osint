"""Phase-6/8 handler: /username <handle> -> enqueue a username-OSINT job."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from apps.bot import audit
from apps.bot.adapter import reply
from apps.bot.auth import Principal, Role
from apps.bot.guard import authorized
from apps.bot.intel_views import render_job_queued, render_usage
from apps.bot.jobs import submit_job
from apps.bot.router import get_command
from database.repositories import UserRepository
from database.session import session_scope


def _query(context: ContextTypes.DEFAULT_TYPE) -> str:
    return " ".join(getattr(context, "args", None) or []).strip()


@authorized(action="username")
async def username_osint(
    update: Update, context: ContextTypes.DEFAULT_TYPE, principal: Principal
) -> None:
    handle = _query(context)
    if not handle:
        spec = get_command("username")
        await reply(update, render_usage("username", spec.usage if spec else "/username <handle>"))
        return

    with session_scope() as session:
        user, _ = UserRepository(session).get_or_create_for_telegram(
            principal.telegram_id,
            role=Role.ADMIN if principal.is_admin else Role.ANALYST,
        )
        user_id = user.id

    app = getattr(context, "application", None)
    bot_data = getattr(app, "bot_data", None) or {}
    chat = update.effective_chat
    job_id = submit_job(
        kind="username_osint",
        params={
            "query": handle,
            "user_id": user_id,
            "chat_id": chat.id if chat is not None else None,
        },
        requested_by=principal.actor,
        queue=bot_data.get("job_queue"),
    )
    audit.record(
        actor=principal.actor,
        action="username",
        resource=f"job:{job_id}",
        metadata={"query": handle},
    )
    await reply(update, render_job_queued(job_id, "username OSINT"))
