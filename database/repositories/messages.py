"""Message repository: dedup on ``(source_type, source_id, message_id)``."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select

from database.models.message import Message
from database.repositories.base import BaseRepository
from database.types import EntityType


class MessageRepository(BaseRepository[Message]):
    model = Message

    def upsert(
        self,
        *,
        source_type: EntityType | str,
        source_id: str,
        message_id: int,
        **fields: object,
    ) -> tuple[Message, bool]:
        st = str(EntityType(source_type))
        msg, created = self._get_or_create(
            source_type=st,
            source_id=source_id,
            message_id=message_id,
            defaults=fields,
        )
        if not created:
            for key, value in fields.items():
                if value is not None and getattr(msg, key, None) != value:
                    setattr(msg, key, value)
        return msg, created

    def for_source(
        self, source_type: EntityType | str, source_id: str, *, limit: int = 100
    ) -> Sequence[Message]:
        stmt = (
            select(Message)
            .where(
                Message.source_type == str(EntityType(source_type)),
                Message.source_id == source_id,
            )
            .order_by(Message.posted_at.desc().nullslast())
            .limit(limit)
        )
        return self.session.execute(stmt).scalars().all()

    def search_text(self, term: str, *, limit: int = 50) -> Sequence[Message]:
        """Naive substring search. Replaced by Postgres FTS in Phase 27."""
        pattern = f"%{term.strip()}%"
        stmt = (
            select(Message)
            .where(Message.text.ilike(pattern))
            .order_by(Message.posted_at.desc().nullslast())
            .limit(limit)
        )
        return self.session.execute(stmt).scalars().all()
