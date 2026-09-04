"""Phase-6 API: username OSINT across public sources."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.deps import Principal, current_user, db_session, get_username_collector, resolve_user
from apps.api.security import rate_limit
from collectors.common.interfaces import Collector
from intelligence.username_osint import UsernameOsintService

router = APIRouter(
    tags=["username-osint"],
    dependencies=[Depends(rate_limit("search", limit_setting="rate_limit_search_per_minute"))],
)

SessionDep = Annotated[Session, Depends(db_session)]
UserDep = Annotated[Principal, Depends(current_user)]
CollectorDep = Annotated[Collector | None, Depends(get_username_collector)]


class UsernameQuery(BaseModel):
    username: str = Field(min_length=1, max_length=190)


class SourceHitOut(BaseModel):
    platform: str
    url: str | None = None
    entity_type: str
    entity_id: str | None = None
    confidence: int
    evidence: list[str] = []


class UsernameOsintOut(BaseModel):
    username: str
    found: bool
    sources: list[SourceHitOut] = []
    same_as_edges: list[dict] = []
    notes: list[str] = []
    search_id: str | None = None
    disclaimer: str


@router.post("/username", response_model=UsernameOsintOut)
async def username_osint(
    body: UsernameQuery, session: SessionDep, user: UserDep, collector: CollectorDep
) -> UsernameOsintOut:
    svc = UsernameOsintService(session, resolve_user(session, user).id, collector=collector)
    result = await svc.run(body.username)
    return UsernameOsintOut(
        username=result.username,
        found=result.found,
        sources=[
            SourceHitOut(
                platform=s.platform,
                url=s.url,
                entity_type=s.entity_type,
                entity_id=s.entity_id,
                confidence=s.confidence,
                evidence=s.evidence,
            )
            for s in result.sources
        ],
        same_as_edges=result.same_as_edges,
        notes=result.notes,
        search_id=result.search_id,
        disclaimer=result.disclaimer,
    )
