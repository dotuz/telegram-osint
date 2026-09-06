import pytest

from database.types import TargetKind
from intelligence.investigation import InvalidTarget, parse_target

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "raw",
    ["@ExampleUser", "exampleuser", "EXAMPLEUSER", "t.me/exampleuser", "https://t.me/ExampleUser"],
)
def test_username_variants_canonicalise_the_same(raw):
    p = parse_target(raw)
    assert p.target_type == TargetKind.TELEGRAM_USER.value
    assert p.canonical == "exampleuser"
    assert p.display == "@exampleuser"


def test_numeric_id_target():
    p = parse_target("123456789")
    assert p.target_type == TargetKind.TELEGRAM_ID.value
    assert p.canonical == "123456789"
    assert not p.is_username
    assert p.display == "123456789"


def test_numeric_id_via_tme_link():
    p = parse_target("https://t.me/123456789")
    assert p.target_type == TargetKind.TELEGRAM_ID.value


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "@",
        "a",  # too short
        "1ab",  # starts with a digit
        "bad name",  # space
        "user__name",  # double underscore
        "x" * 200,  # too long
        "http://example.com/profile",  # non-Telegram URL
        "select * from users",  # junk
        "\x00\x01evil",  # control chars
        "0",  # invalid id
        "-5",  # invalid id
    ],
)
def test_invalid_targets_are_rejected(bad):
    with pytest.raises(InvalidTarget):
        parse_target(bad)


def test_none_is_rejected():
    with pytest.raises(InvalidTarget):
        parse_target(None)
