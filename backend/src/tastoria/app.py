"""Assembly root: builds the FastAPI app, wires module routers, readiness checks and cross-module handlers.

This is the only place that knows every module (ADR 0001); business modules never import it.
"""

from __future__ import annotations

import json
import time
import uuid
import warnings
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import valkey.asyncio as valkey_async
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from PIL import Image
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.types import ASGIApp, Message, Receive, Scope, Send

import tastoria.models_registry  # noqa: F401  (every table in the metadata before the first flush)
from tastoria.core.config import Settings, get_settings
from tastoria.core.db import make_engine, make_sessionmaker
from tastoria.core.errors import install_error_handlers
from tastoria.core.health import metrics
from tastoria.core.health import router as health_router
from tastoria.core.kv import make_valkey
from tastoria.core.logging import configure_logging
from tastoria.core.middleware import RequestContextMiddleware
from tastoria.core.ratelimit import MemoryRateLimiter, ValkeyRateLimiter
from tastoria.modules.admin.router import router as admin_router
from tastoria.modules.admin.surveys_router import router as admin_surveys_router
from tastoria.modules.catalog.router import router as catalog_router
from tastoria.modules.catalog.service import CatalogDeps
from tastoria.modules.cooking.router import router as cooking_router
from tastoria.modules.cooking.service import CookingSubjectData, has_live_cook_session
from tastoria.modules.events.router import router as events_router
from tastoria.modules.events.service import EventsSubjectData
from tastoria.modules.identity.dsr import IdentitySubjectData
from tastoria.modules.identity.mailer import make_mailer
from tastoria.modules.identity.router import router as identity_router
from tastoria.modules.identity.service import BearerAuthenticator
from tastoria.modules.identity.throttle import MemoryLoginThrottle, ValkeyLoginThrottle
from tastoria.modules.journal.router import router as journal_router
from tastoria.modules.meal.router import router as meal_router
from tastoria.modules.meal.service import MealDeps, MealSubjectData, item_owned, load_composer_params
from tastoria.modules.meal_calorie.router import router as meal_calorie_router
from tastoria.modules.meal_calorie.service import DeployedOnnxRef, MealCalorieDeps
from tastoria.modules.meal_logs.router import router as meal_logs_router
from tastoria.modules.meal_logs.service import MealLogSubjectData
from tastoria.modules.mlops import service as mlops
from tastoria.modules.pantry.router import router as pantry_router
from tastoria.modules.pantry.service import PantrySubjectData, available_ingredient_ids
from tastoria.modules.privacy.router import router as privacy_router
from tastoria.modules.privacy.service import PrivacyDeps, SubjectDataHandler, list_purposes
from tastoria.modules.profile.router import router as profile_router
from tastoria.modules.profile.service import ProfileDeps, ProfileSubjectData, make_cipher
from tastoria.modules.scan.queue import ScanQueue
from tastoria.modules.scan.router import router as scan_router
from tastoria.modules.scan.service import ScanDeps, ScanSubjectData
from tastoria.modules.substitute.router import router as shopping_router
from tastoria.modules.substitute.service import SubstituteDeps, SubstituteSubjectData
from tastoria.modules.survey.router import router as survey_router

API_PREFIX = "/api/v1"


class MetricsMiddleware:
    """Pure ASGI HTTP request metrics collector keyed by low-cardinality route template."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        t0 = time.perf_counter()
        status_code = 500

        async def _send(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, _send)
        finally:
            route = scope.get("route")
            path = getattr(route, "path", "__unmatched__") if route is not None else "__unmatched__"
            metrics.observe_http(str(scope.get("method", "GET")), str(path), status_code, time.perf_counter() - t0)


def build_subject_handlers(profile: ProfileDeps) -> list[SubjectDataHandler]:
    """Per-module exporters/erasers for data-subject requests (privacy calls them; ADR 0001 inversion)."""
    return [
        IdentitySubjectData(),
        ProfileSubjectData(profile),
        PantrySubjectData(),
        MealSubjectData(),
        CookingSubjectData(),
        EventsSubjectData(),
        SubstituteSubjectData(),
        ScanSubjectData(Path(profile.settings.storage_dir)),
        MealLogSubjectData(),
    ]


def create_app(settings: Settings | None = None, *, configure_logs: bool = True) -> FastAPI:
    settings = settings or get_settings()
    if configure_logs:
        configure_logging(settings.log_level)
    warnings.filterwarnings("error", category=Image.DecompressionBombWarning)

    engine = make_engine(settings.database_url, pool_size=settings.db_pool_size)
    sessionmaker = make_sessionmaker(engine)
    kv = make_valkey(settings.valkey_url)

    @asynccontextmanager
    async def lifespan(the_app: FastAPI) -> AsyncIterator[None]:
        the_app.state.async_valkey = valkey_async.Valkey.from_url(
            settings.valkey_url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2
        )
        if the_app.state.meal_calorie.barcode_catalog is not None:
            the_app.state.meal_calorie.barcode_catalog.reopen()
        try:
            yield
        finally:
            async_kv = getattr(the_app.state, "async_valkey", None)
            the_app.state.async_valkey = None
            if async_kv is not None:
                try:
                    await async_kv.aclose()
                except Exception:  # noqa: BLE001
                    pass
            try:
                await the_app.state.scan.queue.aclose()
            except Exception:  # noqa: BLE001
                pass
            the_app.state.scan.queue.close()
            try:
                kv.close()
                kv.connection_pool.disconnect()
            except Exception:  # noqa: BLE001
                pass
            the_app.state.meal_calorie.close()
            engine.dispose()

    is_prod = settings.env == "production"
    app = FastAPI(
        title="Tastoria API",
        version="1.0.0",
        openapi_url=None if is_prod else f"{API_PREFIX}/openapi.json",
        docs_url=None if is_prod else f"{API_PREFIX}/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = sessionmaker

    def check_database() -> None:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

    app.state.valkey = kv
    app.state.async_valkey = None

    async def check_valkey() -> None:
        client = getattr(app.state, "async_valkey", None)
        if client is not None:
            await client.ping()
            return
        tmp = valkey_async.Valkey.from_url(
            settings.valkey_url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2
        )
        try:
            await tmp.ping()
        finally:
            await tmp.aclose()

    verified: dict[object, int] = {}  # version id -> artifact size once its SHA-256 matched (hash once per process)

    def check_models() -> None:
        """SD10: a deployed model whose artifact is missing or has another SHA-256 makes the API not ready. No
        deployment at all is not an error here: POST /scans then answers 503 model_unavailable."""
        with app.state.sessionmaker() as s:
            views = list(mlops.active_versions_map(s).values())
        for v in views:
            path = Path(settings.storage_dir) / v.artifact_key
            if verified.get(v.id) == (path.stat().st_size if path.exists() else -1):
                continue
            mlops.artifact_path(Path(settings.storage_dir), v, verify=True)
            verified[v.id] = path.stat().st_size

    app.state.readiness_checks = {"database": check_database, "valkey": check_valkey, "models": check_models}

    if settings.login_throttle_backend == "valkey":
        app.state.login_throttle = ValkeyLoginThrottle(
            kv, max_failures=settings.login_max_failures, lock_s=settings.login_lock_s
        )
    else:
        app.state.login_throttle = MemoryLoginThrottle(
            max_failures=settings.login_max_failures, lock_s=settings.login_lock_s
        )
    if settings.effective_rate_limit_backend == "valkey":
        app.state.rate_limiter = ValkeyRateLimiter(kv, enabled=settings.rate_limit_enabled)
    else:
        app.state.rate_limiter = MemoryRateLimiter(enabled=settings.rate_limit_enabled)
    app.state.mailer = make_mailer(settings)
    app.state.authenticator = BearerAuthenticator(settings)
    app.state.profile = ProfileDeps(settings, make_cipher(settings))
    app.state.privacy = PrivacyDeps(
        settings,
        app.state.sessionmaker,
        handlers=build_subject_handlers(app.state.profile),
        defer_delete=settings.should_defer_delete,
    )

    app.state.catalog = CatalogDeps(
        consent_purposes=list_purposes, available_ingredient_ids=available_ingredient_ids
    )
    # Dependency inversions (ADR 0001): meal may not import cooking, substitute may not import meal.
    app.state.meal = MealDeps(
        has_live_cook_session=has_live_cook_session,
        params=load_composer_params(settings.composer_serving_path),
        storage_dir=Path(settings.storage_dir),
    )
    app.state.substitute = SubstituteDeps(item_owned=item_owned)
    app.state.scan = ScanDeps(settings, app.state.sessionmaker, ScanQueue(settings.valkey_url))

    def _static_serving(fallback_dir: str | Path | None, default_subdir: str) -> dict[str, Any]:
        root = Path(__file__).resolve().parents[3]
        if fallback_dir:
            d = Path(fallback_dir)
        elif default_subdir == "dish_classifier" and settings.meal_calorie_model_dir:
            d = Path(settings.meal_calorie_model_dir).parent / "dish_classifier"
        else:
            d = root / "deploy" / "models" / default_subdir
        p = d / "serving.json"
        if p.is_file():
            return json.loads(p.read_text(encoding="utf-8"))
        return {}

    def _make_onnx_probe(model_name: str, default_subdir: str, fallback_dir: str | Path | None):
        def _probe(current_vid: uuid.UUID | None) -> tuple[bool, DeployedOnnxRef | None]:
            try:
                with app.state.sessionmaker() as s:
                    v = mlops.active_version(s, model_name)
            except SQLAlchemyError:
                return (False, None)
            if v is None:
                if current_vid is not None:
                    mlops.evict_onnx_cache(model_name, keep_version_id=None)
                    return (True, None)
                return (False, None)
            if v.id == current_vid:
                return (False, None)
            mlops.evict_onnx_cache(model_name, keep_version_id=v.id)
            sibling = (Path(settings.storage_dir) / v.artifact_key).parent / "serving.json"
            serving = (
                json.loads(sibling.read_text(encoding="utf-8"))
                if sibling.is_file()
                else _static_serving(fallback_dir, default_subdir)
            )
            ref = DeployedOnnxRef(
                version_id=v.id,
                version=v.version,
                serving=serving,
                loader=lambda v=v: mlops.load_onnx(Path(settings.storage_dir), v),
            )
            return (True, ref)

        return _probe

    app.state.meal_calorie = MealCalorieDeps.from_paths(
        model_dir=settings.meal_calorie_model_dir,
        dish_classifier_model_dir=settings.dish_classifier_model_dir,
        kb_dir=settings.kb_dir,
        kb_processed_dir=settings.kb_processed_dir,
        preload=settings.should_preload_meal_calorie,
        estimator_probe=_make_onnx_probe("meal_calorie", "meal_calorie", settings.meal_calorie_model_dir),
        dish_classifier_probe=_make_onnx_probe(
            "dish_classifier", "dish_classifier", settings.dish_classifier_model_dir
        ),
    )

    install_error_handlers(app)
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(RequestContextMiddleware, min_app_version=settings.min_app_version)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.effective_cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "X-App-Version",
            "X-Client-Platform",
            "X-Request-ID",
            "X-Respondent-Token",
        ],
        expose_headers=["Location", "Retry-After", "X-Request-ID", "ETag"],
    )

    @app.get("/metrics", include_in_schema=False)
    def get_metrics() -> PlainTextResponse:
        depth: int | None = None
        try:
            depth = int(app.state.scan.queue.length())
        except Exception:  # noqa: BLE001 — metrics remain readable if Valkey is unreachable
            depth = None
        return PlainTextResponse(
            metrics.render_prometheus(scan_queue_depth=depth),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    app.include_router(health_router)
    app.include_router(identity_router, prefix=API_PREFIX)
    app.include_router(privacy_router, prefix=API_PREFIX)
    app.include_router(profile_router, prefix=API_PREFIX)
    app.include_router(catalog_router, prefix=API_PREFIX)
    app.include_router(pantry_router, prefix=API_PREFIX)
    app.include_router(meal_router, prefix=API_PREFIX)
    app.include_router(meal_calorie_router, prefix=API_PREFIX)
    app.include_router(shopping_router, prefix=API_PREFIX)
    app.include_router(cooking_router, prefix=API_PREFIX)
    app.include_router(journal_router, prefix=API_PREFIX)
    app.include_router(meal_logs_router, prefix=API_PREFIX)
    app.include_router(events_router, prefix=API_PREFIX)
    app.include_router(survey_router, prefix=API_PREFIX)
    app.include_router(admin_router, prefix=API_PREFIX)
    app.include_router(admin_surveys_router, prefix=API_PREFIX)
    app.include_router(scan_router, prefix=API_PREFIX)
    return app
