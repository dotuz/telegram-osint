"""Persist collector output into the shared intelligence graph.

``COLLECT -> NORMALIZE -> VALIDATE -> STORE`` : this module is the STORE step.
It upserts entities (deduplicated), appends immutable evidence, and observes
relationships. It is deliberately synchronous and transaction-agnostic -- the
caller owns the session/unit of work. Phase 8 calls it from a worker.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from collectors.common.interfaces import (
    CollectResult,
    EvidenceDraft,
    NormalizedRecord,
    RelationshipDraft,
)
from database.repositories import (
    DomainRepository,
    EvidenceRepository,
    ExternalAccountRepository,
    IOCRepository,
    IPRepository,
    MessageRepository,
    RelationshipRepository,
    TelegramAccountRepository,
    TelegramChannelRepository,
    TelegramGroupRepository,
    URLRepository,
    UsernameRepository,
)
from database.types import EntityType
from intelligence.ioc.enrich import IocEnricher
from security.logging import get_logger

_log = get_logger("intelligence.ingest")

# Attribute keys that are structural hints, not entity columns.
_HINT_KEYS = {"_container_ref"}
# Attribute keys that are part of the natural key / not directly settable.
_SKIP_ATTR = {"username_normalized", "name_normalized", "value_normalized"}


@dataclass
class IngestSummary:
    entities_created: int = 0
    entities_updated: int = 0
    evidence_recorded: int = 0
    relationships_observed: int = 0
    iocs_extracted: int = 0
    # ref -> (entity_type, entity_id)
    resolved: dict[str, tuple[str, str]] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)

    def entity_id(self, ref: str) -> str | None:
        hit = self.resolved.get(ref)
        return hit[1] if hit else None


class IngestionService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def ingest(self, result: CollectResult) -> IngestSummary:
        summary = IngestSummary()
        if not result.records:
            return summary

        # Two passes: containers/simple entities first, then messages (which need
        # their container resolved), then evidence, then relationships.
        deferred_messages: list[NormalizedRecord] = []
        for rec in result.records:
            if rec.entity_type == EntityType.MESSAGE.value:
                deferred_messages.append(rec)
                continue
            self._ingest_entity(rec, summary)

        for rec in deferred_messages:
            self._ingest_message(rec, summary)

        for rec in result.records:
            for draft in rec.evidence:
                self._record_evidence(draft, summary)

        for rel in result.relationships:
            self._observe_relationship(rel, summary)

        return summary

    # ------------------------------------------------------------------ entities
    def _ingest_entity(self, rec: NormalizedRecord, summary: IngestSummary) -> None:
        try:
            obj, created = self._dispatch_get_or_create(rec)
        except Exception as exc:  # noqa: BLE001 - one bad record must not sink the batch
            _log.warning(
                "ingest_entity_failed", ref=rec.ref, entity_type=rec.entity_type, error=str(exc)
            )
            summary.skipped.append(rec.ref)
            return

        self._apply_attributes(obj, rec.attributes)
        summary.resolved[rec.ref] = (rec.entity_type, obj.id)
        if created:
            summary.entities_created += 1
        else:
            summary.entities_updated += 1

        # Link domains / websites mentioned in a public bio or description.
        for field_name in ("bio", "description"):
            blurb = rec.attributes.get(field_name)
            if (
                isinstance(blurb, str)
                and blurb
                and rec.entity_type
                in (
                    EntityType.TELEGRAM_ACCOUNT.value,
                    EntityType.TELEGRAM_CHANNEL.value,
                    EntityType.TELEGRAM_GROUP.value,
                )
            ):
                es = IocEnricher(self.session).enrich_entity_text(
                    entity_type=rec.entity_type,
                    entity_id=obj.id,
                    text=blurb,
                    source=(rec.evidence[0].source if rec.evidence else "manual"),
                    source_type=(rec.evidence[0].source_type if rec.evidence else "telegram"),
                    reference=_str_or_none(rec.attributes.get("reference")),
                    field_name=field_name,
                )
                summary.iocs_extracted += es.iocs_created
                summary.relationships_observed += es.relationships_observed
                summary.evidence_recorded += es.evidence_recorded

    def _dispatch_get_or_create(self, rec: NormalizedRecord):  # noqa: ANN202
        nk = rec.natural_key
        et = rec.entity_type
        if et == EntityType.TELEGRAM_ACCOUNT.value:
            return TelegramAccountRepository(self.session).get_or_create(
                telegram_id=nk.get("telegram_id"),
                username=rec.attributes.get("username") or _username_from_nk(nk),
            )
        if et == EntityType.TELEGRAM_GROUP.value:
            return TelegramGroupRepository(self.session).get_or_create(
                telegram_id=nk.get("telegram_id"),
                username=rec.attributes.get("username") or _username_from_nk(nk),
            )
        if et == EntityType.TELEGRAM_CHANNEL.value:
            return TelegramChannelRepository(self.session).get_or_create(
                telegram_id=nk.get("telegram_id"),
                username=rec.attributes.get("username") or _username_from_nk(nk),
            )
        if et == EntityType.USERNAME.value:
            return UsernameRepository(self.session).get_or_create(
                nk.get("platform", "generic"), nk.get("value") or rec.attributes.get("value", "")
            )
        if et == EntityType.DOMAIN.value:
            return DomainRepository(self.session).get_or_create(
                nk.get("name") or rec.attributes.get("name", "")
            )
        if et == EntityType.URL.value:
            return URLRepository(self.session).get_or_create(
                nk.get("url") or rec.attributes.get("url", "")
            )
        if et == EntityType.IP.value:
            return IPRepository(self.session).get_or_create(
                nk.get("address") or rec.attributes.get("address", "")
            )
        if et == EntityType.IOC.value:
            return IOCRepository(self.session).get_or_create(
                nk["ioc_type"], nk.get("value") or rec.attributes.get("value", "")
            )
        if et == EntityType.EXTERNAL_ACCOUNT.value:
            return ExternalAccountRepository(self.session).get_or_create(
                nk.get("platform", "generic"),
                nk.get("identifier") or rec.attributes.get("identifier", ""),
            )
        raise ValueError(f"no ingestion handler for entity_type {et!r}")

    def _ingest_message(self, rec: NormalizedRecord, summary: IngestSummary) -> None:
        container_ref = rec.attributes.get("_container_ref")
        resolved = summary.resolved.get(container_ref) if container_ref else None
        if resolved is None:
            # Fall back to the single container in this batch, if any.
            containers = [
                v
                for v in summary.resolved.values()
                if v[0] in (EntityType.TELEGRAM_GROUP.value, EntityType.TELEGRAM_CHANNEL.value)
            ]
            resolved = containers[0] if len(containers) == 1 else None
        if resolved is None:
            _log.info("ingest_message_no_container", ref=rec.ref)
            summary.skipped.append(rec.ref)
            return

        container_type, container_id = resolved
        cols = {
            k: v for k, v in rec.attributes.items() if k not in _HINT_KEYS and k not in _SKIP_ATTR
        }
        cols["urls_json"] = _as_json(cols.get("urls_json"))
        cols["usernames_json"] = _as_json(cols.get("usernames_json"))
        cols = {k: v for k, v in cols.items() if v is not None}

        try:
            msg, created = MessageRepository(self.session).upsert(
                source_type=container_type,
                source_id=container_id,
                message_id=int(rec.natural_key["message_id"]),
                **cols,
            )
        except Exception as exc:  # noqa: BLE001
            _log.warning("ingest_message_failed", ref=rec.ref, error=str(exc))
            summary.skipped.append(rec.ref)
            return

        summary.resolved[rec.ref] = (EntityType.MESSAGE.value, msg.id)
        summary.entities_created += int(created)
        summary.entities_updated += int(not created)

        # IOC enrichment (Phase 5): extract indicators from the message text and
        # wire them into the graph with evidence. Idempotent.
        text = rec.attributes.get("text")
        if isinstance(text, str) and text:
            enrich = IocEnricher(self.session).enrich_message(
                message_id=msg.id,
                text=text,
                source=(rec.evidence[0].source if rec.evidence else "manual"),
                source_type=(rec.evidence[0].source_type if rec.evidence else "telegram"),
                reference=_str_or_none(rec.attributes.get("source_url")),
                observed_at=rec.evidence[0].observed_at if rec.evidence else None,
            )
            summary.iocs_extracted += enrich.iocs_created
            summary.relationships_observed += enrich.relationships_observed
            summary.evidence_recorded += enrich.evidence_recorded

    def _apply_attributes(self, obj: object, attributes: Mapping[str, object]) -> None:
        for key, value in attributes.items():
            if key in _HINT_KEYS or key in _SKIP_ATTR or value is None:
                continue
            if hasattr(obj, key) and getattr(obj, key) in (None, "", 0, False):
                setattr(obj, key, value)

    # ---------------------------------------------------------------- evidence
    def _record_evidence(self, draft: EvidenceDraft, summary: IngestSummary) -> None:
        resolved = summary.resolved.get(draft.ref)
        if resolved is None:
            return
        entity_type, entity_id = resolved
        try:
            _, created = EvidenceRepository(self.session).record(
                entity_type=entity_type,
                entity_id=entity_id,
                source=draft.source,
                source_type=draft.source_type,
                field=draft.field,
                value=draft.value,
                reference=draft.reference,
                raw_content=draft.raw,
                observed_at=draft.observed_at,
                extraction_method=draft.extraction_method,
                confidence=draft.confidence,
            )
            summary.evidence_recorded += int(created)
        except Exception as exc:  # noqa: BLE001
            _log.warning("ingest_evidence_failed", ref=draft.ref, error=str(exc))

    # ------------------------------------------------------------ relationships
    def _observe_relationship(self, rel: RelationshipDraft, summary: IngestSummary) -> None:
        src = summary.resolved.get(rel.source_ref)
        tgt = summary.resolved.get(rel.target_ref)
        if src is None or tgt is None:
            return
        try:
            _, created = RelationshipRepository(self.session).observe(
                source_type=src[0],
                source_id=src[1],
                target_type=tgt[0],
                target_id=tgt[1],
                rel_type=rel.rel_type,
                confidence=rel.confidence,
            )
            summary.relationships_observed += int(created)
        except Exception as exc:  # noqa: BLE001
            _log.warning("ingest_relationship_failed", error=str(exc))


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _username_from_nk(nk: Mapping[str, object]) -> str | None:
    v = nk.get("username_normalized")
    return str(v) if v else None


def _as_json(value: object) -> str | None:
    import json

    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, default=str)
