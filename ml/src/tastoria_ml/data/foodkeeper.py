"""FSIS FoodKeeper (USDA) -> refrigerator shelf-life table in days.

Source: https://catalog.data.gov/dataset/fsis-foodkeeper-data (CC0 1.0).
The file is a JSON dump of the FoodKeeper workbook:
``{"fileName": ..., "sheets": [{"name": "Product", "data": [[{col: val}, ...], ...]}, ...]}``.

fsis.usda.gov sits behind Akamai and answers HTTP 403 to plain scripted
requests, so ``download`` first tries ``requests`` and, on 403, fetches the
same URL with a headless Chromium (Playwright from ``~/miniconda3/bin/python``,
which is not a dependency of this package).

Run: ``uv run --package tastoria-ml python -m tastoria_ml.data.foodkeeper``
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

import pandas as pd
import requests

URL = "https://www.fsis.usda.gov/shared/data/EN/foodkeeper.json"
CATALOG_URL = "https://catalog.data.gov/dataset/fsis-foodkeeper-data"
LICENSE = "https://creativecommons.org/publicdomain/zero/1.0/"
PLAYWRIGHT_PYTHON = Path.home() / "miniconda3" / "bin" / "python"
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)
# Sanity bounds for the downloaded file (version 128 has 661 products).
MIN_PRODUCTS = 600

_UNIT_DAYS = {
    "hour": 1 / 24,
    "day": 1.0,
    "week": 7.0,
    "month": 30.0,
    "year": 365.0,
}

COLUMNS = [
    "product_id", "category", "name", "subtitle", "keywords",
    "fridge_min_days", "fridge_max_days", "fridge_tips",
]


def to_days(value, metric) -> float:
    """Convert a FoodKeeper (value, metric) pair to days.

    Days=1, Weeks=7, Months=30, Years=365 (singular/plural, any case);
    Hours=1/24. Non-time metrics ("When Ripe", "Package use-by date",
    "Not Recommended", "Indefinitely") or a missing value give NaN.
    """
    if value is None or metric is None:
        return math.nan
    try:
        v = float(value)
    except (TypeError, ValueError):
        return math.nan
    if math.isnan(v):
        return math.nan
    unit = str(metric).strip().lower()
    if unit.endswith("s"):
        unit = unit[:-1]
    factor = _UNIT_DAYS.get(unit)
    return math.nan if factor is None else v * factor


def _sheet(doc: dict, name: str) -> list[dict]:
    for s in doc["sheets"]:
        if s["name"] == name:
            return [{k: v for cell in row for k, v in cell.items()} for row in s["data"]]
    raise KeyError(f"sheet {name!r} not in FoodKeeper JSON")


def _str(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _fridge(row: dict) -> tuple[float, float, str | None]:
    """Refrigerator window. Prefer the generic ``Refrigerate_*`` fields;
    fall back to ``DOP_Refrigerate_*`` (from date of purchase), which is
    where most produce and dairy are recorded."""
    for pre in ("Refrigerate", "DOP_Refrigerate"):
        metric = row.get(f"{pre}_Metric")
        lo = to_days(row.get(f"{pre}_Min"), metric)
        hi = to_days(row.get(f"{pre}_Max"), metric)
        # A one-sided range stays NaN on the missing side (none in v128).
        if not (math.isnan(lo) and math.isnan(hi)):
            return lo, hi, _str(row.get(f"{pre}_tips"))
    tips = _str(row.get("Refrigerate_tips")) or _str(row.get("DOP_Refrigerate_tips"))
    return math.nan, math.nan, tips


def build(raw_json: Path) -> pd.DataFrame:
    doc = json.loads(Path(raw_json).read_text(encoding="utf-8"))
    cats = {}
    for c in _sheet(doc, "Category"):
        name = _str(c.get("Category_Name"))
        sub = _str(c.get("Subcategory_Name"))
        cats[int(c["ID"])] = f"{name} / {sub}" if sub else name
    records = []
    for r in _sheet(doc, "Product"):
        lo, hi, tips = _fridge(r)
        cid = r.get("Category_ID")
        records.append({
            "product_id": int(r["ID"]),
            "category": cats.get(int(cid)) if cid is not None else None,
            "name": _str(r.get("Name")),
            "subtitle": _str(r.get("Name_subtitle")),
            "keywords": _str(r.get("Keywords")),
            "fridge_min_days": lo,
            "fridge_max_days": hi,
            "fridge_tips": tips,
        })
    df = pd.DataFrame.from_records(records, columns=COLUMNS)
    df["fridge_min_days"] = df["fridge_min_days"].astype("float64")
    df["fridge_max_days"] = df["fridge_max_days"].astype("float64")
    return df.sort_values("product_id", ignore_index=True)


_PW_SCRIPT = r"""
import sys
from playwright.sync_api import sync_playwright
url, out, ua = sys.argv[1], sys.argv[2], sys.argv[3]
with sync_playwright() as p:
    b = p.chromium.launch(headless=True, channel="chromium",
                          args=["--disable-blink-features=AutomationControlled"])
    ctx = b.new_context(user_agent=ua, locale="en-US")
    ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
    page = ctx.new_page()
    r = page.goto(url, wait_until="domcontentloaded", timeout=90000)
    if r is None or r.status != 200:
        sys.exit(f"HTTP {None if r is None else r.status}")
    open(out, "wb").write(r.body())
    b.close()
"""


def _fetch_with_browser(url: str, out: Path) -> None:
    if not PLAYWRIGHT_PYTHON.exists():
        raise RuntimeError(f"403 from {url} and no Playwright python at {PLAYWRIGHT_PYTHON}")
    with tempfile.TemporaryDirectory() as td:
        script = Path(td) / "pw_fetch.py"
        script.write_text(_PW_SCRIPT)
        subprocess.run(
            [str(PLAYWRIGHT_PYTHON), "-I", str(script), url, str(out), UA],
            check=True, timeout=180,
        )


def _validate(path: Path) -> dict:
    doc = json.loads(path.read_text(encoding="utf-8"))
    n = len(_sheet(doc, "Product"))
    if n < MIN_PRODUCTS:
        raise ValueError(f"{path}: only {n} products (< {MIN_PRODUCTS}); partial or wrong file?")
    return doc


def download(dest_dir: Path) -> tuple[Path, str]:
    """Download foodkeeper.json into dest_dir. Returns (path, method)."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / "foodkeeper.json"
    tmp = dest_dir / "foodkeeper.json.part"
    r = requests.get(URL, headers={"User-Agent": UA}, timeout=60)
    if r.status_code == 200:
        tmp.write_bytes(r.content)
        method = "requests (plain HTTP GET)"
    elif r.status_code == 403:
        _fetch_with_browser(URL, tmp)
        method = (
            "headless Chromium via Playwright (~/miniconda3/bin/python); "
            "plain HTTP GET returned 403 (Akamai)"
        )
    else:
        r.raise_for_status()
        raise RuntimeError(f"unexpected HTTP {r.status_code}")
    _validate(tmp)
    tmp.replace(out)
    return out, method


def write_source_md(raw_json: Path, method: str) -> Path:
    doc = json.loads(raw_json.read_text(encoding="utf-8"))
    versions = _sheet(doc, "Version")
    cur = next((v for v in versions if _str(v.get("Current_Version"))), versions[-1])
    sha = hashlib.sha256(raw_json.read_bytes()).hexdigest()
    n = len(_sheet(doc, "Product"))
    text = f"""# FSIS FoodKeeper Data

- Dataset page: {CATALOG_URL}
- File URL: {URL}
- Downloaded: {date.today().isoformat()}
- Download method: {method}
- Publisher: Food Safety and Inspection Service (FSIS), USDA
- data.gov metadata: datePublished 2020-11-10, dateModified 2025-01-22, identifier usda-fsis-006
- Data version inside file: {cur.get('Data_Version_Number')} (Modified_Date {cur.get('Modified_Date')}), fileName "{doc.get('fileName')}"
- Products: {n}

## License (verbatim from data.gov metadata)

License: {LICENSE}

(Creative Commons CC0 1.0 Universal Public Domain Dedication.)

## Citation

U.S. Department of Agriculture, Food Safety and Inspection Service. FSIS FoodKeeper Data.
{CATALOG_URL}. Accessed {date.today().isoformat()}.

## Files

| file | bytes | sha256 |
|---|---|---|
| foodkeeper.json | {raw_json.stat().st_size} | {sha} |
"""
    p = raw_json.parent / "SOURCE.md"
    p.write_text(text, encoding="utf-8")
    return p


def main(argv: list[str] | None = None) -> int:
    repo = Path(__file__).resolve().parents[4]
    raw_dir = repo / "data" / "raw" / "foodkeeper"
    out_dir = repo / "data" / "processed" / "foodkeeper"
    raw = raw_dir / "foodkeeper.json"
    if not raw.exists():
        raw, method = download(raw_dir)
        write_source_md(raw, method)
    df = build(raw)
    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_dir / "products.csv", index=False)
    print(f"{len(df)} products, {df.fridge_max_days.notna().sum()} with fridge days -> {out_dir / 'products.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
