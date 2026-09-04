"""Phase-5 API: IOC views (per message, per container, recent)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from apps.api.deps import Principal, current_user, db_session
from database.types import EntityType, IOCType
from intelligence.ioc.service import IocService

router = APIRouter(tags=["ioc"], prefix="/iocs")

SessionDep = Annotated[Session, Depends(db_session)]
UserDep = Annotated[Principal, Depends(current_user)]

_CONTAINER_TYPES = {EntityType.TELEGRAM_CHANNEL.value, EntityType.TELEGRAM_GROUP.value}


@router.get("")
async def list_iocs(
    session: SessionDep,
    user: UserDep,
    message_id: str | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    entity_id: str | None = Query(default=None),
    ioc_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    svc = IocService(session)
    if message_id:
        return {"iocs": svc.for_message(message_id)}
    if entity_type and entity_id:
        if entity_type not in _CONTAINER_TYPES:
            return {"iocs": [], "note": "entity_type must be a telegram channel or group"}
        return {"iocs": svc.for_container(entity_type, entity_id, limit=limit)}
    if ioc_type and ioc_type not in {t.value for t in IOCType}:
        return {"iocs": [], "note": f"unknown ioc_type: {ioc_type}"}
    return {"iocs": svc.recent(limit=limit, ioc_type=ioc_type)}
