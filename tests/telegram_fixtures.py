"""Shared Phase-4 helpers: a seeded FakeTelegramSource + collector."""

from __future__ import annotations

from datetime import UTC, datetime

from collectors.telegram import (
    FakeTelegramSource,
    PublicChat,
    PublicMessage,
    PublicProfile,
    TelegramPublicCollector,
)


def seeded_source() -> FakeTelegramSource:
    src = FakeTelegramSource()
    src.profiles["alice"] = PublicProfile(
        telegram_id=42,
        username="alice",
        display_name="Alice Anderson",
        bio="research | alice.example",
        is_verified=True,
        reference="https://t.me/alice",
    )
    src.chats["opsecnews"] = PublicChat(
        chat_type="channel",
        telegram_id=-1001,
        username="opsecnews",
        title="OpSec News",
        description="daily",
        participants_count=12345,
        reference="https://t.me/opsecnews",
    )
    src.chats["leakclub"] = PublicChat(
        chat_type="supergroup",
        telegram_id=-1002,
        username="leakclub",
        title="Leak Club",
        participants_count=87,
        reference="https://t.me/leakclub",
    )
    src.messages["opsecnews"] = [
        PublicMessage(
            message_id=10,
            chat_username="opsecnews",
            text="breach dump at https://evil.example and mirror http://evil2.example ping @leaker",
            posted_at=datetime(2026, 1, 2, tzinfo=UTC),
            views=999,
            reference="https://t.me/opsecnews/10",
        ),
        PublicMessage(
            message_id=11,
            chat_username="opsecnews",
            text="follow-up thread, no indicators",
            posted_at=datetime(2026, 1, 3, tzinfo=UTC),
            reference="https://t.me/opsecnews/11",
        ),
    ]
    return src


def fake_collector() -> TelegramPublicCollector:
    return TelegramPublicCollector(seeded_source())
