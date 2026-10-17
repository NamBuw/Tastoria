from __future__ import annotations

import uuid

import pytest

from tastoria.modules.profile.crypto import DecryptionFailed, FieldCipher

K1, K2 = bytes(range(32)), bytes(range(1, 33))


def test_roundtrip_and_random_nonce() -> None:
    c = FieldCipher({"a": K1}, "a")
    u = uuid.uuid4()
    b1, kid = c.encrypt(u, "weight_kg_enc", "52.5")
    b2, _ = c.encrypt(u, "weight_kg_enc", "52.5")
    assert kid == "a" and b1 != b2 and b"52.5" not in b1
    assert c.decrypt("a", u, "weight_kg_enc", b1) == "52.5"


def test_blob_is_bound_to_user_and_column() -> None:
    c = FieldCipher({"a": K1}, "a")
    u = uuid.uuid4()
    blob, _ = c.encrypt(u, "weight_kg_enc", "52.5")
    with pytest.raises(DecryptionFailed):
        c.decrypt("a", uuid.uuid4(), "weight_kg_enc", blob)
    with pytest.raises(DecryptionFailed):
        c.decrypt("a", u, "height_cm_enc", blob)


def test_tampering_and_missing_key_fail() -> None:
    c = FieldCipher({"a": K1}, "a")
    u = uuid.uuid4()
    blob, _ = c.encrypt(u, "sex_enc", "female")
    with pytest.raises(DecryptionFailed):
        c.decrypt("a", u, "sex_enc", blob[:-1] + bytes([blob[-1] ^ 1]))
    with pytest.raises(DecryptionFailed):
        c.decrypt("gone", u, "sex_enc", blob)


def test_key_rotation_reads_old_writes_new() -> None:
    old = FieldCipher({"a": K1}, "a")
    u = uuid.uuid4()
    blob, kid = old.encrypt(u, "sex_enc", "male")
    rotated = FieldCipher({"a": K1, "b": K2}, "b")
    assert rotated.decrypt(kid, u, "sex_enc", blob) == "male"
    assert rotated.encrypt(u, "sex_enc", "male")[1] == "b"


def test_bad_configuration() -> None:
    with pytest.raises(ValueError):
        FieldCipher({"a": b"short"}, "a")
    with pytest.raises(ValueError):
        FieldCipher({"a": K1}, "missing")
