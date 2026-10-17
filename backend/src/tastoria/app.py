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
from tastoria.modules.identity.dsr import IdentitySubjectData
from tastoria.modules.identity.mailer import make_mailer
from tastoria.modules.identity.router import router as identity_router
from tastoria.modules.identity.throttle import MemoryLoginThrottle, ValkeyLoginThrottle
from tastoria.modules.privacy.router import router as privacy_router
from tastoria.modules.privacy.service import PrivacyDeps, SubjectDataHandler
from tastoria.modules.profile.router import router as profile_router
from tastoria.modules.profile.service import ProfileDeps, ProfileSubjectData, make_cipher

API_PREFIX = "/api/v1"


def build_subject_handlers(profile: ProfileDeps) -> list[SubjectDataHandler]:
    """Per-module exporters/erasers for data-subject requests (privacy calls them; ADR 0001 inversion)."""
    return [IdentitySubjectData(), ProfileSubjectData(profile)]


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

    if settings.login_throttle_backend == "valkey":
        app.state.login_throttle = ValkeyLoginThrottle(
            kv, max_failures=settings.login_max_failures, lock_s=settings.login_lock_s
        )
    else:
        app.state.login_throttle = MemoryLoginThrottle(
            max_failures=settings.login_max_failures, lock_s=settings.login_lock_s
        )
    app.state.mailer = make_mailer(settings)
    app.state.profile = ProfileDeps(settings, make_cipher(settings))
    app.state.privacy = PrivacyDeps(
        settings, app.state.sessionmaker, handlers=build_subject_handlers(app.state.profile)
    )

    install_error_handlers(app)
    app.add_middleware(RequestContextMiddleware, min_app_version=settings.min_app_version)
    app.include_router(health_router)
    app.include_router(identity_router, prefix=API_PREFIX)
    app.include_router(privacy_router, prefix=API_PREFIX)
    app.include_router(profile_router, prefix=API_PREFIX)
    return app
