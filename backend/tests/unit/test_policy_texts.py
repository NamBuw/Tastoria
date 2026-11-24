from __future__ import annotations

import hashlib
import importlib.util

from tastoria.migrations import MIGRATIONS_DIR
from tastoria.modules.privacy.service import POLICY_DIR


def _load_migration(filename: str):
    spec = importlib.util.spec_from_file_location(filename.removesuffix(".py"), MIGRATIONS_DIR / "versions" / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_published_policy_texts_are_unchanged() -> None:
    """A published policy text is evidence of what users agreed to; edit = new file + new version + migration."""
    m2 = _load_migration("0002_consent_purposes_policies.py")
    for p in m2.PURPOSES:
        raw = (POLICY_DIR / f"{p['code']}-{m2.VERSION}.md").read_bytes()
        assert hashlib.sha256(raw).hexdigest() == p["sha256"], p["code"]
    assert {p["code"] for p in m2.PURPOSES} == {"health_profile", "personalization", "photo_contribution", "survey"}

    m7 = _load_migration("0007_commercial_hardening.py")
    assert m7.VERSION == "2026-11-24"
    for p in m7.POLICIES:
        raw = (POLICY_DIR / f"{p['code']}-{m7.VERSION}.md").read_bytes()
        assert hashlib.sha256(raw).hexdigest() == p["sha256"], p["code"]
        text = raw.decode("utf-8")
        assert "Mỹ Vị" in text
        for forbidden in ("Tastoria", "app", "–", "—"):
            assert forbidden not in text, f"{p['code']} contains {forbidden!r}"
    assert {p["code"] for p in m7.POLICIES} == {"health_profile", "survey"}
