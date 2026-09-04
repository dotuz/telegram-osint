"""Normalized public message.

Only publicly visible messages are stored. Private conversations are never
retrieved or persisted. ``text`` is retained for search and IOC extraction;
media is referenced by metadata only.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin, UUIDPrimaryKey


class Message(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "message"

    # Source container: a telegram_channel / telegram_group (EntityType value + id).
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str] = mapped_column(String(36), nullable=False)

    # Native message id within that container.
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    author_account_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    author_username: Mapped[str | None] = mapped_column(String(64), nullable=True)

    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    reply_to_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    forwarded_from: Mapped[str | None] = mapped_column(String(255), nullable=True)

    views: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Extracted structured bits, JSON text (portable). Populated by normalizers.
    urls_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    usernames_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    entities_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Where this message can be viewed publicly (e.g. https://t.me/<chan>/<id>).
    source_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    __table_args__ = (
        UniqueConstraint("source_type", "source_id", "message_id", name="uq_message_source_msgid"),
        Index("ix_message_source", "source_type", "source_id"),
        Index("ix_message_message_id", "message_id"),
        Index("ix_message_author_account_id", "author_account_id"),
        Index("ix_message_posted_at", "posted_at"),
    )
