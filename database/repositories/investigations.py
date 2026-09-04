"""Per-user (workspace-scoped) repositories: Target, Search, Watchlist, Report.

Every query is filtered by ``user_id``. Methods take an id supplied by a client
and return ``None`` (not another user's row) when it belongs to someone else --
this is the BOLA/IDOR guard at the data layer, re-checked in the API layer.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models.report import Report
from database.models.search import Search, SearchResult
from database.models.target import Target
from database.models.watchlist import Watchlist
from database.normalize import normalize_domain, normalize_email, normalize_username
from database.types import SearchKind, TargetKind, TaskStatus


def _normalize_for_kind(kind: str, value: str) -> str:
    match kind:
        case TargetKind.DOMAIN.value:
            return normalize_domain(value)
        case TargetKind.EMAIL.value:
            return normalize_email(value)
        case TargetKind.TELEGRAM_ID.value:
            return value.strip()
        case _:
            return normalize_username(value)


class ScopedRepository:
    def __init__(self, session: Session, user_id: str) -> None:
        if not user_id:
            raise ValueError("user_id is required for a scoped repository")
        self.session = session
        self.user_id = user_id


class TargetRepository(ScopedRepository):
    def get(self, target_id: str) -> Target | None:
        stmt = select(Target).where(
            Target.id == target_id,
            Target.user_id == self.user_id,
            Target.deleted_at.is_(None),
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def list(self, *, limit: int = 100) -> Sequence[Target]:
        stmt = (
            select(Target)
            .where(Target.user_id == self.user_id, Target.deleted_at.is_(None))
            .order_by(Target.created_at.desc())
            .limit(limit)
        )
        return self.session.execute(stmt).scalars().all()

    def get_or_create(
        self, *, kind: TargetKind | str, value: str, label: str | None = None
    ) -> tuple[Target, bool]:
        k = str(TargetKind(kind))
        norm = _normalize_for_kind(k, value)
        stmt = select(Target).where(
            Target.user_id == self.user_id,
            Target.kind == k,
            Target.value_normalized == norm,
        )
        existing = self.session.execute(stmt).scalar_one_or_none()
        if existing is not None:
            if existing.deleted_at is not None:
                existing.deleted_at = None
            return existing, False
        target = Target(
            user_id=self.user_id,
            kind=k,
            value=value.strip(),
            value_normalized=norm,
            label=label,
        )
        self.session.add(target)
        self.session.flush()
        return target, True

    def soft_delete(self, target_id: str) -> bool:
        target = self.get(target_id)
        if target is None:
            return False
        from database.base import utcnow

        target.deleted_at = utcnow()
        return True


class SearchRepository(ScopedRepository):
    def get(self, search_id: str) -> Search | None:
        stmt = select(Search).where(Search.id == search_id, Search.user_id == self.user_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def list(self, *, limit: int = 50) -> Sequence[Search]:
        stmt = (
            select(Search)
            .where(Search.user_id == self.user_id)
            .order_by(Search.created_at.desc())
            .limit(limit)
        )
        return self.session.execute(stmt).scalars().all()

    def create(
        self,
        *,
        kind: SearchKind | str,
        query: str,
        target_id: str | None = None,
        filters: Mapping[str, object] | None = None,
        job_id: str | None = None,
    ) -> Search:
        search = Search(
            user_id=self.user_id,
            target_id=target_id,
            kind=str(SearchKind(kind)),
            query=query.strip(),
            filters_json=json.dumps(dict(filters), default=str) if filters else None,
            job_id=job_id,
        )
        self.session.add(search)
        self.session.flush()
        return search

    def add_results(self, search_id: str, results: Sequence[Mapping[str, object]]) -> int:
        search = self.get(search_id)
        if search is None:
            return 0
        for i, r in enumerate(results):
            snippet = r.get("snippet")
            evidence_id = r.get("evidence_id")
            matched = r.get("matched_terms")
            self.session.add(
                SearchResult(
                    search_id=search_id,
                    entity_type=str(r["entity_type"]),
                    entity_id=str(r["entity_id"]),
                    rank=int(r.get("rank", i)),  # type: ignore[call-overload]
                    score=float(r.get("score", 0.0)),  # type: ignore[arg-type]
                    snippet=str(snippet) if snippet is not None else None,
                    matched_terms_json=json.dumps(matched) if matched else None,
                    evidence_id=str(evidence_id) if evidence_id is not None else None,
                )
            )
        search.result_count = (search.result_count or 0) + len(results)
        self.session.flush()
        return len(results)

    def set_status(self, search_id: str, status: TaskStatus) -> None:
        search = self.get(search_id)
        if search is not None:
            search.status = status.value
            if status.is_terminal:
                from database.base import utcnow

                search.completed_at = utcnow()

    def results(self, search_id: str, *, limit: int = 100) -> Sequence[SearchResult]:
        if self.get(search_id) is None:
            return []
        stmt = (
            select(SearchResult)
            .where(SearchResult.search_id == search_id)
            .order_by(SearchResult.rank.asc())
            .limit(limit)
        )
        return self.session.execute(stmt).scalars().all()


class WatchlistRepository(ScopedRepository):
    def get(self, watch_id: str) -> Watchlist | None:
        stmt = select(Watchlist).where(Watchlist.id == watch_id, Watchlist.user_id == self.user_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def list(self, *, active_only: bool = False) -> Sequence[Watchlist]:
        stmt = select(Watchlist).where(Watchlist.user_id == self.user_id)
        if active_only:
            stmt = stmt.where(Watchlist.is_active.is_(True))
        stmt = stmt.order_by(Watchlist.created_at.desc())
        return self.session.execute(stmt).scalars().all()

    def count_active(self) -> int:
        return len([w for w in self.list(active_only=True)])

    def add(
        self,
        *,
        kind: TargetKind | str,
        value: str,
        sources: Sequence[str] | None = None,
        target_id: str | None = None,
        max_targets: int | None = None,
    ) -> tuple[Watchlist, bool]:
        k = str(TargetKind(kind))
        norm = _normalize_for_kind(k, value)
        stmt = select(Watchlist).where(
            Watchlist.user_id == self.user_id,
            Watchlist.kind == k,
            Watchlist.value_normalized == norm,
        )
        existing = self.session.execute(stmt).scalar_one_or_none()
        if existing is not None:
            existing.is_active = True
            return existing, False
        if max_targets is not None and self.count_active() >= max_targets:
            raise ValueError(f"watchlist limit reached ({max_targets})")
        watch = Watchlist(
            user_id=self.user_id,
            target_id=target_id,
            kind=k,
            value=value.strip(),
            value_normalized=norm,
            sources_json=json.dumps(list(sources)) if sources else None,
        )
        self.session.add(watch)
        self.session.flush()
        return watch, True

    def remove(self, *, kind: TargetKind | str, value: str) -> bool:
        k = str(TargetKind(kind))
        norm = _normalize_for_kind(k, value)
        stmt = select(Watchlist).where(
            Watchlist.user_id == self.user_id,
            Watchlist.kind == k,
            Watchlist.value_normalized == norm,
        )
        watch = self.session.execute(stmt).scalar_one_or_none()
        if watch is None:
            return False
        watch.is_active = False
        return True


class ReportRepository(ScopedRepository):
    def get(self, report_id: str) -> Report | None:
        stmt = select(Report).where(
            Report.id == report_id,
            Report.user_id == self.user_id,
            Report.deleted_at.is_(None),
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def list(self, *, limit: int = 50) -> Sequence[Report]:
        stmt = (
            select(Report)
            .where(Report.user_id == self.user_id, Report.deleted_at.is_(None))
            .order_by(Report.created_at.desc())
            .limit(limit)
        )
        return self.session.execute(stmt).scalars().all()

    def create(
        self, *, title: str, target_id: str | None = None, job_id: str | None = None
    ) -> Report:
        report = Report(user_id=self.user_id, title=title, target_id=target_id, job_id=job_id)
        self.session.add(report)
        self.session.flush()
        return report

    def set_status(self, report_id: str, status: TaskStatus, *, error: str | None = None) -> None:
        report = self.get(report_id)
        if report is None:
            return
        report.status = status.value
        if error:
            report.error = error
        if status.is_terminal:
            from database.base import utcnow

            report.generated_at = utcnow()
