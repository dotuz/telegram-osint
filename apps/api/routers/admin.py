"""Phase-11 API: dashboard overview stats + audit log (admin)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.deps import Principal, current_user, db_session, require_admin, resolve_user
from database.models import (
    IOC,
    Evidence,
    Job,
    Relationship,
    TelegramAccount,
    User,
    Watchlist,
)
from database.repositories import (
    AuditRepository,
    ReportRepository,
    SearchRepository,
    TargetRepository,
    WatchlistRepository,
)

router = APIRouter(tags=["admin"])

SessionDep = Annotated[Session, Depends(db_session)]
UserDep = Annotated[Principal, Depends(current_user)]


def _count(session: Session, model) -> int:  # noqa: ANN001
    return int(session.execute(select(func.count()).select_from(model)).scalar() or 0)


@router.get("/stats")
async def stats(session: SessionDep, user: UserDep) -> dict:
    me = resolve_user(session, user)
    return {
        "me": {
            "targets": len(TargetRepository(session, me.id).list(limit=10_000)),
            "searches": len(SearchRepository(session, me.id).list(limit=10_000)),
            "reports": len(ReportRepository(session, me.id).list(limit=10_000)),
            "watches": WatchlistRepository(session, me.id).count_active(),
        },
        "graph": {
            "telegram_accounts": _count(session, TelegramAccount),
            "iocs": _count(session, IOC),
            "relationships": _count(session, Relationship),
            "evidence": _count(session, Evidence),
        },
        "jobs_by_state": {
            str(s): int(c)
            for s, c in session.execute(select(Job.state, func.count()).group_by(Job.state)).all()
        },
        "platform": {
            "users": _count(session, User),
            "watchlist_entries": _count(session, Watchlist),
        }
        if user.is_admin
        else {},
    }


@router.get("/audit")
async def audit_log(session: SessionDep, user: UserDep, limit: int = 100) -> dict:
    require_admin(user)
    rows = AuditRepository(session).recent(limit=min(500, max(1, limit)))
    return {
        "audit": [
            {
                "id": a.id,
                "actor": a.actor,
                "action": a.action,
                "resource": a.resource,
                "result": a.result,
                "metadata": a.metadata_json,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in rows
        ]
    }
