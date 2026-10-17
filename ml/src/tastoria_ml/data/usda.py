"""USDA FoodData Central: Foundation Foods (JSON) + SR Legacy (CSV) -> one table per 100 g.

Source page: https://fdc.nal.usda.gov/download-datasets/ (CC0 1.0). `download` reads that page
and takes the newest Foundation JSON and SR Legacy CSV zip it links to; SR Legacy is frozen at
its April 2018 release, Foundation is re-issued about twice a year.

Nutrient ids (FDC `nutrient.id`), all per 100 g:
    energy  1008 Energy (kcal). Many Foundation foods report no 1008, only the Atwater energies,
            so fall back to 2048 (Atwater Specific Factors) and then 2047 (Atwater General).
            SR Legacy's 1008 was itself computed with specific factors, so 2048 comes first.
    protein 1003, fat 1004 (Total lipid), carb 1005 (by difference), fiber 1079 (total dietary),
    sugars  2000 (total incl. NLEA), else 1063 (Sugars, Total), sodium 1093 (mg).
A nutrient the food does not report is NaN, never 0; a reported 0 stays 0.

CLI: python -m tastoria_ml.data.usda --raw data/raw/usda --out data/processed/usda
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

import pandas as pd
import requests

__all__ = ["download", "build", "latest_release_urls", "SR_LEGACY_PUBLISHED_FOODS"]

BASE = "https://fdc.nal.usda.gov"
PAGE = f"{BASE}/download-datasets/"
UA = {"User-Agent": "Mozilla/5.0 (tastoria-ml data pipeline)"}

# "SR Legacy ... contains data on 7,793 food items" (FDC SR Legacy documentation, April 2018).
SR_LEGACY_PUBLISHED_FOODS = 7793

COLUMNS = ["fdc_id", "data_type", "description", "category", "energy_kcal",
           "protein_g", "fat_g", "carb_g", "fiber_g", "sugars_g", "sodium_mg"]

# output column -> nutrient ids in order of preference
NUTRIENTS: dict[str, tuple[int, ...]] = {
    "energy_kcal": (1008, 2048, 2047),
    "protein_g": (1003,),
    "fat_g": (1004,),
    "carb_g": (1005,),
    "fiber_g": (1079,),
    "sugars_g": (2000, 1063),
    "sodium_mg": (1093,),
}
_WANTED = {nid for ids in NUTRIENTS.values() for nid in ids}

_PATTERNS = {
    "foundation_json": re.compile(r"/fdc-datasets/(FoodData_Central_foundation_food_json_(\d{4}-\d{2}(?:-\d{2})?)\.zip)"),
    "sr_legacy_csv": re.compile(r"/fdc-datasets/(FoodData_Central_sr_legacy_food_csv_(\d{4}-\d{2}(?:-\d{2})?)\.zip)"),
}


def latest_release_urls(page_html: str) -> list[str]:
    """Newest Foundation JSON and SR Legacy CSV zip linked from the download page."""
    urls = []
    for kind, pat in _PATTERNS.items():
        found = {(m.group(2), m.group(1)) for m in pat.finditer(page_html)}
        if not found:
            raise RuntimeError(f"no {kind} link on {PAGE}; the page layout has changed")
        _, name = max(found)  # ISO dates sort as strings
        urls.append(f"{BASE}/fdc-datasets/{name}")
    return urls


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(dest_dir: Path) -> list[Path]:
    """Fetch the two zips into dest_dir (skips files already complete). Returns their paths."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    page = requests.get(PAGE, headers=UA, timeout=60)
    page.raise_for_status()
    out = []
    for url in latest_release_urls(page.text):
        target = dest_dir / url.rsplit("/", 1)[1]
        head = requests.head(url, headers=UA, timeout=60, allow_redirects=True)
        head.raise_for_status()
        expected = int(head.headers.get("Content-Length", -1))
        if not (target.exists() and target.stat().st_size == expected):
            tmp = target.with_suffix(".part")
            with requests.get(url, headers=UA, timeout=300, stream=True) as r:
                r.raise_for_status()
                with tmp.open("wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            if expected >= 0 and tmp.stat().st_size != expected:
                raise RuntimeError(f"{url}: got {tmp.stat().st_size} bytes, server says {expected}")
            tmp.replace(target)
        with zipfile.ZipFile(target) as z:
            bad = z.testzip()
            if bad:
                raise RuntimeError(f"{target}: corrupt member {bad}")
        out.append(target)
    return out


def _pick(values: dict[int, float]) -> dict[str, float]:
    row = {}
    for col, ids in NUTRIENTS.items():
        row[col] = next((values[i] for i in ids if i in values and pd.notna(values[i])), float("nan"))
    return row


def _latest(raw_dir: Path, glob: str) -> Path:
    found = sorted(raw_dir.glob(glob))
    if not found:
        raise FileNotFoundError(f"no {glob} in {raw_dir}; run download() first")
    return found[-1]


def _foundation(zip_path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(zip_path) as z:
        name = next(n for n in z.namelist() if n.endswith(".json"))
        data = json.loads(z.read(name))
    rows = []
    for food in data["FoundationFoods"]:
        if food is None:  # 2026-04-30 release: 363 foods followed by 32 nulls
            continue
        values: dict[int, float] = {}
        for fn in food.get("foodNutrients", []):
            nid = fn.get("nutrient", {}).get("id")
            if nid in _WANTED and fn.get("amount") is not None:
                values[nid] = float(fn["amount"])
        rows.append({"fdc_id": int(food["fdcId"]), "data_type": "foundation_food",
                     "description": food["description"],
                     "category": (food.get("foodCategory") or {}).get("description"),
                     **_pick(values)})
    return pd.DataFrame(rows, columns=COLUMNS)


_COUNTS = "all_downloaded_table_record_counts.csv"


def _sr_legacy(zip_path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(zip_path) as z:
        def read(base: str, **kw) -> pd.DataFrame:
            name = next(n for n in z.namelist() if n.rsplit("/", 1)[-1] == base)
            return pd.read_csv(io.BytesIO(z.read(name)), **kw)

        food = read("food.csv", usecols=["fdc_id", "data_type", "description", "food_category_id"])
        cats = read("food_category.csv", usecols=["id", "description"])
        fn = read("food_nutrient.csv", usecols=["fdc_id", "nutrient_id", "amount"])
        if any(n.endswith("/" + _COUNTS) or n == _COUNTS for n in z.namelist()):
            counts = read(_COUNTS).set_index("Table")["Number of Records"]
            for table, got in (("food", len(food)), ("food_nutrient", len(fn))):
                if table in counts and int(counts[table]) != got:
                    raise ValueError(f"{zip_path.name}: {table}.csv has {got} rows, "
                                     f"release says {int(counts[table])}; partial or altered file")
    fn = fn[fn.nutrient_id.isin(_WANTED) & fn.amount.notna()]
    wide = fn.pivot_table(index="fdc_id", columns="nutrient_id", values="amount", aggfunc="first")
    picked = pd.DataFrame(
        [_pick(r.dropna().to_dict()) for _, r in wide.iterrows()], index=wide.index
    ).reindex(columns=list(NUTRIENTS))
    food = food.merge(cats.rename(columns={"id": "food_category_id", "description": "category"}),
                      on="food_category_id", how="left")
    df = food.set_index("fdc_id").join(picked, how="left").reset_index()
    df["data_type"] = "sr_legacy_food"
    return df.reindex(columns=COLUMNS)


def build(raw_dir: Path) -> pd.DataFrame:
    """One row per food from the newest Foundation JSON and SR Legacy CSV zip in raw_dir."""
    raw_dir = Path(raw_dir)
    df = pd.concat([_foundation(_latest(raw_dir, "*foundation_food_json*.zip")),
                    _sr_legacy(_latest(raw_dir, "*sr_legacy_food_csv*.zip"))], ignore_index=True)
    df["fdc_id"] = df["fdc_id"].astype("int64")
    for col in NUTRIENTS:
        df[col] = df[col].astype("float64")
    if not df.fdc_id.is_unique:
        raise ValueError("duplicate fdc_id across Foundation and SR Legacy")
    return df


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--raw", type=Path, default=Path("data/raw/usda"))
    ap.add_argument("--out", type=Path, default=Path("data/processed/usda"))
    ap.add_argument("--download", action="store_true", help="fetch the newest zips first")
    a = ap.parse_args(argv)
    if a.download:
        for p in download(a.raw):
            print(f"{p.name}  {p.stat().st_size} B  sha256 {_sha256(p)}")
    df = build(a.raw)
    a.out.mkdir(parents=True, exist_ok=True)
    df.to_csv(a.out / "foods.csv", index=False)
    print(df.data_type.value_counts().to_string())
    print("non-missing share:\n" + df[list(NUTRIENTS)].notna().mean().round(3).to_string())


if __name__ == "__main__":
    main()
