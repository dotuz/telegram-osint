"""Username-OSINT collector: fan out to every registered adapter.

Produces one ``Username`` record plus one account record per platform where the
handle exists, each with the adapter's own evidence (the request made + what was
observed). Correlation confidence and ``ACCOUNT_POSSIBLY_SAME_AS`` edges are the
intelligence layer's job (``intelligence.username_osint``) -- collectors stay
independent of the intelligence engine.
"""

from __future__ import annotations

import asyncio
import dataclasses
from typing import Any

from collectors.common.interfaces import (
    Collector,
    CollectRequest,
    EvidenceDraft,
    HealthStatus,
    NormalizedRecord,
    RawBundle,
    RelationshipDraft,
)
from collectors.username.base import UsernameAdapter, username_registry
from database.normalize import normalize_username
from database.types import EntityType, RelationshipType, SourceType

KIND_USERNAME = "username_osint"


class UsernameOsintCollector(Collector):
    name = "username_osint"
    source_type = SourceType.WEB.value
    supported_kinds = frozenset({KIND_USERNAME})

    def __init__(self, adapters: list[UsernameAdapter] | None = None) -> None:
        self._adapters = adapters

    def _resolve_adapters(self) -> list[UsernameAdapter]:
        return self._adapters if self._adapters is not None else username_registry.all()

    # ------------------------------------------------------------------ collect
    async def collect(self, request: CollectRequest) -> RawBundle:
        handle = normalize_username(request.query)
        if not handle:
            return RawBundle(kind=request.kind, source=self.source_type, error="empty username")

        adapters = self._resolve_adapters()
        if not adapters:
            return RawBundle(
                kind=request.kind,
                source=self.source_type,
                error="no username-OSINT adapters registered",
            )

        results = await asyncio.gather(*(a.check(handle) for a in adapters), return_exceptions=True)
        payload: list[dict[str, Any]] = []
        notes: list[str] = []
        for adapter, res in zip(adapters, results, strict=True):
            if isinstance(res, BaseException):
                notes.append(f"{adapter.platform}: {type(res).__name__}")
                continue
            if res.error:
                notes.append(f"{res.platform}: {res.error}")
            payload.append(
                {
                    "platform": res.platform,
                    "username": res.username,
                    "exists": res.exists,
                    "url": res.url,
                    "match_confidence": res.match_confidence,
                    "evidence": list(res.evidence),
                    "facts": dataclasses.asdict(res.facts) if res.facts else None,
                }
            )
        return RawBundle(
            kind=request.kind, source=self.source_type, payload=payload, notes=tuple(notes)
        )

    # --------------------------------------------------------------- normalize
    def normalize(self, raw: RawBundle) -> list[NormalizedRecord]:
        handle = _handle_of(raw)
        if handle is None:
            return []

        records: list[NormalizedRecord] = [
            NormalizedRecord(
                ref="username",
                entity_type=EntityType.USERNAME.value,
                natural_key={"platform": "generic", "value_normalized": handle},
                attributes={"value": handle},
            )
        ]

        for i, p in enumerate([p for p in raw.payload if p.get("exists")]):
            ref = f"acct-{i}"
            facts = p.get("facts") or {}
            is_tg = p["platform"] == "telegram"

            if is_tg:
                nk: dict[str, Any] = {"username_normalized": handle}
                tid = _int_or_none(facts.get("account_id"))
                if tid is not None:
                    nk["telegram_id"] = tid
                entity_type = EntityType.TELEGRAM_ACCOUNT.value
            else:
                nk = {"platform": p["platform"], "identifier_normalized": handle}
                entity_type = EntityType.EXTERNAL_ACCOUNT.value

            attrs: dict[str, Any] = {"identifier": handle}
            for src_key, dst_key in (
                ("display_name", "display_name"),
                ("bio", "bio"),
                ("website", "linked_website"),
                ("location", "location"),
            ):
                if facts.get(src_key):
                    attrs[dst_key] = facts[src_key]
            if p.get("url"):
                attrs["profile_url"] = p["url"]

            evidence = tuple(
                EvidenceDraft(
                    ref=ref,
                    field="presence",
                    value=line,
                    source=p["platform"],
                    source_type="username_osint",
                    reference=p.get("url"),
                    confidence=max(0, min(100, int(p["match_confidence"]))),
                    raw=line,
                    extraction_method="username_osint_collector",
                )
                for line in p["evidence"]
            )
            records.append(
                NormalizedRecord(
                    ref=ref,
                    entity_type=entity_type,
                    natural_key=nk,
                    attributes=attrs,
                    evidence=evidence,
                )
            )
        return records

    def relationships(
        self, raw: RawBundle, records: list[NormalizedRecord]
    ) -> list[RelationshipDraft]:
        rels: list[RelationshipDraft] = []
        for i, p in enumerate([p for p in raw.payload if p.get("exists")]):
            rels.append(
                RelationshipDraft(
                    "username",
                    f"acct-{i}",
                    RelationshipType.USERNAME_FOUND_ON.value,
                    confidence=max(0, min(100, int(p["match_confidence"]))),
                )
            )
        return rels

    async def health_check(self) -> HealthStatus:
        adapters = self._resolve_adapters()
        return HealthStatus(
            name=self.name,
            healthy=bool(adapters),
            detail=f"{len(adapters)} adapter(s): {', '.join(a.platform for a in adapters)}",
        )


def _handle_of(raw: RawBundle) -> str | None:
    for p in raw.payload:
        if p.get("username"):
            return normalize_username(p["username"])
    return None


def _int_or_none(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


__all__ = ["KIND_USERNAME", "UsernameOsintCollector"]
