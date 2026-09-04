"""Liveness and readiness probes.

``/health`` -- process is up (no dependency checks).
``/ready``  -- database and Redis are reachable; returns 503 if not.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from sqlalchemy import text

from database.session import get_engine
from security.config import get_settings
from security.logging import get_logger

router = APIRouter(tags=["health"])
_log = get_logger("api.health")


class HealthResponse(BaseModel):
    status: str
    env: str
    version: str = "0.1.0"


class ReadyResponse(BaseModel):
    ready: bool
    checks: dict[str, str]


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    s = get_settings()
    return HealthResponse(status="ok", env=s.app_env)


@router.get("/ready", response_model=ReadyResponse)
def ready(response: Response) -> ReadyResponse:
    checks: dict[str, str] = {}

    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001 - report, don't crash the probe
        checks["database"] = "error"
        _log.warning("readiness_db_failed", error=str(exc))

    try:
        import redis  # local import: not needed for /health

        client = redis.from_url(get_settings().redis_url, socket_connect_timeout=2)
        client.ping()
        checks["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = "error"
        _log.warning("readiness_redis_failed", error=str(exc))

    ok = all(v == "ok" for v in checks.values())
    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadyResponse(ready=ok, checks=checks)
