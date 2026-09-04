"""Inline keyboard builders."""

from __future__ import annotations

from apps.bot.responses import Button

# callback_data prefix for main-menu navigation.
MENU = "menu"


def _cb(action: str) -> str:
    return f"{MENU}:{action}"


MAIN_MENU: tuple[tuple[Button, ...], ...] = (
    (Button("🔎 Search User", _cb("search_user")), Button("👤 Username OSINT", _cb("username"))),
    (Button("💬 Search Messages", _cb("messages")), Button("👥 Group Intelligence", _cb("group"))),
    (Button("📢 Channel Intelligence", _cb("channel")), Button("⭐ Watchlist", _cb("watchlist"))),
    (Button("📄 Generate Report", _cb("report")), Button("🕓 History", _cb("history"))),
    (Button("⚙️ Settings", _cb("settings")), Button("❓ Help", _cb("help"))),
)

BACK_TO_MENU: tuple[tuple[Button, ...], ...] = ((Button("⬅️ Back to menu", _cb("home")),),)
