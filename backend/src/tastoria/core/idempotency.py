"""Idempotency-Key for the create-type POSTs (ADR 0007; openapi parameter IdempotencyKey; table idempotency_keys).

Usage in a router (the user id comes from identity.current_user, which core does not import):

    @router.post("/meal-plans", status_code=201)
    def create(body: X, user: CurrentUser, uow: Uow, idem: IdempotencyKeyDep) -> Response:
        if (replayed := idempotency.begin(uow.session, user.id, idem)) is not None:
            return replayed
        payload = meal.service.create(...)
        return idempotency.finish(uow.session, user.id, idem, 201, payload)

`begin` runs inside the request transaction:
  1. pg_try_advisory_xact_lock(user_id, key) — busy → 409 idempotency_in_progress (+ Retry-After);
  2. stored row with the same request hash → the stored response, verbatim, with `Idempotent-Replayed: true`;
  3. stored row with a different hash → 422 idempotency_key_reused;
  4. none → None; the caller does the work and `finish` stores the response in the same transaction.
Errors roll the whole transaction back, so a failed attempt stores nothing and can be retried with the same key.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from tastoria.core.clock import utcnow
from tastoria.core.errors import PROBLEM_MEDIA_TYPE, ApiError, ProblemCode
from tastoria.core.models import IdempotencyKey

KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
RETENTION_HOURS = 48


@dataclass(frozen=True)
class IdempotencyRequest:
    key: str
    request_sha256: bytes


def _canonical_body(raw: bytes) -> bytes:
    if not raw:
        return b""
    try:
        return json.dumps(json.loads(raw), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    except (ValueError, UnicodeDecodeError):
        return raw


async def idempotency_key(request: Request) -> IdempotencyRequest:
    key = request.headers.get("idempotency-key")
    if key is None:
        raise ApiError(400, ProblemCode.idempotency_key_required)
    if not KEY_PATTERN.match(key):
        raise ApiError(
            400,
            ProblemCode.validation_error,
            errors=[{"pointer": "#/header/Idempotency-Key", "code": "pattern", "message": "16–64 ký tự [A-Za-z0-9_-]"}],
        )
    raw = await request.body()
    digest = hashlib.sha256(
        request.method.encode() + b"\n" + request.url.path.encode() + b"\n" + _canonical_body(raw)
    ).digest()
    return IdempotencyRequest(key, digest)


IdempotencyKeyDep = Annotated[IdempotencyRequest, Depends(idempotency_key)]


def begin(session: Session, user_id: uuid.UUID, idem: IdempotencyRequest) -> JSONResponse | None:
    got = session.execute(
        text("SELECT pg_try_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"idem:{user_id}:{idem.key}"}
    ).scalar_one()
    if not got:
        raise ApiError(409, ProblemCode.idempotency_in_progress, headers={"Retry-After": "1"})
    row = session.scalars(
        select(IdempotencyKey).where(IdempotencyKey.user_id == user_id, IdempotencyKey.key == idem.key)
    ).one_or_none()
    if row is None:
        return None
    if bytes(row.request_sha256) != idem.request_sha256:
        raise ApiError(422, ProblemCode.idempotency_key_reused)
    return JSONResponse(
        row.response_body,
        status_code=row.status_code,
        headers={"Idempotent-Replayed": "true"},
        media_type=PROBLEM_MEDIA_TYPE if row.status_code >= 400 else None,  # a stored 422 (SD03) stays a problem
    )


def finish(
    session: Session,
    user_id: uuid.UUID,
    idem: IdempotencyRequest,
    status_code: int,
    payload: Any,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = jsonable_encoder(payload)
    session.add(
        IdempotencyKey(
            user_id=user_id,
            key=idem.key,
            request_sha256=idem.request_sha256,
            status_code=status_code,
            response_body=body,
            created_at=utcnow(),
        )
    )
    session.flush()
    media = PROBLEM_MEDIA_TYPE if status_code >= 400 else None
    return JSONResponse(body, status_code=status_code, headers=headers, media_type=media)


def purge_expired(session: Session) -> int:
    """UC34: drop keys older than 48 hours."""
    res = session.execute(
        text("DELETE FROM idempotency_keys WHERE created_at < now() - make_interval(hours => :h)"),
        {"h": RETENTION_HOURS},
    )
    return res.rowcount or 0
