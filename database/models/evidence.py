"""Evidence: the immutable, source-referenced record behind every claim.

Rules (enforced by :func:`block_evidence_mutation` and the repository):
  * an ``Evidence`` row is **write-once** -- never updated, never soft-deleted;
  * if an observed value changes, insert a **new** row (a new observation);
  * every row carries ``source``, ``observed_at``/``collected_at``, ``confidence``,
    and a ``content_hash`` of the raw material.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    String,
    Text,
    UniqueConstraint,
    event,
    inspect,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from database.base import Base, UUIDPrimaryKey, utcnow
from database.types import CONFIDENCE_MAX, CONFIDENCE_MIN


class Evidence(Base, UUIDPrimaryKey):
    __tablename__ = "evidence"

    # What this evidence is about (EntityType value + entity id).
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)

    # Which attribute/claim it supports, e.g. "bio", "username", "membership".
    field: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Observed value as JSON text (string, number, object...).
    value_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    source: Mapped[str] = mapped_column(String(64), nullable=False)  # SourceType value
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(1024), nullable=True)  # URL/permalink

    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    extraction_method: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidence: Mapped[int] = mapped_column(nullable=False, default=50)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    __table_args__ = (
        CheckConstraint(
            f"confidence >= {CONFIDENCE_MIN} and confidence <= {CONFIDENCE_MAX}",
            name="confidence_range",
        ),
        UniqueConstraint(
            "entity_type",
            "entity_id",
            "field",
            "source",
            "content_hash",
            name="uq_evidence_observation",
        ),
        Index("ix_evidence_entity", "entity_type", "entity_id"),
        Index("ix_evidence_source", "source"),
        Index("ix_evidence_observed_at", "observed_at"),
        Index("ix_evidence_collected_at", "collected_at"),
        Index("ix_evidence_content_hash", "content_hash"),
    )


class EvidenceImmutableError(RuntimeError):
    """Raised when code attempts to modify or delete a persisted Evidence row."""


# The only sanctioned exception: an entity merge repoints ``entity_id`` from the
# dropped entity to the surviving one. Toggled by ``allow_evidence_repointing``.
_ALLOW_REPOINTING = False


@contextmanager
def allow_evidence_repointing() -> Iterator[None]:
    """Permit ``Evidence.entity_id`` reassignment for the duration of a merge."""
    global _ALLOW_REPOINTING
    prev = _ALLOW_REPOINTING
    _ALLOW_REPOINTING = True
    try:
        yield
    finally:
        _ALLOW_REPOINTING = prev


@event.listens_for(Session, "before_flush")
def block_evidence_mutation(session: Session, _flush_context: object, _instances: object) -> None:
    for obj in session.dirty:
        if not isinstance(obj, Evidence) or not session.is_modified(obj, include_collections=False):
            continue
        changed = {attr.key for attr in inspect(obj).attrs if attr.history.has_changes()}
        if _ALLOW_REPOINTING and changed <= {"entity_id", "entity_type"}:
            continue
        raise EvidenceImmutableError(
            f"Evidence {obj.id} is immutable; record a new observation instead."
        )
    for obj in session.deleted:
        if isinstance(obj, Evidence):
            raise EvidenceImmutableError(f"Evidence {obj.id} is immutable and cannot be deleted.")
