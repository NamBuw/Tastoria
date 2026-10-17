"""AES-256-GCM for profiles.*_enc (ADR 0005). Only the profile module imports this file.

Blob layout: 1 byte format version (0x01) ‖ 12-byte random nonce ‖ ciphertext+tag.
Associated data binds a blob to its row and column, so a ciphertext copied to another user or another column
does not decrypt: b"tastoria:profiles:" + user_id + b":" + column.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

FORMAT_V1 = b"\x01"
NONCE_BYTES = 12


class DecryptionFailed(Exception):
    pass


def _aad(user_id: uuid.UUID, column: str) -> bytes:
    return b"tastoria:profiles:" + str(user_id).encode() + b":" + column.encode()


@dataclass(frozen=True)
class FieldCipher:
    keys: dict[str, bytes]  # enc_key_id -> 32-byte key
    active_key_id: str

    def __post_init__(self) -> None:
        if self.active_key_id not in self.keys:
            raise ValueError(f"active key {self.active_key_id!r} is not configured")
        for kid, k in self.keys.items():
            if len(k) != 32:
                raise ValueError(f"key {kid!r} must be 32 bytes")

    def encrypt(self, user_id: uuid.UUID, column: str, plaintext: str) -> tuple[bytes, str]:
        nonce = os.urandom(NONCE_BYTES)
        ct = AESGCM(self.keys[self.active_key_id]).encrypt(nonce, plaintext.encode("utf-8"), _aad(user_id, column))
        return FORMAT_V1 + nonce + ct, self.active_key_id

    def decrypt(self, key_id: str | None, user_id: uuid.UUID, column: str, blob: bytes) -> str:
        key = self.keys.get(key_id or "")
        if key is None:
            raise DecryptionFailed(f"key {key_id!r} not available")
        blob = bytes(blob)
        if not blob.startswith(FORMAT_V1) or len(blob) < 1 + NONCE_BYTES + 16:
            raise DecryptionFailed("unknown blob format")
        nonce, ct = blob[1 : 1 + NONCE_BYTES], blob[1 + NONCE_BYTES :]
        try:
            return AESGCM(key).decrypt(nonce, ct, _aad(user_id, column)).decode("utf-8")
        except InvalidTag as exc:
            raise DecryptionFailed("authentication failed") from exc
