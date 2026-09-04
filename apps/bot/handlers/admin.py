"""Admin handlers: /admin, /health (Phase 2), /jobs, /stats (Phase 8)."""

from __future__ import annotations

from sqlalchemy import func, select, text
from telegram import Update
from telegram.ext import ContextTypes

from apps.bot import audit
from apps.bot.adapter import reply
from apps.bot.auth import Principal
from apps.bot.guard import authorized
from apps.bot.intel_views import render_jobs, render_stats
from apps.bot.responses import BotMessage
from apps.bot.router import ADMIN_COMMANDS
from apps.bot.views import render_health
from database.models import Job, Search, Target, User
from database.repositories import JobRepository
from database.session import get_engine, session_scope
from security.config import get_settings


@authorized(admin=True, action="admin")
async def admin_overview(
    update: Update, context: ContextTypes.DEFAULT_TYPE, principal: Principal
) -> None:
    lines = ["*Admin*", "", "Admin commands:"]
    for spec in ADMIN_COMMANDS:
        tag = "" if spec.live else f" _(phase {spec.phase})_"
        lines.append(f"/{spec.name} — {spec.summary}{tag}")
    audit.record(actor=principal.actor, action="admin_overview")
    await reply(update, BotMessage(text="\n".join(lines), parse_mode="Markdown"))


@authorized(admin=True, action="health")
async def health_cmd(
    update: Update, context: ContextTypes.DEFAULT_TYPE, principal: Principal
) -> None:
    settings = get_settings()
    checks: dict[str, str] = {}

    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:  # noqa: BLE001
        checks["database"] = "error"

    try:
        import redis

        redis.from_url(settings.redis_url, socket_connect_timeout=2).ping()
        checks["redis"] = "ok"
    except Exception:  # noqa: BLE001
        checks["redis"] = "error"

    audit.record(actor=principal.actor, action="health_check", metadata=checks)
    await reply(update, render_health(checks=checks, env=settings.app_env))


@authorized(admin=True, action="jobs")
async def jobs_cmd(
    update: Update, context: ContextTypes.DEFAULT_TYPE, principal: Principal
) -> None:
    with session_scope() as session:
        rows = [
            {
                "id": j.id,
                "kind": j.kind,
                "state": j.state,
                "progress": j.progress,
                "retry_count": j.retry_count,
            }
            for j in JobRepository(session).recent(limit=15)
        ]
    audit.record(actor=principal.actor, action="jobs_list")
    await reply(update, render_jobs(rows))


@authorized(admin=True, action="stats")
async def stats_cmd(
    update: Update, context: ContextTypes.DEFAULT_TYPE, principal: Principal
) -> None:
    with session_scope() as session:
        by_state: dict[str, int] = {
            str(state): int(count)
            for state, count in session.execute(
                select(Job.state, func.count()).group_by(Job.state)
            ).all()
        }
        stats: dict[str, object] = {
            "jobs_by_state": by_state,
            "users": session.execute(select(func.count()).select_from(User)).scalar() or 0,
            "targets": session.execute(select(func.count()).select_from(Target)).scalar() or 0,
            "searches": session.execute(select(func.count()).select_from(Search)).scalar() or 0,
        }
    try:
        from workers.queue import get_default_queue

        stats["queue_depth"] = get_default_queue().size()
    except Exception:  # noqa: BLE001
        stats["queue_depth"] = "n/a"

    audit.record(actor=principal.actor, action="stats")
    await reply(update, render_stats(stats))
