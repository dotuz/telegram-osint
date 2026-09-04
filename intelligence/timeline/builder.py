"""Chronological timeline construction.

Events are derived from what was actually observed -- evidence timestamps,
message post times, relationship first-seen, account first-observed -- each
carrying its source and (where available) an evidence id. Sorted oldest-first
and grouped by year for rendering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from database.models.evidence import Evidence
from database.models.identifiers import ExternalAccount
from database.models.message import Message
from database.models.relationship import Relationship
from database.models.telegram import TelegramAccount, TelegramChannel, TelegramGroup
from database.types import EntityType

_MAX_EVENTS = 500


@dataclass
class TimelineEvent:
    when: datetime
    kind: str  # "evidence" | "message" | "relationship" | "account"
    title: str
    source: str | None = None
    entity_ref: str | None = None
    evidence_id: str | None = None

    def as_dict(self) -> dict:
        return {
            "when": self.when.isoformat(),
            "year": self.when.year,
            "kind": self.kind,
            "title": self.title,
            "source": self.source,
            "entity_ref": self.entity_ref,
            "evidence_id": self.evidence_id,
        }


@dataclass
class Timeline:
    root: str
    events: list[TimelineEvent] = field(default_factory=list)
    truncated: bool = False

    def by_year(self) -> dict[int, list[dict]]:
        out: dict[int, list[dict]] = {}
        for e in self.events:
            out.setdefault(e.when.year, []).append(e.as_dict())
        return out

    def as_dict(self) -> dict:
        return {
            "root": self.root,
            "truncated": self.truncated,
            "events": [e.as_dict() for e in self.events],
            "by_year": self.by_year(),
        }


class TimelineService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def for_entity(self, entity_type: str, entity_id: str) -> Timeline:
        return self._build(f"{entity_type}:{entity_id}", [(entity_type, entity_id)])

    def for_target(self, target_id: str) -> Timeline:
        from intelligence.relationships.graph import GraphService

        entities = [(EntityType.TARGET.value, target_id)]
        entities += GraphService(self.session).resolved_entities(target_id)
        return self._build(f"{EntityType.TARGET.value}:{target_id}", entities)

    # ------------------------------------------------------------------ internal
    def _build(self, root: str, entities: list[tuple[str, str]]) -> Timeline:
        events: list[TimelineEvent] = []
        for etype, eid in entities:
            events += self._evidence_events(etype, eid)
            events += self._relationship_events(etype, eid)
            if etype in (
                EntityType.TELEGRAM_CHANNEL.value,
                EntityType.TELEGRAM_GROUP.value,
            ):
                events += self._message_events(etype, eid)
            events += self._account_events(etype, eid)

        events = [e for e in events if e.when is not None]
        # SQLite round-trips tz-aware datetimes as naive; normalise so a mix of
        # sources (evidence, messages, relationships) is sortable.
        for e in events:
            if e.when.tzinfo is None:
                e.when = e.when.replace(tzinfo=UTC)
        events.sort(key=lambda e: e.when)
        truncated = len(events) > _MAX_EVENTS
        return Timeline(root=root, events=events[:_MAX_EVENTS], truncated=truncated)

    def _evidence_events(self, etype: str, eid: str) -> list[TimelineEvent]:
        rows = (
            self.session.execute(
                select(Evidence).where(Evidence.entity_type == etype, Evidence.entity_id == eid)
            )
            .scalars()
            .all()
        )
        out = []
        for ev in rows:
            when = ev.observed_at or ev.collected_at
            field_part = f" {ev.field}" if ev.field else ""
            out.append(
                TimelineEvent(
                    when=when,
                    kind="evidence",
                    title=f"Observed{field_part} via {ev.source}",
                    source=ev.source,
                    entity_ref=f"{etype}:{eid}",
                    evidence_id=ev.id,
                )
            )
        return out

    def _relationship_events(self, etype: str, eid: str) -> list[TimelineEvent]:
        rows = (
            self.session.execute(
                select(Relationship).where(
                    or_(
                        (Relationship.source_type == etype) & (Relationship.source_id == eid),
                        (Relationship.target_type == etype) & (Relationship.target_id == eid),
                    )
                )
            )
            .scalars()
            .all()
        )
        out = []
        for rel in rows:
            out.append(
                TimelineEvent(
                    when=rel.first_seen,
                    kind="relationship",
                    title=(
                        f"{rel.rel_type} "
                        f"({rel.source_type} -> {rel.target_type}, confidence {rel.confidence})"
                    ),
                    entity_ref=f"{etype}:{eid}",
                    evidence_id=rel.evidence_id,
                )
            )
        return out

    def _message_events(self, etype: str, eid: str) -> list[TimelineEvent]:
        rows = (
            self.session.execute(
                select(Message)
                .where(
                    Message.source_type == etype,
                    Message.source_id == eid,
                    Message.posted_at.is_not(None),
                )
                .order_by(Message.posted_at)
                .limit(_MAX_EVENTS)
            )
            .scalars()
            .all()
        )
        return [
            TimelineEvent(
                when=m.posted_at,
                kind="message",
                title=f"Public message #{m.message_id}" + (f": {m.text[:80]}" if m.text else ""),
                source="telegram",
                entity_ref=f"{EntityType.MESSAGE.value}:{m.id}",
                evidence_id=None,
            )
            for m in rows
            if m.posted_at is not None
        ]

    def _account_events(self, etype: str, eid: str) -> list[TimelineEvent]:
        out: list[TimelineEvent] = []
        if etype in (
            EntityType.TELEGRAM_ACCOUNT.value,
            EntityType.TELEGRAM_CHANNEL.value,
            EntityType.TELEGRAM_GROUP.value,
        ):
            model: Any = {
                EntityType.TELEGRAM_ACCOUNT.value: TelegramAccount,
                EntityType.TELEGRAM_CHANNEL.value: TelegramChannel,
                EntityType.TELEGRAM_GROUP.value: TelegramGroup,
            }[etype]
            obj = self.session.get(model, eid)
            if obj is not None and obj.first_observed_at is not None:
                out.append(
                    TimelineEvent(
                        when=obj.first_observed_at,
                        kind="account",
                        title="First observed on Telegram",
                        source="telegram",
                        entity_ref=f"{etype}:{eid}",
                    )
                )
        elif etype == EntityType.EXTERNAL_ACCOUNT.value:
            obj = self.session.get(ExternalAccount, eid)
            if obj is not None and obj.created_at is not None:
                out.append(
                    TimelineEvent(
                        when=obj.created_at,
                        kind="account",
                        title=f"External account record created ({obj.platform})",
                        source=obj.platform,
                        entity_ref=f"{etype}:{eid}",
                    )
                )
        return out
