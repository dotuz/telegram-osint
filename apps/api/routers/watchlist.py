"""Phase-9 API: watchlist CRUD + manual poll."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.deps import (
    Principal,
    current_user,
    db_session,
    get_collector,
    get_username_collector,
    resolve_user,
)
from collectors.common.interfaces import Collector
from database.repositories import WatchlistRepository
from database.types import TargetKind
from intelligence.monitoring import WatchMonitor
from security.config import get_settings

router = APIRouter(tags=["watchlist"], prefix="/watchlist")

SessionDep = Annotated[Session, Depends(db_session)]
UserDep = Annotated[Principal, Depends(current_user)]
TgCollectorDep = Annotated[Collector | None, Depends(get_collector)]
UserCollectorDep = Annotated[Collector | None, Depends(get_username_collector)]


class WatchIn(BaseModel):
    value: str = Field(min_length=1, max_length=190)
    sources: list[str] | None = None


def _repo(session: Session, principal) -> WatchlistRepository:
    return WatchlistRepository(session, resolve_user(session, principal).id)


def _row(w) -> dict:  # noqa: ANN001
    return {
        "id": w.id,
        "kind": w.kind,
        "value": w.value,
        "is_active": w.is_active,
        "last_checked_at": w.last_checked_at.isoformat() if w.last_checked_at else None,
    }


@router.get("")
async def list_watches(session: SessionDep, user: UserDep) -> dict:
    return {"watchlist": [_row(w) for w in _repo(session, user).list()]}


@router.post("")
async def add_watch(body: WatchIn, session: SessionDep, user: UserDep) -> dict:
    repo = _repo(session, user)
    limit = get_settings().rate_limit_watch_max_targets
    try:
        entry, created = repo.add(
            kind=TargetKind.USERNAME, value=body.value, sources=body.sources, max_targets=limit
        )
    except ValueError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    return {"created": created, "watch": _row(entry), "active_count": repo.count_active()}


@router.delete("/{value}")
async def remove_watch(value: str, session: SessionDep, user: UserDep) -> dict:
    removed = _repo(session, user).remove(kind=TargetKind.USERNAME, value=value)
    return {"removed": removed}


@router.post("/{watch_id}/poll")
async def poll_now(
    watch_id: str,
    session: SessionDep,
    user: UserDep,
    tg: TgCollectorDep,
    username: UserCollectorDep,
) -> dict:
    entry = _repo(session, user).get(watch_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="watch not found")
    monitor = WatchMonitor(session, telegram_collector=tg, username_collector=username)
    result = await monitor.poll(entry)
    return {
        "target": result.target,
        "activities": [a.as_dict() for a in result.activities],
        "notes": result.notes,
    }
