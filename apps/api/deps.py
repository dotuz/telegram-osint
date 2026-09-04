"""FastAPI dependencies: DB session, current user, RBAC.

Auth resolution order for ``current_user``:
  1. ``Authorization: Bearer <token>`` -- a real signed access token (Phase 11).
  2. ``X-User-Email`` header -- a dev-only shim, **rejected in production**,
     that resolves/creates a user by email. Kept so local dev and the test
     suite don't need a login round-trip.

The dependency returns a light ``Principal`` (email + optional id + role);
endpoints call :func:`resolve_user` inside their own session.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from fastapi import Header, HTTPException
from sqlalchemy.orm import Session

from database.models.user import User
from database.repositories import UserRepository
from database.session import get_sessionmaker
from database.types import Role
from security.auth import TokenError, decode_access_token
from security.config import get_settings

_DEV_DEFAULT_EMAIL = "analyst@local"


@dataclass(frozen=True)
class Principal:
    email: str | None
    user_id: str | None = None
    role: str = Role.ANALYST.value

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN.value

    def __getitem__(self, key: str) -> object:  # legacy ``user["email"]`` support
        return getattr(self, key)


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
    """Collector override hook. Tests override this dependency to inject a fake source."""
    return None


def get_username_collector() -> object | None:
    """Override hook for the username-OSINT collector (tests inject fake adapters)."""
    return None


def current_user(
    authorization: str | None = Header(default=None),
    x_user_email: str | None = Header(default=None),
    x_user_role: str | None = Header(default=None),
) -> Principal:
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        try:
            claims = decode_access_token(token)
        except TokenError as exc:
            raise HTTPException(status_code=401, detail=f"invalid token: {exc}") from exc
        return Principal(
            email=None,
            user_id=str(claims["sub"]),
            role=str(claims.get("role", Role.ANALYST.value)),
        )

    settings = get_settings()
    if settings.is_production:
        raise HTTPException(status_code=401, detail="authentication required")

    role = Role.ADMIN.value if (x_user_role or "").upper() == "ADMIN" else Role.ANALYST.value
    return Principal(email=(x_user_email or _DEV_DEFAULT_EMAIL).strip().lower(), role=role)


def require_admin(principal: Principal) -> Principal:
    # NOTE: used as a plain helper by endpoints (not a Depends) so callers keep
    # one session; role from the token is trusted, role from the dev shim is not.
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="admin role required")
    return principal


def resolve_user(session: Session, principal: Principal | dict | str) -> User:
    """Resolve a :class:`Principal` (or a bare email) to a persisted ``User``."""
    repo = UserRepository(session)

    if isinstance(principal, str):
        principal = Principal(email=principal)
    elif isinstance(principal, dict):  # backwards-compat with older call sites
        principal = Principal(email=principal.get("email"), user_id=principal.get("user_id"))

    if principal.user_id:
        user = repo.get(principal.user_id)
        if user is None:
            raise HTTPException(status_code=401, detail="user not found")
        return user

    email = (principal.email or _DEV_DEFAULT_EMAIL).strip().lower()
    user = repo.get_by_email(email)
    if user is None:
        user = repo.create(email=email)
        session.flush()
    return user
