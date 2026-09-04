"""Watchlist entry: a user's standing request to monitor a public target.

Scoped to ``user_id``. Only public sources are polled. ``last_seen_marker``
stores an opaque per-source cursor (e.g. the last message id) so repeated polls
don't re-notify.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin, UUIDPrimaryKey
from database.types import TargetKind


class Watchlist(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "watchlist"

    user_id: Mapped[str] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    target_id: Mapped[str | None] = mapped_column(
        ForeignKey("target.id", ondelete="CASCADE"), nullable=True
    )

    kind: Mapped[str] = mapped_column(String(24), nullable=False, default=TargetKind.USERNAME.value)
    value: Mapped[str] = mapped_column(String(512), nullable=False)
    value_normalized: Mapped[str] = mapped_column(String(512), nullable=False)

    # JSON list of SourceType values to monitor; null = all supported public sources.
    sources_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_marker: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "user_id", "kind", "value_normalized", name="uq_watchlist_user_kind_value"
        ),
        Index("ix_watchlist_user_id", "user_id"),
        Index("ix_watchlist_active", "is_active"),
    )
