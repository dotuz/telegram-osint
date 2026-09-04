"""Evidence repository: append-only, deduplicating on the observation key."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime

from sqlalchemy import select

from database.models.evidence import Evidence
from database.normalize import content_hash as _content_hash
from database.repositories.base import BaseRepository
from database.types import CONFIDENCE_MAX, CONFIDENCE_MIN, EntityType


class EvidenceRepository(BaseRepository[Evidence]):
    model = Evidence

    def record(
        self,
        *,
        entity_type: EntityType | str,
        entity_id: str,
        source: str,
        source_type: str,
        field: str | None = None,
        value: object = None,
        reference: str | None = None,
        raw_content: str | None = None,
        content_hash: str | None = None,
        observed_at: datetime | None = None,
        extraction_method: str | None = None,
        confidence: int = 50,
        metadata: Mapping[str, object] | None = None,
    ) -> tuple[Evidence, bool]:
        """Insert a new observation, or return the identical one already stored."""
        etype = str(EntityType(entity_type))
        chash = content_hash or _content_hash(
            raw_content
            if raw_content is not None
            else json.dumps(value, default=str, sort_keys=True)
        )
        confidence = max(CONFIDENCE_MIN, min(CONFIDENCE_MAX, int(confidence)))

        stmt = select(Evidence).where(
            Evidence.entity_type == etype,
            Evidence.entity_id == entity_id,
            Evidence.field == field,
            Evidence.source == source,
            Evidence.content_hash == chash,
        )
        existing = self.session.execute(stmt).scalar_one_or_none()
        if existing is not None:
            return existing, False

        evidence, created = self._get_or_create(
            entity_type=etype,
            entity_id=entity_id,
            field=field,
            source=source,
            content_hash=chash,
            defaults={
                "source_type": source_type,
                "reference": reference,
                "value_json": None if value is None else json.dumps(value, default=str),
                "observed_at": observed_at,
                "extraction_method": extraction_method,
                "confidence": confidence,
                "metadata_json": json.dumps(dict(metadata), default=str) if metadata else None,
            },
        )
        return evidence, created

    def for_entity(
        self, entity_type: EntityType | str, entity_id: str, *, limit: int = 200
    ) -> Sequence[Evidence]:
        stmt = (
            select(Evidence)
            .where(
                Evidence.entity_type == str(EntityType(entity_type)),
                Evidence.entity_id == entity_id,
            )
            .order_by(Evidence.collected_at.desc())
            .limit(limit)
        )
        return self.session.execute(stmt).scalars().all()

    def latest_value(
        self, entity_type: EntityType | str, entity_id: str, field: str
    ) -> Evidence | None:
        stmt = (
            select(Evidence)
            .where(
                Evidence.entity_type == str(EntityType(entity_type)),
                Evidence.entity_id == entity_id,
                Evidence.field == field,
            )
            .order_by(Evidence.observed_at.desc().nullslast(), Evidence.collected_at.desc())
            .limit(1)
        )
        return self.session.execute(stmt).scalar_one_or_none()
