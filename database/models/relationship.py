"""Directed edge in the intelligence graph.

Connects any two entities (``entity_type`` + ``entity_id`` pairs). Repeated
observation of the same edge bumps ``last_seen`` and ``observation_count`` while
preserving ``first_seen`` -- it never creates a duplicate row.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin, UUIDPrimaryKey, utcnow
from database.types import CONFIDENCE_MAX, CONFIDENCE_MIN


class Relationship(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "relationship"

    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str] = mapped_column(String(36), nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str] = mapped_column(String(36), nullable=False)
    rel_type: Mapped[str] = mapped_column(String(48), nullable=False)  # RelationshipType value

    confidence: Mapped[int] = mapped_column(nullable=False, default=50)
    observation_count: Mapped[int] = mapped_column(nullable=False, default=1)

    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    # Representative evidence for the edge; full evidence is queried via the graph.
    evidence_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            f"confidence >= {CONFIDENCE_MIN} and confidence <= {CONFIDENCE_MAX}",
            name="confidence_range",
        ),
        UniqueConstraint(
            "source_type",
            "source_id",
            "target_type",
            "target_id",
            "rel_type",
            name="uq_relationship_edge",
        ),
        Index("ix_relationship_source", "source_type", "source_id"),
        Index("ix_relationship_target", "target_type", "target_id"),
        Index("ix_relationship_rel_type", "rel_type"),
        Index("ix_relationship_last_seen", "last_seen"),
    )
