"""Phase-4/8 handlers: /search, /user, /group, /channel, /message, /history.

Collection (``/search``, ``/user``, ``/group``, ``/channel``) is enqueued as a
background job (Phase 8) -- the handler returns immediately and the worker
delivers the result to the chat. ``/message`` (DB-only search) and ``/history``
stay synchronous.
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from apps.bot import audit
from apps.bot.adapter import reply
from apps.bot.auth import Principal, Role
from apps.bot.guard import authorized
from apps.bot.intel_views import (
    render_history,
    render_job_queued,
    render_message_hits,
    render_usage,
)
from apps.bot.jobs import cancel_job, find_job_id, submit_job
from apps.bot.router import get_command
from collectors.common.interfaces import Collector
from database.repositories import UserRepository
from database.session import session_scope
from intelligence.search import TelegramIntelService

_COMMAND_TO_KIND = {
    "search": "telegram_user",
    "user": "telegram_user",
    "group": "telegram_group",
    "channel": "telegram_channel",
}


def _query(context: ContextTypes.DEFAULT_TYPE) -> str:
    return " ".join(getattr(context, "args", None) or []).strip()


def _bot_data(context: ContextTypes.DEFAULT_TYPE) -> dict:
    app = getattr(context, "application", None)
    return getattr(app, "bot_data", None) or {}


def _collector_override(context: ContextTypes.DEFAULT_TYPE) -> Collector | None:
    return _bot_data(context).get("telegram_collector")


def _role_for(principal: Principal) -> Role:
    return Role.ADMIN if principal.is_admin else Role.ANALYST


def _resolve_user_id(principal: Principal) -> str:
    with session_scope() as session:
        user, _ = UserRepository(session).get_or_create_for_telegram(
            principal.telegram_id, role=_role_for(principal)
        )
        return user.id


async def _enqueue(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    principal: Principal,
    *,
    command: str,
) -> None:
    query = _query(context)
    spec = get_command(command)
    if not query:
        await reply(update, render_usage(command, spec.usage if spec else f"/{command} <value>"))
        return

    user_id = _resolve_user_id(principal)
    chat = update.effective_chat
    job_id = submit_job(
        kind=_COMMAND_TO_KIND[command],
        params={
            "query": query,
            "user_id": user_id,
            "chat_id": chat.id if chat is not None else None,
        },
        requested_by=principal.actor,
        queue=_bot_data(context).get("job_queue"),
    )
    audit.record(
        actor=principal.actor,
        action=command,
        resource=f"job:{job_id}",
        metadata={"query": query},
    )
    await reply(update, render_job_queued(job_id, spec.summary if spec else command))


@authorized(action="search")
async def search_user(
    update: Update, context: ContextTypes.DEFAULT_TYPE, principal: Principal
) -> None:
    await _enqueue(update, context, principal, command="search")


@authorized(action="user")
async def user_alias(
    update: Update, context: ContextTypes.DEFAULT_TYPE, principal: Principal
) -> None:
    await _enqueue(update, context, principal, command="user")


@authorized(action="group")
async def group_intel(
    update: Update, context: ContextTypes.DEFAULT_TYPE, principal: Principal
) -> None:
    await _enqueue(update, context, principal, command="group")


@authorized(action="channel")
async def channel_intel(
    update: Update, context: ContextTypes.DEFAULT_TYPE, principal: Principal
) -> None:
    await _enqueue(update, context, principal, command="channel")


@authorized(action="message")
async def message_search(
    update: Update, context: ContextTypes.DEFAULT_TYPE, principal: Principal
) -> None:
    query = _query(context).strip().strip('"')
    spec = get_command("message")
    if not query:
        await reply(update, render_usage("message", spec.usage if spec else '/message "terms"'))
        return

    user_id = _resolve_user_id(principal)
    with session_scope() as session:
        svc = TelegramIntelService(session, user_id, collector=_collector_override(context))
        result = await svc.search_messages(query, limit=25)
        audit.record(
            actor=principal.actor,
            action="message",
            metadata={"query": query, "hits": len(result.items)},
        )
        items = list(result.items)
        notes = list(result.notes)

    await reply(update, render_message_hits(query=query, items=items, notes=notes))


@authorized(action="cancel")
async def cancel_cmd(
    update: Update, context: ContextTypes.DEFAULT_TYPE, principal: Principal
) -> None:
    from apps.bot.responses import BotMessage

    args = getattr(context, "args", None) or []
    if not args:
        await reply(update, render_usage("cancel", "/cancel <job-id>"))
        return
    job_id = find_job_id(
        args[0].strip(),
        requested_by=None if principal.is_admin else principal.actor,
    )
    if job_id is None:
        await reply(update, BotMessage(text="No matching job found (or it isn't yours)."))
        return
    ok = cancel_job(job_id)
    audit.record(
        actor=principal.actor,
        action="cancel",
        resource=f"job:{job_id}",
        result="success" if ok else "denied",
    )
    await reply(
        update,
        BotMessage(
            text=(
                f"🚫 Job `{job_id[:8]}` cancelled."
                if ok
                else f"Job `{job_id[:8]}` is already finished — nothing to cancel."
            ),
            parse_mode="Markdown",
        ),
    )


@authorized(action="history")
async def history(update: Update, context: ContextTypes.DEFAULT_TYPE, principal: Principal) -> None:
    user_id = _resolve_user_id(principal)
    with session_scope() as session:
        rows = TelegramIntelService(session, user_id).history(limit=15)
    await reply(update, render_history(rows))
