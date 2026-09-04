"""Phase-7 callback handler: ``intel:timeline:<id>`` / ``intel:graph:<id>``.

The buttons rendered by ``render_user_intel`` carry an entity id
(``telegram_account`` is assumed -- the only type that gets those buttons today).
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from apps.bot.adapter import reply
from apps.bot.auth import Principal
from apps.bot.guard import authorized
from apps.bot.intel_views import render_graph, render_timeline
from apps.bot.views import render_error
from database.session import session_scope
from database.types import EntityType
from intelligence.relationships import GraphService
from intelligence.timeline import TimelineService


@authorized(action="intel_view")
async def intel_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE, principal: Principal
) -> None:
    query = update.callback_query
    parts = (query.data or "").split(":") if query else []
    if len(parts) != 3:
        await reply(update, render_error())
        return

    _, view, entity_id = parts
    entity_type = EntityType.TELEGRAM_ACCOUNT.value

    with session_scope() as session:
        if view == "timeline":
            tl = TimelineService(session).for_entity(entity_type, entity_id).as_dict()
            root = f"{entity_type}:{entity_id[:8]}"
            await reply(
                update,
                render_timeline(root_label=root, by_year=tl["by_year"], truncated=tl["truncated"]),
            )
        elif view == "graph":
            g = GraphService(session).neighbourhood(entity_type, entity_id, depth=2).as_dict()
            await reply(
                update,
                render_graph(
                    root_label=g["root"],
                    nodes=g["nodes"],
                    edges=g["edges"],
                    truncated=g["truncated"],
                ),
            )
        elif view == "report":
            from apps.bot.views import render_stub

            await reply(update, render_stub(feature="Generate Report", phase=10, usage="/report"))
        else:
            await reply(update, render_error())
