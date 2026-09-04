"""Refresh token records (hashed, rotating).

The raw token is returned to the client once (cookie + body); only its SHA-256
hash is stored. On use it is revoked and a new one issued (`replaced_by`), so a
stolen-then-replayed token is detectable (a revoked token being presented =
theft signal, handled in Phase 12+ as needed).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin, UUIDPrimaryKey


class RefreshToken(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "refresh_token"

    user_id: Mapped[str] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_metadata: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        Index("uq_refresh_token_hash", "token_hash", unique=True),
        Index("ix_refresh_token_user_id", "user_id"),
    )

    @property
    def is_active(self) -> bool:
        from database.base import utcnow

        expires_at = self.expires_at
        if expires_at.tzinfo is None:  # SQLite round-trips aware -> naive
            expires_at = expires_at.replace(tzinfo=UTC)
        return self.revoked_at is None and expires_at > utcnow()
