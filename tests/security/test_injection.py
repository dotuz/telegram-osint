"""Injection: SQLi in params never errors/leaks; report HTML escapes user input."""

import pytest

from tests.security.conftest import auth, token

pytestmark = pytest.mark.security

_SQLI = [
    "' OR '1'='1",
    "'; DROP TABLE user;--",
    "1) UNION SELECT hashed_password FROM user--",
    '" OR 1=1--',
]


@pytest.mark.parametrize("payload", _SQLI)
def test_sqli_in_search_params_is_inert(secure_client, payload):
    h = auth(token(secure_client, "user-a@sec.example.com", "user-a-pass-123"))
    r = secure_client.get("/api/v1/targets", params={"q": payload}, headers=h)
    # parameterised queries -> a normal 200/404/422, never a 500 or a DB error body
    assert r.status_code < 500
    assert "syntax error" not in r.text.lower()
    assert "hashed_password" not in r.text

    # the user table is still there afterwards
    assert secure_client.get("/api/v1/targets", headers=h).status_code == 200


def test_sqli_in_json_body_is_inert(secure_client):
    h = auth(token(secure_client, "user-a@sec.example.com", "user-a-pass-123"))
    r = secure_client.post(
        "/api/v1/targets",
        json={"kind": "username", "value": "'; DROP TABLE target;--"},
        headers=h,
    )
    assert r.status_code < 500
    assert secure_client.get("/api/v1/targets", headers=h).status_code == 200


def test_xss_in_report_html_is_escaped(secure_client):
    h = auth(token(secure_client, "user-a@sec.example.com", "user-a-pass-123"))
    payload = "<script>alert(1)</script>"
    rep = secure_client.post("/api/v1/reports", json={"value": f"@{payload}"}, headers=h).json()
    rid = rep["report"]["id"]

    html = secure_client.get(f"/api/v1/reports/{rid}/download?fmt=html", headers=h)
    assert html.status_code == 200
    body = html.text
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body or payload not in body


def test_json_endpoints_declare_json_content_type(secure_client):
    h = auth(token(secure_client, "user-a@sec.example.com", "user-a-pass-123"))
    r = secure_client.get("/api/v1/targets", headers=h)
    assert r.headers["content-type"].startswith("application/json")
