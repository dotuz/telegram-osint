"""Per-user Investigation repository (BOLA guard at the data layer)."""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select

from database.base import utcnow
from database.models.investigation import Investigation, InvestigationObservation
from database.repositories.investigations import ScopedRepository
from database.types import InvestigationStatus, TargetKind


def _detect_target_type(raw: str) -> str:
    v = raw.strip().lstrip("@")
    if v.isdigit():
        return TargetKind.TELEGRAM_ID.value
    return TargetKind.TELEGRAM_USER.value


class InvestigationRepository(ScopedRepository):
    def get(self, investigation_id: str) -> Investigation | None:
        stmt = select(Investigation).where(
            Investigation.id == investigation_id,
            Investigation.user_id == self.user_id,
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def get_by_public_id(self, public_id: str) -> Investigation | None:
        stmt = select(Investigation).where(
            Investigation.public_id == public_id.strip().upper(),
            Investigation.user_id == self.user_id,
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def list(self, *, limit: int = 50) -> Sequence[Investigation]:
        stmt = (
            select(Investigation)
            .where(Investigation.user_id == self.user_id)
            .order_by(Investigation.created_at.desc())
            .limit(limit)
        )
        return self.session.execute(stmt).scalars().all()

    @staticmethod
    def _new_public_id() -> str:
        # Short, readable, collision-free without a DB round-trip or a race.
        return "INV-" + secrets.token_hex(4).upper()

    def create(self, *, target: str, target_normalized: str) -> Investigation:
        inv = Investigation(
            user_id=self.user_id,
            public_id=self._new_public_id(),
            target=target.strip(),
            target_type=_detect_target_type(target),
            target_normalized=target_normalized,
            status=InvestigationStatus.QUEUED.value,
        )
        self.session.add(inv)
        self.session.flush()
        return inv

    def set_status(
        self,
        investigation_id: str,
        status: InvestigationStatus,
        *,
        error: str | None = None,
    ) -> None:
        inv = self.get(investigation_id)
        if inv is None:
            return
        inv.status = status.value
        if status is InvestigationStatus.RUNNING and inv.started_at is None:
            inv.started_at = utcnow()
        if status.is_terminal:
            inv.completed_at = utcnow()
        if error:
            inv.error = error
        self.session.flush()

    def add_observation(
        self,
        *,
        investigation_id: str,
        observation_type: str,
        resource_kind: str,
        resource_ref: str,
        source: str,
        confidence: int,
        resource_url: str | None = None,
        message_ref: str | None = None,
        snippet: str | None = None,
        observed_at: datetime | None = None,
        evidence_id: str | None = None,
    ) -> InvestigationObservation:
        obs = InvestigationObservation(
            investigation_id=investigation_id,
            observation_type=observation_type,
            resource_kind=resource_kind,
            resource_ref=resource_ref,
            resource_url=resource_url,
            message_ref=message_ref,
            snippet=snippet,
            observed_at=observed_at,
            source=source,
            confidence=confidence,
            evidence_id=evidence_id,
        )
        self.session.add(obs)
        self.session.flush()
        return obs

    def observations(self, investigation_id: str) -> Sequence[InvestigationObservation]:
        stmt = (
            select(InvestigationObservation)
            .where(InvestigationObservation.investigation_id == investigation_id)
            .order_by(
                InvestigationObservation.observed_at.is_(None),
                InvestigationObservation.observed_at,
            )
        )
        return self.session.execute(stmt).scalars().all()
