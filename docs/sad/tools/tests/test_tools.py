"""Kiểm thử cho check_refs.py và gen_traceability.py với mô hình fixture nhỏ."""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import yaml

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import gen_traceability  # noqa: E402

MODEL = {
    "actors": [{"id": "A01", "name": "Khách"}, {"id": "A02", "name": "Người dùng"}],
    "packages": [{"id": "PK1", "name": "Tài khoản"}],
    "use_cases": [
        {"id": "UC01", "pkg": "PK1", "name": "Đăng ký", "primary": "A01", "secondary": [],
         "priority": "M", "rules": ["BR-AUTH-01"]},
        {"id": "UC02", "pkg": "PK1", "name": "Đăng nhập", "primary": "A01", "secondary": [],
         "priority": "M"},
    ],
    "modules": [{"id": "M01", "name": "core", "deps": []},
                {"id": "M02", "name": "identity", "deps": ["core"]}],
    "tables": [
        {"name": "users", "module": "identity", "columns": ["id uuid PK", "email citext NN UQ"], "pk": ["id"]},
        {"name": "sessions", "module": "identity", "columns": ["id uuid PK"], "pk": ["id"]},
        {"name": "orphan_table", "module": "core", "columns": ["id uuid PK"], "pk": ["id"]},
    ],
    "views": [{"name": "v_users", "module": "identity"}],
    "endpoints": [
        ["POST", "/auth/register", "identity", ["UC01"], False, "public"],
        ["POST", "/auth/login", "identity", ["UC02"], False, "public"],
        ["GET", "/policies/{purpose}/current", "identity", ["UC01"], True, "public"],
        ["GET", "/healthz", "core", [], True, "public"],
    ],
    "cli": [{"cmd": "tastoria users import <file>", "module": "identity", "use_cases": ["UC01"]}],
    "business_rules": ["BR-AUTH-01", "BR-AUTH-02"],
    "nfrs": ["NFR-SEC-01", "NFR-A11Y-01"],
}


def uc_file(uid, *, frs, endpoints, tables, tests=(), rules=(), drop=(), body_frs=None,
            extra_body=""):
    meta = {
        "id": uid, "name": {"UC01": "Đăng ký", "UC02": "Đăng nhập"}[uid], "package": "PK1",
        "primary_actor": "A01", "secondary_actors": [], "priority": "M",
        "rules": list(rules), "endpoints": list(endpoints), "tables": list(tables),
        "frs": list(frs), "tests": list(tests),
    }
    for k in drop:
        meta.pop(k)
    rows = "\n".join(f"| {fr} | Hệ thống phải làm X. | Given A When B Then C |"
                     for fr in (frs if body_frs is None else body_frs))
    return ("---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False) + "---\n"
            f"# {uid}\n\n## Yêu cầu chức năng\n\n| Mã | Mô tả | Tiêu chí |\n|---|---|---|\n"
            f"{rows}\n\n{extra_body}\n")


def make_repo(tmp_path: Path, ucs: dict, test_plan: str | None = None) -> Path:
    (tmp_path / "docs/sad/use-cases").mkdir(parents=True)
    (tmp_path / "docs/sad/model.yaml").write_text(yaml.safe_dump(MODEL, allow_unicode=True),
                                                  encoding="utf-8")
    for uid, text in ucs.items():
        (tmp_path / f"docs/sad/use-cases/{uid}.md").write_text(text, encoding="utf-8")
    if test_plan is not None:
        (tmp_path / "docs/sad/06-ke-hoach-kiem-thu.md").write_text(test_plan, encoding="utf-8")
    return tmp_path


def run_check(root: Path, *extra):
    return subprocess.run(
        [sys.executable, str(TOOLS / "check_refs.py"), "--root", str(root), *extra],
        capture_output=True, text=True,
    )


def good_ucs():
    return {
        "UC01": uc_file("UC01", frs=["FR-01-01"], endpoints=["POST /auth/register",
                                                            "GET /policies/{purpose}/current",
                                                            "CLI tastoria users import"],
                        tables=["users", "v_users"], rules=["BR-AUTH-01"],
                        extra_body="Gọi GET /api/v1/policies/survey/current, "
                                   "GET /policies/<purpose>/current và `POST /auth/register`."),
        "UC02": uc_file("UC02", frs=["FR-02-01"], endpoints=["POST /api/v1/auth/login"],
                        tables=["users"]),
    }


def test_clean_fixture_passes(tmp_path):
    root = make_repo(tmp_path, good_ucs())
    r = run_check(root)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "0 lỗi" in r.stdout


def test_unknown_ids_fail(tmp_path):
    ucs = good_ucs()
    ucs["UC02"] = uc_file(
        "UC02", frs=["FR-02-01"], endpoints=["POST /auth/login", "DELETE /auth/everything",
                                             "CLI tastoria nuke"],
        tables=["users", "ghost_table"], rules=["BR-FAKE-09"],
        extra_body="Xem UC99, actor A77, BR-AUTH-07, NFR-SEC-09, FR-02-09, gói PK9, module M42.\n"
                   "Gọi `GET /api/v1/auth/missing` rồi `POST /auth/login`. API ngoài `GET /api/projects` bỏ qua.\n"
                   "NFR-A11Y-01 và SHA256 không được khớp nhầm thành mã actor.",
    )
    root = make_repo(tmp_path, ucs)
    r = run_check(root)
    assert r.returncode == 1
    out = r.stdout
    for needle in ["UC99", "A77", "BR-AUTH-07", "NFR-SEC-09", "FR-02-09", "PK9", "M42",
                   "GET /api/v1/auth/missing", "DELETE /auth/everything", "CLI tastoria nuke",
                   "ghost_table", "BR-FAKE-09"]:
        assert needle in out, f"không báo {needle}:\n{out}"
    assert "A11" not in out and "SHA256" not in out
    assert "/api/projects" not in out
    assert "POST /auth/login\n" not in out
    # báo theo tệp:dòng
    assert "docs/sad/use-cases/UC02.md:" in out
    # --warn-only: vẫn in nhưng thoát 0
    r2 = run_check(root, "--warn-only")
    assert r2.returncode == 0 and "UC99" in r2.stdout


def test_unknown_tc_checked_only_with_test_plan(tmp_path):
    ucs = good_ucs()
    ucs["UC01"] = uc_file("UC01", frs=["FR-01-01"], endpoints=["POST /auth/register"],
                          tables=["users"], tests=["TC-AUTH-01", "TC-AUTH-99"])
    root = make_repo(tmp_path, ucs)
    assert run_check(root).returncode == 0  # chưa có kế hoạch kiểm thử -> không kiểm TC
    (root / "docs/sad/06-ke-hoach-kiem-thu.md").write_text(
        "| Mã | Kiểm | Truy vết |\n|---|---|---|\n| TC-AUTH-01 | x | FR-01-01, BR-AUTH-01 |\n",
        encoding="utf-8")
    r = run_check(root)
    assert r.returncode == 1 and "TC-AUTH-99" in r.stdout and "TC-AUTH-01:" not in r.stdout


def test_frontmatter_missing_key(tmp_path):
    ucs = good_ucs()
    ucs["UC01"] = uc_file("UC01", frs=["FR-01-01"], endpoints=["POST /auth/register"],
                          tables=["users"], drop=("priority", "tests"))
    ucs["UC02"] = uc_file("UC02", frs=["FR-02-01", "FR-02-02"], endpoints=["POST /auth/login"],
                          tables=["users"], body_frs=["FR-02-01"])
    root = make_repo(tmp_path, ucs)
    # id khác tên tệp
    (root / "docs/sad/use-cases/UC03.md").write_text(
        uc_file("UC02", frs=[], endpoints=[], tables=[]), encoding="utf-8")
    # không có front-matter
    (root / "docs/sad/use-cases/UC04.md").write_text("# UC04\n", encoding="utf-8")
    r = run_check(root)
    assert r.returncode == 1
    out = r.stdout
    assert "UC01.md:1: front-matter thiếu khoá: priority" in out
    assert "UC01.md:1: front-matter thiếu khoá: tests" in out
    assert "FR-02-02 khai trong frs nhưng không định nghĩa" in out
    assert "UC03.md:1: id 'UC02' khác tên tệp 'UC03'" in out
    assert "UC04.md:1: thiếu front-matter" in out


def test_traceability_counts_gaps(tmp_path):
    ucs = {
        # UC01 có FR + TC; UC02 không có FR, không có TC
        "UC01": uc_file("UC01", frs=["FR-01-01", "FR-01-02"], endpoints=["POST /auth/register"],
                        tables=["users"], tests=["TC-AUTH-01"]),
        "UC02": uc_file("UC02", frs=[], endpoints=["POST /auth/login"], tables=["sessions"]),
    }
    plan = textwrap.dedent("""\
        # Kế hoạch kiểm thử
        | Mã | Mô tả | Truy vết |
        |---|---|---|
        | TC-AUTH-01 | đăng ký hợp lệ | UC01, FR-01-01 |
        | TC-OPS-01 | kiểm sống | GET /healthz |
        """)
    root = make_repo(tmp_path, ucs, plan)
    res = gen_traceability.build(root, root / "docs/sad/model.yaml")
    g = res["gaps"]
    assert g["endpoint_no_uc"] == []  # /healthz có TC-OPS-01 kiểm
    assert g["table_no_uc"] == ["orphan_table"]
    assert g["br_no_uc_tc"] == ["BR-AUTH-02"]  # BR-AUTH-01 gắn UC01 trong model
    assert g["fr_no_tc"] == ["FR-01-02"]
    assert g["uc_no_fr"] == ["UC02"]
    assert g["uc_no_tc"] == ["UC02"]

    out = root / "docs/sad/08-ma-tran-truy-vet.md"
    r = subprocess.run([sys.executable, str(TOOLS / "gen_traceability.py"), "--root", str(root)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "tổng ô trống 5" in r.stdout
    text = out.read_text(encoding="utf-8")
    assert "| UC01 |" in text and "`FR-01-01`" in text and "`CLI tastoria users import <file>`" in text
    assert "`orphan_table`" in text
    r = subprocess.run([sys.executable, str(TOOLS / "gen_traceability.py"), "--root", str(root),
                        "--strict"], capture_output=True, text=True)
    assert r.returncode == 1

    # Lấp hết ô trống -> --strict thoát 0
    MODEL_FULL = dict(MODEL, tables=[t for t in MODEL["tables"] if t["name"] != "orphan_table"],
                      business_rules=["BR-AUTH-01"])
    (root / "docs/sad/model.yaml").write_text(yaml.safe_dump(MODEL_FULL, allow_unicode=True),
                                              encoding="utf-8")
    (root / "docs/sad/use-cases/UC02.md").write_text(
        uc_file("UC02", frs=["FR-02-01"], endpoints=["POST /auth/login"], tables=["sessions"],
                tests=["TC-AUTH-02"]), encoding="utf-8")
    (root / "docs/sad/06-ke-hoach-kiem-thu.md").write_text(
        plan + "| TC-AUTH-02 | đăng nhập | UC02, FR-02-01 |\n| TC-AUTH-03 | FR thứ hai | FR-01-02 |\n",
        encoding="utf-8")
    r = subprocess.run([sys.executable, str(TOOLS / "gen_traceability.py"), "--root", str(root),
                        "--strict"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout
    assert "tổng ô trống 0" in r.stdout
