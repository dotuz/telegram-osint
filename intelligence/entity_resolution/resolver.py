"""Entity resolution.

Two jobs:
  * :class:`TargetResolver` -- connect a user's ``Target`` to the shared graph
    entities that represent it (``TARGET_IS_ACCOUNT`` / ``TARGET_HAS_USERNAME``),
    with evidence.
  * :func:`merge_entities` -- when two graph rows turn out to be the same thing,
    repoint every relationship / message / evidence row to the survivor and
    soft-mark the loser. The one place evidence ``entity_id`` may change.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from database.models.evidence import Evidence, allow_evidence_repointing
from database.models.message import Message
from database.models.relationship import Relationship
from database.models.target import Target
from database.normalize import normalize_username
from database.repositories import (
    EvidenceRepository,
    RelationshipRepository,
    UsernameRepository,
)
from database.repositories.entities import (
    ExternalAccountRepository,
    TelegramAccountRepository,
)
from database.types import EntityType, RelationshipType, TargetKind
from security.logging import get_logger

_log = get_logger("intelligence.entity_resolution")

_ACCOUNT_TYPES = {EntityType.TELEGRAM_ACCOUNT.value, EntityType.EXTERNAL_ACCOUNT.value}


@dataclass
class ResolutionResult:
    target_id: str
    linked: list[tuple[str, str]] = field(default_factory=list)  # (entity_type, entity_id)
    created_edges: int = 0
    notes: list[str] = field(default_factory=list)


class TargetResolver:
    def __init__(self, session: Session) -> None:
        self.session = session

    def resolve(self, target: Target) -> ResolutionResult:
        """Find graph entities matching the target and link them."""
        result = ResolutionResult(target_id=target.id)
        kind = target.kind
        norm = target.value_normalized

        if kind in (TargetKind.TELEGRAM_USER.value, TargetKind.TELEGRAM_ID.value):
            self._resolve_telegram(target, norm, result)
        elif kind == TargetKind.USERNAME.value:
            self._resolve_username(target, norm, result)
        elif kind == TargetKind.GENERIC.value:
            self._resolve_telegram(target, norm, result)
            self._resolve_username(target, norm, result)
        else:
            result.notes.append(f"no resolver for target kind {kind!r}")
        return result

    def link(
        self,
        target_id: str,
        entity_type: str,
        entity_id: str,
        *,
        rel_type: str | None = None,
        confidence: int = 70,
    ) -> bool:
        rt = rel_type or self._rel_type_for(entity_type)
        if rt is None:
            return False
        _, created = RelationshipRepository(self.session).observe(
            source_type=EntityType.TARGET.value,
            source_id=target_id,
            target_type=entity_type,
            target_id=entity_id,
            rel_type=rt,
            confidence=confidence,
        )
        EvidenceRepository(self.session).record(
            entity_type=EntityType.TARGET.value,
            entity_id=target_id,
            field="resolution",
            value={"linked": f"{entity_type}:{entity_id}", "via": rt},
            source="intelligence",
            source_type="entity_resolution",
            extraction_method="target_resolver",
            confidence=confidence,
        )
        return created

    def resolved_entities(self, target_id: str) -> list[tuple[str, str]]:
        rows = self.session.execute(
            select(Relationship.target_type, Relationship.target_id).where(
                Relationship.source_type == EntityType.TARGET.value,
                Relationship.source_id == target_id,
                Relationship.rel_type.in_(
                    (
                        RelationshipType.TARGET_IS_ACCOUNT.value,
                        RelationshipType.TARGET_HAS_USERNAME.value,
                    )
                ),
            )
        ).all()
        return [(t, i) for t, i in rows]

    # ------------------------------------------------------------------ internal
    def _rel_type_for(self, entity_type: str) -> str | None:
        if entity_type in _ACCOUNT_TYPES:
            return RelationshipType.TARGET_IS_ACCOUNT.value
        if entity_type == EntityType.USERNAME.value:
            return RelationshipType.TARGET_HAS_USERNAME.value
        return None

    def _resolve_telegram(self, target: Target, norm: str, result: ResolutionResult) -> None:
        from database.models.telegram import TelegramAccount

        obj = None
        if target.kind == TargetKind.TELEGRAM_ID.value and target.value.lstrip("-").isdigit():
            obj = self.session.execute(
                select(TelegramAccount).where(TelegramAccount.telegram_id == int(target.value))
            ).scalar_one_or_none()
        if obj is None:
            obj = self.session.execute(
                select(TelegramAccount).where(
                    TelegramAccount.username_normalized == normalize_username(norm)
                )
            ).scalar_one_or_none()
        if obj is None:
            result.notes.append("no telegram account collected for this target yet")
            return
        if self.link(target.id, EntityType.TELEGRAM_ACCOUNT.value, obj.id, confidence=75):
            result.created_edges += 1
        result.linked.append((EntityType.TELEGRAM_ACCOUNT.value, obj.id))

    def _resolve_username(self, target: Target, norm: str, result: ResolutionResult) -> None:
        handle = normalize_username(norm)
        uname, _ = UsernameRepository(self.session).get_or_create("generic", handle)
        if self.link(target.id, EntityType.USERNAME.value, uname.id, confidence=60):
            result.created_edges += 1
        result.linked.append((EntityType.USERNAME.value, uname.id))

        # link every account already discovered under that handle
        tg = (
            self.session.execute(
                select(TelegramAccountRepository.model).where(
                    TelegramAccountRepository.model.username_normalized == handle
                )
            )
            .scalars()
            .all()
        )
        ext = (
            self.session.execute(
                select(ExternalAccountRepository.model).where(
                    ExternalAccountRepository.model.identifier_normalized == handle
                )
            )
            .scalars()
            .all()
        )
        for tg_obj in tg:
            if self.link(target.id, EntityType.TELEGRAM_ACCOUNT.value, tg_obj.id, confidence=55):
                result.created_edges += 1
            result.linked.append((EntityType.TELEGRAM_ACCOUNT.value, tg_obj.id))
        for ext_obj in ext:
            if self.link(target.id, EntityType.EXTERNAL_ACCOUNT.value, ext_obj.id, confidence=55):
                result.created_edges += 1
            result.linked.append((EntityType.EXTERNAL_ACCOUNT.value, ext_obj.id))


@dataclass
class MergeResult:
    kept: str
    dropped: str
    relationships_repointed: int = 0
    messages_repointed: int = 0
    evidence_repointed: int = 0


def merge_entities(
    session: Session,
    *,
    keep: tuple[str, str],
    drop: tuple[str, str],
) -> MergeResult:
    """Repoint every reference from ``drop`` (entity_type, id) onto ``keep``.

    Relationship edges that would become self-loops or duplicates are removed.
    """
    if keep[0] != drop[0]:
        raise ValueError("cannot merge entities of different types")
    keep_type, keep_id = keep
    drop_type, drop_id = drop
    if keep_id == drop_id:
        raise ValueError("keep and drop are the same entity")

    res = MergeResult(kept=f"{keep_type}:{keep_id}", dropped=f"{drop_type}:{drop_id}")

    # relationships
    rels = (
        session.execute(
            select(Relationship).where(
                ((Relationship.source_type == drop_type) & (Relationship.source_id == drop_id))
                | ((Relationship.target_type == drop_type) & (Relationship.target_id == drop_id))
            )
        )
        .scalars()
        .all()
    )
    repo = RelationshipRepository(session)
    for rel in rels:
        s_type, s_id = rel.source_type, rel.source_id
        t_type, t_id = rel.target_type, rel.target_id
        if (s_type, s_id) == (drop_type, drop_id):
            s_type, s_id = keep_type, keep_id
        if (t_type, t_id) == (drop_type, drop_id):
            t_type, t_id = keep_type, keep_id
        session.delete(rel)
        session.flush()
        if (s_type, s_id) != (t_type, t_id):
            repo.observe(
                source_type=s_type,
                source_id=s_id,
                target_type=t_type,
                target_id=t_id,
                rel_type=rel.rel_type,
                confidence=rel.confidence,
            )
        res.relationships_repointed += 1

    # messages sourced from (container) or authored by the dropped entity
    sourced = session.execute(
        update(Message)
        .where(Message.source_type == drop_type, Message.source_id == drop_id)
        .values(source_id=keep_id, source_type=keep_type)
    )
    authored = session.execute(
        update(Message)
        .where(Message.author_account_id == drop_id)
        .values(author_account_id=keep_id)
    )
    res.messages_repointed = int(getattr(sourced, "rowcount", 0) or 0) + int(
        getattr(authored, "rowcount", 0) or 0
    )

    # evidence (the sanctioned repointing)
    ev_rows = (
        session.execute(
            select(Evidence).where(Evidence.entity_type == drop_type, Evidence.entity_id == drop_id)
        )
        .scalars()
        .all()
    )
    with allow_evidence_repointing():
        for ev in ev_rows:
            ev.entity_id = keep_id
            ev.entity_type = keep_type
        session.flush()
    res.evidence_repointed = len(ev_rows)

    _log.info(
        "entities_merged",
        kept=res.kept,
        dropped=res.dropped,
        rels=res.relationships_repointed,
        msgs=res.messages_repointed,
        ev=res.evidence_repointed,
    )
    return res
