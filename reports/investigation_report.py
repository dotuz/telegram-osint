"""Render a completed :class:`Investigation` into a JSON/HTML/PDF report.

Mirrors ``reports/service.py`` but for the investigation domain: the section
set is the "REFACTOR" spec §18 layout, every section separates OBSERVED from
INFERRED, and a DATA VISIBILITY LIMITATIONS section is always present.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from database.base import utcnow
from database.models.investigation import Investigation
from database.repositories import InvestigationRepository, ReportRepository
from database.types import Assertion, TaskStatus
from intelligence.confidence.engine import assert_safe_phrasing
from reports.models import Claim, ReportContent, Section
from reports.renderers import PDF_AVAILABLE, render_html, render_json, render_pdf
from security.config import get_settings
from security.logging import get_logger

_log = get_logger("reports.investigation")

_METHODOLOGY = (
    "The target identifier is normalized, then queried against the configured "
    "public Telegram source and public OSINT collectors. Each returned item is "
    "classified (AUTHOR / MENTION / REPLY / REFERENCE / UNKNOWN) from the "
    "evidence available -- a mention is never promoted to authorship. "
    "Cross-platform username correlation produces potential-match confidence, "
    "never a confirmed identity. No private account, session, credential, or "
    "message-history access is performed."
)


def _s(content: ReportContent, key: str, *, claims=None, data=None) -> Section:
    sec = content.section(key)
    if claims:
        sec.claims.extend(claims)
    if data:
        sec.data.update(data)
    return sec


def build_investigation_content(
    session: Session, investigation: Investigation, *, report_id: str
) -> ReportContent:
    summary = json.loads(investigation.summary_json or "{}")
    counts: dict = summary.get("counts", {})
    repo = InvestigationRepository(session, investigation.user_id)
    observations = list(repo.observations(investigation.id))

    content = ReportContent(
        report_id=report_id,
        title=f"Telegram Public OSINT Investigation — {investigation.target}",
        target={
            "value": investigation.target,
            "type": investigation.target_type,
            "normalized": investigation.target_normalized,
            "investigation": investigation.public_id,
        },
        generated_at=utcnow(),
    )

    narrative = summary.get("narrative") or "Investigation completed."
    assert_safe_phrasing(narrative)
    _s(
        content,
        "executive_summary",
        claims=[Claim(text=narrative, assertion=Assertion.INFERENCE.value)],
        data={"counts": counts, "confidence": investigation.confidence},
    )

    _s(
        content,
        "target_information",
        claims=[
            Claim(
                text=f"Target as supplied: {investigation.target}", assertion=Assertion.FACT.value
            ),
            Claim(
                text=f"Canonical target: {investigation.target_normalized} "
                f"({investigation.target_type})",
                assertion=Assertion.FACT.value,
            ),
        ],
    )

    profile = summary.get("profile")
    if profile:
        _s(
            content,
            "public_profile",
            claims=[
                Claim(text=f"{k}: {v}", assertion=Assertion.FACT.value)
                for k, v in profile.items()
                if k not in ("username_normalized",) and v not in (None, "")
            ],
            data={"profile": profile},
        )
    else:
        _s(
            content,
            "public_profile",
            claims=[
                Claim(
                    text="No public profile data was observable for this target.",
                    assertion=Assertion.UNKNOWN.value,
                )
            ],
        )

    # observed resources
    resources: dict[str, dict] = {}
    for o in observations:
        r = resources.setdefault(
            o.resource_ref,
            {"resource": o.resource_ref, "url": o.resource_url, "observations": 0, "types": {}},
        )
        r["observations"] += 1
        r["types"][o.observation_type] = r["types"].get(o.observation_type, 0) + 1
    _s(
        content,
        "observed_public_resources",
        claims=[
            Claim(
                text=f"Target-related public activity observed in {r['resource']} "
                f"({r['observations']} observation(s)).",
                assertion=Assertion.INFERENCE.value,
            )
            for r in resources.values()
        ]
        or [
            Claim(
                text="No public resources with target-related activity were observed.",
                assertion=Assertion.UNKNOWN.value,
            )
        ],
        data={"resources": list(resources.values())},
    )

    def _obs_rows(kinds: set[str]) -> list[dict]:
        return [
            {
                "type": o.observation_type,
                "resource": o.resource_ref,
                "url": o.resource_url,
                "message_ref": o.message_ref,
                "snippet": o.snippet,
                "observed_at": o.observed_at.isoformat() if o.observed_at else None,
                "confidence": o.confidence,
            }
            for o in observations
            if o.observation_type in kinds
        ]

    authored = _obs_rows({"AUTHOR"})
    _s(
        content,
        "public_message_activity",
        claims=[
            Claim(
                text=f"{len(authored)} publicly accessible message(s) with sufficient "
                f"evidence of target authorship.",
                assertion=Assertion.INFERENCE.value,
            )
        ],
        data={
            "authored": authored,
            "all_observations": _obs_rows(set(o.observation_type for o in observations)),
        },
    )
    _s(
        content,
        "mentions",
        data={"mentions": _obs_rows({"MENTION"})},
        claims=[
            Claim(
                text=f"{counts.get('MENTION', 0)} public mention(s) of the target by others.",
                assertion=Assertion.INFERENCE.value,
            )
        ],
    )
    _s(
        content,
        "replies",
        data={"replies": _obs_rows({"REPLY"})},
        claims=[
            Claim(
                text=f"{counts.get('REPLY', 0)} public repl(y/ies) associated with the target.",
                assertion=Assertion.INFERENCE.value,
            )
        ],
    )

    # timeline
    events = sorted(
        (
            {
                "when": o.observed_at.isoformat(),
                "type": o.observation_type,
                "source": o.resource_ref,
                "url": o.resource_url,
                "confidence": o.confidence,
            }
            for o in observations
            if o.observed_at is not None
        ),
        key=lambda e: str(e["when"]),
    )
    _s(
        content,
        "timeline",
        data={"events": events},
        claims=[
            Claim(
                text=f"{len(events)} time-stamped public event(s).",
                assertion=Assertion.FACT.value,
            )
        ],
    )

    aliases = summary.get("aliases") or []
    _s(
        content,
        "entities",
        data={"aliases": aliases, "iocs": summary.get("iocs") or []},
        claims=[
            Claim(
                text=f"{alias['platform']}: {alias['label']}",
                assertion=Assertion.INFERENCE.value,
                confidence=alias.get("confidence"),
            )
            for alias in aliases
        ]
        or [
            Claim(
                text="No cross-platform aliases were correlated.",
                assertion=Assertion.UNKNOWN.value,
            )
        ],
    )
    _s(
        content,
        "relationships",
        claims=[
            Claim(
                text="A shared username across platforms is a POSSIBLE same-entity "
                "signal, never a confirmed identity.",
                assertion=Assertion.INFERENCE.value,
            )
        ],
        data={"same_as": [{"platform": a["platform"], "band": a.get("band")} for a in aliases]},
    )

    _s(
        content,
        "evidence",
        data={
            "observations": [
                {
                    "id": o.id,
                    "type": o.observation_type,
                    "source": o.source,
                    "url": o.resource_url,
                    "observed_at": o.observed_at.isoformat() if o.observed_at else None,
                    "confidence": o.confidence,
                }
                for o in observations
            ]
        },
        claims=[
            Claim(
                text=f"{len(observations)} evidence-backed public observation(s) recorded.",
                assertion=Assertion.FACT.value,
            )
        ],
    )

    _s(
        content,
        "confidence",
        data={"overall": investigation.confidence, "by_signal": counts},
        claims=[
            Claim(
                text=(
                    f"Overall confidence: {investigation.confidence}/100."
                    if investigation.confidence is not None
                    else "Overall confidence: NOT OBSERVABLE (no public source configured)."
                ),
                assertion=Assertion.INFERENCE.value,
                confidence=investigation.confidence,
            )
        ],
    )

    _s(
        content,
        "limitations",
        claims=[
            Claim(text=item, assertion=Assertion.FACT.value)
            for item in summary.get("limitations", [])
        ],
    )
    _s(
        content,
        "methodology",
        claims=[Claim(text=_METHODOLOGY, assertion=Assertion.FACT.value)],
        data={"steps": summary.get("notes", [])},
    )
    _s(
        content,
        "audit_information",
        data={
            "investigation_id": investigation.id,
            "public_id": investigation.public_id,
            "created_by": investigation.user_id,
            "created_at": investigation.created_at.isoformat()
            if investigation.created_at
            else None,
            "completed_at": investigation.completed_at.isoformat()
            if investigation.completed_at
            else None,
            "job_id": investigation.job_id,
        },
    )
    return content


def generate_investigation_report(session: Session, investigation_id: str) -> str:
    inv = session.get(Investigation, investigation_id)
    if inv is None:
        raise LookupError(investigation_id)

    reports = ReportRepository(session, inv.user_id)
    report = reports.create(
        title=f"Investigation {inv.public_id} — {inv.target}", job_id=inv.job_id
    )
    session.flush()

    content = build_investigation_content(session, inv, report_id=report.id)
    out_dir = Path(get_settings().reports_dir) / report.id
    out_dir.mkdir(parents=True, exist_ok=True)

    json_text = render_json(content)
    artifacts: dict[str, str] = {}
    (out_dir / "report.json").write_text(json_text, encoding="utf-8")
    artifacts["json"] = str(out_dir / "report.json")
    (out_dir / "report.html").write_text(render_html(content), encoding="utf-8")
    artifacts["html"] = str(out_dir / "report.html")
    if PDF_AVAILABLE:
        (out_dir / "report.pdf").write_bytes(render_pdf(content))
        artifacts["pdf"] = str(out_dir / "report.pdf")

    report.content_json = json_text
    report.artifacts_json = json.dumps(artifacts)
    report.summary = content.section("executive_summary").claims[0].text
    report.generated_at = _now()
    reports.set_status(report.id, TaskStatus.COMPLETED)
    session.flush()

    _log.info("investigation_report_generated", investigation_id=inv.id, report_id=report.id)
    return report.id


def _now() -> datetime:
    return utcnow()


__all__ = ["build_investigation_content", "generate_investigation_report"]
