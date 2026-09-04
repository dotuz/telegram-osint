import pytest

from database.models.target import Target
from database.repositories import TargetRepository, UserRepository
from database.types import Assertion, TargetKind
from reports.builder import ReportBuilder
from reports.models import SECTION_ORDER
from tests.report_fixtures import seed_target

pytestmark = pytest.mark.integration


@pytest.fixture
async def built(db_session):
    u = UserRepository(db_session).create(email="a@example.com")
    db_session.commit()
    tid = await seed_target(db_session, u.id)
    db_session.commit()
    target = db_session.get(Target, tid)
    content = ReportBuilder(db_session, u.id).build("report-1", target)
    return db_session, content


def test_all_fifteen_sections_in_order(built):
    _session, content = built
    keys = [s["key"] for s in content.as_dict()["sections"]]
    assert keys == list(SECTION_ORDER)


def test_profile_facts_carry_evidence(built):
    _session, content = built
    sec = content.sections["public_telegram_presence"]
    fact_claims = [
        c for c in sec.claims if c.assertion == Assertion.FACT.value and "profile" in c.text
    ]
    assert fact_claims
    assert all(c.evidence_refs for c in fact_claims)


def test_username_section_has_disclaimer_and_inference_tag(built):
    _session, content = built
    sec = content.sections["username_intelligence"]
    text = " ".join(c.text for c in sec.claims)
    assert "not proof of a shared identity" in text
    assert any(c.assertion == Assertion.INFERENCE.value for c in sec.claims)


def test_limitations_state_the_boundary(built):
    _session, content = built
    text = " ".join(c.text for c in content.sections["limitations"].claims).lower()
    assert "no private" in text
    assert "public" in text


def test_empty_target_is_all_unknown(db_session):
    u = UserRepository(db_session).create(email="b@example.com")
    target, _ = TargetRepository(db_session, u.id).get_or_create(
        kind=TargetKind.USERNAME, value="@nobody"
    )
    db_session.commit()

    content = ReportBuilder(db_session, u.id).build("r2", target)
    presence = content.sections["public_telegram_presence"]
    assert all(c.assertion == Assertion.UNKNOWN.value for c in presence.claims)


def test_ioc_section_present_and_honest(built):
    _session, content = built
    sec = content.sections["ioc"]
    # target 'alice' is not linked to a channel here, so no IOCs -> UNKNOWN, not a guess
    assert sec.claims
    assert any(c.assertion == Assertion.UNKNOWN.value for c in sec.claims)
