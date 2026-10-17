from __future__ import annotations

import hashlib
import importlib.util

from tastoria.migrations import MIGRATIONS_DIR
from tastoria.modules.privacy.service import POLICY_DIR


def _migration_0002():
    spec = importlib.util.spec_from_file_location(
        "m0002", MIGRATIONS_DIR / "versions/0002_consent_purposes_policies.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_published_policy_texts_are_unchanged() -> None:
    """A published policy text is evidence of what users agreed to; edit = new file + new version + migration."""
    m = _migration_0002()
    for p in m.PURPOSES:
        raw = (POLICY_DIR / f"{p['code']}-{m.VERSION}.md").read_bytes()
        assert hashlib.sha256(raw).hexdigest() == p["sha256"], p["code"]
    assert {p["code"] for p in m.PURPOSES} == {"health_profile", "personalization", "photo_contribution", "survey"}
