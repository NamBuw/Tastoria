"""Access JWT (15 min, `kid` header, claims sub/role/tv) and opaque refresh / reset tokens (ADR 0004)."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import jwt

from tastoria.core.config import Settings


@dataclass(frozen=True)
class AccessClaims:
    user_id: uuid.UUID
    role: str
    token_version: int


class InvalidAccessToken(Exception):
    pass


def new_opaque_token() -> str:
    return secrets.token_urlsafe(32)  # 32 random bytes


def sha256(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def issue_access_token(settings: Settings, *, user_id: uuid.UUID, role: str, token_version: int, now: datetime) -> str:
    kid = settings.jwt_active_kid
    claims = {
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "sub": str(user_id),
        "role": role,
        "tv": token_version,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=settings.access_token_ttl_s)).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, settings.jwt_keys[kid], algorithm="HS256", headers={"kid": kid})


def decode_access_token(settings: Settings, token: str) -> AccessClaims:
    try:
        kid = jwt.get_unverified_header(token).get("kid")
        key = settings.jwt_keys.get(kid) if isinstance(kid, str) else None
        if key is None:
            raise InvalidAccessToken("unknown kid")
        claims = jwt.decode(
            token,
            key,
            algorithms=["HS256"],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "sub", "iss", "aud", "tv"]},
        )
        return AccessClaims(uuid.UUID(claims["sub"]), str(claims.get("role", "user")), int(claims["tv"]))
    except (jwt.PyJWTError, ValueError, KeyError, TypeError) as exc:
        raise InvalidAccessToken(str(exc)) from exc
