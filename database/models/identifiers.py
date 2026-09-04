"""Username and external-account entities (shared, deduplicated).

A ``Username`` is a handle observed on some platform. An ``ExternalAccount`` is a
concrete account profile on a non-Telegram public source (GitHub, Reddit, ...).

Two accounts sharing a username are **not** assumed to be the same person -- that
judgement lives in ``relationship`` rows with evidence and a confidence score.
"""

from __future__ import annotations

from sqlalchemy import Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin, UUIDPrimaryKey


class Username(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "username"

    # Platform this handle was seen on (SourceType value), or "generic".
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[str] = mapped_column(String(190), nullable=False)
    value_normalized: Mapped[str] = mapped_column(String(190), nullable=False)

    __table_args__ = (
        UniqueConstraint("platform", "value_normalized", name="uq_username_platform_value"),
        Index("ix_username_value_normalized", "value_normalized"),
    )


class ExternalAccount(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "external_account"

    platform: Mapped[str] = mapped_column(String(32), nullable=False)  # SourceType value
    # Stable identifier on that platform (login/slug/numeric id as string).
    identifier: Mapped[str] = mapped_column(String(190), nullable=False)
    identifier_normalized: Mapped[str] = mapped_column(String(190), nullable=False)

    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    profile_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    linked_website: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "platform", "identifier_normalized", name="uq_external_account_platform_identifier"
        ),
        Index("ix_external_account_identifier_normalized", "identifier_normalized"),
    )
