#!/usr/bin/env python3
"""Tổng hợp yêu cầu chức năng (FR) từ các đặc tả use case vào SRS.

Nguồn: bảng FR trong thân docs/sad/use-cases/UCxx.md, dòng có dạng
  | FR-xx-yy | Phát biểu | MoSCoW | Tiêu chí chấp nhận |
Script sinh hai khối Markdown và (với --write) thay vào docs/sad/01-SRS.md giữa
các cặp mốc:
  <!-- BEGIN:FR-TABLE -->      ... <!-- END:FR-TABLE -->
  <!-- BEGIN:UC-MOSCOW -->     ... <!-- END:UC-MOSCOW -->

Cách dùng:
  collect_frs.py            in hai khối ra stdout
  collect_frs.py --write    ghi vào 01-SRS.md
  collect_frs.py --check    thoát 1 nếu 01-SRS.md lệch với kết quả sinh ra
Kiểm thêm: FR trùng mã, FR sai số UC, MoSCoW ngoài {M, S, C, W}, frs trong
front-matter lệch bảng FR. Có lỗi thì thoát 2.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
UC_DIR = ROOT / "docs/sad/use-cases"
SRS = ROOT / "docs/sad/01-SRS.md"
MODEL = ROOT / "docs/sad/model.yaml"
FR_ROW = re.compile(r"^\s*\|\s*\**`?(FR-(\d\d)-\d\d)`?\**\s*\|")
MOSCOW = ("M", "S", "C", "W")
MOSCOW_VI = {"M": "Must", "S": "Should", "C": "Could", "W": "Won't"}


def split_row(line: str) -> list[str]:
    """Tách ô bảng Markdown: bỏ qua '|' đã thoát (\\|) và '|' nằm trong `code`."""
    cells, buf, in_code, i = [], [], False, 0
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s) and s[i + 1] == "|":
            buf.append("\\|")
            i += 2
            continue
        if ch == "`":
            in_code = not in_code
        if ch == "|" and not in_code:
            cells.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
        i += 1
    cells.append("".join(buf).strip())
    return cells


def front_matter(text: str) -> dict:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return yaml.safe_load("\n".join(lines[1:i])) or {}
    return {}


def collect():
    model = yaml.safe_load(MODEL.read_text(encoding="utf-8"))
    ucs = {u["id"]: u for u in model["use_cases"]}
    pk_names = {p["id"]: p["name"] for p in model["packages"]}
    frs, errors = [], []
    seen = {}
    for p in sorted(UC_DIR.glob("UC*.md")):
        text = p.read_text(encoding="utf-8")
        meta = front_matter(text)
        uc_id = p.stem
        found = []
        for n, line in enumerate(text.splitlines(), start=1):
            m = FR_ROW.match(line)
            if not m:
                continue
            cells = split_row(line)
            if len(cells) < 3:
                errors.append(f"{p.name}:{n}: dòng FR thiếu cột")
                continue
            fr_id, stmt, prio = m.group(1), cells[1], cells[2].strip("* ")
            if m.group(2) != uc_id[2:]:
                errors.append(f"{p.name}:{n}: {fr_id} không thuộc {uc_id}")
            if prio not in MOSCOW:
                errors.append(f"{p.name}:{n}: {fr_id} MoSCoW lạ '{prio}'")
            if fr_id in seen:
                errors.append(f"{p.name}:{n}: {fr_id} trùng (đã có ở {seen[fr_id]})")
                continue
            seen[fr_id] = p.name
            found.append(fr_id)
            frs.append({"id": fr_id, "uc": uc_id, "stmt": stmt, "prio": prio})
        listed = list(meta.get("frs") or [])
        if set(listed) != set(found):
            errors.append(f"{p.name}: front-matter frs lệch bảng FR "
                          f"(thiếu trong bảng: {sorted(set(listed) - set(found))}, "
                          f"thiếu trong frs: {sorted(set(found) - set(listed))})")
    missing = sorted(set(ucs) - {p.stem for p in UC_DIR.glob("UC*.md")})
    if missing:
        errors.append(f"thiếu tệp đặc tả cho: {missing}")
    frs.sort(key=lambda f: f["id"])
    return frs, ucs, pk_names, errors


def fr_table(frs) -> str:
    c = Counter(f["prio"] for f in frs)
    out = [f"Tổng số: {len(frs)} FR — "
           + ", ".join(f"{k} ({MOSCOW_VI[k]}) {c.get(k, 0)}" for k in MOSCOW if c.get(k, 0) or k != "W")
           + ". Tiêu chí chấp nhận Given/When/Then của từng FR nằm trong tệp đặc tả UC tương ứng.",
           "",
           "| Mã | UC | Phát biểu | MoSCoW |",
           "|---|---|---|---|"]
    for f in frs:
        out.append(f"| {f['id']} | {f['uc']} | {f['stmt']} | {f['prio']} |")
    return "\n".join(out)


def uc_moscow(frs, ucs, pk_names) -> str:
    per = {u: Counter() for u in ucs}
    for f in frs:
        per[f["uc"]][f["prio"]] += 1
    out = ["| UC | Tên | Gói | MoSCoW UC | Số FR | FR M | FR S | FR C |",
           "|---|---|---|---|---|---|---|---|"]
    tot = Counter()
    for uid in sorted(ucs):
        u, c = ucs[uid], per[uid]
        tot.update(c)
        out.append(f"| {uid} | {u['name']} | {u['pkg']} | {u['priority']} | {sum(c.values())} "
                   f"| {c['M']} | {c['S']} | {c['C']} |")
    uc_c = Counter(u["priority"] for u in ucs.values())
    out.append(f"| **Tổng** | {len(ucs)} UC | | M {uc_c['M']} · S {uc_c['S']} · C {uc_c['C']} "
               f"| {sum(tot.values())} | {tot['M']} | {tot['S']} | {tot['C']} |")
    return "\n".join(out)


def replace_block(text: str, name: str, body: str) -> str:
    rx = re.compile(rf"(<!-- BEGIN:{name} -->\n)(?:.*?\n)?(<!-- END:{name} -->)", re.S)
    if not rx.search(text):
        raise SystemExit(f"01-SRS.md thiếu mốc BEGIN/END:{name}")
    return rx.sub(lambda m: m.group(1) + body + "\n" + m.group(2), text, count=1)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--write", action="store_true")
    g.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    frs, ucs, pk_names, errors = collect()
    for e in errors:
        print(f"LỖI  {e}", file=sys.stderr)
    blocks = {"FR-TABLE": fr_table(frs), "UC-MOSCOW": uc_moscow(frs, ucs, pk_names)}
    if a.write or a.check:
        old = SRS.read_text(encoding="utf-8")
        new = old
        for k, v in blocks.items():
            new = replace_block(new, k, v)
        if a.write:
            SRS.write_text(new, encoding="utf-8")
            print(f"collect_frs: ghi {len(frs)} FR vào {SRS.relative_to(ROOT)}")
        elif new != old:
            print("collect_frs: 01-SRS.md lệch với đặc tả UC, chạy lại --write", file=sys.stderr)
            return 1
        else:
            print(f"collect_frs: 01-SRS.md khớp ({len(frs)} FR)")
    else:
        for k, v in blocks.items():
            print(f"<!-- {k} -->\n{v}\n")
    return 2 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
