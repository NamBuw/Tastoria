"""Opaque keyset cursors (openapi PageCursor): base64url of a JSON list of the sort key of the last item returned.

Lists sorted by (created_at, id) use `encode_created(created_at, id)`; lists sorted by a computed key (pantry
urgency) put their own tuple in the cursor. A cursor that does not decode is a 400 validation_error on `cursor`.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime
from typing import Any

from tastoria.core.errors import ApiError, ProblemCode

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


def encode(key: list[Any]) -> str:
    raw = json.dumps(key, separators=(",", ":"), default=str).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode(cursor: str | None) -> list[Any] | None:
    if cursor is None:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        key = json.loads(raw)
        if not isinstance(key, list):
            raise ValueError
        return key
    except (ValueError, json.JSONDecodeError):
        raise ApiError(
            400,
            ProblemCode.validation_error,
            errors=[{"pointer": "#/query/cursor", "code": "invalid_cursor", "message": "Con trỏ trang không hợp lệ."}],
        ) from None


def encode_created(created_at: datetime, id_: uuid.UUID) -> str:
    return encode([created_at.isoformat(), str(id_)])


def decode_created(cursor: str | None) -> tuple[datetime, uuid.UUID] | None:
    key = decode(cursor)
    if key is None:
        return None
    try:
        return datetime.fromisoformat(key[0]), uuid.UUID(key[1])
    except (IndexError, TypeError, ValueError):
        raise ApiError(
            400,
            ProblemCode.validation_error,
            errors=[{"pointer": "#/query/cursor", "code": "invalid_cursor", "message": "Con trỏ trang không hợp lệ."}],
        ) from None
