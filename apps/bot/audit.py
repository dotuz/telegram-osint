"""Best-effort audit logging for bot actions.

A failed audit write must never break a user interaction, so every call is
wrapped and only logged on failure.
"""

from __future__ import annotations

from collections.abc import Mapping

from database.session import session_scope
from security.logging import get_logger

_log = get_logger("bot.audit")


def record(
    *,
    actor: str,
    action: str,
    resource: str | None = None,
    result: str = "success",
    metadata: Mapping[str, object] | None = None,
) -> None:
    try:
        from database.repositories import AuditRepository

        with session_scope() as session:
            AuditRepository(session).record(
                actor=actor,
                action=action,
                resource=resource,
                result=result,
                metadata=metadata,
            )
    except Exception as exc:  # noqa: BLE001 - audit must not break the handler
        _log.warning("audit_write_failed", action=action, error=str(exc))
