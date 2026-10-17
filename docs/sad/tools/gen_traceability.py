#!/usr/bin/env python3
"""Sinh ma trận truy vết docs/sad/08-ma-tran-truy-vet.md.

Nguồn: model.yaml (UC -> endpoint/CLI -> module, UC -> BR) + front-matter UC
(frs, tables, tests, rules) + bảng TC trong docs/sad/06-ke-hoach-kiem-thu.md
(mỗi dòng định nghĩa TC liệt kê FR/BR/UC mà ca đó kiểm).

Ô trống được đếm theo nhóm:
  - endpoint không UC nào dùng (và không TC nào kiểm)
  - bảng không UC nào dùng
  - BR không UC nào và không TC nào tham chiếu
  - FR không có TC
  - UC không có FR
  - UC không có TC

Cách dùng: gen_traceability.py [--strict] [--root DIR] [--model FILE] [--out FILE]
--strict: thoát mã 1 nếu còn ô trống.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_refs import (  # noqa: E402
    DEFAULT_ROOT, GENERATED_MATRIX_REL, ID_PATTERNS, TEST_PLAN_REL, as_list, load_model,
    load_use_case_files, parse_test_plan,
)


def cell(items) -> str:
    items = [str(i) for i in items if i not in (None, "")]
    return "<br>".join(f"`{i}`" for i in items) if items else "—"


def build(root: Path, model_path: Path):
    model = load_model(model_path)
    ucs = load_use_case_files(root)
    plan = parse_test_plan(root)

    rows = []
    fr_owner = {}  # FR -> UC
    fr_tc = {}  # FR -> set TC
    uc_tables = {}
    br_used_uc = {}
    tc_by_uc = {}
    for tc, refs in plan.tc_refs.items():
        for r in refs:
            if r.startswith("FR-"):
                fr_tc.setdefault(r, set()).add(tc)
            if r.startswith("UC"):
                tc_by_uc.setdefault(r, set()).add(tc)

    for uid, mu in model.use_cases.items():
        f = ucs.get(uid)
        meta = (f.meta or {}) if f else {}
        frs = [str(x) for x in as_list(meta.get("frs"))]
        if f:
            # FR định nghĩa trong thân nhưng quên khai trong frs vẫn được tính
            frs += [fr for fr in f.fr_defs if fr not in frs]
        tables = [str(x) for x in as_list(meta.get("tables"))]
        tests = sorted(set(str(x) for x in as_list(meta.get("tests"))) | tc_by_uc.get(uid, set()))
        eps = [e for e in model.endpoints if uid in e["ucs"]]
        clis = [c for c in model.cli if uid in c["use_cases"]]
        # endpoint khai ở front-matter mà model không gắn: vẫn tính là "được dùng"
        extra_eps, extra_cli = [], []
        for s in as_list(meta.get("endpoints")):
            s = str(s)
            if s.startswith("CLI "):
                c = model.cli_lookup(s)
                if c and c not in clis:
                    extra_cli.append(c)
            else:
                ep = model.endpoint_lookup(s)
                if ep and ep not in eps:
                    extra_eps.append(ep)
        eps += extra_eps
        clis += extra_cli
        modules = []
        for m in [e["module"] for e in eps] + [c["module"] for c in clis]:
            if m not in modules:
                modules.append(m)
        rules = list(dict.fromkeys(list(mu.get("rules", [])) + [str(r) for r in as_list(meta.get("rules"))]))
        for r in rules:
            br_used_uc.setdefault(r, set()).add(uid)
        for fr in frs:
            fr_owner.setdefault(fr, uid)
            if f and fr in f.fr_defs:
                # TC ghi ngay trong dòng định nghĩa FR cũng được tính
                line = f.fr_defs[fr][1]
                for tc in ID_PATTERNS["tc"].findall(line):
                    if tc in plan.tc_defs:
                        fr_tc.setdefault(fr, set()).add(tc)
        uc_tables[uid] = tables
        rows.append({
            "uc": uid, "name": mu.get("name", ""), "has_file": f is not None, "frs": frs,
            "access": [e["label"] for e in eps] + [f"CLI {c['cmd']}" for c in clis],
            "modules": modules, "tables": tables, "tests": tests, "rules": rules,
        })

    # ---- ô trống
    used_ep = {e["key"] for r in rows for e in model.endpoints if e["label"] in r["access"]}
    gaps = {}
    ep_no_uc = []
    for e in model.endpoints:
        if e["key"] in used_ep:
            continue
        tcs = sorted(tc for tc, (_, line) in plan.tc_defs.items()
                     if e["path"] in line and e["method"] in line)
        ep_no_uc.append((e, tcs))
    gaps["endpoint_no_uc"] = [e["label"] for e, tcs in ep_no_uc if not tcs]
    used_tables = {t for ts in uc_tables.values() for t in ts}
    gaps["table_no_uc"] = [t for t in model.tables if t not in used_tables]
    br_tc = {}
    for tc, refs in plan.tc_refs.items():
        for r in refs:
            if r.startswith("BR-"):
                br_tc.setdefault(r, set()).add(tc)
    gaps["br_no_uc_tc"] = [b for b in model.brs if b not in br_used_uc and b not in br_tc]
    all_frs = [fr for r in rows for fr in r["frs"]]
    gaps["fr_no_tc"] = [fr for fr in all_frs if not fr_tc.get(fr)]
    gaps["uc_no_fr"] = [r["uc"] for r in rows if not r["frs"]]
    gaps["uc_no_tc"] = [r["uc"] for r in rows if not r["tests"]]
    return {
        "model": model, "rows": rows, "gaps": gaps, "ep_no_uc": ep_no_uc,
        "fr_owner": fr_owner, "fr_tc": fr_tc, "br_used_uc": br_used_uc, "br_tc": br_tc,
        "plan_exists": plan.exists,
    }


GAP_TITLES = {
    "endpoint_no_uc": "Endpoint không UC nào dùng và không TC nào kiểm",
    "table_no_uc": "Bảng không UC nào dùng",
    "br_no_uc_tc": "BR không UC nào và không TC nào tham chiếu",
    "fr_no_tc": "FR chưa có TC",
    "uc_no_fr": "UC chưa có FR",
    "uc_no_tc": "UC chưa có TC",
}


def render(res) -> str:
    model, rows, gaps = res["model"], res["rows"], res["gaps"]
    out = []
    w = out.append
    w("# Ma trận truy vết")
    w("")
    w("> Tệp sinh tự động bởi `docs/sad/tools/gen_traceability.py` từ `docs/sad/model.yaml`, "
      "front-matter `docs/sad/use-cases/UCxx.md` và `" + TEST_PLAN_REL + "`. Không sửa tay; "
      "sửa nguồn rồi chạy lại script.")
    w("")
    w("## 1. Tóm tắt ô trống")
    w("")
    w("| Nhóm | Số lượng |")
    w("|---|---|")
    for k, title in GAP_TITLES.items():
        w(f"| {title} | {len(gaps[k])} |")
    w(f"| **Tổng** | **{sum(len(v) for v in gaps.values())}** |")
    w("")
    if not res["plan_exists"]:
        w(f"Chưa có `{TEST_PLAN_REL}`: mọi FR và UC được tính là chưa có TC.")
        w("")
    w("## 2. Ma trận UC × FR × endpoint/CLI × module × bảng × TC")
    w("")
    w("| UC | Tên | FR | Endpoint / CLI | Module | Bảng / view | TC |")
    w("|---|---|---|---|---|---|---|")
    for r in rows:
        name = r["name"] + ("" if r["has_file"] else " *(chưa có tệp đặc tả)*")
        w(f"| {r['uc']} | {name} | {cell(r['frs'])} | {cell(r['access'])} | "
          f"{cell(r['modules'])} | {cell(r['tables'])} | {cell(r['tests'])} |")
    w("")
    w("## 3. FR → TC")
    w("")
    fr_rows = [(fr, r["uc"]) for r in rows for fr in r["frs"]]
    if fr_rows:
        w("| FR | UC | TC |")
        w("|---|---|---|")
        for fr, uc in fr_rows:
            w(f"| {fr} | {uc} | {cell(sorted(res['fr_tc'].get(fr, [])))} |")
    else:
        w("Chưa có FR nào được định nghĩa.")
    w("")
    w("## 4. BR → UC, TC")
    w("")
    w("| BR | UC | TC |")
    w("|---|---|---|")
    for b in model.brs:
        w(f"| {b} | {cell(sorted(res['br_used_uc'].get(b, [])))} | {cell(sorted(res['br_tc'].get(b, [])))} |")
    w("")
    w("## 5. Độ phủ ngược")
    w("")
    w("### 5.1. Endpoint không UC nào dùng")
    w("")
    if res["ep_no_uc"]:
        w("| Endpoint | Module | TC kiểm |")
        w("|---|---|---|")
        for e, tcs in res["ep_no_uc"]:
            w(f"| `{e['label']}` | {e['module']} | {cell(tcs)} |")
        w("")
        w("Endpoint có TC kiểm (ví dụ endpoint vận hành) không tính là ô trống.")
    else:
        w("Không có.")
    w("")
    sections = [
        ("5.2. Bảng không UC nào dùng", gaps["table_no_uc"]),
        ("5.3. BR không UC nào và không TC nào tham chiếu", gaps["br_no_uc_tc"]),
        ("5.4. FR chưa có TC", gaps["fr_no_tc"]),
        ("5.5. UC chưa có FR", gaps["uc_no_fr"]),
        ("5.6. UC chưa có TC", gaps["uc_no_tc"]),
    ]
    for title, items in sections:
        w(f"### {title}")
        w("")
        w(", ".join(f"`{i}`" for i in items) if items else "Không có.")
        w("")
    return "\n".join(out).rstrip() + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Sinh ma trận truy vết")
    ap.add_argument("--strict", action="store_true", help="thoát 1 nếu còn ô trống")
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    ap.add_argument("--model", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)
    root = args.root.resolve()
    res = build(root, args.model or root / "docs/sad/model.yaml")
    out = args.out or root / GENERATED_MATRIX_REL
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(res), encoding="utf-8")
    total = 0
    for k, title in GAP_TITLES.items():
        items = res["gaps"][k]
        total += len(items)
        shown = ", ".join(items[:12]) + (" ..." if len(items) > 12 else "")
        print(f"{title}: {len(items)}" + (f" [{shown}]" if items else ""))
    print(f"gen_traceability: đã ghi {out}; tổng ô trống {total}")
    return 1 if (args.strict and total) else 0


if __name__ == "__main__":
    sys.exit(main())
