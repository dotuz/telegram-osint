"""Admin handlers that are live in Phase 2: /admin, /health."""

from __future__ import annotations

from sqlalchemy import text
from telegram import Update
from telegram.ext import ContextTypes

from apps.bot import audit
from apps.bot.adapter import reply
from apps.bot.auth import Principal
from apps.bot.guard import authorized
from apps.bot.responses import BotMessage
from apps.bot.router import ADMIN_COMMANDS
from apps.bot.views import render_health
from database.session import get_engine
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
