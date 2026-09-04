"""FastAPI dependencies.

``current_user`` is a **development shim** until Phase 11/12 auth lands: it
resolves a user from the ``X-User-Email`` header (default ``analyst@local``) and
creates one on first use. Real session/JWT auth + RBAC replaces this.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Header
from sqlalchemy.orm import Session

from database.models.user import User
from database.repositories import UserRepository
from database.session import get_sessionmaker

_DEV_DEFAULT_EMAIL = "analyst@local"


def db_session() -> Iterator[Session]:
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_collector() -> object | None:
    """Collector override hook. Returns ``None`` -> the service builds the default
    Telegram collector. Tests override this dependency to inject a fake source."""
    return None


def current_user(
    x_user_email: str | None = Header(default=None),
) -> dict[str, str]:
    """Return ``{"email": ...}`` for the caller. Resolution to a row happens in
    the endpoint's session so we don't leak a session from a dependency."""
    return {"email": (x_user_email or _DEV_DEFAULT_EMAIL).strip().lower()}


def resolve_user(session: Session, email: str) -> User:
    repo = UserRepository(session)
    user = repo.get_by_email(email)
    if user is None:
        user = repo.create(email=email)
        session.flush()
    return user
