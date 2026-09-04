"""Relationship (graph edge) repository with observe-or-bump semantics."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from sqlalchemy import or_, select

from database.base import utcnow
from database.models.relationship import Relationship
from database.repositories.base import BaseRepository
from database.types import CONFIDENCE_MAX, CONFIDENCE_MIN, EntityType, RelationshipType


class RelationshipRepository(BaseRepository[Relationship]):
    model = Relationship

    def observe(
        self,
        *,
        source_type: EntityType | str,
        source_id: str,
        target_type: EntityType | str,
        target_id: str,
        rel_type: RelationshipType | str,
        confidence: int = 50,
        evidence_id: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> tuple[Relationship, bool]:
        """Create the edge, or bump ``last_seen`` / ``observation_count`` if it exists.

        ``confidence`` is kept at the maximum ever observed; ``first_seen`` is
        preserved.
        """
        st, tt = str(EntityType(source_type)), str(EntityType(target_type))
        rt = str(RelationshipType(rel_type))
        confidence = max(CONFIDENCE_MIN, min(CONFIDENCE_MAX, int(confidence)))

        edge, created = self._get_or_create(
            source_type=st,
            source_id=source_id,
            target_type=tt,
            target_id=target_id,
            rel_type=rt,
            defaults={
                "confidence": confidence,
                "evidence_id": evidence_id,
                "metadata_json": json.dumps(dict(metadata), default=str) if metadata else None,
            },
        )
        if not created:
            edge.last_seen = utcnow()
            edge.observation_count += 1
            edge.confidence = max(edge.confidence, confidence)
            if evidence_id and not edge.evidence_id:
                edge.evidence_id = evidence_id
        return edge, created

    def neighbours(
        self, entity_type: EntityType | str, entity_id: str, *, limit: int = 500
    ) -> Sequence[Relationship]:
        et = str(EntityType(entity_type))
        stmt = (
            select(Relationship)
            .where(
                or_(
                    (Relationship.source_type == et) & (Relationship.source_id == entity_id),
                    (Relationship.target_type == et) & (Relationship.target_id == entity_id),
                )
            )
            .order_by(Relationship.last_seen.desc())
            .limit(limit)
        )
        return self.session.execute(stmt).scalars().all()
