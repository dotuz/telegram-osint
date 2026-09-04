"""Public Telegram content collectors (Bot API + optionally authorized operator account)."""

from collectors.telegram.collector import (
    KIND_CHANNEL,
    KIND_GROUP,
    KIND_MESSAGE_SEARCH,
    KIND_USER,
    TelegramPublicCollector,
)
from collectors.telegram.source import (
    BotApiTelegramSource,
    FakeTelegramSource,
    NullTelegramSource,
    PublicChat,
    PublicMessage,
    PublicProfile,
    TelegramSource,
    build_source,
)

__all__ = [
    "BotApiTelegramSource",
    "FakeTelegramSource",
    "KIND_CHANNEL",
    "KIND_GROUP",
    "KIND_MESSAGE_SEARCH",
    "KIND_USER",
    "NullTelegramSource",
    "PublicChat",
    "PublicMessage",
    "PublicProfile",
    "TelegramPublicCollector",
    "TelegramSource",
    "build_source",
]
