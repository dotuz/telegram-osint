"""Turn extracted IOCs into graph entities, evidence, and relationships.

Runs during ingestion (on every stored public message) and is also callable
standalone to re-process historical text. Idempotent: dedup at every layer means
re-running adds nothing new.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from database.repositories import (
    DomainRepository,
    EvidenceRepository,
    IOCRepository,
    IPRepository,
    RelationshipRepository,
    URLRepository,
    UsernameRepository,
)
from database.types import EntityType, IOCType, RelationshipType, SourceType
from intelligence.ioc.extract import IocMatch, extract_iocs
from security.logging import get_logger

_log = get_logger("intelligence.ioc.enrich")

# IOC type -> (MESSAGE_CONTAINS_* relationship, per-type confidence)
_MESSAGE_REL: dict[str, tuple[str, int]] = {
    IOCType.IPV4.value: (RelationshipType.MESSAGE_CONTAINS_IP.value, 80),
    IOCType.IPV6.value: (RelationshipType.MESSAGE_CONTAINS_IP.value, 80),
    IOCType.DOMAIN.value: (RelationshipType.MESSAGE_CONTAINS_DOMAIN.value, 70),
    IOCType.URL.value: (RelationshipType.MESSAGE_CONTAINS_URL.value, 85),
    IOCType.TELEGRAM_URL.value: (RelationshipType.MESSAGE_CONTAINS_URL.value, 85),
    IOCType.EMAIL.value: (RelationshipType.MESSAGE_CONTAINS_IOC.value, 85),
    IOCType.MD5.value: (RelationshipType.MESSAGE_CONTAINS_IOC.value, 90),
    IOCType.SHA1.value: (RelationshipType.MESSAGE_CONTAINS_IOC.value, 90),
    IOCType.SHA256.value: (RelationshipType.MESSAGE_CONTAINS_IOC.value, 90),
    IOCType.CVE.value: (RelationshipType.MESSAGE_CONTAINS_IOC.value, 90),
    IOCType.TELEGRAM_USERNAME.value: (RelationshipType.MESSAGE_MENTIONS_USERNAME.value, 75),
}

_DERIVED_CONFIDENCE_PENALTY = 10


@dataclass
class EnrichSummary:
    iocs_created: int = 0
    relationships_observed: int = 0
    evidence_recorded: int = 0
    by_type: dict[str, int] = field(default_factory=dict)

    def _bump(self, ioc_type: str) -> None:
        self.by_type[ioc_type] = self.by_type.get(ioc_type, 0) + 1


class IocEnricher:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------ public
    def enrich_message(
        self,
        *,
        message_id: str,
        text: str | None,
        source: str,
        source_type: str = "telegram",
        reference: str | None = None,
        observed_at: datetime | None = None,
    ) -> EnrichSummary:
        return self._enrich(
            container_type=EntityType.MESSAGE.value,
            container_id=message_id,
            text=text,
            source=source,
            source_type=source_type,
            reference=reference,
            observed_at=observed_at,
        )

    def enrich_entity_text(
        self,
        *,
        entity_type: str,
        entity_id: str,
        text: str | None,
        source: str,
        source_type: str = "telegram",
        reference: str | None = None,
        field_name: str = "bio",
    ) -> EnrichSummary:
        """Lighter pass for account/channel bios & descriptions: link domains/URLs."""
        summary = EnrichSummary()
        if not text:
            return summary
        for match in extract_iocs(text):
            if match.ioc_type not in (
                IOCType.DOMAIN.value,
                IOCType.URL.value,
                IOCType.TELEGRAM_URL.value,
                IOCType.EMAIL.value,
            ):
                continue
            ioc, created = self._upsert_ioc(match, summary)
            self._record_ioc_evidence(
                ioc.id, match, source, source_type, reference, text, field_name
            )
            summary.evidence_recorded += 1
            rel = (
                RelationshipType.ACCOUNT_LINKED_TO_WEBSITE.value
                if match.ioc_type in (IOCType.URL.value, IOCType.TELEGRAM_URL.value)
                else RelationshipType.DOMAIN_REFERENCED_BY_ACCOUNT.value
            )
            _, r_created = RelationshipRepository(self.session).observe(
                source_type=entity_type,
                source_id=entity_id,
                target_type=EntityType.IOC.value,
                target_id=ioc.id,
                rel_type=rel,
                confidence=60,
            )
            summary.relationships_observed += int(r_created)
        return summary

    # ------------------------------------------------------------------ engine
    def _enrich(
        self,
        *,
        container_type: str,
        container_id: str,
        text: str | None,
        source: str,
        source_type: str,
        reference: str | None,
        observed_at: datetime | None,
    ) -> EnrichSummary:
        summary = EnrichSummary()
        if not text:
            return summary

        for match in extract_iocs(text):
            try:
                self._ingest_match(
                    match,
                    container_type,
                    container_id,
                    source,
                    source_type,
                    reference,
                    text,
                    observed_at,
                    summary,
                )
            except Exception as exc:  # noqa: BLE001 - one IOC must not sink the pass
                _log.warning("ioc_enrich_failed", ioc_type=match.ioc_type, error=str(exc))
        return summary

    def _ingest_match(
        self,
        match: IocMatch,
        container_type: str,
        container_id: str,
        source: str,
        source_type: str,
        reference: str | None,
        text: str,
        observed_at: datetime | None,
        summary: EnrichSummary,
    ) -> None:
        ioc, _ = self._upsert_ioc(match, summary)
        typed = self._link_typed_entity(ioc, match)

        self._record_ioc_evidence(
            ioc.id, match, source, source_type, reference, text, "observed_in_message", observed_at
        )
        summary.evidence_recorded += 1

        rel_type, base_conf = _MESSAGE_REL.get(
            match.ioc_type, (RelationshipType.MESSAGE_CONTAINS_IOC.value, 70)
        )
        conf = base_conf - (_DERIVED_CONFIDENCE_PENALTY if match.derived_from else 0)

        # MESSAGE -> IOC
        _, created = RelationshipRepository(self.session).observe(
            source_type=container_type,
            source_id=container_id,
            target_type=EntityType.IOC.value,
            target_id=ioc.id,
            rel_type=RelationshipType.MESSAGE_CONTAINS_IOC.value
            if container_type == EntityType.MESSAGE.value
            else rel_type,
            confidence=conf,
        )
        summary.relationships_observed += int(created)

        # MESSAGE -> typed entity (domain / ip / url) with the specific rel type
        if typed is not None and container_type == EntityType.MESSAGE.value:
            typed_type, typed_id = typed
            _, tcreated = RelationshipRepository(self.session).observe(
                source_type=container_type,
                source_id=container_id,
                target_type=typed_type,
                target_id=typed_id,
                rel_type=rel_type,
                confidence=conf,
            )
            summary.relationships_observed += int(tcreated)

        # Telegram @mention -> Username entity + MESSAGE_MENTIONS_USERNAME
        if match.ioc_type == IOCType.TELEGRAM_USERNAME.value:
            uname, _ = UsernameRepository(self.session).get_or_create("telegram", match.value)
            _, ucreated = RelationshipRepository(self.session).observe(
                source_type=container_type,
                source_id=container_id,
                target_type=EntityType.USERNAME.value,
                target_id=uname.id,
                rel_type=RelationshipType.MESSAGE_MENTIONS_USERNAME.value,
                confidence=conf,
            )
            summary.relationships_observed += int(ucreated)

    def _upsert_ioc(self, match: IocMatch, summary: EnrichSummary):  # noqa: ANN202
        ioc, created = IOCRepository(self.session).get_or_create(match.ioc_type, match.value)
        if created:
            summary.iocs_created += 1
            summary._bump(match.ioc_type)
        return ioc, created

    def _link_typed_entity(self, ioc: Any, match: IocMatch) -> tuple[str, str] | None:
        typed_type: str | None = None
        typed_id: str | None = None
        obj: Any = None
        if match.ioc_type in (IOCType.IPV4.value, IOCType.IPV6.value):
            obj, _ = IPRepository(self.session).get_or_create(match.value)
            typed_type = EntityType.IP.value
        elif match.ioc_type == IOCType.DOMAIN.value:
            obj, _ = DomainRepository(self.session).get_or_create(match.value)
            typed_type = EntityType.DOMAIN.value
        elif match.ioc_type in (IOCType.URL.value, IOCType.TELEGRAM_URL.value):
            obj, _ = URLRepository(self.session).get_or_create(match.value)
            typed_type = EntityType.URL.value
        if obj is not None:
            typed_id = obj.id

        if typed_type is not None and typed_id is not None:
            if ioc.linked_entity_id is None:
                ioc.linked_entity_type = typed_type
                ioc.linked_entity_id = typed_id
            return typed_type, typed_id
        return None

    def _record_ioc_evidence(
        self,
        ioc_id: str,
        match: IocMatch,
        source: str,
        source_type: str,
        reference: str | None,
        text: str,
        field_name: str,
        observed_at: datetime | None = None,
    ) -> None:
        snippet = text[max(0, match.start - 60) : match.end + 60]
        EvidenceRepository(self.session).record(
            entity_type=EntityType.IOC.value,
            entity_id=ioc_id,
            field=field_name,
            value=match.value,
            source=source or SourceType.MANUAL.value,
            source_type=source_type,
            reference=reference,
            raw_content=snippet,
            observed_at=observed_at,
            extraction_method="ioc_regex",
            confidence=80 - (_DERIVED_CONFIDENCE_PENALTY if match.derived_from else 0),
        )
