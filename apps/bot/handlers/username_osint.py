"""Phase-6 handler: /username <handle> -> multi-source username OSINT."""

from __future__ import annotations

import contextlib

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from apps.bot import audit
from apps.bot.adapter import reply
from apps.bot.auth import Principal
from apps.bot.guard import authorized
from apps.bot.intel_views import render_source_unavailable, render_usage, render_username_osint
from apps.bot.router import get_command
from database.repositories import UserRepository
from database.session import session_scope
from database.types import Role
from intelligence.username_osint import UsernameOsintService


def _query(context: ContextTypes.DEFAULT_TYPE) -> str:
    return " ".join(getattr(context, "args", None) or []).strip()


def _collector_override(context: ContextTypes.DEFAULT_TYPE):  # noqa: ANN202
    app = getattr(context, "application", None)
    return (getattr(app, "bot_data", None) or {}).get("username_collector")


@authorized(action="username")
async def username_osint(
    update: Update, context: ContextTypes.DEFAULT_TYPE, principal: Principal
) -> None:
    handle = _query(context)
    if not handle:
        spec = get_command("username")
        await reply(update, render_usage("username", spec.usage if spec else "/username <handle>"))
        return

    chat = update.effective_chat
    if chat is not None:
        with contextlib.suppress(Exception):
            await chat.send_action(ChatAction.TYPING)

    with session_scope() as session:
        user, _ = UserRepository(session).get_or_create_for_telegram(
            principal.telegram_id,
            role=Role.ADMIN if principal.is_admin else Role.ANALYST,
        )
        svc = UsernameOsintService(session, user.id, collector=_collector_override(context))
        result = await svc.run(handle)
        audit.record(
            actor=principal.actor,
            action="username",
            metadata={"query": handle, "sources_found": len(result.sources)},
        )
        username = result.username
        found = result.found
        notes = list(result.notes)
        disclaimer = result.disclaimer
        sources = [
            {
                "platform": s.platform,
                "url": s.url,
                "confidence": s.confidence,
                "evidence": s.evidence,
            }
            for s in result.sources
        ]

    if not found and any("no username-OSINT adapters" in n for n in notes):
        await reply(update, render_source_unavailable())
        return

    await reply(
        update,
        render_username_osint(
            username=username, found=found, sources=sources, notes=notes, disclaimer=disclaimer
        ),
    )
