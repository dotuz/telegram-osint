"""Phase-7 API: targets, entity graph, timeline."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.deps import Principal, current_user, db_session, resolve_user
from database.repositories import TargetRepository
from database.types import TargetKind
from intelligence.entity_resolution import TargetResolver
from intelligence.relationships import GraphService
from intelligence.timeline import TimelineService

router = APIRouter(tags=["graph"])

SessionDep = Annotated[Session, Depends(db_session)]
UserDep = Annotated[Principal, Depends(current_user)]


class CreateTarget(BaseModel):
    kind: str = Field(default=TargetKind.GENERIC.value)
    value: str = Field(min_length=1, max_length=512)
    label: str | None = None


class TargetOut(BaseModel):
    id: str
    kind: str
    value: str
    label: str | None = None
    resolved_entities: list[str] = []


def _targets(session: Session, principal) -> TargetRepository:
    return TargetRepository(session, resolve_user(session, principal).id)


def _target_or_404(session: Session, principal, target_id: str):  # noqa: ANN202
    t = _targets(session, principal).get(target_id)
    if t is None:
        raise HTTPException(status_code=404, detail="target not found")
    return t


@router.get("/targets")
async def list_targets(session: SessionDep, user: UserDep) -> dict:
    rows = _targets(session, user).list()
    return {
        "targets": [{"id": t.id, "kind": t.kind, "value": t.value, "label": t.label} for t in rows]
    }


@router.post("/targets", response_model=TargetOut)
async def create_target(body: CreateTarget, session: SessionDep, user: UserDep) -> TargetOut:
    try:
        kind = TargetKind(body.kind)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"unknown target kind: {body.kind}") from exc

    repo = _targets(session, user)
    target, _ = repo.get_or_create(kind=kind, value=body.value, label=body.label)
    session.flush()
    resolution = TargetResolver(session).resolve(target)
    return TargetOut(
        id=target.id,
        kind=target.kind,
        value=target.value,
        label=target.label,
        resolved_entities=[f"{t}:{i}" for t, i in resolution.linked],
    )


@router.get("/targets/{target_id}", response_model=TargetOut)
async def get_target(target_id: str, session: SessionDep, user: UserDep) -> TargetOut:
    target = _target_or_404(session, user, target_id)
    resolved = TargetResolver(session).resolved_entities(target_id)
    return TargetOut(
        id=target.id,
        kind=target.kind,
        value=target.value,
        label=target.label,
        resolved_entities=[f"{t}:{i}" for t, i in resolved],
    )


@router.get("/targets/{target_id}/graph")
async def target_graph(
    target_id: str,
    session: SessionDep,
    user: UserDep,
    depth: int = Query(default=2, ge=1, le=3),
) -> dict:
    _target_or_404(session, user, target_id)
    return GraphService(session).for_target(target_id, depth=depth).as_dict()


@router.get("/targets/{target_id}/timeline")
async def target_timeline(target_id: str, session: SessionDep, user: UserDep) -> dict:
    _target_or_404(session, user, target_id)
    return TimelineService(session).for_target(target_id).as_dict()


@router.get("/entities/{entity_type}/{entity_id}/graph")
async def entity_graph(
    entity_type: str,
    entity_id: str,
    session: SessionDep,
    user: UserDep,
    depth: int = Query(default=1, ge=1, le=3),
) -> dict:
    return GraphService(session).neighbourhood(entity_type, entity_id, depth=depth).as_dict()


@router.get("/entities/{entity_type}/{entity_id}/timeline")
async def entity_timeline(
    entity_type: str, entity_id: str, session: SessionDep, user: UserDep
) -> dict:
    return TimelineService(session).for_entity(entity_type, entity_id).as_dict()
