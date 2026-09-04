"""Audit-log repository (append-only)."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models.audit_log import AuditLog

# Keys that must never be persisted into the audit metadata blob.
_FORBIDDEN_KEYS = {
    "password",
    "passwd",
    "secret",
    "token",
    "otp",
    "code",
    "cookie",
    "session",
    "api_key",
    "apikey",
    "authorization",
    "auth",
    "bearer",
}


def _scrub(metadata: Mapping[str, object] | None) -> str | None:
    if not metadata:
        return None
    cleaned = {
        k: ("<redacted>" if k.lower() in _FORBIDDEN_KEYS else v) for k, v in metadata.items()
    }
    return json.dumps(cleaned, default=str, separators=(",", ":"))


class AuditRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def record(
        self,
        *,
        actor: str,
        action: str,
        resource: str | None = None,
        result: str = "success",
        ip_metadata: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            actor=actor,
            action=action,
            resource=resource,
            result=result,
            ip_metadata=ip_metadata,
            metadata_json=_scrub(metadata),
        )
        self._session.add(entry)
        self._session.flush()
        return entry

    def recent(self, *, limit: int = 100, actor: str | None = None) -> Sequence[AuditLog]:
        stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
        if actor is not None:
            stmt = stmt.where(AuditLog.actor == actor)
        return self._session.execute(stmt).scalars().all()
