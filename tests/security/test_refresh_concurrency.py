"""Concurrent rotation of one refresh token must not yield two valid successors.

Phase 13 hardening: ``rotate`` now takes ``SELECT ... FOR UPDATE`` on the token
row so a second concurrent rotation serialises behind the first and then falls
into reuse detection (family revocation) instead of minting a second lineage.
"""

import os
import threading

import pytest

from database.repositories import UserRepository
from database.repositories.refresh_tokens import (
    RefreshTokenRepository,
    RefreshTokenReuseError,
)
from database.session import session_scope

pytestmark = pytest.mark.security

# In-memory SQLite shares one connection across threads (StaticPool), so it cannot
# model two concurrent transactions. This test is only meaningful against a real
# server database -- run the suite with TOI_TEST_DATABASE_URL set (e.g. Postgres).
_SERVER_DB = bool(os.environ.get("TOI_TEST_DATABASE_URL"))


@pytest.mark.skipif(not _SERVER_DB, reason="needs a real concurrent DB (TOI_TEST_DATABASE_URL)")
def test_two_racing_rotations_do_not_both_succeed(db_session):
    with session_scope() as s:
        user = UserRepository(s).create(email="race@example.com")
        s.commit()
        raw = RefreshTokenRepository(s).issue(user)
        s.commit()

    results: list[tuple[str, object]] = []
    barrier = threading.Barrier(2)

    def worker() -> None:
        barrier.wait()
        try:
            with session_scope() as s:
                new_raw, _ = RefreshTokenRepository(s).rotate(raw)
            results.append(("ok", new_raw))
        except RefreshTokenReuseError as exc:
            results.append(("reuse", str(exc)))
        except Exception as exc:  # noqa: BLE001
            results.append(("error", repr(exc)))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(results) == 2
    oks = [r for r in results if r[0] == "ok"]
    # At most one rotation may succeed; the other must be rejected (reuse).
    assert len(oks) <= 1
    assert any(r[0] == "reuse" for r in results) or len(oks) == 1

    # Whatever tokens exist, the original is dead and no two successors are active.
    with session_scope() as s:
        repo = RefreshTokenRepository(s)
        assert repo._get(raw) is not None and not repo._get(raw).is_active
        active = sum(1 for (kind, tok) in results if kind == "ok" and _is_active(repo, tok))
        assert active <= 1


def _is_active(repo: RefreshTokenRepository, raw: str) -> bool:
    row = repo._get(raw)
    return bool(row and row.is_active)
