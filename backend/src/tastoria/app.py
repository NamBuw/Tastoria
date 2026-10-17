"""Assembly root: builds the FastAPI app, wires module routers, readiness checks and cross-module handlers.

This is the only place that knows every module (ADR 0001); business modules never import it.
"""

from __future__ import annotations

from fastapi import FastAPI
from sqlalchemy import text

from tastoria.core.config import Settings, get_settings
from tastoria.core.db import make_engine, make_sessionmaker
from tastoria.core.errors import install_error_handlers
from tastoria.core.health import router as health_router
from tastoria.core.kv import make_valkey
from tastoria.core.logging import configure_logging
from tastoria.core.middleware import RequestContextMiddleware

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None, *, configure_logs: bool = True) -> FastAPI:
    settings = settings or get_settings()
    if configure_logs:
        configure_logging(settings.log_level)

    app = FastAPI(
        title="Tastoria API",
        version="1.0.0",
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
    )
    app.state.settings = settings
    engine = make_engine(settings.database_url, pool_size=settings.db_pool_size)
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)

    def check_database() -> None:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

    kv = make_valkey(settings.valkey_url)
    app.state.valkey = kv

    def check_valkey() -> None:
        kv.ping()

    app.state.readiness_checks = {"database": check_database, "valkey": check_valkey}

    install_error_handlers(app)
    app.add_middleware(RequestContextMiddleware, min_app_version=settings.min_app_version)
    app.include_router(health_router)
    return app
