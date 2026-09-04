"""HTTP security: headers, Origin validation, and the rate-limit dependency."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from apps.api.deps import Principal, current_user
from security.config import get_settings
from security.logging import get_logger
from security.ratelimit import enforce

_log = get_logger("api.security")

_STATE_CHANGING = {"POST", "PUT", "PATCH", "DELETE"}

_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Content-Security-Policy": (
        "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; "
        "img-src 'self' data:; style-src 'self' 'unsafe-inline'; font-src 'self'"
    ),
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        resp = await call_next(request)
        for k, v in _HEADERS.items():
            resp.headers.setdefault(k, v)
        if get_settings().is_production:
            resp.headers.setdefault(
                "Strict-Transport-Security", "max-age=63072000; includeSubDomains"
            )
        return resp


class OriginCheckMiddleware(BaseHTTPMiddleware):
    """Reject a state-changing request whose ``Origin`` is present but not allowed.

    Requests with no ``Origin`` (server-to-server, curl) pass -- token auth plus
    the CORS layer already bound browser callers. This is defence in depth for
    the (future) cookie flow.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        settings = get_settings()
        if (
            settings.enforce_origin_check
            and request.method in _STATE_CHANGING
            and (origin := request.headers.get("origin"))
        ):
            allowed = set(settings.cors_allowed_origins)
            if origin not in allowed:
                _log.warning("origin_rejected", origin=origin, path=request.url.path)
                return Response(status_code=403, content="origin not allowed")
        return await call_next(request)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def rate_limit(
    bucket: str,
    *,
    limit_setting: str = "rate_limit_api_per_minute",
    window_seconds: int = 60,
):
    """Dependency factory: limit ``bucket`` per principal **and** per client IP.

    The limit is read from ``Settings.<limit_setting>`` at request time. Keying
    on the resolved principal (not just the IP) means a shared IP or a spoofed
    ``X-Forwarded-For`` cannot lift another user's limit.
    """

    def _dep(
        request: Request,
        principal: Annotated[Principal, Depends(current_user)],
    ) -> None:
        settings = get_settings()
        limit = int(getattr(settings, limit_setting))
        subject = principal.user_id or principal.email or "anon"
        # Per-principal limit is the real quota; the per-IP key is a much wider
        # backstop against a single host churning many principals -- so one user
        # hitting their limit never blocks a different user behind the same IP.
        ip_limit = max(limit, limit * settings.rate_limit_ip_burst_multiplier)
        for key, key_limit in (
            (f"{bucket}:sub:{subject}", limit),
            (f"{bucket}:ip:{_client_ip(request)}", ip_limit),
        ):
            result = enforce([key], limit=key_limit, window_seconds=window_seconds)
            if not result.allowed:
                raise HTTPException(
                    status_code=429,
                    detail="rate limit exceeded",
                    headers={
                        "Retry-After": str(result.retry_after),
                        "X-RateLimit-Limit": str(result.limit),
                        "X-RateLimit-Remaining": "0",
                    },
                )

    return _dep


def login_rate_limit(request: Request) -> None:
    """Rate-limit login by client IP only (no principal yet)."""
    s = get_settings()
    result = enforce(
        [f"login:ip:{_client_ip(request)}"],
        limit=s.rate_limit_login_per_minute,
        window_seconds=60,
    )
    if not result.allowed:
        raise HTTPException(
            status_code=429,
            detail="too many login attempts",
            headers={"Retry-After": str(result.retry_after)},
        )
