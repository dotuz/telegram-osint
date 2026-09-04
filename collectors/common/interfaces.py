"""Collector DTOs and the :class:`Collector` base class."""

from __future__ import annotations

import abc
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# ----------------------------------------------------------------------------
# request / response DTOs
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class CollectRequest:
    """What to collect. ``kind`` is collector-specific (see ``supported_kinds``)."""

    query: str
    kind: str
    limit: int = 50
    since: datetime | None = None
    options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvidenceDraft:
    """A single observed fact, not yet persisted.

    ``ref`` points at the :class:`NormalizedRecord` this evidence is about (by its
    ``ref``); the ingestion layer resolves it to a concrete entity id.
    """

    ref: str
    field: str | None
    value: Any
    source: str  # SourceType value
    source_type: str
    reference: str | None = None
    observed_at: datetime | None = None
    confidence: int = 50
    raw: str | None = None  # raw material for the content hash
    extraction_method: str | None = None


@dataclass(frozen=True)
class NormalizedRecord:
    """A canonical entity to upsert, with the evidence that supports it."""

    ref: str  # local id, unique within one CollectResult
    entity_type: str  # EntityType value
    natural_key: Mapping[str, Any]  # dedup key, e.g. {"telegram_id": 42}
    attributes: Mapping[str, Any] = field(default_factory=dict)
    evidence: tuple[EvidenceDraft, ...] = ()


@dataclass(frozen=True)
class RelationshipDraft:
    source_ref: str
    target_ref: str
    rel_type: str  # RelationshipType value
    confidence: int = 50


@dataclass(frozen=True)
class RawBundle:
    """Opaque payload returned by ``collect`` and consumed by ``normalize``."""

    kind: str
    source: str
    payload: Sequence[Mapping[str, Any]] = ()
    partial: bool = False
    error: str | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class CollectResult:
    source: str
    ok: bool
    records: tuple[NormalizedRecord, ...] = ()
    relationships: tuple[RelationshipDraft, ...] = ()
    partial: bool = False
    error: str | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class HealthStatus:
    name: str
    healthy: bool
    detail: str | None = None


class CollectorError(RuntimeError):
    """Raised for unrecoverable collector failures. Message is user-safe-ish but
    handlers still substitute a generic string before showing users."""


# ----------------------------------------------------------------------------
# base class
# ----------------------------------------------------------------------------


class Collector(abc.ABC):
    #: stable slug, e.g. "telegram_public"
    name: str = ""
    #: SourceType value
    source_type: str = ""
    #: request kinds this collector handles
    supported_kinds: frozenset[str] = frozenset()

    def supports(self, kind: str) -> bool:
        return kind in self.supported_kinds

    @abc.abstractmethod
    async def collect(self, request: CollectRequest) -> RawBundle:
        """Fetch raw data. Network-bound. Must honour timeouts and rate limits."""

    @abc.abstractmethod
    def normalize(self, raw: RawBundle) -> list[NormalizedRecord]:
        """Pure: raw payload -> canonical records. No I/O."""

    def relationships(
        self, raw: RawBundle, records: list[NormalizedRecord]
    ) -> list[RelationshipDraft]:
        """Pure: derive graph edges from the normalized records. Optional."""
        return []

    def validate(self, records: list[NormalizedRecord]) -> list[NormalizedRecord]:
        """Pure: drop records with no usable natural key. Override for more."""
        out: list[NormalizedRecord] = []
        seen: set[tuple] = set()
        for rec in records:
            key = (rec.entity_type, tuple(sorted(rec.natural_key.items())))
            if not rec.natural_key or all(v in (None, "", []) for v in rec.natural_key.values()):
                continue
            if key in seen:
                continue
            seen.add(key)
            out.append(rec)
        return out

    @abc.abstractmethod
    async def health_check(self) -> HealthStatus: ...

    async def run(self, request: CollectRequest) -> CollectResult:
        """Orchestrate collect -> normalize -> validate. Never raises."""
        if not self.supports(request.kind):
            return CollectResult(
                source=self.source_type, ok=False, error=f"unsupported kind: {request.kind}"
            )
        try:
            raw = await self.collect(request)
        except CollectorError as exc:
            return CollectResult(source=self.source_type, ok=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001 - collectors must degrade gracefully
            return CollectResult(
                source=self.source_type, ok=False, error=f"{type(exc).__name__}: {exc}"
            )

        records = self.validate(self.normalize(raw))
        rels = self.relationships(raw, records)
        return CollectResult(
            source=self.source_type,
            ok=raw.error is None,
            records=tuple(records),
            relationships=tuple(rels),
            partial=raw.partial,
            error=raw.error,
            notes=raw.notes,
        )
