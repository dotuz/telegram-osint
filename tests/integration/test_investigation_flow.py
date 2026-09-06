"""Investigation orchestration: service run, observation typing, report, IDOR."""

from datetime import UTC, datetime

import pytest

from collectors.telegram import FakeTelegramSource, PublicMessage, PublicProfile
from collectors.telegram.collector import TelegramPublicCollector
from database.models.investigation import Investigation
from database.repositories import InvestigationRepository, UserRepository
from database.session import session_scope
from database.types import InvestigationStatus
from intelligence.investigation import InvestigationService
from tests.username_fixtures import alice_collector

pytestmark = pytest.mark.integration


def _source() -> FakeTelegramSource:
    src = FakeTelegramSource()
    src.profiles["alice"] = PublicProfile(
        telegram_id=42, username="alice", display_name="Alice A.", reference="https://t.me/alice"
    )
    src.messages["opsecnews"] = [
        PublicMessage(
            message_id=1,
            chat_username="opsecnews",
            author_username="alice",
            text="alice here, posting an update",
            posted_at=datetime(2026, 3, 1, tzinfo=UTC),
            reference="https://t.me/opsecnews/1",
        ),
        PublicMessage(
            message_id=2,
            chat_username="opsecnews",
            author_username="bob",
            text="has anyone seen @alice lately?",
            posted_at=datetime(2026, 3, 2, tzinfo=UTC),
            reference="https://t.me/opsecnews/2",
        ),
        PublicMessage(
            message_id=3,
            chat_username="opsecnews",
            author_username="carol",
            text="@alice you are wrong about that",
            reply_to_message_id=1,
            posted_at=datetime(2026, 3, 3, tzinfo=UTC),
            reference="https://t.me/opsecnews/3",
        ),
    ]
    return src


@pytest.fixture
def user(db_session):
    u = UserRepository(db_session).create(email="op@example.com")
    db_session.commit()
    return u


async def test_investigation_run_classifies_and_reports(db_session, user):
    with session_scope() as s:
        inv = InvestigationRepository(s, user.id).create(target="@alice", target_normalized="alice")
        s.commit()
        inv_id = inv.id

    svc = InvestigationService(
        db_session,
        user.id,
        telegram_collector=TelegramPublicCollector(_source()),
        username_collector=alice_collector(),
    )
    result = await svc.run(inv_id)

    assert result.status == InvestigationStatus.COMPLETED.value
    assert result.counts["AUTHOR"] == 1
    assert result.counts["MENTION"] == 1
    assert result.counts["REPLY"] == 1
    assert result.counts["observations"] == 3
    assert result.counts["aliases"] >= 1
    assert result.confidence is not None and result.confidence > 0
    assert result.report_id is not None

    inv = db_session.get(Investigation, inv_id)
    assert inv.status == InvestigationStatus.COMPLETED.value
    obs = list(InvestigationRepository(db_session, user.id).observations(inv_id))
    assert {o.observation_type for o in obs} == {"AUTHOR", "MENTION", "REPLY"}
    assert all(o.confidence > 0 for o in obs)


async def test_no_source_is_not_observable_not_fabricated(db_session, user):
    with session_scope() as s:
        inv = InvestigationRepository(s, user.id).create(target="@ghost", target_normalized="ghost")
        s.commit()
        inv_id = inv.id

    # default TelegramPublicCollector with no configured source
    svc = InvestigationService(db_session, user.id, username_collector=alice_collector())
    result = await svc.run(inv_id)

    assert result.status == InvestigationStatus.COMPLETED.value
    assert result.counts["observations"] == 0
    assert "NOT OBSERVABLE" in result.narrative
    assert any("NOT OBSERVABLE" in x for x in result.limitations)


def test_investigation_is_scoped_to_its_owner(db_session):
    a = UserRepository(db_session).create(email="a@example.com")
    b = UserRepository(db_session).create(email="b@example.com")
    db_session.commit()

    inv = InvestigationRepository(db_session, a.id).create(target="@x", target_normalized="x")
    db_session.flush()

    assert InvestigationRepository(db_session, b.id).get(inv.id) is None
    assert InvestigationRepository(db_session, b.id).get_by_public_id(inv.public_id) is None
    assert InvestigationRepository(db_session, a.id).get(inv.id) is not None
