"""Public Telegram entities: accounts, groups, channels.

These are **shared, deduplicated** records of publicly observable Telegram
objects. Presence of a row asserts nothing about private membership or content.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin, UUIDPrimaryKey


class TelegramAccount(Base, UUIDPrimaryKey, TimestampMixin):
    """A Telegram user account, keyed by numeric id where known."""

    __tablename__ = "telegram_account"

    telegram_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    username_normalized: Mapped[str | None] = mapped_column(String(64), nullable=True)

    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_bot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_scam: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Public profile photo: store a content hash / reference, never the raw image here.
    photo_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)

    first_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("telegram_id", name="uq_telegram_account_telegram_id"),
        Index("ix_telegram_account_username_normalized", "username_normalized"),
        Index("ix_telegram_account_telegram_id", "telegram_id"),
    )


class _TelegramGroupChannelBase(UUIDPrimaryKey, TimestampMixin):
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    username_normalized: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    participants_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    first_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TelegramGroup(Base, _TelegramGroupChannelBase):
    __tablename__ = "telegram_group"

    __table_args__ = (
        UniqueConstraint("telegram_id", name="uq_telegram_group_telegram_id"),
        Index("ix_telegram_group_username_normalized", "username_normalized"),
        Index("ix_telegram_group_telegram_id", "telegram_id"),
    )


class TelegramChannel(Base, _TelegramGroupChannelBase):
    __tablename__ = "telegram_channel"

    posting_frequency_per_day: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (
        UniqueConstraint("telegram_id", name="uq_telegram_channel_telegram_id"),
        Index("ix_telegram_channel_username_normalized", "username_normalized"),
        Index("ix_telegram_channel_telegram_id", "telegram_id"),
    )
