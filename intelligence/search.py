"""Telegram intelligence service.

Ties the collector, the ingestion layer, and the per-user investigation tables
together. Used by the bot handlers and the API. Collection failures degrade to
whatever is already in the shared graph -- one unavailable source never produces
an error page.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from collectors.common.interfaces import Collector, CollectRequest, CollectResult
from collectors.telegram.collector import (
    KIND_CHANNEL,
    KIND_GROUP,
    KIND_MESSAGE_SEARCH,
    KIND_USER,
    TelegramPublicCollector,
)
from database.models.telegram import TelegramAccount, TelegramChannel, TelegramGroup
from database.normalize import normalize_username
from database.repositories import EvidenceRepository, MessageRepository, SearchRepository
from database.types import EntityType, SearchKind, TargetKind, TaskStatus
from intelligence.ingest import IngestionService
from intelligence.ioc.service import IocService
from security.logging import get_logger

_log = get_logger("intelligence.search")

_KIND_TO_SEARCHKIND = {
    KIND_USER: SearchKind.USERNAME,
    KIND_GROUP: SearchKind.GROUP,
    KIND_CHANNEL: SearchKind.CHANNEL,
    KIND_MESSAGE_SEARCH: SearchKind.KEYWORD,
}


@dataclass
class IntelResult:
    kind: str
    found: bool
    entity_type: str | None = None
    entity_id: str | None = None
    summary: dict = field(default_factory=dict)
    items: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    search_id: str | None = None
    source_available: bool = True


class TelegramIntelService:
    def __init__(
        self,
        session: Session,
        user_id: str,
        *,
        collector: Collector | None = None,
    ) -> None:
        self.session = session
        self.user_id = user_id
        self.collector = collector or TelegramPublicCollector()
        self._searches = SearchRepository(session, user_id)

    # ------------------------------------------------------------------ public
    async def search_user(self, query: str) -> IntelResult:
        return await self._run(KIND_USER, query, target_kind=TargetKind.TELEGRAM_USER)

    async def group_intel(self, query: str) -> IntelResult:
        return await self._run(KIND_GROUP, query)

    async def channel_intel(self, query: str) -> IntelResult:
        return await self._run(KIND_CHANNEL, query)

    async def search_messages(self, query: str, *, limit: int = 20) -> IntelResult:
        return await self._run(KIND_MESSAGE_SEARCH, query, limit=limit)

    def history(self, *, limit: int = 20) -> list[dict]:
        rows = self._searches.list(limit=limit)
        return [
            {
                "id": s.id,
                "kind": s.kind,
                "query": s.query,
                "status": s.status,
                "result_count": s.result_count,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in rows
        ]

    # ------------------------------------------------------------------ engine
    async def _run(
        self,
        kind: str,
        query: str,
        *,
        limit: int = 50,
        target_kind: TargetKind | None = None,
    ) -> IntelResult:
        query = query.strip()
        search = self._searches.create(
            kind=_KIND_TO_SEARCHKIND[kind], query=query, filters={"telegram_kind": kind}
        )
        self.session.flush()

        result: CollectResult = await self.collector.run(
            CollectRequest(query=query, kind=kind, limit=limit)
        )
        ingest = IngestionService(self.session).ingest(result)

        notes = list(result.notes)
        if result.error:
            notes.append(result.error)

        out = IntelResult(
            kind=kind,
            found=False,
            notes=notes,
            search_id=search.id,
            source_available=result.error != "no public Telegram source is configured",
        )

        if kind == KIND_MESSAGE_SEARCH:
            self._fill_message_search(query, limit, out)
        else:
            self._fill_entity(kind, query, ingest, out)

        self._persist_results(search.id, out)
        self._searches.set_status(
            search.id, TaskStatus.COMPLETED if out.found or not result.error else TaskStatus.FAILED
        )
        return out

    # ----------------------------------------------------------------- fillers
    def _fill_entity(self, kind: str, query: str, ingest: object, out: IntelResult) -> None:
        norm = normalize_username(query)
        if kind == KIND_USER:
            model: Any = TelegramAccount
            etype = EntityType.TELEGRAM_ACCOUNT.value
        elif kind == KIND_GROUP:
            model, etype = TelegramGroup, EntityType.TELEGRAM_GROUP.value
        else:
            model, etype = TelegramChannel, EntityType.TELEGRAM_CHANNEL.value

        obj = None
        if query.lstrip("-").isdigit():
            obj = self.session.execute(
                select(model).where(model.telegram_id == int(query))
            ).scalar_one_or_none()
        if obj is None:
            obj = self.session.execute(
                select(model).where(model.username_normalized == norm)
            ).scalar_one_or_none()

        if obj is None:
            out.notes.append("no public data found for this identifier")
            return

        out.found = True
        out.entity_type = etype
        out.entity_id = obj.id
        out.summary = self._entity_summary(etype, obj.id, obj)

    def _entity_summary(self, etype: str, entity_id: str, obj: Any) -> dict:
        ev_repo = EvidenceRepository(self.session)
        base: dict = {"id": entity_id}
        for attr in (
            "telegram_id",
            "username",
            "display_name",
            "title",
            "bio",
            "description",
            "participants_count",
            "is_verified",
            "is_scam",
        ):
            if hasattr(obj, attr):
                base[attr] = getattr(obj, attr)
        base = {k: v for k, v in base.items() if v is not None}

        # Public presence: how many messages we've observed for a chat + IOC count.
        if etype in (EntityType.TELEGRAM_GROUP.value, EntityType.TELEGRAM_CHANNEL.value):
            base["observed_messages"] = len(
                MessageRepository(self.session).for_source(etype, entity_id, limit=1000)
            )
            base["ioc_count"] = len(IocService(self.session).for_container(etype, entity_id))
        base["evidence_count"] = len(ev_repo.for_entity(etype, entity_id))
        return base

    def _fill_message_search(self, query: str, limit: int, out: IntelResult) -> None:
        rows = MessageRepository(self.session).search_text(query, limit=limit)
        ioc_svc = IocService(self.session)
        out.items = [
            {
                "entity_type": EntityType.MESSAGE.value,
                "entity_id": m.id,
                "message_id": m.message_id,
                "text": (m.text or "")[:500],
                "author_username": m.author_username,
                "posted_at": m.posted_at.isoformat() if m.posted_at else None,
                "source_url": m.source_url,
                "iocs": [
                    {"ioc_type": i["ioc_type"], "value": i["value"]}
                    for i in ioc_svc.for_message(m.id)
                ],
            }
            for m in rows
        ]
        out.found = bool(out.items)
        if not out.items:
            out.notes.append("no matching public messages in the collected corpus for this query")

    def _persist_results(self, search_id: str, out: IntelResult) -> None:
        results: list[dict] = []
        if out.entity_id:
            results.append(
                {"entity_type": out.entity_type, "entity_id": out.entity_id, "score": 1.0}
            )
        for i, item in enumerate(out.items):
            results.append(
                {
                    "entity_type": item["entity_type"],
                    "entity_id": item["entity_id"],
                    "rank": i,
                    "score": 0.5,
                    "snippet": item.get("text", "")[:200],
                }
            )
        if results:
            self._searches.add_results(search_id, results)
