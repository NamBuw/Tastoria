"""Food.com Recipes and Interactions (Majumder, Li, Ni, McAuley, EMNLP 2019).

Source: Kaggle dataset `shuyangli94/food-com-recipes-and-user-interactions`, version 2
(2019-11-08). Only the two raw tables are used:

- RAW_recipes.csv       294,520,189 bytes: name, id, minutes, contributor_id, submitted, tags,
                        nutrition, n_steps, steps, description, ingredients, n_ingredients
- RAW_interactions.csv  349,436,524 bytes: user_id, recipe_id, date, rating, review

The files are fetched from Kaggle's public per-file endpoint, which serves this dataset without
an API token. No Hugging Face copy has the same bytes (checked 2026-10-17), so a mirror is not
used. Each file must match the size published by Kaggle within 1% before it is kept.

Rules applied by `build`:
- `rating` 0 means a review written without choosing stars, not a score of zero. The row is
  kept with rating 0 and `has_rating=False`.
- `tags`, `nutrition`, `ingredients` are Python list literals in the CSV and become lists.
  `nutrition` is [calories, total fat, sugar, sodium, protein, saturated fat, carbohydrates],
  calories in kcal and the rest in % daily value (Kaggle discussion; not documented in the paper).
- An empty text cell stays missing (NaN/None), never the string "nan".

Run: uv run --package tastoria-ml python -m tastoria_ml.data.foodcom
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

import pandas as pd
import requests

__all__ = ["FILES", "EXPECTED_BYTES", "download", "build", "check_size"]

DATASET = "shuyangli94/food-com-recipes-and-user-interactions"
DATASET_VERSION = 2
KAGGLE_PAGE = f"https://www.kaggle.com/datasets/{DATASET}"
KAGGLE_FILE_URL = "https://www.kaggle.com/api/v1/datasets/download/{dataset}/{name}?datasetVersionNumber={ver}"
LICENSE = "Data files © Original Authors"

FILES = ("RAW_recipes.csv", "RAW_interactions.csv")
# totalBytes from https://www.kaggle.com/api/v1/datasets/list/<DATASET> (version 2)
EXPECTED_BYTES = {"RAW_recipes.csv": 294_520_189, "RAW_interactions.csv": 349_436_524}
SIZE_TOLERANCE = 0.01

# Scale the paper and Kaggle page report for the raw crawl: 230K+ recipes, 1M+ reviews, 2000-2018.
MIN_RECIPES = 230_000
MIN_INTERACTIONS = 1_000_000
YEAR_RANGE = ("2000", "2018")

CITATION = """Bodhisattwa Prasad Majumder, Shuyang Li, Jianmo Ni, Julian McAuley. 2019.
Generating Personalized Recipes from Historical User Preferences. In Proceedings of EMNLP-IJCNLP
2019, pages 5976-5982. https://aclanthology.org/D19-1613/ doi:10.18653/v1/D19-1613"""


def check_size(path: Path, expected: int, tol: float = SIZE_TOLERANCE) -> None:
    """Raise ValueError unless `path` is within `tol` (relative) of `expected` bytes."""
    size = Path(path).stat().st_size
    if abs(size - expected) > tol * expected:
        raise ValueError(f"{path}: size {size} bytes, expected {expected} ±{tol:.0%}")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _fetch_one(name: str, dest_dir: Path) -> Path:
    url = KAGGLE_FILE_URL.format(dataset=DATASET, name=name, ver=DATASET_VERSION)
    zpath = dest_dir / f".{name}.zip.part"
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(zpath, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    # Kaggle serves "<name>.zip"; take only the member with the expected name, never a path.
    tmp = dest_dir / f".{name}.part"
    with zipfile.ZipFile(zpath) as zf:
        members = [m for m in zf.namelist() if Path(m).name == name]
        if len(members) != 1:
            raise ValueError(f"{url}: archive has {zf.namelist()}, expected one {name}")
        with zf.open(members[0]) as src, open(tmp, "wb") as dst:
            shutil.copyfileobj(src, dst, 1 << 20)
    zpath.unlink()
    check_size(tmp, EXPECTED_BYTES[name])
    out = dest_dir / name
    tmp.replace(out)
    return out


def _write_source_md(dest_dir: Path, paths: list[Path]) -> None:
    today = dt.date.today().isoformat()
    rows = "\n".join(
        f"| `{p.name}` | {p.stat().st_size:,} | {EXPECTED_BYTES[p.name]:,} | `{_sha256(p)}` |" for p in paths
    )
    text = f"""# Food.com Recipes and Interactions

- Dataset page: {KAGGLE_PAGE} (version {DATASET_VERSION}, last updated 2019-11-08, owner Shuyang Li)
- Files fetched from: `{KAGGLE_FILE_URL.format(dataset=DATASET, name='<file>', ver=DATASET_VERSION)}`
  (Kaggle public endpoint, no API token; it redirects to a signed Google Cloud Storage zip)
- Downloaded: {today}
- License (verbatim, from the Kaggle page): "{LICENSE}"
- Paper: https://aclanthology.org/D19-1613/

## Citation

{CITATION}

## Files

| File | Bytes | Kaggle totalBytes | sha256 |
|---|---:|---:|---|
{rows}

## Notes

- Raw crawl of Food.com (formerly GeniusKitchen). The paper reports 230K+ recipes and 1M+
  reviews spanning 2000-2018; its filtered set (180K+ recipes, 700K+ reviews) is in the
  `interactions_*`/`PP_*` files, which are not downloaded here.
- `rating` 0 = a review posted without stars, not a zero score.
- Not re-hosted on Hugging Face with identical bytes as of {today}, so the original Kaggle files
  are used.
"""
    (dest_dir / "SOURCE.md").write_text(text, encoding="utf-8")


def download(dest_dir: Path) -> list[Path]:
    """Fetch RAW_recipes.csv and RAW_interactions.csv into `dest_dir` and write SOURCE.md.

    Files already present with the published size are not fetched again.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in FILES:
        p = dest_dir / name
        try:
            check_size(p, EXPECTED_BYTES[name])
        except (FileNotFoundError, ValueError):
            p = _fetch_one(name, dest_dir)
        paths.append(p)
    _write_source_md(dest_dir, paths)
    return paths


def _list_literal(s: object) -> list:
    if not isinstance(s, str) or not s.strip():
        return []
    v = ast.literal_eval(s)
    if not isinstance(v, list):
        raise ValueError(f"not a list literal: {s[:80]!r}")
    return v


def _load_recipes(raw_dir: Path) -> pd.DataFrame:
    df = pd.read_csv(
        raw_dir / "RAW_recipes.csv",
        usecols=["name", "id", "minutes", "tags", "nutrition", "n_steps", "ingredients", "n_ingredients"],
        dtype={"name": "string", "tags": "string", "nutrition": "string", "ingredients": "string"},
        keep_default_na=False,
        na_values={"name": [""], "minutes": [""], "n_steps": [""], "n_ingredients": [""]},
    )
    name = df["name"].str.strip().replace("", pd.NA).astype(object)
    out = pd.DataFrame(
        {
            "recipe_id": df["id"].astype("int64"),
            "name": name.where(name.notna(), None),
            "minutes": df["minutes"].astype("int64"),
            "tags": df["tags"].map(lambda s: [str(x) for x in _list_literal(s)]),
            "nutrition": df["nutrition"].map(lambda s: [float(x) for x in _list_literal(s)]),
            "n_steps": df["n_steps"].astype("int64"),
            "ingredients": df["ingredients"].map(lambda s: [str(x) for x in _list_literal(s)]),
            "n_ingredients": df["n_ingredients"].astype("int64"),
        }
    )
    if out["recipe_id"].duplicated().any():
        raise ValueError("duplicate recipe ids in RAW_recipes.csv")
    return out


def _load_interactions(raw_dir: Path) -> pd.DataFrame:
    df = pd.read_csv(
        raw_dir / "RAW_interactions.csv",
        usecols=["user_id", "recipe_id", "date", "rating"],
        dtype={"user_id": "int64", "recipe_id": "int64", "rating": "int64", "date": "string"},
    )
    bad = ~df["rating"].between(0, 5)
    if bad.any():
        raise ValueError(f"{int(bad.sum())} ratings outside 0-5")
    df["date"] = pd.to_datetime(df["date"], format="%Y-%m-%d")
    df["has_rating"] = df["rating"] > 0
    return df[["user_id", "recipe_id", "date", "rating", "has_rating"]]


def build(raw_dir: Path, out_dir: Path, check_scale: bool = True) -> dict:
    """Normalise the raw tables into recipes.parquet / interactions.parquet and stats.json.

    With `check_scale` (default) the tables must reach the published scale; a truncated or
    different file raises ValueError before anything is written.
    """
    raw_dir, out_dir = Path(raw_dir), Path(out_dir)
    recipes = _load_recipes(raw_dir)
    inter = _load_interactions(raw_dir)

    hist = inter["rating"].value_counts().sort_index()
    stats = {
        "n_recipes": int(len(recipes)),
        "n_users": int(inter["user_id"].nunique()),
        "n_interactions": int(len(inter)),
        "n_rated": int(inter["has_rating"].sum()),
        "date_min": inter["date"].min().date().isoformat(),
        "date_max": inter["date"].max().date().isoformat(),
        "rating_hist": {str(k): int(v) for k, v in hist.items()},
    }
    if check_scale:
        problems = []
        if stats["n_interactions"] < MIN_INTERACTIONS:
            problems.append(f"n_interactions {stats['n_interactions']} < {MIN_INTERACTIONS}")
        if stats["n_recipes"] < MIN_RECIPES:
            problems.append(f"n_recipes {stats['n_recipes']} < {MIN_RECIPES}")
        if not (YEAR_RANGE[0] <= stats["date_min"][:4] and stats["date_max"][:4] <= YEAR_RANGE[1]):
            problems.append(f"dates {stats['date_min']}..{stats['date_max']} outside {YEAR_RANGE}")
        if problems:
            raise ValueError("Food.com tables do not match the published scale: " + "; ".join(problems))

    out_dir.mkdir(parents=True, exist_ok=True)
    recipes.to_parquet(out_dir / "recipes.parquet", index=False)
    inter.to_parquet(out_dir / "interactions.parquet", index=False)
    (out_dir / "stats.json").write_text(json.dumps(stats, indent=2) + "\n")
    return stats


def main() -> None:
    repo = Path(__file__).resolve().parents[4]
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--raw", type=Path, default=repo / "data" / "raw" / "foodcom")
    ap.add_argument("--out", type=Path, default=repo / "data" / "processed" / "foodcom")
    ap.add_argument("--skip-download", action="store_true")
    args = ap.parse_args()
    if not args.skip_download:
        for p in download(args.raw):
            print(p, p.stat().st_size)
    print(json.dumps(build(args.raw, args.out), indent=2))


if __name__ == "__main__":
    main()
