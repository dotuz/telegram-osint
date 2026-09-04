"""Per-user repository isolation (data-layer BOLA/IDOR guard)."""

import pytest

from database.repositories import (
    ReportRepository,
    SearchRepository,
    TargetRepository,
    UserRepository,
    WatchlistRepository,
)
from database.types import SearchKind, TargetKind

pytestmark = pytest.mark.integration


@pytest.fixture
def two_users(db_session):
    repo = UserRepository(db_session)
    a = repo.create(email="a@example.com")
    b = repo.create(email="b@example.com")
    db_session.commit()
    return a, b


def test_target_not_visible_across_users(db_session, two_users):
    a, b = two_users
    ta, _ = TargetRepository(db_session, a.id).get_or_create(
        kind=TargetKind.USERNAME, value="@victim"
    )
    db_session.commit()

    assert TargetRepository(db_session, a.id).get(ta.id) is not None
    assert TargetRepository(db_session, b.id).get(ta.id) is None
    assert list(TargetRepository(db_session, b.id).list()) == []


def test_target_dedup_per_user(db_session, two_users):
    a, _ = two_users
    repo = TargetRepository(db_session, a.id)
    t1, c1 = repo.get_or_create(kind=TargetKind.USERNAME, value="@x")
    t2, c2 = repo.get_or_create(kind=TargetKind.USERNAME, value="X")
    db_session.commit()
    assert c1 is True and c2 is False and t1.id == t2.id


def test_search_and_results_scoped(db_session, two_users):
    a, b = two_users
    s = SearchRepository(db_session, a.id).create(kind=SearchKind.KEYWORD, query="example.com")
    SearchRepository(db_session, a.id).add_results(
        s.id, [{"entity_type": "domain", "entity_id": "d1", "score": 1.0}]
    )
    db_session.commit()

    assert SearchRepository(db_session, b.id).get(s.id) is None
    assert list(SearchRepository(db_session, b.id).results(s.id)) == []
    assert len(SearchRepository(db_session, a.id).results(s.id)) == 1


def test_report_scoped(db_session, two_users):
    a, b = two_users
    r = ReportRepository(db_session, a.id).create(title="Dossier")
    db_session.commit()
    assert ReportRepository(db_session, b.id).get(r.id) is None


def test_watchlist_limit_enforced(db_session, two_users):
    a, _ = two_users
    repo = WatchlistRepository(db_session, a.id)
    repo.add(kind=TargetKind.USERNAME, value="one", max_targets=2)
    repo.add(kind=TargetKind.USERNAME, value="two", max_targets=2)
    db_session.commit()
    with pytest.raises(ValueError, match="limit reached"):
        repo.add(kind=TargetKind.USERNAME, value="three", max_targets=2)


def test_scoped_repo_requires_user_id(db_session):
    with pytest.raises(ValueError, match="user_id is required"):
        TargetRepository(db_session, "")
