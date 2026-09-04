"""FastAPI application factory.

Phase 1: bootstrapping, config-driven CORS, request context, health probes.
Auth/RBAC, CSRF, rate limiting, and domain routers land in later phases.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.middleware import RequestContextMiddleware
from apps.api.routers import health, intel
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

    app.include_router(health.router)
    app.include_router(intel.router, prefix="/api/v1")

    return app


app = create_app()
