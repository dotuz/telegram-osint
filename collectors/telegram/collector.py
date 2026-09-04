"""Public Telegram collector.

Request kinds:
  * ``telegram_user``            -- public profile for an @username / id
  * ``telegram_group``           -- public group metadata + recent public messages
  * ``telegram_channel``         -- public channel metadata + recent public posts
  * ``telegram_message_search``  -- search public messages (source-dependent)
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Mapping
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
from collectors.telegram.source import (
    TelegramSource,
    build_source,
)
from database.normalize import normalize_username
from database.types import EntityType, RelationshipType, SourceType

KIND_USER = "telegram_user"
KIND_GROUP = "telegram_group"
KIND_CHANNEL = "telegram_channel"
KIND_MESSAGE_SEARCH = "telegram_message_search"

_URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.IGNORECASE)
_MENTION_RE = re.compile(r"(?<![\w@])@([A-Za-z][A-Za-z0-9_]{3,31})")


class TelegramPublicCollector(Collector):
    name = "telegram_public"
    source_type = SourceType.TELEGRAM_PUBLIC.value
    supported_kinds = frozenset({KIND_USER, KIND_GROUP, KIND_CHANNEL, KIND_MESSAGE_SEARCH})

    def __init__(self, source: TelegramSource | None = None) -> None:
        self.source: TelegramSource = source or build_source()

    # ------------------------------------------------------------------ collect
    async def collect(self, request: CollectRequest) -> RawBundle:
        if not await self.source.available():
            return RawBundle(
                kind=request.kind,
                source=self.source_type,
                error="no public Telegram source is configured",
            )

        handle = request.query.strip()
        if request.kind == KIND_USER:
            profile = await self.source.get_profile(handle)
            if profile is None:
                return RawBundle(
                    kind=request.kind,
                    source=self.source_type,
                    notes=("no public profile data available for this identifier",),
                )
            return RawBundle(
                kind=request.kind,
                source=self.source_type,
                payload=[{"type": "profile", **dataclasses.asdict(profile)}],
            )

        if request.kind in (KIND_GROUP, KIND_CHANNEL):
            chat = await self.source.get_chat(handle)
            if chat is None:
                return RawBundle(
                    kind=request.kind,
                    source=self.source_type,
                    notes=("no public data available for this chat",),
                )
            payload: list[dict[str, Any]] = [{"type": "chat", **dataclasses.asdict(chat)}]
            notes: tuple[str, ...] = ()
            msgs = await self.source.get_messages(handle, limit=request.limit, since=request.since)
            if not msgs:
                notes = ("message history is not publicly readable via this source",)
            payload += [{"type": "message", **dataclasses.asdict(m)} for m in msgs]
            return RawBundle(
                kind=request.kind, source=self.source_type, payload=payload, notes=notes
            )

        # KIND_MESSAGE_SEARCH
        msgs = await self.source.search_messages(handle, limit=request.limit)
        notes = () if msgs else ("message search returned nothing for this source",)
        return RawBundle(
            kind=request.kind,
            source=self.source_type,
            payload=[{"type": "message", **dataclasses.asdict(m)} for m in msgs],
            notes=notes,
        )

    # --------------------------------------------------------------- normalize
    def normalize(self, raw: RawBundle) -> list[NormalizedRecord]:
        records: list[NormalizedRecord] = []
        # Synthesise a container record per distinct chat referenced by messages
        # that have no explicit chat in the payload (e.g. message search).
        have_chat = any(item.get("type") == "chat" for item in raw.payload)
        synth_containers: dict[str, NormalizedRecord] = {}

        for i, item in enumerate(raw.payload):
            kind = item.get("type")
            if kind == "profile":
                records.append(self._normalize_profile(item, i))
            elif kind == "chat":
                records.append(self._normalize_chat(item, raw.kind, i))
            elif kind == "message":
                if not have_chat and item.get("chat_username"):
                    key = normalize_username(item["chat_username"])
                    if key not in synth_containers:
                        synth_containers[key] = NormalizedRecord(
                            ref=f"chat-synth-{len(synth_containers)}",
                            entity_type=EntityType.TELEGRAM_CHANNEL.value,
                            natural_key={"username_normalized": key},
                            attributes={
                                "username": item["chat_username"],
                                "username_normalized": key,
                            },
                            evidence=(),
                        )
                rec = self._normalize_message(
                    item,
                    i,
                    synth_containers.get(
                        normalize_username(item["chat_username"])
                        if item.get("chat_username")
                        else ""
                    ),
                )
                if rec is not None:
                    records.append(rec)

        return list(synth_containers.values()) + records

    def relationships(
        self, raw: RawBundle, records: list[NormalizedRecord]
    ) -> list[RelationshipDraft]:
        rels: list[RelationshipDraft] = []
        containers = {
            r.ref: r
            for r in records
            if r.entity_type in (EntityType.TELEGRAM_GROUP.value, EntityType.TELEGRAM_CHANNEL.value)
        }
        single_container = next(iter(containers), None) if len(containers) == 1 else None

        for rec in records:
            if rec.entity_type != EntityType.MESSAGE.value:
                continue
            container_ref = rec.attributes.get("_container_ref") or single_container
            if container_ref is None:
                continue
            container = containers.get(container_ref)
            is_channel = raw.kind == KIND_CHANNEL or (
                container is not None and container.entity_type == EntityType.TELEGRAM_CHANNEL.value
            )
            rel = (
                RelationshipType.MESSAGE_IN_CHANNEL.value
                if is_channel
                else RelationshipType.MESSAGE_IN_GROUP.value
            )
            rels.append(RelationshipDraft(rec.ref, container_ref, rel, confidence=90))
        return rels

    # ------------------------------------------------------------------ health
    async def health_check(self) -> HealthStatus:
        try:
            ok = await self.source.available()
        except Exception as exc:  # noqa: BLE001
            return HealthStatus(name=self.name, healthy=False, detail=str(exc))
        return HealthStatus(
            name=self.name,
            healthy=ok,
            detail=f"source={getattr(self.source, 'name', '?')}" + ("" if ok else " (unavailable)"),
        )

    # ---------------------------------------------------------------- internals
    def _ev(self, ref: str, field: str, value: Any, reference: str | None, conf: int = 80):
        return EvidenceDraft(
            ref=ref,
            field=field,
            value=value,
            source=self.source_type,
            source_type="telegram",
            reference=reference,
            confidence=conf,
            raw=f"{field}={value!r}",
            extraction_method="telegram_public_collector",
        )

    def _normalize_profile(self, item: Mapping[str, Any], idx: int) -> NormalizedRecord:
        ref = f"account-{idx}"
        username = item.get("username")
        nk: dict[str, Any] = {}
        if item.get("telegram_id") is not None:
            nk["telegram_id"] = item["telegram_id"]
        if username:
            nk["username_normalized"] = normalize_username(username)
        attrs = {
            k: item.get(k)
            for k in ("display_name", "bio", "is_bot", "is_verified", "is_scam", "photo_reference")
            if item.get(k) is not None
        }
        if username:
            attrs["username"] = username
            attrs["username_normalized"] = normalize_username(username)
        reference = item.get("reference")
        ev = tuple(
            self._ev(ref, f, v, reference)
            for f, v in attrs.items()
            if f not in ("username_normalized",)
        )
        return NormalizedRecord(
            ref=ref,
            entity_type=EntityType.TELEGRAM_ACCOUNT.value,
            natural_key=nk,
            attributes=attrs,
            evidence=ev,
        )

    def _normalize_chat(self, item: Mapping[str, Any], req_kind: str, idx: int) -> NormalizedRecord:
        is_channel = item.get("chat_type") == "channel" or req_kind == KIND_CHANNEL
        etype = EntityType.TELEGRAM_CHANNEL.value if is_channel else EntityType.TELEGRAM_GROUP.value
        ref = f"chat-{idx}"
        username = item.get("username")
        nk: dict[str, Any] = {}
        if item.get("telegram_id") is not None:
            nk["telegram_id"] = item["telegram_id"]
        if username:
            nk["username_normalized"] = normalize_username(username)
        attrs = {
            k: item.get(k)
            for k in ("title", "description", "participants_count", "is_public")
            if item.get(k) is not None
        }
        if username:
            attrs["username"] = username
            attrs["username_normalized"] = normalize_username(username)
        reference = item.get("reference")
        ev = tuple(
            self._ev(ref, f, v, reference) for f, v in attrs.items() if f != "username_normalized"
        )
        return NormalizedRecord(
            ref=ref, entity_type=etype, natural_key=nk, attributes=attrs, evidence=ev
        )

    def _normalize_message(
        self, item: Mapping[str, Any], idx: int, container: NormalizedRecord | None
    ) -> NormalizedRecord | None:
        message_id = item.get("message_id")
        if message_id is None:
            return None
        ref = f"message-{idx}"
        text = item.get("text")
        urls = sorted(set(_URL_RE.findall(text or "")))
        mentions = sorted({m.lower() for m in _MENTION_RE.findall(text or "")})

        chat_username = item.get("chat_username")
        chat_key = (
            normalize_username(chat_username)
            if chat_username
            else str(item.get("chat_id") or "unknown")
        )
        # dedup key within this result; the ingestion layer maps container_ref ->
        # the real chat entity id to build the DB (source_type, source_id, msg_id).
        nk = {"container_key": chat_key, "message_id": message_id}

        attrs: dict[str, Any] = {
            "text": text,
            "posted_at": item.get("posted_at"),
            "author_username": item.get("author_username"),
            "author_id": item.get("author_id"),
            "reply_to_message_id": item.get("reply_to_message_id"),
            "forwarded_from": item.get("forwarded_from"),
            "views": item.get("views"),
            "source_url": item.get("reference"),
            "urls_json": urls or None,
            "usernames_json": mentions or None,
        }
        attrs = {k: v for k, v in attrs.items() if v is not None}
        if container is not None:
            attrs["_container_ref"] = container.ref

        ev = (self._ev(ref, "text", text, item.get("reference"), conf=85),) if text else ()
        return NormalizedRecord(
            ref=ref,
            entity_type=EntityType.MESSAGE.value,
            natural_key=nk,
            attributes=attrs,
            evidence=ev,
        )


__all__ = [
    "KIND_CHANNEL",
    "KIND_GROUP",
    "KIND_MESSAGE_SEARCH",
    "KIND_USER",
    "TelegramPublicCollector",
]
