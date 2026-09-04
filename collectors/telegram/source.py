"""Telegram data sources.

A *source* is a thin, swappable adapter over some way of reading **public**
Telegram data. The collector depends only on the :class:`TelegramSource`
protocol, so it is fully testable offline.

Sources, best-to-worst by coverage:
  * ``OperatorTelegramSource`` -- an explicitly authorized operator account
    (Telethon/Pyrogram). Only used when ``TELEGRAM_OPERATOR_*`` is configured
    and the library is installed. Not bundled; raises if unavailable.
  * ``BotApiTelegramSource`` -- the Bot API. Can read public chat metadata; it
    cannot read channel/group history it is not a member/admin of, and cannot
    search messages. Honest about those limits (returns empty + a note).
  * ``NullTelegramSource`` -- nothing configured; everything returns empty.
  * ``FakeTelegramSource`` -- in-memory, for local demos and tests only.

No source ever handles sessions, tokens, OTPs, passwords, or private content.
"""

from __future__ import annotations

import contextlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from security.logging import get_logger

_log = get_logger("collectors.telegram.source")


@dataclass(frozen=True)
class PublicProfile:
    telegram_id: int | None = None
    username: str | None = None
    display_name: str | None = None
    bio: str | None = None
    is_bot: bool = False
    is_verified: bool = False
    is_scam: bool = False
    photo_reference: str | None = None
    reference: str | None = None  # e.g. https://t.me/<username>


@dataclass(frozen=True)
class PublicChat:
    chat_type: str = "channel"  # "group" | "supergroup" | "channel"
    telegram_id: int | None = None
    username: str | None = None
    title: str | None = None
    description: str | None = None
    participants_count: int | None = None
    is_public: bool = True
    reference: str | None = None


@dataclass(frozen=True)
class PublicMessage:
    message_id: int
    chat_username: str | None = None
    chat_id: int | None = None
    author_id: int | None = None
    author_username: str | None = None
    text: str | None = None
    posted_at: datetime | None = None
    reply_to_message_id: int | None = None
    forwarded_from: str | None = None
    views: int | None = None
    reference: str | None = None


@dataclass(frozen=True)
class SourceResult:
    """Wraps a source call so partial failures carry a note instead of raising."""

    ok: bool = True
    note: str | None = None


@runtime_checkable
class TelegramSource(Protocol):
    name: str

    async def available(self) -> bool: ...

    async def get_profile(self, username: str) -> PublicProfile | None: ...

    async def get_chat(self, username: str) -> PublicChat | None: ...

    async def get_messages(
        self, chat: str, *, limit: int = 50, since: datetime | None = None
    ) -> Sequence[PublicMessage]: ...

    async def search_messages(self, query: str, *, limit: int = 50) -> Sequence[PublicMessage]: ...


class NullTelegramSource:
    name = "null"

    async def available(self) -> bool:
        return False

    async def get_profile(self, username: str) -> PublicProfile | None:
        return None

    async def get_chat(self, username: str) -> PublicChat | None:
        return None

    async def get_messages(
        self, chat: str, *, limit: int = 50, since: datetime | None = None
    ) -> Sequence[PublicMessage]:
        return []

    async def search_messages(self, query: str, *, limit: int = 50) -> Sequence[PublicMessage]:
        return []


@dataclass
class FakeTelegramSource:
    """In-memory source for demos/tests. Seed with public data you already have."""

    name: str = "fake"
    profiles: dict[str, PublicProfile] = field(default_factory=dict)
    chats: dict[str, PublicChat] = field(default_factory=dict)
    messages: dict[str, list[PublicMessage]] = field(default_factory=dict)

    async def available(self) -> bool:
        return True

    @staticmethod
    def _key(username: str) -> str:
        return username.strip().lstrip("@").lower()

    async def get_profile(self, username: str) -> PublicProfile | None:
        return self.profiles.get(self._key(username))

    async def get_chat(self, username: str) -> PublicChat | None:
        return self.chats.get(self._key(username))

    async def get_messages(
        self, chat: str, *, limit: int = 50, since: datetime | None = None
    ) -> Sequence[PublicMessage]:
        msgs = self.messages.get(self._key(chat), [])
        if since is not None:
            msgs = [m for m in msgs if m.posted_at is None or m.posted_at >= since]
        return list(msgs)[:limit]

    async def search_messages(self, query: str, *, limit: int = 50) -> Sequence[PublicMessage]:
        q = query.strip().lower()
        hits = [
            m for msgs in self.messages.values() for m in msgs if m.text and q in m.text.lower()
        ]
        return hits[:limit]


class BotApiTelegramSource:
    """Reads public chat metadata via the Telegram Bot API.

    Limits (returned as empty results, never fabricated): the Bot API cannot
    read message history for chats the bot is not in, and cannot search.
    """

    name = "bot_api"

    def __init__(self, bot: object) -> None:  # telegram.Bot, kept loose for testability
        self._bot = bot

    async def available(self) -> bool:
        return self._bot is not None

    async def _get_chat(self, username: str):  # noqa: ANN202
        handle = username.strip()
        if not handle.startswith("@") and not handle.lstrip("-").isdigit():
            handle = f"@{handle}"
        return await self._bot.get_chat(handle)  # type: ignore[attr-defined]

    async def get_profile(self, username: str) -> PublicProfile | None:
        try:
            chat = await self._get_chat(username)
        except Exception as exc:  # noqa: BLE001
            _log.info("bot_api_get_profile_failed", error=str(exc))
            return None
        if getattr(chat, "type", None) != "private":
            return None
        uname = getattr(chat, "username", None)
        return PublicProfile(
            telegram_id=getattr(chat, "id", None),
            username=uname,
            display_name=" ".join(
                p
                for p in [getattr(chat, "first_name", None), getattr(chat, "last_name", None)]
                if p
            )
            or None,
            bio=getattr(chat, "bio", None),
            is_bot=bool(getattr(chat, "is_bot", False)),
            reference=f"https://t.me/{uname}" if uname else None,
        )

    async def get_chat(self, username: str) -> PublicChat | None:
        try:
            chat = await self._get_chat(username)
        except Exception as exc:  # noqa: BLE001
            _log.info("bot_api_get_chat_failed", error=str(exc))
            return None
        ctype = getattr(chat, "type", "channel")
        if ctype == "private":
            return None
        count = None
        with contextlib.suppress(Exception):
            count = await self._bot.get_chat_member_count(chat.id)  # type: ignore[attr-defined]
        uname = getattr(chat, "username", None)
        return PublicChat(
            chat_type=ctype,
            telegram_id=getattr(chat, "id", None),
            username=uname,
            title=getattr(chat, "title", None),
            description=getattr(chat, "description", None),
            participants_count=count,
            is_public=bool(uname),
            reference=f"https://t.me/{uname}" if uname else None,
        )

    async def get_messages(
        self, chat: str, *, limit: int = 50, since: datetime | None = None
    ) -> Sequence[PublicMessage]:
        # Not available via the Bot API for chats the bot isn't in.
        return []

    async def search_messages(self, query: str, *, limit: int = 50) -> Sequence[PublicMessage]:
        return []


class OperatorTelegramSource:
    """Placeholder for an explicitly authorized operator account.

    Wiring a real Telethon/Pyrogram client is deferred; until then this reports
    unavailable so the collector degrades to the Bot API / DB.
    """

    name = "operator"

    def __init__(self, *, api_id: str | None, api_hash: str | None, session: str | None) -> None:
        self._configured = bool(api_id and api_hash and session)

    async def available(self) -> bool:
        return False

    async def get_profile(self, username: str) -> PublicProfile | None:
        return None

    async def get_chat(self, username: str) -> PublicChat | None:
        return None

    async def get_messages(
        self, chat: str, *, limit: int = 50, since: datetime | None = None
    ) -> Sequence[PublicMessage]:
        return []

    async def search_messages(self, query: str, *, limit: int = 50) -> Sequence[PublicMessage]:
        return []


def build_source(settings: object | None = None) -> TelegramSource:
    """Pick the best available source from settings."""
    from security.config import get_settings

    s = settings or get_settings()

    if getattr(s, "telegram_operator_session", None):
        _log.info("telegram_operator_configured_but_not_wired")

    token = ""
    tok = getattr(s, "telegram_bot_token", None)
    if tok is not None:
        token = tok.get_secret_value() if hasattr(tok, "get_secret_value") else str(tok)

    if token:
        try:
            from telegram import Bot

            return BotApiTelegramSource(Bot(token))
        except Exception as exc:  # noqa: BLE001
            _log.warning("bot_api_source_init_failed", error=str(exc))

    return NullTelegramSource()
