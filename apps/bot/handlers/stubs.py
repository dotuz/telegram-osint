"""Factory for not-yet-implemented commands.

Every command in the registry that isn't live yet gets a handler that explains
which phase delivers it and shows the planned usage -- so the command surface is
complete and discoverable from day one without fabricating functionality.
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from apps.bot import audit
from apps.bot.adapter import reply
from apps.bot.auth import Principal
from apps.bot.guard import authorized
from apps.bot.router import CommandSpec
from apps.bot.views import render_stub


def make_stub_handler(spec: CommandSpec):  # noqa: ANN201 - returns a PTB handler
    @authorized(admin=spec.admin, action=spec.name)
    async def handler(
        update: Update, context: ContextTypes.DEFAULT_TYPE, principal: Principal
    ) -> None:
        audit.record(actor=principal.actor, action=spec.name, resource=f"command:{spec.name}")
        await reply(update, render_stub(feature=spec.summary, phase=spec.phase, usage=spec.usage))

    handler.__name__ = f"stub_{spec.name}"
    return handler
