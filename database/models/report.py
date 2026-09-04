"""Report: an asynchronously generated intelligence dossier for a target.

Scoped to ``user_id``. The structured content is stored as JSON; rendered
artifacts (PDF/HTML/JSON files) are referenced by path/URI in
``artifacts_json``. Every material claim in ``content_json`` carries evidence
references produced by the intelligence engine.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKey
from database.types import TaskStatus


class Report(Base, UUIDPrimaryKey, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "report"

    user_id: Mapped[str] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    target_id: Mapped[str | None] = mapped_column(
        ForeignKey("target.id", ondelete="SET NULL"), nullable=True
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=TaskStatus.PENDING.value
    )
    job_id: Mapped[str | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), nullable=True
    )

    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON: {"pdf": "...", "html": "...", "json": "..."} of storage references.
    artifacts_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_report_user_id", "user_id"),
        Index("ix_report_target_id", "target_id"),
        Index("ix_report_status", "status"),
        Index("ix_report_created_at", "created_at"),
    )
