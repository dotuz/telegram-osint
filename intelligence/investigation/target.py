"""Parse and validate an investigation target: a Telegram @username or numeric id.

``@ExampleUser``, ``exampleuser``, ``EXAMPLE``, ``t.me/exampleuser`` and
``https://t.me/exampleuser`` all resolve to the same canonical username target.
A run of digits resolves to a ``telegram_user_id`` target.

Rejected (with a user-facing message): empty input, control characters,
over-long input, non-Telegram URLs, and anything that is not a syntactically
valid Telegram username or id.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from database.normalize import normalize_username
from database.types import TargetKind

_MAX_RAW_LEN = 128
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
# Telegram usernames: 5-32 chars, [A-Za-z0-9_], must start with a letter,
# cannot end with an underscore, no double underscores (Telegram's own rule).
_USERNAME_RE = re.compile(r"^[a-z][a-z0-9_]{3,30}[a-z0-9]$")
_NON_TG_URL_RE = re.compile(r"^[a-z]+://", re.IGNORECASE)
_TG_HOST_RE = re.compile(r"^(https?://)?(t\.me|telegram\.me|telegram\.dog)/", re.IGNORECASE)


class InvalidTarget(ValueError):
    """The supplied target is not a usable Telegram username or id."""


@dataclass(frozen=True)
class ParsedTarget:
    raw: str
    target_type: str  # TargetKind.TELEGRAM_USER.value | TargetKind.TELEGRAM_ID.value
    canonical: str  # normalized username, or the digit string

    @property
    def is_username(self) -> bool:
        return self.target_type == TargetKind.TELEGRAM_USER.value

    @property
    def display(self) -> str:
        return f"@{self.canonical}" if self.is_username else self.canonical


def parse_target(raw: str | None) -> ParsedTarget:
    if raw is None:
        raise InvalidTarget("No target supplied. Send a Telegram @username or numeric id.")
    text = raw.strip()
    if not text:
        raise InvalidTarget("Empty target. Send a Telegram @username or numeric id.")
    if len(text) > _MAX_RAW_LEN:
        raise InvalidTarget("Target is too long.")
    if _CONTROL_RE.search(text):
        raise InvalidTarget("Target contains invalid characters.")

    # A non-Telegram URL is not a supported target.
    if _NON_TG_URL_RE.match(text) and not _TG_HOST_RE.match(text):
        raise InvalidTarget("Only Telegram usernames/ids or t.me links are supported.")

    bare = text.lstrip("@")
    # Numeric id?
    digits = bare
    if _TG_HOST_RE.match(text):
        digits = normalize_username(text)  # strips the t.me/ wrapper
    if digits.isdigit():
        if not (3 <= len(digits) <= 15) or int(digits) <= 0:
            raise InvalidTarget("Not a valid Telegram numeric id.")
        return ParsedTarget(raw=text, target_type=TargetKind.TELEGRAM_ID.value, canonical=digits)

    # For the username path, reject anything the (lossy) normalizer would have to
    # strip -- "bad name", "select * from users" etc. must NOT silently become a
    # username. Allow the bare handle or a t.me/<handle> link only.
    handle_src = normalize_username(text) if _TG_HOST_RE.match(text) else bare
    if not re.fullmatch(r"[A-Za-z0-9_]+", handle_src):
        raise InvalidTarget(
            "Not a valid Telegram username. Use letters, digits and underscores only."
        )

    canonical = normalize_username(text)
    if not _USERNAME_RE.match(canonical) or "__" in canonical:
        raise InvalidTarget(
            "Not a valid Telegram username. Usernames are 5-32 characters, "
            "letters/digits/underscores, and start with a letter."
        )
    return ParsedTarget(raw=text, target_type=TargetKind.TELEGRAM_USER.value, canonical=canonical)
