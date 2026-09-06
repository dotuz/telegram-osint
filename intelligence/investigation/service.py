"""Investigation orchestrator.

Turns a stored ``Investigation`` (target = Telegram @username or numeric id)
into a set of **public** observations, entities, a timeline, an overall
confidence, and a report -- reusing the existing collectors, ingestion,
username-OSINT, IOC, timeline and report machinery.

Honesty rules (spec sections 2, 9, 11, 32):
  * every observation carries an ``observation_type`` assigned once by the
    classifier -- a MENTION is never promoted to AUTHOR;
  * when a public Telegram source is not configured, the relevant steps report
    "NOT OBSERVABLE", they do not fabricate membership or messages;
  * the report always carries a DATA VISIBILITY LIMITATIONS section.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from collectors.common.interfaces import Collector, CollectRequest, CollectResult
from collectors.telegram.collector import KIND_MESSAGE_SEARCH, KIND_USER, TelegramPublicCollector
from database.models.investigation import Investigation
from database.repositories import InvestigationRepository
from database.types import (
    InvestigationStatus,
    ObservationResourceKind,
    SourceType,
)
from intelligence.investigation.classifier import classify_observation
from intelligence.investigation.target import ParsedTarget, parse_target
from intelligence.ioc.extract import extract_iocs
from security.logging import get_logger

_log = get_logger("intelligence.investigation")

_NO_SOURCE = "no public Telegram source is configured"

STEPS = (
    "Target normalization",
    "Public Telegram footprint",
    "Public mentions",
    "Public messages",
    "Entity correlation",
    "Report generation",
)

_BASE_LIMITATIONS = (
    "Private groups and private chats cannot be verified by this investigation.",
    "Absence of an observation does not prove absence of activity.",
    "Deleted or edited public content may not be recoverable.",
    "Username matches across platforms are potential matches, not confirmed identity.",
)


@dataclass
class InvestigationResult:
    investigation_id: str
    public_id: str
    status: str
    counts: dict[str, int] = field(default_factory=dict)
    confidence: int | None = None
    narrative: str = ""
    limitations: list[str] = field(default_factory=list)
    report_id: str | None = None


class InvestigationService:
    def __init__(
        self,
        session: Session,
        user_id: str,
        *,
        telegram_collector: Collector | None = None,
        username_collector: Collector | None = None,
    ) -> None:
        self.session = session
        self.user_id = user_id
        self._repo = InvestigationRepository(session, user_id)
        self._tg = telegram_collector or TelegramPublicCollector()
        self._username_collector = username_collector

    async def run(self, investigation_id: str) -> InvestigationResult:
        inv = self._repo.get(investigation_id)
        if inv is None:
            raise LookupError(f"investigation {investigation_id} not found")

        self._repo.set_status(investigation_id, InvestigationStatus.RUNNING)
        try:
            target = parse_target(inv.target)
        except ValueError as exc:
            self._repo.set_status(
                investigation_id, InvestigationStatus.FAILED, error=f"invalid target: {exc}"
            )
            return InvestigationResult(
                inv.id, inv.public_id, InvestigationStatus.FAILED.value, narrative=str(exc)
            )

        from security.config import get_settings

        limitations = list(_BASE_LIMITATIONS)
        notes: list[str] = []
        source_configured = True
        s = get_settings()
        operator_configured = bool(
            (s.telegram_operator_session and s.telegram_operator_session.get_secret_value())
            or (s.telegram_operator_api_id and s.telegram_operator_api_hash)
        )
        if not operator_configured:
            limitations.append(
                "Comprehensive public message/mention search across Telegram requires "
                "an authorized operator account (TELEGRAM_OPERATOR_*). Without one, "
                "message and mention discovery is limited to the configured source and "
                "may be NOT OBSERVABLE."
            )

        # --- [2] public Telegram footprint (profile) ---
        profile_rec: dict | None = None
        prof = await self._tg.run(CollectRequest(query=target.display, kind=KIND_USER, limit=1))
        if prof.error == _NO_SOURCE:
            source_configured = False
            limitations.append(
                "No authorized public Telegram source is configured; public profile, "
                "message and mention discovery are NOT OBSERVABLE with the current "
                "Telegram access model."
            )
        notes += list(prof.notes)
        for rec in prof.records:
            if rec.entity_type == "telegram_account":
                profile_rec = dict(rec.attributes)

        # --- [3]/[4] public mentions + messages ---
        msg_result: CollectResult | None = None
        if source_configured:
            msg_result = await self._tg.run(
                CollectRequest(query=target.canonical, kind=KIND_MESSAGE_SEARCH, limit=50)
            )
            notes += list(msg_result.notes)

        observations = self._build_observations(inv, target, msg_result)

        # --- [5] entity correlation (username OSINT for username targets) ---
        aliases: list[dict] = []
        alias_confidence: int | None = None
        if target.is_username:
            aliases, alias_confidence, alias_notes = await self._username_osint(target)
            notes += alias_notes

        iocs = self._extract_iocs(observations)

        # --- confidence + summary ---
        counts = _count(observations)
        counts["aliases"] = len(aliases)
        counts["iocs"] = len(iocs)
        confidence = self._overall_confidence(observations, alias_confidence, source_configured)
        narrative = self._narrative(
            target, counts, source_configured, operator_configured=operator_configured
        )

        inv.confidence = confidence
        inv.summary_json = json.dumps(
            {
                "target": {"type": target.target_type, "canonical": target.canonical},
                "counts": counts,
                "narrative": narrative,
                "limitations": limitations,
                "notes": sorted({n for n in notes if n}),
                "profile": profile_rec,
                "aliases": aliases,
                "iocs": iocs,
            }
        )

        # --- [6] report ---
        report_id: str | None = None
        try:
            from reports.investigation_report import generate_investigation_report

            report_id = generate_investigation_report(self.session, inv.id)
            inv.report_id = report_id
        except Exception:  # noqa: BLE001 - a report failure must not fail the investigation
            _log.exception("investigation_report_failed", investigation_id=inv.id)
            notes.append("report generation failed")

        self._repo.set_status(investigation_id, InvestigationStatus.COMPLETED)
        self.session.flush()

        return InvestigationResult(
            investigation_id=inv.id,
            public_id=inv.public_id,
            status=InvestigationStatus.COMPLETED.value,
            counts=counts,
            confidence=confidence,
            narrative=narrative,
            limitations=limitations,
            report_id=report_id,
        )

    # ------------------------------------------------------------------ steps
    def _build_observations(
        self,
        inv: Investigation,
        target: ParsedTarget,
        msg_result: CollectResult | None,
    ) -> list[dict]:
        out: list[dict] = []
        if msg_result is None:
            return out
        for rec in msg_result.records:
            if rec.entity_type != "message":
                continue
            a = dict(rec.attributes)
            obs_type, conf = classify_observation(
                target=target,
                author_username=a.get("author_username"),
                author_id=a.get("author_id"),
                text=a.get("text"),
                is_reply=a.get("reply_to_message_id") is not None,
            )
            url = a.get("source_url")
            resource_ref = a.get("_container_ref") or "unknown"
            if url and "t.me/" in url:
                resource_ref = url.split("t.me/", 1)[1].split("/")[0]
            observed_at = _coerce_dt(a.get("posted_at"))
            row = self._repo.add_observation(
                investigation_id=inv.id,
                observation_type=obs_type.value,
                resource_kind=ObservationResourceKind.CHANNEL.value,
                resource_ref=str(resource_ref)[:255],
                resource_url=url,
                message_ref=str(a["message_id"]) if a.get("message_id") is not None else None,
                snippet=(a.get("text") or "")[:500] or None,
                observed_at=observed_at,
                source=SourceType.TELEGRAM_PUBLIC.value,
                confidence=conf,
            )
            out.append(
                {
                    "id": row.id,
                    "type": obs_type.value,
                    "resource": str(resource_ref),
                    "url": url,
                    "message_ref": row.message_ref,
                    "snippet": row.snippet,
                    "observed_at": observed_at.isoformat() if observed_at else None,
                    "confidence": conf,
                }
            )
        return out

    async def _username_osint(
        self, target: ParsedTarget
    ) -> tuple[list[dict], int | None, list[str]]:
        from intelligence.username_osint import UsernameOsintService

        svc = UsernameOsintService(self.session, self.user_id, collector=self._username_collector)
        result = await svc.run(target.canonical)
        aliases = [
            {
                "platform": s.platform,
                "url": s.url,
                "confidence": s.confidence,
                "band": s.band,
                "label": s.label,
                "evidence": s.evidence,
            }
            for s in result.sources
        ]
        best = max((s.confidence for s in result.sources), default=None)
        return aliases, best, list(result.notes)

    def _extract_iocs(self, observations: list[dict]) -> list[dict]:
        seen: set[tuple[str, str]] = set()
        out: list[dict] = []
        for obs in observations:
            for hit in extract_iocs(obs.get("snippet") or ""):
                key = (hit.ioc_type, hit.value)
                if key in seen:
                    continue
                seen.add(key)
                out.append({"type": hit.ioc_type, "value": hit.value})
        return out

    def _overall_confidence(
        self,
        observations: list[dict],
        alias_confidence: int | None,
        source_configured: bool,
    ) -> int | None:
        if not source_configured and alias_confidence is None:
            return None
        signals: list[int] = [
            o["confidence"] for o in observations if o["type"] in ("AUTHOR", "REPLY")
        ]
        if alias_confidence is not None:
            signals.append(alias_confidence)
        mentions = [o["confidence"] for o in observations if o["type"] == "MENTION"]
        if mentions:
            signals.append(min(60, max(mentions)))
        if not signals:
            if observations or alias_confidence:
                return 20
            return 0 if source_configured else None
        return min(95, max(signals))

    def _narrative(
        self,
        target: ParsedTarget,
        counts: dict[str, int],
        source_configured: bool,
        *,
        operator_configured: bool = True,
    ) -> str:
        if not source_configured:
            return (
                f"No authorized public Telegram source is configured, so public "
                f"footprint discovery for {target.display} is NOT OBSERVABLE with the "
                f"current access model. Cross-platform username correlation "
                f"({counts.get('aliases', 0)} potential alias(es)) was still attempted."
            )
        if counts.get("observations", 0) == 0 and not operator_configured:
            return (
                f"Public message/mention discovery for {target.display} is NOT "
                f"OBSERVABLE with the current Telegram access model (no authorized "
                f"operator account; the Bot API cannot search public messages). "
                f"Cross-platform username correlation found "
                f"{counts.get('aliases', 0)} potential alias(es)."
            )
        parts = [f"{counts.get('observations', 0)} public observation(s) for {target.display}"]
        if counts.get("AUTHOR"):
            parts.append(f"{counts['AUTHOR']} likely authored")
        if counts.get("MENTION"):
            parts.append(f"{counts['MENTION']} mention(s)")
        if counts.get("REPLY"):
            parts.append(f"{counts['REPLY']} repl(y/ies)")
        return "; ".join(parts) + "."


# --------------------------------------------------------------------- helpers


def _count(observations: list[dict]) -> dict[str, int]:
    c = {"observations": len(observations)}
    for t in ("AUTHOR", "MENTION", "REPLY", "REFERENCE", "UNKNOWN"):
        c[t] = sum(1 for o in observations if o["type"] == t)
    c["resources"] = len({o["resource"] for o in observations if o.get("resource")})
    return c


def _coerce_dt(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def link_job(session: Session, investigation_id: str, job_id: str) -> None:
    inv = session.get(Investigation, investigation_id)
    if inv is not None:
        inv.job_id = job_id
        session.flush()


__all__ = ["STEPS", "InvestigationResult", "InvestigationService", "link_job"]
