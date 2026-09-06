"""``/investigate`` -- the primary command of the Telegram public-OSINT product.

``/investigate @username`` or ``/investigate 123456789`` creates an
Investigation, queues it, and returns the INV id. ``/investigate`` with no
argument prompts for the target; the next plain-text message is treated as the
target (see :func:`handle_target_text`, wired from a text MessageHandler).
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from apps.bot import audit
from apps.bot.adapter import reply
from apps.bot.auth import AccessDenied, Principal, Role, resolve_principal
from apps.bot.guard import authorized
from apps.bot.intel_views import render_investigation_started
from apps.bot.jobs import submit_job
from apps.bot.quota import check_and_consume, referral_link
from apps.bot.responses import BotMessage
from apps.bot.views import render_denied, render_quota_exceeded
from database.repositories import InvestigationRepository, UserRepository
from database.session import session_scope
from intelligence.investigation import InvalidTarget, parse_target

_AWAIT_KEY = "awaiting_investigate_target"


def _args_target(context: ContextTypes.DEFAULT_TYPE) -> str:
    return " ".join(getattr(context, "args", None) or []).strip()


async def _start(
    update: Update, context: ContextTypes.DEFAULT_TYPE, principal: Principal, raw: str
) -> None:
    try:
        parsed = parse_target(raw)
    except InvalidTarget as exc:
        await reply(update, BotMessage(text=f"⚠ {exc}"))
        return

    with session_scope() as session:
        user, _ = UserRepository(session).get_or_create_for_telegram(
            principal.telegram_id,
            role=Role.ADMIN if principal.is_admin else Role.ANALYST,
        )
        inv = InvestigationRepository(session, user.id).create(
            target=parsed.raw, target_normalized=parsed.canonical
        )
        session.commit()
        inv_id, public_id, user_id = inv.id, inv.public_id, user.id

    chat = update.effective_chat
    job_id = submit_job(
        kind="investigation",
        params={
            "investigation_id": inv_id,
            "user_id": user_id,
            "chat_id": chat.id if chat is not None else None,
        },
        requested_by=principal.actor,
        queue=(getattr(getattr(context, "application", None), "bot_data", None) or {}).get(
            "job_queue"
        ),
    )
    audit.record(
        actor=principal.actor,
        action="investigation_created",
        resource=f"investigation:{public_id}",
        metadata={"target": parsed.display, "job": job_id},
    )
    await reply(update, render_investigation_started(public_id, parsed.display))


@authorized(action="investigate", quota=True)
async def investigate_cmd(
    update: Update, context: ContextTypes.DEFAULT_TYPE, principal: Principal
) -> None:
    raw = _args_target(context)
    if not raw:
        if hasattr(context, "user_data") and context.user_data is not None:
            context.user_data[_AWAIT_KEY] = True
        await reply(
            update,
            BotMessage(text="Send a Telegram @username or numeric Telegram ID to investigate."),
        )
        return
    await _start(update, context, principal, raw)


async def handle_target_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Consume the next plain-text message after a bare ``/investigate``.

    Not wrapped in ``@authorized``: it must stay silent for un-awaited free
    text (and never consume quota / emit a denial for it). Auth + quota are
    checked inline, only once we know a target was actually submitted.
    """
    ud = getattr(context, "user_data", None)
    if not ud or not ud.pop(_AWAIT_KEY, False):
        return  # not awaiting a target -> ignore

    raw = (getattr(update.effective_message, "text", "") or "").strip()
    if not raw:
        return

    user = update.effective_user
    telegram_id = user.id if user else None
    try:
        principal = resolve_principal(telegram_id)
    except AccessDenied:
        await reply(update, render_denied())
        return

    if principal.is_public:
        status = check_and_consume(principal.telegram_id)
        if not status.allowed:
            bot_data = getattr(getattr(context, "application", None), "bot_data", None) or {}
            await reply(
                update,
                render_quota_exceeded(
                    used=status.used,
                    limit=status.limit,
                    referrals=status.referrals,
                    required_referrals=status.required_referrals,
                    link=referral_link(bot_data.get("bot_username"), principal.telegram_id),
                ),
            )
            return

    await _start(update, context, principal, raw)
