"""FastAPI application factory.

Middleware order (outermost first): security headers, Origin check, CORS,
request context. Auth is per-route (``current_user``); rate limits are per-route
dependencies (``rate_limit(...)``).
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.middleware import RequestContextMiddleware
from apps.api.routers import (
    auth,
    graph,
    health,
    intel,
    investigations,
    iocs,
    jobs,
    reports,
    username,
    watchlist,
)
from apps.api.security import OriginCheckMiddleware, SecurityHeadersMiddleware
from collectors.bootstrap import register_default_collectors
from security.config import Settings, get_settings
from security.logging import configure_logging, get_logger


@asynccontextmanager
async def _lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    configure_logging(level=settings.log_level, json_output=settings.log_json)
    log = get_logger("api")
    settings.require_production_secrets()
    register_default_collectors()
    log.info("api_startup", env=settings.app_env, debug=settings.app_debug)
    yield
    log.info("api_shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    app = FastAPI(
        title="Telegram OSINT Intelligence Platform API",
        version="0.1.0",
        description="Public-data intelligence, correlation, and reporting.",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url=None,
        lifespan=_lifespan,
    )
    app.state.settings = settings

    # CORS: explicit origins only. Credentials are enabled, so wildcard is refused
    # by Settings validation -- never reachable here.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-CSRF-Token"],
        max_age=600,
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(OriginCheckMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)

    app.include_router(health.router)
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(investigations.router, prefix="/api/v1")
    app.include_router(intel.router, prefix="/api/v1")
    app.include_router(iocs.router, prefix="/api/v1")
    app.include_router(username.router, prefix="/api/v1")
    app.include_router(graph.router, prefix="/api/v1")
    app.include_router(jobs.router, prefix="/api/v1")
    app.include_router(watchlist.router, prefix="/api/v1")
    app.include_router(reports.router, prefix="/api/v1")

    from apps.api.routers import admin as admin_router

    app.include_router(admin_router.router, prefix="/api/v1")

    return app


app = create_app()
