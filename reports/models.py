"""Report content model.

A report is a tree of **sections**, each a list of :class:`Claim` and/or
structured blocks. Every material claim carries the ids of the ``evidence`` rows
that support it and is tagged ``FACT`` / ``INFERENCE`` / ``UNKNOWN``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime

from database.types import Assertion

# The 15 legacy dossier sections, in order (original spec section 15).
SECTION_ORDER: tuple[str, ...] = (
    "executive_summary",
    "target_information",
    "public_telegram_presence",
    "public_groups",
    "public_channels",
    "public_messages",
    "username_intelligence",
    "external_osint",
    "ioc",
    "timeline",
    "entity_graph",
    "evidence",
    "confidence_scores",
    "collection_timestamps",
    "limitations",
)

# The Telegram public-OSINT *investigation* report layout ("REFACTOR" spec §18).
INVESTIGATION_SECTION_ORDER: tuple[str, ...] = (
    "executive_summary",
    "target_information",
    "public_profile",
    "observed_public_resources",
    "public_message_activity",
    "mentions",
    "replies",
    "timeline",
    "entities",
    "relationships",
    "evidence",
    "confidence",
    "limitations",
    "methodology",
    "audit_information",
)

SECTION_TITLES: dict[str, str] = {
    "executive_summary": "Executive Summary",
    "target_information": "Target Information",
    "public_profile": "Public Profile",
    "public_telegram_presence": "Public Telegram Presence",
    "observed_public_resources": "Observed Public Resources",
    "public_groups": "Public Groups",
    "public_channels": "Public Channels",
    "public_messages": "Public Messages",
    "public_message_activity": "Public Message Activity",
    "mentions": "Mentions",
    "replies": "Replies",
    "username_intelligence": "Username Intelligence",
    "external_osint": "External OSINT",
    "ioc": "Indicators of Compromise",
    "timeline": "Timeline",
    "entity_graph": "Entity Graph",
    "entities": "Entities",
    "relationships": "Relationships",
    "evidence": "Evidence",
    "confidence_scores": "Confidence Scores",
    "confidence": "Confidence",
    "collection_timestamps": "Collection Timestamps",
    "limitations": "Data Visibility Limitations",
    "methodology": "Methodology",
    "audit_information": "Audit Information",
}

_ALL_SECTION_ORDER: tuple[str, ...] = SECTION_ORDER + tuple(
    k for k in INVESTIGATION_SECTION_ORDER if k not in SECTION_ORDER
)


@dataclass
class Claim:
    text: str
    assertion: str = Assertion.FACT.value
    evidence_refs: list[str] = field(default_factory=list)
    confidence: int | None = None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Section:
    key: str
    claims: list[Claim] = field(default_factory=list)
    data: dict = field(default_factory=dict)

    @property
    def title(self) -> str:
        return SECTION_TITLES.get(self.key, self.key.replace("_", " ").title())

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "title": self.title,
            "claims": [c.as_dict() for c in self.claims],
            "data": self.data,
        }


@dataclass
class ReportContent:
    report_id: str
    title: str
    target: dict
    generated_at: datetime
    sections: dict[str, Section] = field(default_factory=dict)

    def section(self, key: str) -> Section:
        return self.sections.setdefault(key, Section(key=key))

    def as_dict(self) -> dict:
        ordered = [k for k in _ALL_SECTION_ORDER if k in self.sections]
        ordered += [k for k in self.sections if k not in _ALL_SECTION_ORDER]
        return {
            "report_id": self.report_id,
            "title": self.title,
            "target": self.target,
            "generated_at": self.generated_at.isoformat(),
            "sections": [self.sections[k].as_dict() for k in ordered],
        }
