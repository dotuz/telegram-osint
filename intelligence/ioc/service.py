"""Read side: IOCs for a message, a container (channel/group), or recently seen."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models.evidence import Evidence
from database.models.ioc import IOC
from database.models.message import Message
from database.models.relationship import Relationship
from database.types import EntityType, RelationshipType

_IOC_EDGE_TYPES = (
    RelationshipType.MESSAGE_CONTAINS_IOC.value,
    RelationshipType.MESSAGE_CONTAINS_DOMAIN.value,
    RelationshipType.MESSAGE_CONTAINS_IP.value,
    RelationshipType.MESSAGE_CONTAINS_URL.value,
)


class IocService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def for_message(self, message_id: str) -> list[dict]:
        ioc_ids = self._ioc_ids_from_messages([message_id])
        return self._hydrate(ioc_ids)

    def for_container(
        self, container_type: str, container_id: str, *, limit: int = 500
    ) -> list[dict]:
        """IOCs across all messages we've collected for a channel/group."""
        msg_ids = list(
            self.session.execute(
                select(Message.id)
                .where(Message.source_type == container_type, Message.source_id == container_id)
                .limit(limit)
            )
            .scalars()
            .all()
        )
        return self._hydrate(self._ioc_ids_from_messages(msg_ids))

    def recent(self, *, limit: int = 50, ioc_type: str | None = None) -> list[dict]:
        stmt = select(IOC).order_by(IOC.created_at.desc()).limit(limit)
        if ioc_type:
            stmt = stmt.where(IOC.ioc_type == ioc_type)
        return [self._row(i) for i in self.session.execute(stmt).scalars().all()]

    # ------------------------------------------------------------------ internals
    def _ioc_ids_from_messages(self, message_ids: Sequence[str]) -> set[str]:
        if not message_ids:
            return set()
        rows = self.session.execute(
            select(Relationship.target_id, Relationship.target_type).where(
                Relationship.source_type == EntityType.MESSAGE.value,
                Relationship.source_id.in_(list(message_ids)),
                Relationship.rel_type.in_(_IOC_EDGE_TYPES),
            )
        ).all()
        ioc_ids = {tid for tid, ttype in rows if ttype == EntityType.IOC.value}
        # also resolve typed domain/ip/url targets back to their IOC row
        typed = [(tid, ttype) for tid, ttype in rows if ttype != EntityType.IOC.value]
        for tid, ttype in typed:
            hit = self.session.execute(
                select(IOC.id).where(IOC.linked_entity_type == ttype, IOC.linked_entity_id == tid)
            ).scalar_one_or_none()
            if hit:
                ioc_ids.add(hit)
        return ioc_ids

    def _hydrate(self, ioc_ids: set[str]) -> list[dict]:
        if not ioc_ids:
            return []
        iocs = self.session.execute(select(IOC).where(IOC.id.in_(list(ioc_ids)))).scalars().all()
        return sorted(
            (self._row(i) for i in iocs),
            key=lambda r: (r["ioc_type"], r["value"]),
        )

    def _row(self, ioc: IOC) -> dict:
        ev_count = self.session.execute(
            select(Evidence.id).where(
                Evidence.entity_type == EntityType.IOC.value, Evidence.entity_id == ioc.id
            )
        ).all()
        return {
            "id": ioc.id,
            "ioc_type": ioc.ioc_type,
            "value": ioc.value,
            "value_normalized": ioc.value_normalized,
            "times_observed": ioc.times_observed,
            "linked_entity_type": ioc.linked_entity_type,
            "linked_entity_id": ioc.linked_entity_id,
            "evidence_count": len(ev_count),
        }
