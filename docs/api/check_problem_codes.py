#!/usr/bin/env python3
"""Đối chiếu mã lỗi trong tài liệu với danh mục `ProblemCode` của docs/api/openapi-v1.yaml.

Quét docs/sad/use-cases/UC*.md, docs/sad/01-SRS.md, docs/sad/06-ke-hoach-kiem-thu.md và docs/uml/**/*.puml.
Báo (tệp:dòng) khi:
  - một mã lỗi được nhắc (dạng "409 `x`", "`code = x`", "mã `x`") không có trong enum ProblemCode;
  - mã có trong enum nhưng đi với mã HTTP khác với danh mục (`x-catalog`);
  - còn mã đã đổi tên ở bản OpenAPI trước (validation_failed, account_locked, ...).
Thoát mã 1 nếu có chỗ lệch.

Dùng: uv run --with pyyaml python docs/api/check_problem_codes.py [--root DIR]
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
OLD = ["validation_failed", "account_locked", "token_reused", "token_invalid", "undo_window_closed",
       "infeasible_tray", "scan_not_ready", "image_invalid", "policy_version_outdated"]
PATS = [
    re.compile(r"\b([1-5]\d\d)\b`?,?\s*(?:problem\+json\s*)?\(?\s*`(?:code\s*=\s*)?([a-z][a-z0-9_]+)`"),
    re.compile(r"()`code\s*=\s*([a-z][a-z0-9_]+)`"),
    re.compile(r"()\bmã lỗi `([a-z][a-z0-9_]+)`"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(ROOT))
    a = ap.parse_args()
    root = pathlib.Path(a.root)
    spec = yaml.safe_load((root / "docs/api/openapi-v1.yaml").read_text(encoding="utf-8"))
    pc = spec["components"]["schemas"]["ProblemCode"]
    cat = {e["code"]: {s.strip() for s in e["status"].split(",")} for e in pc["x-catalog"]}
    assert set(cat) == set(pc["enum"]), "x-catalog lệch enum"
    model = yaml.safe_load((root / "docs/sad/model.yaml").read_text(encoding="utf-8"))
    columns = {str(c).split()[0] for t in model["tables"] for c in t["columns"]}

    files = sorted((root / "docs/sad/use-cases").glob("UC*.md")) + [
        root / "docs/sad/01-SRS.md", root / "docs/sad/06-ke-hoach-kiem-thu.md"] + sorted(
        p for p in (root / "docs/uml").rglob("*.puml"))
    old_re = re.compile(r"(?<![a-z_])(" + "|".join(OLD) + r")(?![a-z_])")
    bad: set[str] = set()
    for f in files:
        if not f.exists():
            continue
        rel = f.relative_to(root)
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            for m in old_re.finditer(line):
                bad.add(f"{rel}:{i}: mã cũ `{m.group(1)}` (không còn trong ProblemCode)")
            for p in PATS:
                for m in p.finditer(line):
                    st, c = m.group(1), m.group(2)
                    if c in columns or c in OLD:
                        continue
                    if c not in cat:
                        if st and int(st) >= 400:
                            bad.add(f"{rel}:{i}: mã `{c}` không có trong ProblemCode")
                    elif st and st not in cat[c]:
                        bad.add(f"{rel}:{i}: `{c}` đi với HTTP {st}, danh mục ghi {'/'.join(sorted(cat[c]))}")
    for b in sorted(bad):
        print(b)
    print(f"check_problem_codes: {len(cat)} mã trong danh mục; {len(bad)} chỗ lệch")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
