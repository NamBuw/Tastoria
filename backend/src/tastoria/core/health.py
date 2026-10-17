"""GET /healthz (process alive, no DB) and GET /readyz (dependencies), both at the root, outside /api/v1.

Readiness checks are registered by the assembly root (tastoria.app) under the names of the OpenAPI
`Readiness.checks` object. A check that is not registered (e.g. `models` before the scan slice deploys a
detector) is reported as "ok" because nothing in this deployment depends on it yet.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

log = logging.getLogger("tastoria.health")
router = APIRouter(tags=["core"])

READINESS_CHECKS = ("database", "valkey", "models")


@router.get("/healthz", operation_id="core_get_health")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", operation_id="core_get_readiness")
def readyz(request: Request) -> JSONResponse:
    checks: dict[str, Callable[[], None]] = getattr(request.app.state, "readiness_checks", {})
    results: dict[str, str] = {}
    for name in READINESS_CHECKS:
        fn = checks.get(name)
        if fn is None:
            results[name] = "ok"
            continue
        try:
            fn()
            results[name] = "ok"
        except Exception as exc:  # report, never raise
            log.warning("readiness check failed", extra={"check": name, "error": repr(exc)})
            results[name] = "fail"
    ready = all(v == "ok" for v in results.values())
    body = {"status": "ready" if ready else "not_ready", "checks": results}
    if ready:
        return JSONResponse(body)
    return JSONResponse(body, status_code=503, headers={"Retry-After": "5"})
