"""Pure-ASGI middleware: request_id, one JSON access-log line per request, X-App-Version gate (412 app_too_old).

Unexpected exceptions are turned into a 500 problem+json here, so the response still carries X-Request-ID.
Request bodies are never logged (they may hold passwords or body metrics).
"""

from __future__ import annotations

import logging
import re
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from tastoria.core.context import set_request_id
from tastoria.core.errors import ProblemCode, problem_response

log = logging.getLogger("tastoria.request")
_RID_OK = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def _version_tuple(v: str) -> tuple[int, int, int] | None:
    m = _SEMVER.match(v)
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, *, min_app_version: str = "0.0.0") -> None:
        self.app = app
        self.min_version = _version_tuple(min_app_version) or (0, 0, 0)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        incoming = headers.get("x-request-id", "")
        rid = incoming if _RID_OK.match(incoming) else uuid.uuid4().hex
        set_request_id(rid)
        started = time.perf_counter()
        status_holder = {"status": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                message.setdefault("headers", [])
                message["headers"].append((b"x-request-id", rid.encode()))
            await send(message)

        path = scope.get("path", "")
        try:
            app_version = headers.get("x-app-version")
            if app_version is not None and path.startswith("/api/"):
                parsed = _version_tuple(app_version)
                if parsed is not None and parsed < self.min_version:
                    resp = problem_response(412, ProblemCode.app_too_old, instance=path)
                    await resp(scope, receive, send_wrapper)
                    return
            await self.app(scope, receive, send_wrapper)
        except Exception:
            log.exception("unhandled error")
            resp = problem_response(500, ProblemCode.internal_error, instance=path)
            await resp(scope, receive, send_wrapper)
        finally:
            log.info(
                "request",
                extra={
                    "method": scope.get("method"),
                    "path": path,
                    "status": status_holder["status"],
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
