"""Investigation: the top-level aggregate of the Telegram public-OSINT product.

A user supplies a Telegram ``@username`` or numeric id; one ``Investigation``
row tracks the whole run (queue -> workers -> observations -> correlation ->
report). It is **scoped to ``user_id``** (BOLA guard) and owns its
``InvestigationObservation`` rows (CASCADE).

Nothing here claims private-account data. Every observation is a *public*
observation with an ``observation_type`` (AUTHOR / MENTION / REPLY / REFERENCE
/ UNKNOWN) that is assigned once and never auto-upgraded.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin, UUIDPrimaryKey
from database.types import InvestigationStatus


class Investigation(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "investigation"

    user_id: Mapped[str] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    # Human-facing id, e.g. "INV-000123".
    public_id: Mapped[str] = mapped_column(String(16), nullable=False)

    target: Mapped[str] = mapped_column(String(255), nullable=False)  # as supplied
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)  # TargetKind value
    target_normalized: Mapped[str] = mapped_column(String(255), nullable=False)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=InvestigationStatus.QUEUED.value
    )
    job_id: Mapped[str | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), nullable=True
    )
    report_id: Mapped[str | None] = mapped_column(
        ForeignKey("report.id", ondelete="SET NULL"), nullable=True
    )

    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0-100 overall
    # JSON: {"counts": {...}, "narrative": "...", "limitations": [...]}
    summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_investigation_user_id", "user_id"),
        Index("ix_investigation_public_id", "public_id", unique=True),
        Index("ix_investigation_target_normalized", "target_normalized"),
        Index("ix_investigation_status", "status"),
        Index("ix_investigation_created_at", "created_at"),
    )


class InvestigationObservation(Base, UUIDPrimaryKey):
    __tablename__ = "investigation_observation"

    investigation_id: Mapped[str] = mapped_column(
        ForeignKey("investigation.id", ondelete="CASCADE"), nullable=False
    )
    observation_type: Mapped[str] = mapped_column(String(16), nullable=False)  # ObservationType
    resource_kind: Mapped[str] = mapped_column(
        String(16), nullable=False
    )  # ObservationResourceKind
    resource_ref: Mapped[str] = mapped_column(
        String(255), nullable=False
    )  # username / title / host
    resource_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    message_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    source: Mapped[str] = mapped_column(String(32), nullable=False)  # SourceType value
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    evidence_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_investigation_observation_investigation_id", "investigation_id"),
        Index("ix_investigation_observation_type", "observation_type"),
        Index("ix_investigation_observation_observed_at", "observed_at"),
    )
