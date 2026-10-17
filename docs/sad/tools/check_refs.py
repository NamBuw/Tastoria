#!/usr/bin/env python3
"""Kiểm tra mã tham chiếu trong bộ tài liệu phân tích thiết kế Tastoria.

Nguồn sự thật: docs/sad/model.yaml. Script quét
  docs/sad/**/*.md, docs/uml/**/*.puml, docs/erd/*.puml, docs/adr/*.md
và báo mọi mã (actor, UC, gói, module, BR, NFR, FR, TC, endpoint) không tồn tại
dưới dạng tệp:dòng. Ngoài ra kiểm front-matter của docs/sad/use-cases/UCxx.md.

Cách dùng:
  check_refs.py [--warn-only] [--root DIR] [--model FILE]
Thoát mã 1 nếu có lỗi (trừ khi --warn-only).

Module này cũng được gen_traceability.py dùng lại (load_model, load_use_case_files,
parse_test_plan).
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_ROOT = Path(__file__).resolve().parents[3]
API_PREFIX = "/api/v1"
TEST_PLAN_REL = "docs/sad/06-ke-hoach-kiem-thu.md"
UC_DIR_REL = "docs/sad/use-cases"
GENERATED_MATRIX_REL = "docs/sad/08-ma-tran-truy-vet.md"

FRONT_MATTER_KEYS = [
    "id", "name", "package", "primary_actor", "secondary_actors", "priority",
    "rules", "endpoints", "tables", "frs", "tests",
]
LIST_KEYS = ["secondary_actors", "rules", "endpoints", "tables", "frs", "tests"]

# Biên trái/phải: không dính chữ, số, gạch nối (tránh khớp "NFR-A11Y-01" thành A11, "SHA256"...).
_L = r"(?<![A-Za-z0-9_\-])"
_R = r"(?![A-Za-z0-9_])"
ID_PATTERNS = {
    "actor": re.compile(_L + r"A\d\d" + _R),
    "use_case": re.compile(_L + r"UC\d\d" + _R),
    "package": re.compile(_L + r"PK\d+" + _R),
    "module": re.compile(_L + r"M\d\d" + _R),
    "br": re.compile(_L + r"BR-[A-Z]+-\d\d" + _R),
    "nfr": re.compile(_L + r"NFR-[A-Z0-9]+-\d\d" + _R),
    "fr": re.compile(_L + r"FR-\d\d-\d\d" + _R),
    "tc": re.compile(_L + r"TC-[A-Z0-9]+-\d{2,}" + _R),
}
HTTP_RE = re.compile(_L + r"(GET|POST|PUT|PATCH|DELETE)\s+(/[A-Za-z0-9_\-/{}<>.:]*)")
# Dòng bảng Markdown mà ô đầu là một mã: dùng để nhận diện ĐỊNH NGHĨA FR/TC.
TABLE_ROW_ID_RE = r"^\s*\|\s*\**`?({pat})`?\**\s*\|"
HEADING_ID_RE = r"^\s*#{{1,6}}\s+\**`?({pat})`?\**(?![A-Za-z0-9_\-])"
FR_BARE = r"FR-\d\d-\d\d"
TC_BARE = r"TC-[A-Z0-9]+-\d{2,}"


# ---------------------------------------------------------------- mô hình
@dataclass
class Model:
    actors: dict
    packages: dict
    use_cases: dict  # id -> dict
    modules: dict  # name -> dict ; ids in module_ids
    module_ids: set
    tables: dict  # name -> dict
    views: dict
    endpoints: list  # list of dict(method, path, key, module, ucs, idem, auth)
    endpoint_keys: dict  # normalized key -> endpoint
    cli: list  # list of dict(cmd, module, use_cases)
    brs: list
    nfrs: list

    def endpoint_lookup(self, text: str):
        """Khớp chính xác theo mẫu; nếu không có, cho phép giá trị cụ thể ở vị trí tham số
        (GET /policies/survey/current khớp GET /policies/{purpose}/current)."""
        key = normalize_endpoint(text)
        if not key:
            return None
        if key in self.endpoint_keys:
            return self.endpoint_keys[key]
        method, path = key.split(" ", 1)
        segs = path.split("/")
        for ep in self.endpoints:
            em, ep_path = ep["key"].split(" ", 1)
            esegs = ep_path.split("/")
            if em == method and len(esegs) == len(segs) and all(
                    e == g or e == "{}" for e, g in zip(esegs, segs)):
                return ep
        return None

    def cli_lookup(self, text: str):
        return match_cli(self.cli, text)


def normalize_path(path: str) -> str:
    path = path.strip().split("?")[0].split("#")[0]
    if path.startswith(API_PREFIX + "/") or path == API_PREFIX:
        path = path[len(API_PREFIX):] or "/"
    # tham số đường dẫn viết {id}, <id> hoặc :id đều quy về {}
    path = re.sub(r"\{[^}]*\}|<[^>]*>", "{}", path)
    path = re.sub(r"/:[A-Za-z_]\w*", "/{}", path)
    path = path.rstrip(".,;:")
    if len(path) > 1:
        path = path.rstrip("/")
    return path


def normalize_endpoint(text: str):
    m = re.match(r"^\s*(GET|POST|PUT|PATCH|DELETE)\s+(\S+)\s*$", str(text))
    if not m:
        return None
    return f"{m.group(1)} {normalize_path(m.group(2))}"


def cli_fixed_prefix(cmd: str) -> str:
    """Phần cố định của lệnh trước tham số đầu tiên (<...> hoặc --...)."""
    out = []
    for tok in cmd.split():
        if tok.startswith("<") or tok.startswith("--"):
            break
        out.append(tok)
    return " ".join(out)


def match_cli(cli: list, text: str):
    """So khớp tiền tố: 'tastoria mlops deploy' khớp 'tastoria mlops deploy <name> <version>';
    'tastoria labeling push' khớp 'tastoria labeling push|pull'."""
    given = " ".join(str(text).split())
    if given.startswith("CLI "):
        given = given[4:].strip()
    if len(given.split()) < 2:
        return None
    for c in cli:
        cmd = " ".join(c["cmd"].split())
        fixed = cli_fixed_prefix(cmd)
        if cmd.startswith(given) or (fixed and given.startswith(fixed)):
            return c
        # dạng "push|pull": cho phép viết một nhánh
        toks = fixed.split()
        if toks and "|" in toks[-1]:
            base = " ".join(toks[:-1])
            for alt in toks[-1].split("|"):
                if given == f"{base} {alt}" or given.startswith(f"{base} {alt} "):
                    return c
    return None


def load_model(path: Path) -> Model:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    actors = {a["id"]: a for a in data.get("actors", [])}
    packages = {p["id"]: p for p in data.get("packages", [])}
    use_cases = {u["id"]: u for u in data.get("use_cases", [])}
    modules = {m["name"]: m for m in data.get("modules", [])}
    module_ids = {m["id"] for m in data.get("modules", [])}
    tables = {t["name"]: t for t in data.get("tables", [])}
    views = {v["name"]: v for v in data.get("views", [])}
    endpoints, keys = [], {}
    for e in data.get("endpoints", []):
        method, path, module, ucs, idem, auth = (list(e) + [None] * 6)[:6]
        ep = {
            "method": method, "path": path, "module": module, "ucs": list(ucs or []),
            "idem": idem, "auth": auth, "label": f"{method} {path}",
            "key": f"{method} {normalize_path(path)}",
        }
        endpoints.append(ep)
        keys[ep["key"]] = ep
    cli = [dict(c, use_cases=list(c.get("use_cases", []))) for c in data.get("cli", [])]
    return Model(actors, packages, use_cases, modules, module_ids, tables, views,
                 endpoints, keys, cli, list(data.get("business_rules", [])),
                 list(data.get("nfrs", [])))


# ---------------------------------------------------------------- tệp UC
@dataclass
class UCFile:
    path: Path
    meta: dict | None
    body: str
    body_offset: int  # số dòng trước thân (để in tệp:dòng)
    fm_error: str | None = None
    fr_defs: dict = field(default_factory=dict)  # FR id -> (line, row text)


def split_front_matter(text: str):
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, text, 0, "thiếu front-matter YAML (dòng đầu phải là ---)"
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            raw = "\n".join(lines[1:i])
            body = "\n".join(lines[i + 1:])
            try:
                meta = yaml.safe_load(raw) or {}
            except yaml.YAMLError as exc:
                return None, body, i + 1, f"front-matter YAML lỗi: {exc}"
            if not isinstance(meta, dict):
                return None, body, i + 1, "front-matter không phải ánh xạ YAML"
            return meta, body, i + 1, None
    return None, text, 0, "front-matter không có dòng --- đóng"


def find_definitions(text: str, bare: str, offset: int = 0) -> dict:
    """Mã được ĐỊNH NGHĨA = ô đầu của một dòng bảng Markdown hoặc đầu một tiêu đề."""
    row_re = re.compile(TABLE_ROW_ID_RE.format(pat=bare))
    head_re = re.compile(HEADING_ID_RE.format(pat=bare))
    defs = {}
    for n, line in enumerate(text.splitlines(), start=1 + offset):
        m = row_re.match(line) or head_re.match(line)
        if m and m.group(1) not in defs:
            defs[m.group(1)] = (n, line)
    return defs


def load_use_case_files(root: Path) -> dict:
    out = {}
    d = root / UC_DIR_REL
    if not d.is_dir():
        return out
    for p in sorted(d.glob("UC*.md")):
        text = p.read_text(encoding="utf-8")
        meta, body, off, err = split_front_matter(text)
        uc = UCFile(p, meta, body, off, err)
        uc.fr_defs = find_definitions(body, FR_BARE, off)
        out[p.stem] = uc
    return out


@dataclass
class TestPlan:
    exists: bool
    tc_defs: dict  # TC id -> (line, row text)
    tc_refs: dict  # TC id -> set of ids (FR/BR/UC/NFR) mentioned in its definition row


def parse_test_plan(root: Path) -> TestPlan:
    p = root / TEST_PLAN_REL
    if not p.exists():
        return TestPlan(False, {}, {})
    text = p.read_text(encoding="utf-8")
    defs = find_definitions(text, TC_BARE)
    refs = {}
    for tc, (_, line) in defs.items():
        ids = set()
        for kind in ("fr", "br", "nfr", "use_case"):
            ids.update(ID_PATTERNS[kind].findall(line))
        refs[tc] = ids
    return TestPlan(True, defs, refs)


def as_list(v):
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return [v]


# ---------------------------------------------------------------- kiểm tra
class Report:
    def __init__(self, root: Path):
        self.root = root
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def _loc(self, path: Path, line):
        try:
            rel = path.resolve().relative_to(self.root.resolve())
        except ValueError:
            rel = path
        return f"{rel}:{line}" if line else f"{rel}"

    def error(self, path, line, msg):
        self.errors.append(f"{self._loc(path, line)}: {msg}")

    def warn(self, path, line, msg):
        self.warnings.append(f"{self._loc(path, line)}: {msg}")


def scan_files(root: Path) -> list[Path]:
    files = set()
    files.update((root / "docs/sad").rglob("*.md"))
    files.update((root / "docs/uml").rglob("*.puml"))
    files.update((root / "docs/erd").glob("*.puml"))
    files.update((root / "docs/adr").glob("*.md"))
    out_dir = (root / "docs/uml/out").resolve()
    return sorted(f for f in files if out_dir not in f.resolve().parents)


def check_references(model: Model, root: Path, fr_defined: set, plan: TestPlan, rep: Report):
    valid = {
        "actor": set(model.actors), "use_case": set(model.use_cases),
        "package": set(model.packages), "module": set(model.module_ids),
        "br": set(model.brs), "nfr": set(model.nfrs),
    }
    labels = {"actor": "actor", "use_case": "use case", "package": "gói", "module": "module",
              "br": "BR", "nfr": "NFR", "fr": "FR", "tc": "TC"}
    # Chỉ kiểm đường dẫn của API Tastoria: có tiền tố /api/v1 hoặc đoạn đầu trùng một endpoint
    # trong model (tránh báo nhầm API bên ngoài như Label Studio, Mailpit).
    known_roots = {e["key"].split(" ", 1)[1].split("/")[1] for e in model.endpoints}
    for f in scan_files(root):
        try:
            text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            rep.error(f, None, "không đọc được UTF-8")
            continue
        for n, line in enumerate(text.splitlines(), start=1):
            for kind, rx in ID_PATTERNS.items():
                for ident in rx.findall(line):
                    if kind == "fr":
                        ok = ident in fr_defined
                    elif kind == "tc":
                        if not plan.exists:
                            continue
                        ok = ident in plan.tc_defs
                    else:
                        ok = ident in valid[kind]
                    if not ok:
                        rep.error(f, n, f"mã {labels[kind]} không tồn tại: {ident}")
            for m in HTTP_RE.finditer(line):
                path = m.group(2)
                norm = normalize_path(path)
                if norm in ("", "/"):
                    continue
                if not path.startswith(API_PREFIX + "/") and norm.split("/")[1] not in known_roots:
                    continue
                label = f"{m.group(1)} {path}"
                if model.endpoint_lookup(label) is None:
                    rep.error(f, n, f"endpoint không có trong model.yaml: {label}")


def check_use_case_files(model: Model, ucs: dict, plan: TestPlan, rep: Report):
    tables_and_views = set(model.tables) | set(model.views)
    rules_ok = set(model.brs) | set(model.nfrs)
    for stem, uc in ucs.items():
        p = uc.path
        if uc.fm_error:
            rep.error(p, 1, uc.fm_error)
            continue
        meta = uc.meta
        missing = [k for k in FRONT_MATTER_KEYS if k not in meta]
        for k in missing:
            rep.error(p, 1, f"front-matter thiếu khoá: {k}")
        for k in LIST_KEYS:
            if k in meta and meta[k] is not None and not isinstance(meta[k], list):
                rep.error(p, 1, f"front-matter '{k}' phải là danh sách")
        uid = meta.get("id")
        if "id" in meta and uid != stem:
            rep.error(p, 1, f"id '{uid}' khác tên tệp '{stem}'")
        mu = model.use_cases.get(uid) if uid else None
        if "id" in meta and mu is None:
            rep.error(p, 1, f"use case không có trong model.yaml: {uid}")
        if mu:
            if "package" in meta and meta["package"] != mu.get("pkg"):
                rep.error(p, 1, f"package '{meta['package']}' khác model.yaml '{mu.get('pkg')}'")
            if "primary_actor" in meta and meta["primary_actor"] != mu.get("primary"):
                rep.error(p, 1, f"primary_actor '{meta['primary_actor']}' khác model.yaml '{mu.get('primary')}'")
            if "priority" in meta and meta["priority"] != mu.get("priority"):
                rep.error(p, 1, f"priority '{meta['priority']}' khác model.yaml '{mu.get('priority')}'")
            if "name" in meta and meta["name"] != mu.get("name"):
                rep.warn(p, 1, f"name khác model.yaml: '{meta['name']}' / '{mu.get('name')}'")
        for a in as_list(meta.get("secondary_actors")):
            if a not in model.actors:
                rep.error(p, 1, f"secondary_actors có actor không tồn tại: {a}")
        if mu and "secondary_actors" in meta:
            if set(as_list(meta.get("secondary_actors"))) != set(mu.get("secondary", [])):
                rep.warn(p, 1, f"secondary_actors {as_list(meta.get('secondary_actors'))} khác model.yaml {mu.get('secondary', [])}")
        for r in as_list(meta.get("rules")):
            if r not in rules_ok:
                rep.error(p, 1, f"rules có mã không tồn tại: {r}")
        if mu and "rules" in meta:
            missing_rules = [r for r in mu.get("rules", []) if r not in as_list(meta.get("rules"))]
            if missing_rules:
                rep.warn(p, 1, f"rules thiếu so với model.yaml: {missing_rules}")
        listed_eps, listed_cli = set(), set()
        for e in as_list(meta.get("endpoints")):
            s = str(e).strip()
            if s.startswith("CLI "):
                c = model.cli_lookup(s)
                if c is None:
                    rep.error(p, 1, f"lệnh CLI không có trong model.yaml: {s}")
                else:
                    listed_cli.add(c["cmd"])
                continue
            ep = model.endpoint_lookup(s)
            if ep is None:
                rep.error(p, 1, f"endpoint không có trong model.yaml: {s}")
            else:
                listed_eps.add(ep["key"])
                if uid and uid not in ep["ucs"]:
                    rep.warn(p, 1, f"endpoint {ep['label']} không gắn {uid} trong model.yaml")
        if uid and "endpoints" in meta:
            for ep in model.endpoints:
                if uid in ep["ucs"] and ep["key"] not in listed_eps:
                    rep.warn(p, 1, f"model.yaml gắn {ep['label']} cho {uid} nhưng front-matter không liệt kê")
            for c in model.cli:
                if uid in c["use_cases"] and c["cmd"] not in listed_cli:
                    rep.warn(p, 1, f"model.yaml gắn CLI '{c['cmd']}' cho {uid} nhưng front-matter không liệt kê")
        for t in as_list(meta.get("tables")):
            if t not in tables_and_views:
                rep.error(p, 1, f"tables có bảng/view không tồn tại: {t}")
        for fr in as_list(meta.get("frs")):
            if not re.fullmatch(FR_BARE, str(fr)):
                rep.error(p, 1, f"frs có mã sai dạng FR-xx-yy: {fr}")
            elif fr not in uc.fr_defs:
                rep.error(p, 1, f"{fr} khai trong frs nhưng không định nghĩa trong bảng FR của thân tệp")
        if uid and re.fullmatch(r"UC\d\d", str(uid)):
            num = str(uid)[2:]
            for fr, (line, _) in uc.fr_defs.items():
                if fr[3:5] != num:
                    rep.error(p, line, f"{fr} định nghĩa trong {uid} nhưng số UC không khớp")
                if "frs" in meta and fr not in as_list(meta.get("frs")):
                    rep.warn(p, line, f"{fr} định nghĩa trong thân nhưng không có trong frs")
        if plan.exists:
            for tc in as_list(meta.get("tests")):
                if tc not in plan.tc_defs:
                    rep.error(p, 1, f"tests có TC không định nghĩa trong {TEST_PLAN_REL}: {tc}")


def collect_fr_definitions(ucs: dict, rep: Report | None = None) -> set:
    seen = {}
    for uc in ucs.values():
        for fr, (line, _) in uc.fr_defs.items():
            if fr in seen and rep is not None:
                rep.error(uc.path, line, f"{fr} định nghĩa trùng (đã có ở {seen[fr].name})")
            seen.setdefault(fr, uc.path)
    return set(seen)


def run(root: Path, model_path: Path) -> Report:
    rep = Report(root)
    model = load_model(model_path)
    ucs = load_use_case_files(root)
    plan = parse_test_plan(root)
    fr_defined = collect_fr_definitions(ucs, rep)
    check_use_case_files(model, ucs, plan, rep)
    check_references(model, root, fr_defined, plan, rep)
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--warn-only", action="store_true", help="luôn thoát 0, chỉ in")
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    ap.add_argument("--model", type=Path, default=None)
    ap.add_argument("--quiet-warnings", action="store_true", help="không in cảnh báo")
    args = ap.parse_args(argv)
    root = args.root.resolve()
    model_path = args.model or root / "docs/sad/model.yaml"
    rep = run(root, model_path)
    for e in rep.errors:
        print(f"LỖI  {e}")
    if not args.quiet_warnings:
        for w in rep.warnings:
            print(f"CẢNH BÁO  {w}")
    print(f"check_refs: {len(rep.errors)} lỗi, {len(rep.warnings)} cảnh báo")
    if rep.errors and not args.warn_only:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
