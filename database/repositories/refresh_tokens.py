"""Refresh-token repository: issue, rotate (revoke + reissue), revoke."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.base import utcnow
from database.models.refresh_token import RefreshToken
from database.models.user import User
from security.auth import hash_refresh_token, new_refresh_token
from security.config import get_settings


class RefreshTokenReuseError(RuntimeError):
    """A revoked/unknown refresh token was presented -- possible theft."""


class RefreshTokenRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def issue(
        self, user: User, *, user_agent: str | None = None, ip_metadata: str | None = None
    ) -> str:
        raw, digest = new_refresh_token()
        ttl = get_settings().refresh_token_ttl_seconds
        self.session.add(
            RefreshToken(
                user_id=user.id,
                token_hash=digest,
                expires_at=utcnow() + timedelta(seconds=ttl),
                user_agent=(user_agent or "")[:255] or None,
                ip_metadata=ip_metadata,
            )
        )
        self.session.flush()
        return raw

    def _get(self, raw: str) -> RefreshToken | None:
        return self.session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw))
        ).scalar_one_or_none()

    def rotate(
        self, raw: str, *, user_agent: str | None = None, ip_metadata: str | None = None
    ) -> tuple[str, User]:
        row = self._get(raw)
        if row is None:
            raise RefreshTokenReuseError("unknown refresh token")
        if not row.is_active:
            # Presenting a revoked token: nuke the whole family for that user.
            self.revoke_all(row.user_id)
            raise RefreshTokenReuseError("refresh token already used or expired")

        user = self.session.get(User, row.user_id)
        if user is None or not user.is_active:
            raise RefreshTokenReuseError("user unavailable")

        new_raw = self.issue(user, user_agent=user_agent, ip_metadata=ip_metadata)
        new_row = self._get(new_raw)
        row.revoked_at = utcnow()
        row.replaced_by = new_row.id if new_row else None
        self.session.flush()
        return new_raw, user

    def revoke(self, raw: str) -> bool:
        row = self._get(raw)
        if row is None or row.revoked_at is not None:
            return False
        row.revoked_at = utcnow()
        self.session.flush()
        return True

    def revoke_all(self, user_id: str) -> int:
        rows = (
            self.session.execute(
                select(RefreshToken).where(
                    RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
                )
            )
            .scalars()
            .all()
        )
        now = utcnow()
        for r in rows:
            r.revoked_at = now
        self.session.flush()
        return len(rows)
