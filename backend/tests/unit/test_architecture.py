"""Module boundaries of docs/sad/model.yaml are enforced (ADR 0001, NFR-MAINT-01)."""

from __future__ import annotations

import subprocess
import sys

from conftest import BACKEND_DIR


def test_importlinter_contracts_are_generated_from_model_yaml() -> None:
    r = subprocess.run(
        [sys.executable, str(BACKEND_DIR / "scripts/gen_importlinter.py"), "--check"], capture_output=True, text=True
    )
    assert r.returncode == 0, r.stderr


def test_import_contracts_hold() -> None:
    lint = BACKEND_DIR.parent / ".venv/bin/lint-imports"
    cmd = [str(lint)] if lint.exists() else [sys.executable, "-m", "importlinter.cli"]
    r = subprocess.run([*cmd, "--config", str(BACKEND_DIR / ".importlinter")], capture_output=True, text=True,
                       cwd=BACKEND_DIR)  # fmt: skip
    assert r.returncode == 0, r.stdout + r.stderr
    assert "0 broken" in r.stdout
