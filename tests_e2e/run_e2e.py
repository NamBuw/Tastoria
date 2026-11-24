#!/usr/bin/env python3
"""Opaque-box 4-tier E2E test suite runner for Tastoria."""

from __future__ import annotations

import argparse
import ast
import importlib
import os
import py_compile
import subprocess
import sys
from pathlib import Path

TESTS_E2E_DIR = Path(__file__).resolve().parent
PYTEST_INI = TESTS_E2E_DIR / "pytest.ini"
DEFAULT_BASE_URL = "http://127.0.0.1:6880"
REQUIRED_IMPORTS = ("pytest", "httpx", "PIL", "yaml", "playwright")


def run_syntax_check() -> int:
    """Run py_compile + ast.parse on every .py file under tests_e2e/ and verify imports."""
    py_files = sorted(TESTS_E2E_DIR.rglob("*.py"))
    if not py_files:
        print("ERROR: No .py files found under", TESTS_E2E_DIR, file=sys.stderr)
        return 1

    for path in py_files:
        try:
            source = path.read_text(encoding="utf-8")
            ast.parse(source, filename=str(path))
            py_compile.compile(str(path), doraise=True)
        except Exception as exc:  # noqa: BLE001
            print(f"SYNTAX ERROR in {path}: {exc}", file=sys.stderr)
            return 1

    missing: list[str] = []
    for mod in REQUIRED_IMPORTS:
        try:
            importlib.import_module(mod)
        except Exception as exc:  # noqa: BLE001
            missing.append(f"{mod} ({exc})")

    if missing:
        print(f"IMPORT ERROR: Missing required E2E packages: {', '.join(missing)}", file=sys.stderr)
        return 1

    print(
        f"syntax-check OK: {len(py_files)} Python files parsed & compiled; "
        f"imports OK ({', '.join(REQUIRED_IMPORTS)})"
    )
    return 0


def _build_marker_expr(tier: str, skip_browser: bool) -> str | None:
    parts: list[str] = []
    if tier != "all":
        parts.append(f"tier{tier}")
    if skip_browser:
        parts.append("not browser")
    if not parts:
        return None
    return " and ".join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Tastoria opaque-box 4-tier E2E suite.")
    parser.add_argument(
        "--tier",
        choices=("1", "2", "3", "4", "all"),
        default="all",
        help="Select E2E tier to run (default: all)",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("TASTORIA_E2E_BASE_URL", DEFAULT_BASE_URL),
        help=f"Target Tastoria base URL (default: TASTORIA_E2E_BASE_URL or {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--syntax-check",
        action="store_true",
        help="Run py_compile + ast.parse + dependency import checks and exit",
    )
    parser.add_argument(
        "--dry-run",
        "--collect-only",
        dest="collect_only",
        action="store_true",
        help="Run syntax check and pytest --collect-only without executing tests",
    )
    parser.add_argument(
        "--skip-browser",
        action="store_true",
        help="Exclude @pytest.mark.browser tests",
    )
    parser.add_argument(
        "--junit-xml",
        default=None,
        help="Optional path to write JUnit XML test report",
    )
    parser.add_argument(
        "-k",
        dest="keyword_expr",
        default=None,
        help="Optional pytest -k expression to filter tests",
    )

    args = parser.parse_args(argv)

    if args.syntax_check:
        return run_syntax_check()

    if args.collect_only:
        rc = run_syntax_check()
        if rc != 0:
            return rc

    env = dict(os.environ)
    env["TASTORIA_E2E_BASE_URL"] = args.base_url.rstrip("/")

    cmd: list[str] = [
        sys.executable,
        "-m",
        "pytest",
        "-c",
        str(PYTEST_INI),
        str(TESTS_E2E_DIR),
    ]

    marker_expr = _build_marker_expr(args.tier, args.skip_browser)
    if marker_expr:
        cmd.extend(["-m", marker_expr])

    if args.keyword_expr:
        cmd.extend(["-k", args.keyword_expr])

    if args.collect_only:
        cmd.append("--collect-only")

    if args.junit_xml:
        junit_path = Path(args.junit_xml)
        junit_path.parent.mkdir(parents=True, exist_ok=True)
        cmd.extend(["--junitxml", str(junit_path)])

    proc = subprocess.run(cmd, env=env, check=False)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
