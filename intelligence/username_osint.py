"""Username-OSINT service.

Runs the fan-out collector, persists the discovered accounts, then -- in the
intelligence layer where it belongs -- scores how strongly each account's public
signals corroborate the others, records that correlation as evidence, and adds
``ACCOUNT_POSSIBLY_SAME_AS`` edges. Never asserts a shared identity.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from collectors.common.interfaces import Collector, CollectRequest, NormalizedRecord
from collectors.username.collector import KIND_USERNAME, UsernameOsintCollector
from database.normalize import normalize_username
from database.repositories import EvidenceRepository, RelationshipRepository, SearchRepository
from database.types import EntityType, RelationshipType, SearchKind, TaskStatus
from intelligence.confidence import IdentityFacts, score_account, score_pair
from intelligence.ingest import IngestionService
from security.logging import get_logger

_log = get_logger("intelligence.username_osint")

_SAME_AS_THRESHOLD = 45


@dataclass
class SourceHit:
    platform: str
    url: str | None
    entity_type: str
    entity_id: str | None
    confidence: int  # correlation confidence (0-100), not raw presence
    band: str
    label: str
    evidence: list[str] = field(default_factory=list)


@dataclass
class UsernameOsintResult:
    username: str
    found: bool
    sources: list[SourceHit] = field(default_factory=list)
    same_as_edges: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    search_id: str | None = None
    disclaimer: str = (
        "A matching username is not proof of a shared identity. Each result is a "
        "potential match supported only by the public evidence listed."
    )


class UsernameOsintService:
    def __init__(
        self, session: Session, user_id: str, *, collector: Collector | None = None
    ) -> None:
        self.session = session
        self.user_id = user_id
        self.collector = collector or UsernameOsintCollector()
        self._searches = SearchRepository(session, user_id)

    async def run(self, username: str) -> UsernameOsintResult:
        handle = normalize_username(username)
        search = self._searches.create(
            kind=SearchKind.USERNAME, query=handle, filters={"mode": "username_osint"}
        )
        self.session.flush()

        result = await self.collector.run(CollectRequest(query=handle, kind=KIND_USERNAME))
        summary = IngestionService(self.session).ingest(result)

        out = UsernameOsintResult(
            username=handle, found=False, notes=list(result.notes), search_id=search.id
        )
        if result.error:
            out.notes.append(result.error)

        account_recs = [r for r in result.records if r.entity_type != EntityType.USERNAME.value]
        facts = {r.ref: _facts_from_record(r) for r in account_recs}

        db_results: list[dict] = []
        for rec in account_recs:
            entity_id = summary.entity_id(rec.ref)
            peers = [f for ref, f in facts.items() if ref != rec.ref]
            corr = score_account(facts[rec.ref], peers)

            presence_ev = [e.value for e in rec.evidence if isinstance(e.value, str)]
            corr_line = f"{corr.label} score {corr.score}" + (
                f" — {'; '.join(s.detail for s in corr.signals)}" if corr.signals else ""
            )

            if entity_id is not None:
                self._record_correlation_evidence(rec.entity_type, entity_id, corr_line, corr.score)

            out.sources.append(
                SourceHit(
                    platform=_platform_of(rec),
                    url=_str(rec.attributes.get("profile_url")),
                    entity_type=rec.entity_type,
                    entity_id=entity_id,
                    confidence=corr.score,
                    band=corr.band,
                    label=corr.label,
                    evidence=[*presence_ev, corr_line],
                )
            )
            if entity_id is not None:
                snippet = f"{_platform_of(rec)}: {rec.attributes.get('profile_url') or ''}"
                db_results.append(
                    {
                        "entity_type": rec.entity_type,
                        "entity_id": entity_id,
                        "score": corr.score / 100,
                        "snippet": snippet,
                        "matched_terms": [handle],
                    }
                )

        out.same_as_edges = self._link_same_as(account_recs, facts, summary)

        out.sources.sort(key=lambda s: -s.confidence)
        out.found = bool(out.sources)
        if db_results:
            self._searches.add_results(search.id, db_results)
        self._searches.set_status(
            search.id,
            TaskStatus.COMPLETED if out.found or not result.error else TaskStatus.FAILED,
        )
        return out

    # ------------------------------------------------------------------ internals
    def _record_correlation_evidence(
        self, entity_type: str, entity_id: str, line: str, score: int
    ) -> None:
        EvidenceRepository(self.session).record(
            entity_type=entity_type,
            entity_id=entity_id,
            field="identity_correlation",
            value=line,
            source="intelligence",
            source_type="correlation",
            raw_content=line,
            extraction_method="confidence_engine",
            confidence=score,
        )

    def _link_same_as(
        self,
        account_recs: list[NormalizedRecord],
        facts: dict[str, IdentityFacts],
        summary,  # noqa: ANN001
    ) -> list[dict]:
        edges: list[dict] = []
        for i in range(len(account_recs)):
            for j in range(i + 1, len(account_recs)):
                ra, rb = account_recs[i], account_recs[j]
                pair = score_pair(facts[ra.ref], facts[rb.ref])
                if pair.score < _SAME_AS_THRESHOLD:
                    continue
                ida, idb = summary.entity_id(ra.ref), summary.entity_id(rb.ref)
                if ida and idb:
                    RelationshipRepository(self.session).observe(
                        source_type=ra.entity_type,
                        source_id=ida,
                        target_type=rb.entity_type,
                        target_id=idb,
                        rel_type=RelationshipType.ACCOUNT_POSSIBLY_SAME_AS.value,
                        confidence=pair.score,
                        metadata={"signals": [s.name for s in pair.signals]},
                    )
                edges.append(
                    {
                        "a": _platform_of(ra),
                        "b": _platform_of(rb),
                        "confidence": pair.score,
                        "band": pair.band,
                        "signals": [s.detail for s in pair.signals],
                    }
                )
        return edges


def _facts_from_record(rec: NormalizedRecord) -> IdentityFacts:
    a = rec.attributes
    return IdentityFacts(
        display_name=_str(a.get("display_name")),
        bio=_str(a.get("bio")),
        website=_str(a.get("linked_website")),
        location=_str(a.get("location")),
    )


def _platform_of(rec: NormalizedRecord) -> str:
    p = rec.natural_key.get("platform")
    if p:
        return str(p)
    return "telegram" if rec.entity_type == EntityType.TELEGRAM_ACCOUNT.value else "unknown"


def _str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
