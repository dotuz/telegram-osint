"""Sliding-window rate limiting.

One :class:`RateLimiter` per process, Redis-backed with an in-memory fallback
(same pattern as the job queue). Keys are opaque strings built by the caller,
e.g. ``search:user:<id>`` and ``search:ip:<addr>``.

Limits are configurable (``RATE_LIMIT_*``) and the whole thing is switched off
by ``RATE_LIMIT_ENABLED=false`` -- the test-suite default.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Lock
from typing import Protocol

from security.config import get_settings
from security.logging import get_logger

_log = get_logger("security.ratelimit")


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int  # seconds until the oldest hit ages out


class RateLimiter(Protocol):
    def hit(self, key: str, *, limit: int, window_seconds: int) -> RateLimitResult: ...


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def hit(self, key: str, *, limit: int, window_seconds: int) -> RateLimitResult:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            q = self._events[key]
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= limit:
                retry = max(1, int(q[0] + window_seconds - now) + 1)
                return RateLimitResult(False, limit, 0, retry)
            q.append(now)
            return RateLimitResult(True, limit, limit - len(q), 0)

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


class RedisRateLimiter:
    def __init__(self, url: str) -> None:
        import redis

        self._r = redis.from_url(url, decode_responses=True)

    def hit(self, key: str, *, limit: int, window_seconds: int) -> RateLimitResult:
        now = time.time()
        member = f"{now:.6f}-{id(now)}"
        rkey = f"toi:rl:{key}"
        pipe = self._r.pipeline()
        pipe.zremrangebyscore(rkey, 0, now - window_seconds)
        pipe.zadd(rkey, {member: now})
        pipe.zcard(rkey)
        pipe.expire(rkey, window_seconds + 1)
        _, _, count, _ = pipe.execute()
        count = int(count)
        if count > limit:
            self._r.zrem(rkey, member)
            oldest = self._r.zrange(rkey, 0, 0, withscores=True)
            retry = 1
            if oldest:
                oldest_score = float(oldest[0][1])
                retry = max(1, int(oldest_score + window_seconds - now) + 1)
            return RateLimitResult(False, limit, 0, retry)
        return RateLimitResult(True, limit, max(0, limit - count), 0)


_limiter: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        try:
            _limiter = RedisRateLimiter(get_settings().redis_url)
            _limiter.hit("__probe__", limit=1, window_seconds=1)
            _log.info("rate_limiter_ready", backend="redis")
        except Exception as exc:  # noqa: BLE001
            _log.warning("redis_ratelimiter_unavailable_using_memory", error=str(exc))
            _limiter = InMemoryRateLimiter()
    return _limiter


def set_rate_limiter(limiter: RateLimiter | None) -> None:
    global _limiter
    _limiter = limiter


def enforce(keys: list[str], *, limit: int, window_seconds: int) -> RateLimitResult:
    """Check every key; the first that trips wins. No-op when disabled."""
    settings = get_settings()
    if not settings.rate_limit_enabled:
        return RateLimitResult(True, limit, limit, 0)
    limiter = get_rate_limiter()
    worst = RateLimitResult(True, limit, limit, 0)
    for key in keys:
        r = limiter.hit(key, limit=limit, window_seconds=window_seconds)
        if not r.allowed:
            return r
        if r.remaining < worst.remaining:
            worst = r
    return worst
