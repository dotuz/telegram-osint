"""Phase-9 handlers: /watch, /unwatch, /watchlist."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from apps.bot import audit
from apps.bot.adapter import reply
from apps.bot.auth import Principal, Role
from apps.bot.guard import authorized
from apps.bot.intel_views import render_usage, render_watch_added, render_watchlist
from apps.bot.jobs import submit_job
from apps.bot.responses import BotMessage
from database.normalize import normalize_username
from database.repositories import TargetRepository, UserRepository, WatchlistRepository
from database.session import session_scope
from database.types import TargetKind
from intelligence.entity_resolution import TargetResolver
from security.config import get_settings


def _args(context: ContextTypes.DEFAULT_TYPE) -> list[str]:
    return list(getattr(context, "args", None) or [])


def _queue(context: ContextTypes.DEFAULT_TYPE):  # noqa: ANN202
    app = getattr(context, "application", None)
    return (getattr(app, "bot_data", None) or {}).get("job_queue")


def _user_id(principal: Principal) -> str:
    with session_scope() as session:
        user, _ = UserRepository(session).get_or_create_for_telegram(
            principal.telegram_id,
            role=Role.ADMIN if principal.is_admin else Role.ANALYST,
        )
        return user.id


@authorized(action="watch")
async def watch_cmd(
    update: Update, context: ContextTypes.DEFAULT_TYPE, principal: Principal
) -> None:
    args = _args(context)
    if not args:
        await reply(update, render_usage("watch", "/watch @username [source1,source2]"))
        return

    handle = normalize_username(args[0])
    sources = args[1].split(",") if len(args) > 1 else None
    limit = get_settings().rate_limit_watch_max_targets
    user_id = _user_id(principal)

    with session_scope() as session:
        repo = WatchlistRepository(session, user_id)
        try:
            entry, _created = repo.add(
                kind=TargetKind.USERNAME, value=handle, sources=sources, max_targets=limit
            )
        except ValueError:
            await reply(
                update,
                BotMessage(
                    text=(f"Watchlist limit reached ({limit}). Use /unwatch to free a slot.")
                ),
            )
            audit.record(
                actor=principal.actor,
                action="watch",
                result="denied",
                metadata={"reason": "limit", "value": handle},
            )
            return

        target, _ = TargetRepository(session, user_id).get_or_create(
            kind=TargetKind.USERNAME, value=handle
        )
        session.flush()
        TargetResolver(session).resolve(target)
        count = repo.count_active()
        session.commit()
        watch_id = entry.id

    submit_job(
        kind="watch_poll",
        params={"watchlist_id": watch_id},
        requested_by=principal.actor,
        queue=_queue(context),
    )
    audit.record(
        actor=principal.actor,
        action="watch",
        resource=f"watchlist:{watch_id}",
        metadata={"value": handle},
    )
    await reply(update, render_watch_added(value=f"@{handle}", count=count, limit=limit))


@authorized(action="unwatch")
async def unwatch_cmd(
    update: Update, context: ContextTypes.DEFAULT_TYPE, principal: Principal
) -> None:
    args = _args(context)
    if not args:
        await reply(update, render_usage("unwatch", "/unwatch @username"))
        return
    handle = normalize_username(args[0])
    user_id = _user_id(principal)
    with session_scope() as session:
        ok = WatchlistRepository(session, user_id).remove(kind=TargetKind.USERNAME, value=handle)
        session.commit()
    audit.record(
        actor=principal.actor,
        action="unwatch",
        result="success" if ok else "denied",
        metadata={"value": handle},
    )
    await reply(
        update,
        BotMessage(
            text=(
                f"Stopped watching `@{handle}`." if ok else f"`@{handle}` isn't on your watchlist."
            ),
            parse_mode="Markdown",
        ),
    )


@authorized(action="watchlist")
async def watchlist_cmd(
    update: Update, context: ContextTypes.DEFAULT_TYPE, principal: Principal
) -> None:
    user_id = _user_id(principal)
    with session_scope() as session:
        rows = [
            {
                "value": w.value,
                "is_active": w.is_active,
                "last_checked_at": w.last_checked_at.isoformat() if w.last_checked_at else None,
            }
            for w in WatchlistRepository(session, user_id).list()
        ]
    await reply(update, render_watchlist(rows))
