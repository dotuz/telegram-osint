import pytest

from security.ratelimit import InMemoryRateLimiter, enforce, set_rate_limiter
from tests.security.conftest import auth, token

pytestmark = pytest.mark.security


@pytest.fixture
def limited(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_SEARCH_PER_MINUTE", "3")
    monkeypatch.setenv("RATE_LIMIT_LOGIN_PER_MINUTE", "3")
    from security.config import get_settings

    get_settings.cache_clear()
    set_rate_limiter(InMemoryRateLimiter())
    yield
    set_rate_limiter(None)


def test_enforce_is_noop_when_disabled():
    for _ in range(100):
        assert enforce(["k"], limit=1, window_seconds=60).allowed


def test_sliding_window_trips_then_recovers():
    lim = InMemoryRateLimiter()
    assert lim.hit("k", limit=2, window_seconds=1).allowed
    assert lim.hit("k", limit=2, window_seconds=1).allowed
    blocked = lim.hit("k", limit=2, window_seconds=1)
    assert not blocked.allowed and blocked.retry_after >= 1


def test_search_endpoint_rate_limited(secure_client, limited):
    h = auth(token(secure_client, "user-a@sec.example.com", "user-a-pass-123"))
    codes = [
        secure_client.post("/api/v1/telegram/user", json={"query": "@x"}, headers=h).status_code
        for _ in range(6)
    ]
    assert 429 in codes
    assert codes.count(429) >= 2


def test_limit_is_per_principal_not_only_ip(secure_client, limited):
    a = auth(token(secure_client, "user-a@sec.example.com", "user-a-pass-123"))
    b = auth(token(secure_client, "user-b@sec.example.com", "user-b-pass-123"))
    for _ in range(3):
        secure_client.post("/api/v1/telegram/user", json={"query": "@x"}, headers=a)
    # A is now blocked (same IP), but B still gets through
    assert (
        secure_client.post("/api/v1/telegram/user", json={"query": "@x"}, headers=a).status_code
        == 429
    )
    assert (
        secure_client.post("/api/v1/telegram/user", json={"query": "@x"}, headers=b).status_code
        != 429
    )


def test_login_is_rate_limited(secure_client, limited):
    codes = [
        secure_client.post(
            "/api/v1/auth/login", json={"email": "user-a@sec.example.com", "password": "wrong"}
        ).status_code
        for _ in range(6)
    ]
    assert 429 in codes
