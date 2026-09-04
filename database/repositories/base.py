"""Repository primitives.

Repositories are the only place that build queries against ORM models. They take
a :class:`~sqlalchemy.orm.Session` and never open transactions themselves --
the caller owns the unit of work (``session_scope`` or the FastAPI dependency).

All lookups are parameterised by SQLAlchemy; raw SQL string building is banned.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.base import Base

T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    model: type[T]

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, entity_id: str) -> T | None:
        return self.session.get(self.model, entity_id)

    def add(self, obj: T) -> T:
        self.session.add(obj)
        self.session.flush()
        return obj

    def _get_or_create(self, *, defaults: dict | None = None, **filters) -> tuple[T, bool]:
        """Return ``(instance, created)``. Safe under a unique constraint race.

        Uses a SAVEPOINT so a duplicate insert doesn't poison the outer
        transaction; on conflict it re-selects the winning row.
        """
        stmt = select(self.model).filter_by(**filters)
        existing = self.session.execute(stmt).scalar_one_or_none()
        if existing is not None:
            return existing, False

        obj = self.model(**filters, **(defaults or {}))
        try:
            with self.session.begin_nested():
                self.session.add(obj)
                self.session.flush()
            return obj, True
        except IntegrityError:
            found = self.session.execute(stmt).scalar_one_or_none()
            if found is None:  # pragma: no cover - constraint other than the filter
                raise
            return found, False
