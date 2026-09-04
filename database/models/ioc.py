"""Indicator of Compromise entity (shared, deduplicated).

IOCs are extracted from public content by ``intelligence/ioc`` (Phase 5) and
always reference the evidence they came from via ``relationship`` rows.
"""

from __future__ import annotations

from sqlalchemy import Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin, UUIDPrimaryKey


class IOC(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "ioc"

    ioc_type: Mapped[str] = mapped_column(String(24), nullable=False)  # IOCType value
    value: Mapped[str] = mapped_column(String(512), nullable=False)  # as observed
    value_normalized: Mapped[str] = mapped_column(String(512), nullable=False)

    # Optional denormalised link to the typed entity (domain/ip/url) it also is.
    linked_entity_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    linked_entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    times_observed: Mapped[int] = mapped_column(nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint("ioc_type", "value_normalized", name="uq_ioc_type_value"),
        Index("ix_ioc_value_normalized", "value_normalized"),
        Index("ix_ioc_type", "ioc_type"),
    )
