import pytest

from apps.bot.router import ALL_COMMANDS, get_command, help_lines, public_command_menu
from apps.bot.views import (
    START_BODY,
    START_TITLE,
    render_help,
    render_start,
    render_stub,
    render_unknown_command,
)

pytestmark = pytest.mark.unit


def test_render_start_has_title_body_and_menu():
    msg = render_start(first_name="Ann")
    assert START_TITLE in msg.text
    assert START_BODY in msg.text
    assert "Ann" in msg.text
    # 5 rows x 2 buttons in the main menu.
    assert len(msg.keyboard) == 5
    assert all(len(row) == 2 for row in msg.keyboard)


def test_start_never_asks_for_credentials():
    import re

    text = render_start().text.lower()
    # whole-word check: "footprint"/"presence" etc. must not trip the "otp" term
    for forbidden in ("password", "login code", "otp", "session", "token", "phone number"):
        assert not re.search(rf"\b{re.escape(forbidden)}\b", text), forbidden


def test_render_help_hides_admin_commands_from_non_admin():
    non_admin = render_help(commands=help_lines(is_admin=False), is_admin=False).text
    admin = render_help(commands=help_lines(is_admin=True), is_admin=True).text
    assert "/users" not in non_admin
    assert "/users" in admin
    assert "/start" in non_admin


def test_help_lines_marks_unreleased_phases():
    lines = dict(help_lines(is_admin=True))
    assert "phase" in lines["settings"]  # phase 11, not shipped
    assert "phase" not in lines["start"]  # live
    assert "phase" not in lines["report"]  # phase 10, shipped


def test_render_stub_mentions_phase_and_usage():
    spec = get_command("username")
    msg = render_stub(feature=spec.summary, phase=spec.phase, usage=spec.usage)
    assert "phase 6" in msg.text
    assert "/username" in msg.text


def test_command_registry_is_consistent():
    names = [c.name for c in ALL_COMMANDS]
    assert len(names) == len(set(names)), "duplicate command names"
    for spec in ALL_COMMANDS:
        assert spec.usage.startswith("/")
    # Public menu excludes admin commands.
    assert "health" not in dict(public_command_menu())


def test_get_command_normalizes_slash_and_case():
    assert get_command("/START") is get_command("start")
    assert get_command("nope") is None


def test_render_unknown_command_points_to_help():
    assert "/help" in render_unknown_command().text
