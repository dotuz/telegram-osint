import json
from pathlib import Path

import pytest

from database.models.report import Report
from database.models.target import Target
from database.repositories import UserRepository
from reports.builder import ReportBuilder
from reports.models import Claim, ReportContent, Section
from reports.renderers import render_html, render_json, render_pdf
from reports.service import generate_report
from tests.report_fixtures import make_report, seed_target

pytestmark = pytest.mark.integration


def _content_with_hostile_text() -> ReportContent:
    from datetime import UTC, datetime

    c = ReportContent(
        report_id="r",
        title="t",
        target={"value": "<script>x</script>"},
        generated_at=datetime.now(UTC),
    )
    c.section("executive_summary").claims.append(
        Claim(text="<img src=x onerror=alert(1)>", assertion="FACT")
    )
    c.section("executive_summary").data["text"] = "hi"
    return c


def test_json_renderer_roundtrips():
    d = json.loads(render_json(_content_with_hostile_text()))
    assert d["title"] == "t"
    assert d["sections"][0]["claims"][0]["text"] == "<img src=x onerror=alert(1)>"


def test_html_renderer_escapes_untrusted_text():
    html = render_html(_content_with_hostile_text())
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html
    assert "onerror=alert(1)" not in html or "&lt;img" in html
    assert "public OSINT" in html.lower() or "public" in html.lower()


def test_pdf_renderer_produces_pdf_bytes():
    data = render_pdf(_content_with_hostile_text())
    assert data[:4] == b"%PDF"
    assert len(data) > 400


@pytest.fixture
async def report(db_session):
    u = UserRepository(db_session).create(email="a@example.com")
    db_session.commit()
    tid = await seed_target(db_session, u.id)
    db_session.commit()
    rid = make_report(db_session, u.id, tid)
    db_session.commit()
    return db_session, u.id, rid


def test_generate_writes_all_artifacts_and_updates_row(report):
    session, _uid, rid = report
    result = generate_report(session, rid)
    session.commit()

    assert result.status == "COMPLETED"
    assert set(result.artifacts) == {"json", "html", "pdf"}
    for path in result.artifacts.values():
        assert Path(path).is_file()

    row = session.get(Report, rid)
    session.refresh(row)
    assert row.status == "COMPLETED"
    assert row.content_json and json.loads(row.content_json)["report_id"] == rid
    assert row.summary


def test_generate_respects_requested_formats(report):
    session, _uid, rid = report
    result = generate_report(session, rid, formats=["json"])
    assert set(result.artifacts) == {"json"}


def test_generate_fails_gracefully_without_target(db_session):
    u = UserRepository(db_session).create(email="c@example.com")
    from database.repositories import ReportRepository

    rep = ReportRepository(db_session, u.id).create(title="orphan", target_id=None)
    db_session.commit()

    result = generate_report(db_session, rep.id)
    db_session.commit()
    assert result.status == "FAILED"
    assert db_session.get(Report, rep.id).status == "FAILED"


def test_builder_target_fixture_types(db_session):
    # sanity: ReportBuilder needs a Target instance, not an id
    u = UserRepository(db_session).create(email="d@example.com")
    from database.repositories import TargetRepository
    from database.types import TargetKind

    t, _ = TargetRepository(db_session, u.id).get_or_create(kind=TargetKind.USERNAME, value="x")
    db_session.commit()
    content = ReportBuilder(db_session, u.id).build("r", db_session.get(Target, t.id))
    assert isinstance(content.section("evidence"), Section)
