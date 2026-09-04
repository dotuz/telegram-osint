"""Command registry.

A single source of truth for: which commands exist, what they do, whether they
require admin, and which build phase makes them functional. Used to register
handlers, publish the Telegram command menu, and generate ``/help``.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Bump this as phases ship. A command is "live" once its phase has landed.
CURRENT_PHASE = 6


@dataclass(frozen=True)
class CommandSpec:
    name: str
    summary: str
    usage: str
    admin: bool = False
    # Build phase at which this command becomes functional.
    phase: int = 2
    # Long-running commands enqueue a background job instead of blocking (Phase 8).
    long_running: bool = False

    @property
    def live(self) -> bool:
        return self.phase <= CURRENT_PHASE


USER_COMMANDS: tuple[CommandSpec, ...] = (
    CommandSpec("start", "Show the main menu", "/start", phase=2),
    CommandSpec("help", "List available commands", "/help", phase=2),
    CommandSpec("whoami", "Show your Telegram ID and role", "/whoami", phase=2),
    CommandSpec(
        "search",
        "Search a Telegram user by @username or numeric ID",
        "/search @username | /search <telegram_id>",
        phase=4,
        long_running=True,
    ),
    CommandSpec("user", "Alias of /search", "/user @username", phase=4, long_running=True),
    CommandSpec(
        "username",
        "Username OSINT across public sources",
        "/username <username>",
        phase=6,
        long_running=True,
    ),
    CommandSpec("group", "Public group intelligence", "/group <group>", phase=4, long_running=True),
    CommandSpec(
        "channel", "Public channel intelligence", "/channel <channel>", phase=4, long_running=True
    ),
    CommandSpec(
        "message", "Search public messages", '/message "search terms"', phase=4, long_running=True
    ),
    CommandSpec("watch", "Add a target to your watchlist", "/watch @username", phase=9),
    CommandSpec("unwatch", "Remove a target from your watchlist", "/unwatch @username", phase=9),
    CommandSpec(
        "report",
        "Generate an intelligence report",
        "/report @username",
        phase=10,
        long_running=True,
    ),
    CommandSpec("history", "Your recent searches and reports", "/history", phase=4),
    CommandSpec("settings", "Your preferences", "/settings", phase=11),
)

ADMIN_COMMANDS: tuple[CommandSpec, ...] = (
    CommandSpec("admin", "Admin overview", "/admin", admin=True, phase=2),
    CommandSpec("health", "Backend health checks", "/health", admin=True, phase=2),
    CommandSpec("jobs", "List background jobs", "/jobs", admin=True, phase=8),
    CommandSpec("stats", "Usage statistics", "/stats", admin=True, phase=8),
    CommandSpec("audit", "Recent audit log entries", "/audit", admin=True, phase=12),
    CommandSpec("users", "Manage authorized users", "/users", admin=True, phase=12),
)

ALL_COMMANDS: tuple[CommandSpec, ...] = USER_COMMANDS + ADMIN_COMMANDS

_BY_NAME = {c.name: c for c in ALL_COMMANDS}


def get_command(name: str) -> CommandSpec | None:
    return _BY_NAME.get(name.lstrip("/").lower())


def help_lines(*, is_admin: bool) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for spec in ALL_COMMANDS:
        if spec.admin and not is_admin:
            continue
        tag = "" if spec.live else f" (phase {spec.phase})"
        out.append((spec.name, spec.summary + tag))
    return out


def public_command_menu() -> list[tuple[str, str]]:
    """(command, description) pairs for Telegram's non-admin command menu."""
    return [(c.name, c.summary) for c in USER_COMMANDS]
