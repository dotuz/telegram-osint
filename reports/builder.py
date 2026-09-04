"""Assemble a :class:`ReportContent` for a target from the intelligence graph.

Read-only. Every stated fact is traced back to ``evidence`` rows; where a fact is
not known the report says ``UNKNOWN`` rather than guessing.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from database.models.evidence import Evidence
from database.models.identifiers import ExternalAccount
from database.models.ioc import IOC
from database.models.message import Message
from database.models.relationship import Relationship
from database.models.target import Target
from database.models.telegram import TelegramAccount, TelegramChannel, TelegramGroup
from database.repositories import EvidenceRepository
from database.types import Assertion, EntityType, RelationshipType
from intelligence.entity_resolution import TargetResolver
from intelligence.relationships import GraphService
from intelligence.timeline import TimelineService
from reports.models import Claim, ReportContent
from security.logging import get_logger

_log = get_logger("reports.builder")

_MSG_SAMPLE = 25
_TIMELINE_CAP = 120
_EVIDENCE_CAP = 300


class ReportBuilder:
    def __init__(self, session: Session, user_id: str) -> None:
        self.session = session
        self.user_id = user_id
        self._ev = EvidenceRepository(session)

    def build(self, report_id: str, target: Target) -> ReportContent:
        resolved = TargetResolver(self.session).resolved_entities(target.id)
        content = ReportContent(
            report_id=report_id,
            title=f"OSINT report — {target.value}",
            target={
                "id": target.id,
                "kind": target.kind,
                "value": target.value,
                "label": target.label,
            },
            generated_at=datetime.now(UTC),
        )

        accounts = self._entities(resolved, EntityType.TELEGRAM_ACCOUNT.value, TelegramAccount)
        channels = self._entities(resolved, EntityType.TELEGRAM_CHANNEL.value, TelegramChannel)
        groups = self._entities(resolved, EntityType.TELEGRAM_GROUP.value, TelegramGroup)
        externals = self._entities(resolved, EntityType.EXTERNAL_ACCOUNT.value, ExternalAccount)

        self._target_information(content, target, resolved)
        self._telegram_presence(content, accounts)
        self._chats(content, "public_groups", groups, EntityType.TELEGRAM_GROUP.value)
        self._chats(content, "public_channels", channels, EntityType.TELEGRAM_CHANNEL.value)
        self._messages(content, channels + groups)
        self._username_intelligence(content, externals, target)
        self._external_osint(content, resolved)
        self._iocs(content, resolved, channels + groups)
        self._timeline(content, target.id)
        self._graph(content, target.id)
        self._evidence(content, resolved)
        self._confidence(content, externals)
        self._timestamps(content, resolved)
        self._limitations(content, resolved, accounts, channels, groups)
        self._executive_summary(content, accounts, channels, groups, externals)
        return content

    # ------------------------------------------------------------------ helpers
    def _entities(self, resolved: list[tuple[str, str]], etype: str, model: Any) -> list:
        ids = [i for t, i in resolved if t == etype]
        if not ids:
            return []
        return list(self.session.execute(select(model).where(model.id.in_(ids))).scalars().all())

    def _latest(self, etype: str, eid: str, field: str) -> tuple[object, str | None]:
        ev = self._ev.latest_value(etype, eid, field)
        if ev is None:
            return None, None
        try:
            value = json.loads(ev.value_json) if ev.value_json else None
        except (ValueError, TypeError):
            value = ev.value_json
        return value, ev.id

    def _evidence_for(self, etype: str, eid: str) -> list[Evidence]:
        return list(self._ev.for_entity(etype, eid, limit=_EVIDENCE_CAP))

    # ------------------------------------------------------------------ sections
    def _target_information(
        self, content: ReportContent, target: Target, resolved: list[tuple[str, str]]
    ) -> None:
        sec = content.section("target_information")
        sec.data = {
            "kind": target.kind,
            "value": target.value,
            "label": target.label,
            "notes": target.notes,
            "resolved_entities": [f"{t}:{i}" for t, i in resolved],
            "created_at": target.created_at.isoformat() if target.created_at else None,
        }
        sec.claims.append(
            Claim(
                text=f"Investigation target: {target.value} ({target.kind}).",
                assertion=Assertion.FACT.value,
            )
        )
        if not resolved:
            sec.claims.append(
                Claim(
                    text="No public graph entities have been resolved to this target yet.",
                    assertion=Assertion.UNKNOWN.value,
                )
            )

    def _telegram_presence(self, content: ReportContent, accounts: list) -> None:
        sec = content.section("public_telegram_presence")
        if not accounts:
            sec.claims.append(
                Claim(
                    text="No public Telegram account observed.", assertion=Assertion.UNKNOWN.value
                )
            )
            return
        for acc in accounts:
            etype = EntityType.TELEGRAM_ACCOUNT.value
            block: dict = {"id": acc.id, "telegram_id": acc.telegram_id, "username": acc.username}
            for field in ("display_name", "bio", "is_verified", "is_scam"):
                value, ev_id = self._latest(etype, acc.id, field)
                observed = value if value is not None else getattr(acc, field, None)
                block[field] = observed
                if observed not in (None, "", False):
                    sec.claims.append(
                        Claim(
                            text=f"Public profile {field.replace('_', ' ')}: {observed}",
                            assertion=Assertion.FACT.value,
                            evidence_refs=[ev_id] if ev_id else [],
                        )
                    )
            sec.data.setdefault("accounts", []).append(block)
        sec.claims.append(
            Claim(
                text=(
                    "A known Telegram ID does not grant access to private groups, chats, "
                    "or messages. Only public data is reported."
                ),
                assertion=Assertion.FACT.value,
            )
        )

    def _chats(self, content: ReportContent, key: str, chats: list, etype: str) -> None:
        sec = content.section(key)
        if not chats:
            sec.claims.append(
                Claim(
                    text=f"No public {key.split('_')[-1]} observed.",
                    assertion=Assertion.UNKNOWN.value,
                )
            )
            return
        for chat in chats:
            msg_count = (
                self.session.execute(
                    select(func.count())
                    .select_from(Message)
                    .where(Message.source_type == etype, Message.source_id == chat.id)
                ).scalar()
                or 0
            )
            sec.data.setdefault("items", []).append(
                {
                    "id": chat.id,
                    "title": chat.title,
                    "username": chat.username,
                    "telegram_id": chat.telegram_id,
                    "participants_count": chat.participants_count,
                    "observed_messages": msg_count,
                }
            )
            title = chat.title or chat.username or chat.id[:8]
            sec.claims.append(
                Claim(
                    text=f"{title}: {msg_count} public message(s) collected.",
                    assertion=Assertion.FACT.value,
                )
            )

    def _messages(self, content: ReportContent, containers: list) -> None:
        sec = content.section("public_messages")
        ids = [c.id for c in containers]
        rows: list[Message] = []
        if ids:
            rows = list(
                self.session.execute(
                    select(Message)
                    .where(Message.source_id.in_(ids))
                    .order_by(Message.posted_at.desc().nullslast())
                    .limit(_MSG_SAMPLE)
                )
                .scalars()
                .all()
            )
        sec.data["sample"] = [
            {
                "message_id": m.message_id,
                "text": (m.text or "")[:500],
                "author_username": m.author_username,
                "posted_at": m.posted_at.isoformat() if m.posted_at else None,
                "source_url": m.source_url,
            }
            for m in rows
        ]
        sec.claims.append(
            Claim(
                text=f"{len(rows)} public message(s) sampled (of the collected corpus).",
                assertion=Assertion.FACT.value,
            )
        )
        if not rows:
            sec.claims.append(
                Claim(
                    text="No public messages have been collected for this target.",
                    assertion=Assertion.UNKNOWN.value,
                )
            )

    def _username_intelligence(
        self, content: ReportContent, externals: list, target: Target
    ) -> None:
        sec = content.section("username_intelligence")
        if not externals:
            sec.claims.append(
                Claim(
                    text="No external accounts sharing this handle were discovered.",
                    assertion=Assertion.UNKNOWN.value,
                )
            )
            return
        for acc in externals:
            etype = EntityType.EXTERNAL_ACCOUNT.value
            corr = self._ev.latest_value(etype, acc.id, "identity_correlation")
            block = {
                "platform": acc.platform,
                "identifier": acc.identifier,
                "profile_url": acc.profile_url,
                "display_name": acc.display_name,
                "correlation": corr.value_json if corr is not None else None,
                "correlation_confidence": corr.confidence if corr is not None else None,
            }
            sec.data.setdefault("accounts", []).append(block)
            sec.claims.append(
                Claim(
                    text=(
                        f"Account with the same handle found on {acc.platform}: "
                        f"{acc.profile_url or acc.identifier}."
                    ),
                    assertion=Assertion.INFERENCE.value,
                    evidence_refs=[e.id for e in self._evidence_for(etype, acc.id)][:5],
                    confidence=corr.confidence if corr is not None else None,
                )
            )
        sec.claims.append(
            Claim(
                text=(
                    "A matching username is not proof of a shared identity. Each entry is a "
                    "potential match supported only by the public evidence listed."
                ),
                assertion=Assertion.FACT.value,
            )
        )

    def _external_osint(self, content: ReportContent, resolved: list[tuple[str, str]]) -> None:
        sec = content.section("external_osint")
        websites: list[dict] = []
        for etype, eid in resolved:
            rows = (
                self.session.execute(
                    select(Relationship).where(
                        Relationship.source_type == etype,
                        Relationship.source_id == eid,
                        Relationship.rel_type.in_(
                            (
                                RelationshipType.ACCOUNT_LINKED_TO_WEBSITE.value,
                                RelationshipType.DOMAIN_REFERENCED_BY_ACCOUNT.value,
                            )
                        ),
                    )
                )
                .scalars()
                .all()
            )
            for rel in rows:
                websites.append(
                    {
                        "from": f"{etype}:{eid}",
                        "to": f"{rel.target_type}:{rel.target_id}",
                        "relationship": rel.rel_type,
                        "confidence": rel.confidence,
                    }
                )
        sec.data["linked"] = websites
        if websites:
            sec.claims.append(
                Claim(
                    text=f"{len(websites)} public website/domain link(s) associated with target.",
                    assertion=Assertion.INFERENCE.value,
                )
            )
        else:
            sec.claims.append(
                Claim(
                    text="No linked public websites or domains found.",
                    assertion=Assertion.UNKNOWN.value,
                )
            )

    def _iocs(
        self, content: ReportContent, resolved: list[tuple[str, str]], containers: list
    ) -> None:
        sec = content.section("ioc")
        msg_ids = []
        if containers:
            msg_ids = list(
                self.session.execute(
                    select(Message.id).where(Message.source_id.in_([c.id for c in containers]))
                )
                .scalars()
                .all()
            )
        ioc_ids: set[str] = set()
        if msg_ids:
            rows = self.session.execute(
                select(Relationship.target_id, Relationship.target_type).where(
                    Relationship.source_type == EntityType.MESSAGE.value,
                    Relationship.source_id.in_(msg_ids),
                )
            ).all()
            ioc_ids = {i for i, t in rows if t == EntityType.IOC.value}
        iocs = (
            list(self.session.execute(select(IOC).where(IOC.id.in_(ioc_ids))).scalars().all())
            if ioc_ids
            else []
        )
        sec.data["items"] = [
            {"type": i.ioc_type, "value": i.value, "times_observed": i.times_observed} for i in iocs
        ]
        by_type: dict[str, int] = {}
        for i in iocs:
            by_type[i.ioc_type] = by_type.get(i.ioc_type, 0) + 1
        sec.data["by_type"] = by_type
        if iocs:
            sec.claims.append(
                Claim(
                    text=f"{len(iocs)} indicator(s) extracted from public messages: "
                    + ", ".join(f"{k}×{v}" for k, v in sorted(by_type.items())),
                    assertion=Assertion.FACT.value,
                )
            )
        else:
            sec.claims.append(
                Claim(
                    text="No indicators of compromise extracted.", assertion=Assertion.UNKNOWN.value
                )
            )

    def _timeline(self, content: ReportContent, target_id: str) -> None:
        sec = content.section("timeline")
        tl = TimelineService(self.session).for_target(target_id)
        sec.data = {
            "by_year": {str(y): evs[:_TIMELINE_CAP] for y, evs in tl.by_year().items()},
            "truncated": tl.truncated,
        }
        sec.claims.append(
            Claim(
                text=f"{len(tl.events)} dated public event(s) on the timeline.",
                assertion=Assertion.FACT.value,
            )
        )

    def _graph(self, content: ReportContent, target_id: str) -> None:
        sec = content.section("entity_graph")
        view = GraphService(self.session).for_target(target_id, depth=2, max_nodes=80)
        sec.data = view.as_dict()
        sec.claims.append(
            Claim(
                text=(
                    f"{len(view.nodes)} entities and {len(view.edges)} relationships in the "
                    f"target's neighbourhood."
                ),
                assertion=Assertion.FACT.value,
            )
        )

    def _evidence(self, content: ReportContent, resolved: list[tuple[str, str]]) -> None:
        sec = content.section("evidence")
        rows: list[Evidence] = []
        for etype, eid in resolved:
            rows.extend(self._evidence_for(etype, eid))
        rows = rows[:_EVIDENCE_CAP]
        sec.data["items"] = [
            {
                "id": e.id,
                "entity": f"{e.entity_type}:{e.entity_id}",
                "field": e.field,
                "source": e.source,
                "reference": e.reference,
                "observed_at": e.observed_at.isoformat() if e.observed_at else None,
                "collected_at": e.collected_at.isoformat() if e.collected_at else None,
                "confidence": e.confidence,
                "extraction_method": e.extraction_method,
            }
            for e in rows
        ]
        sec.claims.append(
            Claim(
                text=f"{len(rows)} evidence record(s) support this report.",
                assertion=Assertion.FACT.value,
            )
        )

    def _confidence(self, content: ReportContent, externals: list) -> None:
        sec = content.section("confidence_scores")
        scores = []
        for acc in externals:
            corr = self._ev.latest_value(
                EntityType.EXTERNAL_ACCOUNT.value, acc.id, "identity_correlation"
            )
            if corr is not None:
                scores.append(
                    {"platform": acc.platform, "score": corr.confidence, "detail": corr.value_json}
                )
        sec.data["correlations"] = scores
        if scores:
            for s in scores:
                sec.claims.append(
                    Claim(
                        text=f"{s['platform']}: {s['score']}% potential-match confidence.",
                        assertion=Assertion.INFERENCE.value,
                        confidence=s["score"],
                    )
                )
        else:
            sec.claims.append(
                Claim(
                    text="No correlation confidence scores computed.",
                    assertion=Assertion.UNKNOWN.value,
                )
            )

    def _timestamps(self, content: ReportContent, resolved: list[tuple[str, str]]) -> None:
        sec = content.section("collection_timestamps")
        rows: list[Evidence] = []
        for etype, eid in resolved:
            rows.extend(self._evidence_for(etype, eid))
        if not rows:
            sec.claims.append(
                Claim(text="No collection timestamps available.", assertion=Assertion.UNKNOWN.value)
            )
            return
        collected = [e.collected_at for e in rows if e.collected_at]
        by_source: dict[str, str] = {}
        for e in rows:
            if e.collected_at and (
                e.source not in by_source or e.collected_at.isoformat() > by_source[e.source]
            ):
                by_source[e.source] = e.collected_at.isoformat()
        sec.data = {
            "first_collected": min(collected).isoformat() if collected else None,
            "last_collected": max(collected).isoformat() if collected else None,
            "last_by_source": by_source,
        }
        sec.claims.append(
            Claim(
                text=(
                    f"Evidence collected between {sec.data['first_collected']} and "
                    f"{sec.data['last_collected']}."
                ),
                assertion=Assertion.FACT.value,
            )
        )

    def _limitations(
        self,
        content: ReportContent,
        resolved: list[tuple[str, str]],
        accounts: list,
        channels: list,
        groups: list,
    ) -> None:
        sec = content.section("limitations")
        items = [
            "Only publicly accessible data and Telegram Bot API data was used.",
            "No private groups, chats, messages, sessions, or credentials were accessed.",
            "Username matches across platforms are potential matches, not confirmed identity.",
        ]
        if not resolved:
            items.append("No graph entities resolved to the target — the report is near-empty.")
        if not accounts:
            items.append("No public Telegram account was located for this handle.")
        if not (channels or groups):
            items.append("No public channel or group activity was collected.")
        from security.config import get_settings

        if not get_settings().telegram_operator_session:
            items.append(
                "No authorized operator account is configured; message history for chats the "
                "bot is not in could not be read."
            )
        sec.data["items"] = items
        for text in items:
            sec.claims.append(Claim(text=text, assertion=Assertion.FACT.value))

    def _executive_summary(
        self,
        content: ReportContent,
        accounts: list,
        channels: list,
        groups: list,
        externals: list,
    ) -> None:
        sec = content.section("executive_summary")
        parts = []
        if accounts:
            parts.append(f"{len(accounts)} public Telegram account(s)")
        if channels or groups:
            parts.append(
                f"{len(channels)} channel(s) / {len(groups)} group(s) with public activity"
            )
        if externals:
            parts.append(f"{len(externals)} same-handle account(s) on other public platforms")
        summary = "This report consolidates public OSINT for the target. " + (
            "Observed: " + "; ".join(parts) + "." if parts else "No public presence was located."
        )
        sec.data["text"] = summary
        sec.claims.append(Claim(text=summary, assertion=Assertion.INFERENCE.value))
        sec.claims.append(
            Claim(
                text=(
                    "All findings are supported by the evidence in section 12 and are "
                    "labelled FACT / INFERENCE / UNKNOWN."
                ),
                assertion=Assertion.FACT.value,
            )
        )
