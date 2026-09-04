"""Search and SearchResult: a user's query and its ranked hits.

Scoped to ``user_id``. Long searches run as jobs (Phase 8); ``job_id`` links to
the background job that populated the results.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin, UUIDPrimaryKey
from database.types import SearchKind, TaskStatus


class Search(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "search"

    user_id: Mapped[str] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    target_id: Mapped[str | None] = mapped_column(
        ForeignKey("target.id", ondelete="SET NULL"), nullable=True
    )

    kind: Mapped[str] = mapped_column(String(24), nullable=False, default=SearchKind.KEYWORD.value)
    query: Mapped[str] = mapped_column(String(1024), nullable=False)
    filters_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=TaskStatus.PENDING.value
    )
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    job_id: Mapped[str | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_search_user_id", "user_id"),
        Index("ix_search_target_id", "target_id"),
        Index("ix_search_created_at", "created_at"),
    )


class SearchResult(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "search_result"

    search_id: Mapped[str] = mapped_column(
        ForeignKey("search.id", ondelete="CASCADE"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)

    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    matched_terms_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    __table_args__ = (
        Index("ix_search_result_search_id", "search_id"),
        Index("ix_search_result_entity", "entity_type", "entity_id"),
    )
