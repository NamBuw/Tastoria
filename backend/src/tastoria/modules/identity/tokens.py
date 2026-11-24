"""Access JWT (15 min, `kid` header, claims sub/role/tv/mfa), opaque tokens, and RFC 6238 TOTP + AES-GCM (ADR 0004)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import struct
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import quote

import jwt
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from tastoria.core.config import Settings

_TOTP_FORMAT_V1 = b"\x01"
_TOTP_NONCE_BYTES = 12


@dataclass(frozen=True)
class AccessClaims:
    user_id: uuid.UUID
    role: str
    token_version: int
    mfa: bool = False


class InvalidAccessToken(Exception):
    pass


class TotpDecryptionFailed(Exception):
    pass


def new_opaque_token() -> str:
    return secrets.token_urlsafe(32)  # 32 random bytes


def sha256(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def issue_access_token(
    settings: Settings,
    *,
    user_id: uuid.UUID,
    role: str,
    token_version: int,
    now: datetime,
    mfa: bool = False,
) -> str:
    kid = settings.jwt_active_kid
    claims = {
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "sub": str(user_id),
        "role": role,
        "tv": token_version,
        "mfa": bool(mfa),
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
        return AccessClaims(
            uuid.UUID(claims["sub"]),
            str(claims.get("role", "user")),
            int(claims["tv"]),
            bool(claims.get("mfa", False)),
        )
    except (jwt.PyJWTError, ValueError, KeyError, TypeError) as exc:
        raise InvalidAccessToken(str(exc)) from exc


# ---------------------------------------------------------------- RFC 6238 TOTP & AES-256-GCM storage


def generate_totp_secret() -> bytes:
    return secrets.token_bytes(20)


def totp_secret_b32(secret: bytes) -> str:
    return base64.b32encode(secret).decode("ascii").rstrip("=")


def provisioning_uri(secret_b32: str, email: str, *, issuer: str = "Mỹ Vị") -> str:
    label = quote(f"{issuer}:{email}", safe=":")
    q_issuer = quote(issuer, safe="")
    return f"otpauth://totp/{label}?secret={secret_b32}&issuer={q_issuer}&algorithm=SHA1&digits=6&period=30"


def _hotp(secret: bytes, counter: int, digits: int = 6) -> str:
    msg = struct.pack(">Q", counter)
    digest = hmac.new(secret, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % (10**digits)
    return f"{code:0{digits}d}"


def verify_totp(secret: bytes, code: str, *, now: datetime, window: int = 1, period: int = 30, digits: int = 6) -> bool:
    clean = code.strip()
    if len(clean) != digits or not clean.isascii() or not clean.isdigit():
        return False
    counter = int(now.timestamp()) // period
    matched = False
    for offset in range(-window, window + 1):
        if hmac.compare_digest(_hotp(secret, counter + offset, digits), clean):
            matched = True
    return matched


def _totp_aad(user_id: uuid.UUID) -> bytes:
    return b"tastoria:users:totp:" + str(user_id).encode("ascii")


def encrypt_totp_secret(settings: Settings, user_id: uuid.UUID, secret: bytes) -> tuple[bytes, str]:
    key_id = settings.health_enc_active_key_id
    key = settings.enc_key(key_id)
    if key is None:
        raise ValueError(f"active encryption key {key_id!r} is not configured")
    nonce = os.urandom(_TOTP_NONCE_BYTES)
    ct = AESGCM(key).encrypt(nonce, secret, _totp_aad(user_id))
    return _TOTP_FORMAT_V1 + nonce + ct, key_id


def decrypt_totp_secret(settings: Settings, key_id: str | None, user_id: uuid.UUID, blob: bytes) -> bytes:
    key = settings.enc_key(key_id or "")
    if key is None:
        raise TotpDecryptionFailed(f"key {key_id!r} not available")
    raw = bytes(blob)
    if not raw.startswith(_TOTP_FORMAT_V1) or len(raw) < 1 + _TOTP_NONCE_BYTES + 16:
        raise TotpDecryptionFailed("invalid totp secret blob")
    nonce, ct = raw[1 : 1 + _TOTP_NONCE_BYTES], raw[1 + _TOTP_NONCE_BYTES :]
    try:
        return AESGCM(key).decrypt(nonce, ct, _totp_aad(user_id))
    except InvalidTag as exc:
        raise TotpDecryptionFailed("authentication failed") from exc
