"""Platform user (dashboard / bot operator account).

A user owns a private workspace: their targets, searches, watchlists, and
reports are scoped to ``user_id`` and never visible to other users. The public
intelligence graph (accounts, domains, IOCs, evidence) is shared.

Authentication (password hashing, MFA, sessions) is wired in Phase 11/12; this
model just holds the identity and role.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKey
from database.types import Role


class User(Base, UUIDPrimaryKey, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "user"

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default=Role.ANALYST.value)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Set once auth lands; nullable until then.
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Optional link to a Telegram identity (numeric id) for bot<->dashboard mapping.
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    __table_args__ = (
        UniqueConstraint("email", name="uq_user_email"),
        Index("ix_user_telegram_user_id", "telegram_user_id"),
        Index("ix_user_role", "role"),
    )

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN.value
