"""Core handlers: /start, /help, /whoami, and main-menu navigation."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from apps.bot import audit
from apps.bot.adapter import reply
from apps.bot.auth import Principal
from apps.bot.guard import authorized
from apps.bot.router import get_command, help_lines
from apps.bot.views import (
    MENU_ACTION_TO_COMMAND,
    render_help,
    render_menu_home,
    render_start,
    render_stub,
    render_unknown_command,
    render_whoami,
)
from database.repositories import UserRepository
from database.session import session_scope
from database.types import Role


def _referrer_id(context: ContextTypes.DEFAULT_TYPE) -> int | None:
    args = getattr(context, "args", None) or []
    if args and args[0].startswith("ref_"):
        try:
            return int(args[0][len("ref_") :])
        except ValueError:
            return None
    return None


@authorized(action="start")
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE, principal: Principal) -> None:
    user = update.effective_user
    audit.record(actor=principal.actor, action="start")

    if principal.is_public:
        # Public tier: resolve/create the row so a referral (if any) is
        # captured at first contact -- it can only be recorded once.
        with session_scope() as session:
            repo = UserRepository(session)
            row, created = repo.get_or_create_for_telegram(principal.telegram_id, role=Role.USER)
            referrer = _referrer_id(context)
            if created and referrer is not None:
                repo.record_referral(row, inviter_telegram_id=referrer)

    await reply(update, render_start(first_name=user.first_name if user else None))


@authorized(action="help")
async def help_cmd(
    update: Update, context: ContextTypes.DEFAULT_TYPE, principal: Principal
) -> None:
    await reply(
        update,
        render_help(commands=help_lines(is_admin=principal.is_admin), is_admin=principal.is_admin),
    )


@authorized(action="whoami")
async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE, principal: Principal) -> None:
    await reply(update, render_whoami(telegram_id=principal.telegram_id, role=principal.role.value))


@authorized(action="menu")
async def menu_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE, principal: Principal
) -> None:
    """Handle ``menu:*`` inline-button presses."""
    query = update.callback_query
    action = (query.data or "").split(":", 1)[-1] if query else ""

    if action in ("home", ""):
        await reply(update, render_menu_home())
        return

    if action == "help":
        await reply(
            update,
            render_help(
                commands=help_lines(is_admin=principal.is_admin), is_admin=principal.is_admin
            ),
        )
        return

    command_name = MENU_ACTION_TO_COMMAND.get(action)
    spec = get_command(command_name) if command_name else None
    if spec is None:
        await reply(update, render_menu_home())
        return

    audit.record(actor=principal.actor, action="menu_select", resource=f"command:{spec.name}")
    await reply(
        update,
        render_stub(feature=spec.summary, phase=spec.phase, usage=spec.usage),
    )


@authorized(action="unknown")
async def unknown_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE, principal: Principal
) -> None:
    await reply(update, render_unknown_command())
