"""Background job record.

Long-running OSINT collection never runs inside a Telegram handler or an HTTP
request. Handlers create a :class:`Job` row, enqueue it, and return immediately.
Workers transition the state machine and record progress.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin, new_uuid


class JobState(enum.StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    @property
    def is_terminal(self) -> bool:
        return self in {JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED}


class Job(Base, TimestampMixin):
    __tablename__ = "job"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)

    # e.g. "username_osint", "user_search", "report_generate", "watch_poll"
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default=JobState.PENDING.value)

    # Who requested it (Telegram numeric id or dashboard user id); never a secret.
    requested_by: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # JSON-serialised request parameters and result summary (portable across PG/sqlite).
    params_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "state in ('PENDING','RUNNING','COMPLETED','FAILED','CANCELLED')",
            name="state_valid",
        ),
        CheckConstraint("progress >= 0 and progress <= 100", name="progress_range"),
        Index("ix_job_state_kind", "state", "kind"),
        Index("ix_job_requested_by", "requested_by"),
        Index("ix_job_created_at", "created_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Job {self.id} {self.kind} {self.state} {self.progress}%>"
