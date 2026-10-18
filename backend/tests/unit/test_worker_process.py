"""The worker process maps every table it writes through (regression: the first live scan failed with
NoReferencedTableError because `tastoria worker` never imported the models of identity / catalog)."""

from __future__ import annotations

import subprocess
import sys

CODE = """
import tastoria.cli as cli
cli.load_all_models()
from tastoria.core.db import Base
for t in Base.metadata.sorted_tables:
    for fk in t.foreign_keys:
        fk.column  # raises NoReferencedTableError when the referred table is not mapped
names = set(Base.metadata.tables)
assert {"scans", "scan_items", "detections", "pantry_lots", "users", "ingredients", "model_versions"} <= names
print("ok")
"""


def test_worker_entry_point_maps_every_referenced_table() -> None:
    r = subprocess.run([sys.executable, "-c", CODE], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "ok"
