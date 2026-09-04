import pytest

from collectors.common.interfaces import CollectRequest
from collectors.username.collector import KIND_USERNAME, UsernameOsintCollector
from database.models import Evidence, ExternalAccount, Relationship, TelegramAccount, Username
from database.repositories import UserRepository
from database.types import TaskStatus
from intelligence.username_osint import UsernameOsintService
from tests.username_fixtures import FakeAdapter, alice_collector

pytestmark = pytest.mark.integration


async def test_collector_fanout_and_partial_failure():
    result = await alice_collector().run(CollectRequest(query="@Alice", kind=KIND_USERNAME))
    assert result.ok
    types = [r.entity_type for r in result.records]
    assert types.count("username") == 1
    # github + telegram exist; reddit not-found excluded; gitlab raised
    assert types.count("external_account") == 1
    assert types.count("telegram_account") == 1
    assert any("gitlab" in n for n in result.notes)
    rels = {r.rel_type for r in result.relationships}
    assert "USERNAME_FOUND_ON" in rels


async def test_collector_unsupported_kind():
    r = await alice_collector().run(CollectRequest(query="x", kind="nope"))
    assert r.ok is False


@pytest.fixture
def user(db_session):
    u = UserRepository(db_session).create(email="a@example.com")
    db_session.commit()
    return u


async def test_service_persists_accounts_edges_and_correlation(db_session, user):
    svc = UsernameOsintService(db_session, user.id, collector=alice_collector())
    result = await svc.run("@Alice")
    db_session.commit()

    assert result.found
    assert db_session.query(Username).count() == 1
    assert db_session.query(ExternalAccount).filter_by(identifier="alice").count() == 1
    assert db_session.query(TelegramAccount).count() == 1

    rel_types = {r.rel_type for r in db_session.query(Relationship).all()}
    assert "USERNAME_FOUND_ON" in rel_types
    assert "ACCOUNT_POSSIBLY_SAME_AS" in rel_types  # same display name + username

    corr = db_session.query(Evidence).filter_by(field="identity_correlation").all()
    assert corr and all(e.extraction_method == "confidence_engine" for e in corr)

    # per-source confidence + disclaimer, never an identity claim
    assert result.sources[0].confidence >= 45
    assert "not proof" in result.disclaimer
    for s in result.sources:
        assert "the same person" not in " ".join(s.evidence).lower()


async def test_service_records_search(db_session, user):
    svc = UsernameOsintService(db_session, user.id, collector=alice_collector())
    result = await svc.run("alice")
    db_session.commit()
    from database.models import Search, SearchResult

    search = db_session.get(Search, result.search_id)
    assert search.status == TaskStatus.COMPLETED.value
    assert db_session.query(SearchResult).filter_by(search_id=result.search_id).count() == 2


async def test_service_idempotent(db_session, user):
    for _ in range(2):
        svc = UsernameOsintService(db_session, user.id, collector=alice_collector())
        await svc.run("alice")
        db_session.commit()
    assert db_session.query(ExternalAccount).count() == 1
    assert db_session.query(TelegramAccount).count() == 1


async def test_service_no_adapters_note(db_session, user):
    svc = UsernameOsintService(db_session, user.id, collector=UsernameOsintCollector([]))
    result = await svc.run("alice")
    db_session.commit()
    assert result.found is False
    assert any("no username-OSINT adapters" in n for n in result.notes)


async def test_service_not_found_everywhere(db_session, user):
    from collectors.username.base import AdapterResult
    from database.models import Search

    coll = UsernameOsintCollector(
        [FakeAdapter("github", AdapterResult.not_found("github", "ghost"))]
    )
    svc = UsernameOsintService(db_session, user.id, collector=coll)
    result = await svc.run("ghost")
    db_session.commit()
    assert result.found is False
    assert db_session.get(Search, result.search_id).status == TaskStatus.COMPLETED.value
