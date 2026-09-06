"""Classify a public message/observation by how it relates to the target.

Mandatory distinction (spec section 11): a MENTION is never silently promoted
to AUTHOR. Authorship requires the observation's own author field to match the
target; everything weaker is MENTION / REPLY / REFERENCE / UNKNOWN.
"""

from __future__ import annotations

import re

from database.normalize import normalize_username
from database.types import ObservationType
from intelligence.investigation.target import ParsedTarget

_MENTION_RE = re.compile(r"(?<![\w@])@([A-Za-z][A-Za-z0-9_]{3,31})")
_TME_RE = re.compile(r"(?:https?://)?t\.me/([A-Za-z][A-Za-z0-9_]{3,31})", re.IGNORECASE)


def _mentions_username(text: str | None, username: str) -> bool:
    if not text:
        return False
    handles = {m.lower() for m in _MENTION_RE.findall(text)}
    handles |= {normalize_username(m) for m in _TME_RE.findall(text)}
    return username in handles


def _plain_reference(text: str | None, username: str) -> bool:
    if not text:
        return False
    return re.search(rf"(?<![\w@]){re.escape(username)}(?![\w])", text, re.IGNORECASE) is not None


def classify_observation(
    *,
    target: ParsedTarget,
    author_username: str | None = None,
    author_id: int | None = None,
    text: str | None = None,
    is_reply: bool = False,
    reply_to_author: str | None = None,
) -> tuple[ObservationType, int]:
    """Return ``(observation_type, confidence 0-100)``."""
    if target.is_username:
        tgt = target.canonical
        if author_username and normalize_username(author_username) == tgt:
            return ObservationType.AUTHOR, 92
        if is_reply and (
            (reply_to_author and normalize_username(reply_to_author) == tgt)
            or _mentions_username(text, tgt)
        ):
            return ObservationType.REPLY, 70
        if _mentions_username(text, tgt):
            return ObservationType.MENTION, 80
        if _plain_reference(text, tgt):
            return ObservationType.REFERENCE, 55
        return ObservationType.UNKNOWN, 30

    # numeric telegram id target
    try:
        tid = int(target.canonical)
    except ValueError:
        return ObservationType.UNKNOWN, 20
    if author_id is not None and author_id == tid:
        return ObservationType.AUTHOR, 92
    if text and target.canonical in text:
        return ObservationType.REFERENCE, 45
    return ObservationType.UNKNOWN, 25
