"""Argon2id password hashing via pwdlib (ADR 0004; passlib does not run on Python 3.13+)."""

from __future__ import annotations

from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

_hasher = PasswordHash((Argon2Hasher(),))
# Verified against when the email is unknown, so both failure paths cost one Argon2 verification.
_DUMMY_HASH = _hasher.hash("tastoria-timing-equaliser")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> tuple[bool, str | None]:
    """Returns (ok, new_hash_if_parameters_changed)."""
    if password_hash is None:
        _hasher.verify(password, _DUMMY_HASH)
        return False, None
    return _hasher.verify_and_update(password, password_hash)
