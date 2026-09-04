"""IDOR / BOLA: one user must never reach another user's resources."""

import pytest

from tests.security.conftest import auth, token

pytestmark = pytest.mark.security


def test_targets_reports_watchlist_isolated(secure_client):
    a = auth(token(secure_client, "user-a@sec.example.com", "user-a-pass-123"))
    b = auth(token(secure_client, "user-b@sec.example.com", "user-b-pass-123"))

    tgt = secure_client.post(
        "/api/v1/targets", json={"kind": "username", "value": "@victim"}, headers=a
    ).json()
    tid = tgt["id"]

    # B cannot see or reach A's target
    assert secure_client.get("/api/v1/targets", headers=b).json()["targets"] == []
    assert secure_client.get(f"/api/v1/targets/{tid}", headers=b).status_code == 404
    assert secure_client.get(f"/api/v1/targets/{tid}/graph", headers=b).status_code == 404
    assert secure_client.get(f"/api/v1/targets/{tid}/timeline", headers=b).status_code == 404

    # watchlist
    secure_client.post("/api/v1/watchlist", json={"value": "@w"}, headers=a)
    assert secure_client.get("/api/v1/watchlist", headers=b).json()["watchlist"] == []

    # reports
    rep = secure_client.post("/api/v1/reports", json={"value": "@victim"}, headers=a).json()
    rid = rep["report"]["id"]
    assert secure_client.get("/api/v1/reports", headers=b).json()["reports"] == []
    assert secure_client.get(f"/api/v1/reports/{rid}", headers=b).status_code == 404
    assert (
        secure_client.get(f"/api/v1/reports/{rid}/download?fmt=json", headers=b).status_code == 404
    )


def test_jobs_scoped_to_requester(secure_client):
    from database.repositories import JobRepository
    from database.session import session_scope

    a = auth(token(secure_client, "user-a@sec.example.com", "user-a-pass-123"))
    admin = auth(token(secure_client, "admin@sec.example.com", "adminpass-123"))

    with session_scope() as s:
        job = JobRepository(s).create(kind="telegram_user", params={}, requested_by="telegram:99")
        jid = job.id
        s.commit()

    assert secure_client.get(f"/api/v1/jobs/{jid}", headers=a).status_code == 404
    assert secure_client.post(f"/api/v1/jobs/{jid}/cancel", headers=a).status_code == 404
    assert secure_client.get(f"/api/v1/jobs/{jid}", headers=admin).status_code == 200


def test_audit_is_admin_only(secure_client):
    a = auth(token(secure_client, "user-a@sec.example.com", "user-a-pass-123"))
    admin = auth(token(secure_client, "admin@sec.example.com", "adminpass-123"))
    assert secure_client.get("/api/v1/audit", headers=a).status_code == 403
    assert secure_client.get("/api/v1/audit", headers=admin).status_code == 200
