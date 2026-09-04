"""Watchlist monitoring.

For each active watchlist entry, re-collect the target's **public** presence,
compare against the entry's ``last_seen_marker``, and emit an :class:`Activity`
per genuinely new public event. Markers are updated so the next poll doesn't
re-notify.

Only public sources are polled. Nothing here touches private content.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from collectors.common.interfaces import Collector, CollectRequest
from collectors.telegram.collector import KIND_GROUP, TelegramPublicCollector
from database.base import utcnow
from database.models.message import Message
from database.models.telegram import TelegramChannel, TelegramGroup
from database.models.watchlist import Watchlist
from database.normalize import normalize_username
from database.types import EntityType
from intelligence.ingest import IngestionService
from security.logging import get_logger

_log = get_logger("intelligence.monitoring")


@dataclass
class Activity:
    source: str  # human label, e.g. "Public Channel"
    kind: str  # "message" | "account" | "profile"
    detail: str
    when: datetime | None = None
    reference: str | None = None

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "kind": self.kind,
            "detail": self.detail,
            "when": self.when.isoformat() if self.when else None,
            "reference": self.reference,
        }


@dataclass
class PollResult:
    watchlist_id: str
    target: str
    activities: list[Activity] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class WatchMonitor:
    def __init__(
        self,
        session: Session,
        *,
        telegram_collector: Collector | None = None,
        username_collector: Collector | None = None,
    ) -> None:
        self.session = session
        self.telegram_collector = telegram_collector or TelegramPublicCollector()
        self.username_collector = username_collector

    async def poll(self, entry: Watchlist) -> PollResult:
        handle = normalize_username(entry.value_normalized or entry.value)
        marker = json.loads(entry.last_seen_marker or "{}")
        result = PollResult(watchlist_id=entry.id, target=f"@{handle}")

        await self._poll_telegram(handle, marker, result)
        await self._poll_username_platforms(entry, handle, marker, result)

        entry.last_seen_marker = json.dumps(marker)
        entry.last_checked_at = utcnow()
        self.session.flush()
        return result

    # ------------------------------------------------------------------ telegram
    async def _poll_telegram(self, handle: str, marker: dict, result: PollResult) -> None:
        collected = await self.telegram_collector.run(
            CollectRequest(query=handle, kind=KIND_GROUP, limit=50)
        )
        if collected.error:
            result.notes.append(collected.error)
            return
        IngestionService(self.session).ingest(collected)

        norm = normalize_username(handle)
        container = (
            self.session.execute(
                select(TelegramChannel).where(TelegramChannel.username_normalized == norm)
            ).scalar_one_or_none()
            or self.session.execute(
                select(TelegramGroup).where(TelegramGroup.username_normalized == norm)
            ).scalar_one_or_none()
        )
        if container is None:
            return

        is_channel = isinstance(container, TelegramChannel)
        etype = EntityType.TELEGRAM_CHANNEL.value if is_channel else EntityType.TELEGRAM_GROUP.value
        label = "Public Channel" if is_channel else "Public Group"

        seen_max = int(marker.get("telegram_max_msg_id", 0))
        rows = (
            self.session.execute(
                select(Message)
                .where(Message.source_type == etype, Message.source_id == container.id)
                .order_by(Message.message_id)
            )
            .scalars()
            .all()
        )

        new_max = seen_max
        for m in rows:
            if m.message_id <= seen_max:
                continue
            new_max = max(new_max, m.message_id)
            result.activities.append(
                Activity(
                    source=label,
                    kind="message",
                    detail=(m.text or "New public message detected.")[:200],
                    when=m.posted_at,
                    reference=m.source_url,
                )
            )
        marker["telegram_max_msg_id"] = new_max

    # ------------------------------------------------------------------ platforms
    async def _poll_username_platforms(
        self, entry: Watchlist, handle: str, marker: dict, result: PollResult
    ) -> None:
        if self.username_collector is None:
            return
        collected = await self.username_collector.run(
            CollectRequest(query=handle, kind="username_osint")
        )
        if collected.error:
            result.notes.append(collected.error)
            return
        IngestionService(self.session).ingest(collected)

        known: set[str] = set(marker.get("platforms", []))
        found: set[str] = {
            str(rec.natural_key["platform"])
            for rec in collected.records
            if rec.entity_type == EntityType.EXTERNAL_ACCOUNT.value
            and rec.natural_key.get("platform")
        }
        for platform in sorted(found - known):
            result.activities.append(
                Activity(
                    source=str(platform).capitalize(),
                    kind="account",
                    detail=f"New public account discovered for this handle on {platform}.",
                )
            )
        marker["platforms"] = sorted(known | found)


# --------------------------------------------------------------------------- scheduling


def due_watchlist_ids(session: Session, *, interval_seconds: int, limit: int = 200) -> list[str]:
    """Active entries never checked, or last checked longer ago than ``interval``."""
    from datetime import timedelta

    cutoff = utcnow() - timedelta(seconds=interval_seconds)
    rows = (
        session.execute(
            select(Watchlist.id)
            .where(
                Watchlist.is_active.is_(True),
                (Watchlist.last_checked_at.is_(None)) | (Watchlist.last_checked_at < cutoff),
            )
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return list(rows)


def mark_scheduled(session: Session, watchlist_id: str) -> None:
    """Optimistically stamp ``last_checked_at`` so a slow poll isn't re-enqueued."""
    entry = session.get(Watchlist, watchlist_id)
    if entry is not None:
        entry.last_checked_at = utcnow()
        session.flush()
