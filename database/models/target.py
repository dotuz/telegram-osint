"""Target: the subject of an investigation, owned by one user.

Scoped to ``user_id``. A target is an investigation handle; the actual observed
data hangs off the shared graph and is associated via ``relationship`` rows
(e.g. ``TARGET_IS_ACCOUNT``, ``TARGET_HAS_USERNAME``).
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKey
from database.types import TargetKind


class Target(Base, UUIDPrimaryKey, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "target"

    user_id: Mapped[str] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False)

    kind: Mapped[str] = mapped_column(String(24), nullable=False, default=TargetKind.GENERIC.value)
    value: Mapped[str] = mapped_column(String(512), nullable=False)  # as entered
    value_normalized: Mapped[str] = mapped_column(String(512), nullable=False)

    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "kind", "value_normalized", name="uq_target_user_kind_value"),
        Index("ix_target_user_id", "user_id"),
        Index("ix_target_value_normalized", "value_normalized"),
    )
