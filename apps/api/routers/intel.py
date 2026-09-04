"""Phase-4 API: public Telegram intelligence + search history + source health."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.deps import Principal, current_user, db_session, get_collector, resolve_user
from collectors.common.interfaces import Collector
from collectors.common.registry import registry
from intelligence.search import IntelResult, TelegramIntelService

router = APIRouter(tags=["telegram-intel"])

SessionDep = Annotated[Session, Depends(db_session)]
UserDep = Annotated[Principal, Depends(current_user)]
CollectorDep = Annotated[Collector | None, Depends(get_collector)]


class Query(BaseModel):
    query: str = Field(min_length=1, max_length=512)


class MessageQuery(Query):
    limit: int = Field(default=25, ge=1, le=100)


class IntelResponse(BaseModel):
    kind: str
    found: bool
    entity_type: str | None = None
    entity_id: str | None = None
    summary: dict = {}
    items: list[dict] = []
    notes: list[str] = []
    search_id: str | None = None
    source_available: bool = True


def _svc(session: Session, principal, collector: Collector | None = None) -> TelegramIntelService:
    user = resolve_user(session, principal)
    return TelegramIntelService(session, user.id, collector=collector)


def _to_response(result: IntelResult) -> IntelResponse:
    return IntelResponse(
        kind=result.kind,
        found=result.found,
        entity_type=result.entity_type,
        entity_id=result.entity_id,
        summary=result.summary,
        items=result.items,
        notes=result.notes,
        search_id=result.search_id,
        source_available=result.source_available,
    )


@router.post("/telegram/user", response_model=IntelResponse)
async def telegram_user(
    body: Query, session: SessionDep, user: UserDep, collector: CollectorDep
) -> IntelResponse:
    return _to_response(await _svc(session, user, collector).search_user(body.query))


@router.post("/telegram/group", response_model=IntelResponse)
async def telegram_group(
    body: Query, session: SessionDep, user: UserDep, collector: CollectorDep
) -> IntelResponse:
    return _to_response(await _svc(session, user, collector).group_intel(body.query))


@router.post("/telegram/channel", response_model=IntelResponse)
async def telegram_channel(
    body: Query, session: SessionDep, user: UserDep, collector: CollectorDep
) -> IntelResponse:
    return _to_response(await _svc(session, user, collector).channel_intel(body.query))


@router.post("/telegram/messages", response_model=IntelResponse)
async def telegram_messages(
    body: MessageQuery, session: SessionDep, user: UserDep, collector: CollectorDep
) -> IntelResponse:
    svc = _svc(session, user, collector)
    return _to_response(await svc.search_messages(body.query, limit=body.limit))


@router.get("/searches")
async def search_history(session: SessionDep, user: UserDep) -> dict:
    return {"searches": _svc(session, user).history(limit=50)}


@router.get("/sources/health")
async def sources_health() -> dict:
    checks = await registry.health()
    return {"sources": [{"name": c.name, "healthy": c.healthy, "detail": c.detail} for c in checks]}
