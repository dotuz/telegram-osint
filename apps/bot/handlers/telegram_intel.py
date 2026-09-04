"""Phase-4 handlers: /search, /user, /group, /channel, /message, /history.

Collection runs inline with a bounded call for now; Phase 8 moves it to a
background job (the service is the same one the worker will call). Handlers stay
non-blocking for other users because python-telegram-bot dispatches concurrently.
"""

from __future__ import annotations

import contextlib

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from apps.bot import audit
from apps.bot.adapter import reply
from apps.bot.auth import Principal, Role
from apps.bot.guard import authorized
from apps.bot.intel_views import (
    render_chat_intel,
    render_history,
    render_message_hits,
    render_source_unavailable,
    render_usage,
    render_user_intel,
)
from apps.bot.router import get_command
from collectors.common.interfaces import Collector
from database.repositories import UserRepository
from database.session import session_scope
from intelligence.search import TelegramIntelService


def _query(context: ContextTypes.DEFAULT_TYPE) -> str:
    return " ".join(getattr(context, "args", None) or []).strip()


def _collector_override(context: ContextTypes.DEFAULT_TYPE) -> Collector | None:
    app = getattr(context, "application", None)
    bot_data = getattr(app, "bot_data", None) or {}
    return bot_data.get("telegram_collector")


def _role_for(principal: Principal) -> Role:
    return Role.ADMIN if principal.is_admin else Role.ANALYST


async def _resolve_user_id(principal: Principal) -> str:
    with session_scope() as session:
        user, _ = UserRepository(session).get_or_create_for_telegram(
            principal.telegram_id, role=_role_for(principal)
        )
        return user.id


async def _typing(update: Update) -> None:
    chat = update.effective_chat
    if chat is not None:
        with contextlib.suppress(Exception):
            await chat.send_action(ChatAction.TYPING)


async def _run_entity(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    principal: Principal,
    *,
    command: str,
    method: str,
) -> None:
    query = _query(context)
    spec = get_command(command)
    if not query:
        await reply(update, render_usage(command, spec.usage if spec else f"/{command} <value>"))
        return

    await _typing(update)
    user_id = await _resolve_user_id(principal)
    with session_scope() as session:
        svc = TelegramIntelService(session, user_id, collector=_collector_override(context))
        result = await getattr(svc, method)(query)
        audit.record(
            actor=principal.actor,
            action=command,
            resource=f"{result.entity_type}:{result.entity_id}" if result.entity_id else None,
            metadata={"query": query, "found": result.found},
        )
        payload = {
            "query": query,
            "found": result.found,
            "summary": dict(result.summary),
            "notes": list(result.notes),
            "entity_id": result.entity_id,
            "kind": result.kind,
            "source_available": result.source_available,
        }

    if not payload["source_available"] and not payload["found"]:
        await reply(update, render_source_unavailable())
        return

    if command in ("search", "user"):
        await reply(
            update,
            render_user_intel(
                **{k: payload[k] for k in ("query", "found", "summary", "notes", "entity_id")}
            ),
        )
    else:
        await reply(
            update,
            render_chat_intel(
                kind=payload["kind"],
                query=query,
                found=payload["found"],
                summary=payload["summary"],
                notes=payload["notes"],
            ),
        )


@authorized(action="search")
async def search_user(
    update: Update, context: ContextTypes.DEFAULT_TYPE, principal: Principal
) -> None:
    await _run_entity(update, context, principal, command="search", method="search_user")


@authorized(action="user")
async def user_alias(
    update: Update, context: ContextTypes.DEFAULT_TYPE, principal: Principal
) -> None:
    await _run_entity(update, context, principal, command="user", method="search_user")


@authorized(action="group")
async def group_intel(
    update: Update, context: ContextTypes.DEFAULT_TYPE, principal: Principal
) -> None:
    await _run_entity(update, context, principal, command="group", method="group_intel")


@authorized(action="channel")
async def channel_intel(
    update: Update, context: ContextTypes.DEFAULT_TYPE, principal: Principal
) -> None:
    await _run_entity(update, context, principal, command="channel", method="channel_intel")


@authorized(action="message")
async def message_search(
    update: Update, context: ContextTypes.DEFAULT_TYPE, principal: Principal
) -> None:
    query = _query(context).strip().strip('"')
    spec = get_command("message")
    if not query:
        await reply(update, render_usage("message", spec.usage if spec else '/message "terms"'))
        return

    await _typing(update)
    user_id = await _resolve_user_id(principal)
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


@authorized(action="history")
async def history(update: Update, context: ContextTypes.DEFAULT_TYPE, principal: Principal) -> None:
    user_id = await _resolve_user_id(principal)
    with session_scope() as session:
        rows = TelegramIntelService(session, user_id).history(limit=15)
    await reply(update, render_history(rows))
