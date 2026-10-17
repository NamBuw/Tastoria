"""Public produce-freshness image sets from Mendeley Data (both CC BY 4.0).

- Local Spinach Leaf Dataset v3 (skf6w2s2h2): red / water / Malabar spinach, fresh vs non-fresh.
  Version 3 holds two zips. Their image sets are byte-identical (same 3,999 names, same CRC32),
  one under ``Local Spanish Leaf Disease Dataset/`` and one under ``Augmented data/``. Only the
  first is downloaded; the plan skips the augmented part.
- AgriFreshNET v1 (42m5tb7yv9): 24 folders = 8 produce x {Fresh, Semi-Fresh, Rotten}, each folder
  named with a shelf-life range in days. Only ``Processed Data.zip`` is published (the "Raw Data.zip"
  named in the dataset's method text is not in the file listing). Many files inside it are
  augmented copies named ``aug_<n>_<original>``; ``group_id`` ties them to their original.

Run: ``uv run --package tastoria-ml python -m tastoria_ml.data.freshness_sources``
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import shutil
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Literal

import pandas as pd
import requests

Dataset = Literal["local_spinach_leaf", "agrifreshnet"]

API = "https://data.mendeley.com/public-api/datasets"
IMAGE_EXT = {".jpg", ".jpeg", ".png"}
LABEL3 = {"tuoi", "dung_som", "dung_ngay"}

# File ids, sizes and sha256 are taken from the Mendeley public API listing (17/10/2026) and checked
# again against the live listing on download; a mismatch stops the download.
SOURCES: dict[str, dict] = {
    "local_spinach_leaf": {
        "id": "skf6w2s2h2",
        "version": 3,
        "files": [
            {
                "id": "de50a0f7-6292-49ae-89cd-99498128ba46",
                "filename": "Local Spanish Leaf Disease Dataset.zip",
                "size": 300291182,
                "sha256": "70ca59fbfa44a2112de343ab2ba05afb4ca101ccc4323baf73adbf95c6946da9",
            }
        ],
        "skipped": [
            {
                "id": "67181715-cde2-4e5a-b9fb-0fe0aca918ec",
                "filename": "local Spinach Fresh and Non Fresh Dataset.zip",
                "size": 300130942,
                "sha256": "7380c39b0073881226da8ea080737785594a1c732a3e2592a56fe671220198ab",
                "reason": "top folder 'Augmented data/'; same 3,999 file names with identical CRC32 as the "
                "kept zip (checked from the zip central directory via HTTP range reads), so it adds no images",
            }
        ],
        "expected_images": 3999,
    },
    "agrifreshnet": {
        "id": "42m5tb7yv9",
        "version": 1,
        "files": [
            {
                "id": "7b216853-8f3b-47fd-b1ae-df88a367a1d1",
                "filename": "Processed Data.zip",
                "size": 347828971,
                "sha256": "6607a48bf2817f9dfc8d4a1c32ce663c1d8308b4b1251e9bf65f074fcac53f11",
            }
        ],
        "skipped": [],
        "expected_images": 24 * 590,
    },
}

AGRI_LABEL3 = {"Fresh": "tuoi", "Semi-Fresh": "dung_som", "Rotten": "dung_ngay"}
SPINACH_LABEL3 = {"fresh": "tuoi", "non-fresh": "dung_ngay"}

_AGRI_RE = re.compile(r"^(semi[\s_-]*fresh|fresh|rotten)\s+([a-z]+)\s*\(\s*(\d+)\s*-\s*(\d+)\s*\)$", re.I)
_SPINACH_RE = re.compile(r"^(\w+ spinach)\s+(non\s*fresh|fresh)$", re.I)


# ---------- helpers ----------


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_file(path: Path, size: int, sha256: str) -> None:
    actual = path.stat().st_size
    if actual != size:
        raise ValueError(f"{path}: size {actual} != published {size}")
    digest = sha256_of(path)
    if digest != sha256:
        raise ValueError(f"{path}: sha256 {digest} != published {sha256}")


def safe_extract(zip_path: Path, out_dir: Path) -> None:
    out_dir = out_dir.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            target = (out_dir / name).resolve()
            if target != out_dir and out_dir not in target.parents:
                raise ValueError(f"unsafe path in {zip_path}: {name!r}")
        out_dir.mkdir(parents=True, exist_ok=True)
        zf.extractall(out_dir)


def parse_agrifreshnet_folder(name: str) -> tuple[str, str, int, int]:
    """'Semi fresh Pineapple (15-25)' -> ('pineapple', 'Semi-Fresh', 15, 25)."""
    m = _AGRI_RE.match(name.strip())
    if not m:
        raise ValueError(f"unexpected AgriFreshNET folder: {name!r}")
    state = m.group(1).lower()
    state = "Semi-Fresh" if state.startswith("semi") else state.capitalize()
    return m.group(2).lower(), state, int(m.group(3)), int(m.group(4))


def parse_spinach_folder(name: str) -> tuple[str, str]:
    """'Water Spinach Non fresh' -> ('water spinach', 'non-fresh')."""
    m = _SPINACH_RE.match(name.strip())
    if not m:
        raise ValueError(f"unexpected Local Spinach folder: {name!r}")
    label = "non-fresh" if m.group(2).lower().startswith("non") else "fresh"
    return m.group(1).lower(), label


def _original_stem(filename: str) -> str:
    """aug_12_IMG_1_HDR_AE~3.jpg -> IMG_1_HDR_AE (augmented copies and burst/HDR variants share it)."""
    stem = Path(filename).stem
    stem = re.sub(r"^aug_\d+_", "", stem)
    return re.sub(r"~\d+$", "", stem)


# ---------- download ----------


def _api_get(path: str, **params) -> object:
    r = requests.get(f"{API}/{path}", params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def download(dataset: Dataset, dest_dir: Path) -> Path:
    """Download the non-augmented zip(s) of ``dataset`` into ``dest_dir``, verify, extract, write SOURCE.md.

    Returns ``dest_dir``. Images end up under ``dest_dir/extracted/``.
    """
    src = SOURCES[dataset]
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    meta = _api_get(src["id"], version=src["version"])
    listing = _api_get(f"{src['id']}/files", folder_id="root", version=src["version"])
    (dest_dir / "mendeley_metadata.json").write_text(
        json.dumps({"dataset": meta, "files": listing}, ensure_ascii=False, indent=2)
    )
    live = {f["id"]: f for f in listing}
    today = dt.date.today().isoformat()
    records = []
    for f in src["files"]:
        lf = live.get(f["id"])
        if lf is None:
            raise ValueError(f"{dataset}: file {f['filename']} ({f['id']}) no longer listed by Mendeley")
        cd = lf["content_details"]
        if cd["size"] != f["size"] or cd["sha256_hash"] != f["sha256"]:
            raise ValueError(f"{dataset}: Mendeley listing changed for {f['filename']}: {cd}")
        out = dest_dir / f["filename"]
        if not (out.is_file() and out.stat().st_size == f["size"]):
            tmp = out.with_suffix(out.suffix + ".part")
            with requests.get(cd["download_url"], stream=True, timeout=120) as r:
                r.raise_for_status()
                with open(tmp, "wb") as fh:
                    shutil.copyfileobj(r.raw, fh, length=1 << 20)
            tmp.replace(out)
        verify_file(out, f["size"], f["sha256"])
        safe_extract(out, dest_dir / "extracted")
        records.append({**f, "download_url": cd["download_url"]})
    write_source_md(dataset, dest_dir, meta, records, today)
    return dest_dir


def _citation(meta: dict) -> str:
    authors = "; ".join(
        f"{c.get('last_name', '').strip()}, {c.get('first_name', '').strip()}" for c in meta.get("contributors", [])
    )
    year = meta["publish_date"][:4]
    return (
        f"{authors} ({year}), “{meta['name'].strip()}”, Mendeley Data, V{meta['version']}, "
        f"doi: {meta['doi']['id']}"
    )


def _class_table(dataset: str, dest_dir: Path) -> str:
    rows = _scan_dataset(dataset, dest_dir)
    if not rows:
        return ""
    df = pd.DataFrame(rows)
    lines = ["| produce | label_raw | folder | images | augmented (aug_*) |", "|---|---|---|---|---|"]
    for (prod, lab, folder), g in df.groupby(["produce", "label_raw", "source_folder"]):
        lines.append(f"| {prod} | {lab} | `{folder}` | {len(g)} | {int(g.is_augmented.sum())} |")
    lines.append(f"\nTotal images: {len(df)}; distinct produce: {df.produce.nunique()} "
                 f"({', '.join(sorted(df.produce.unique()))}).")
    return "\n".join(lines)


def write_source_md(dataset: str, dest_dir: Path, meta: dict, records: list[dict], today: str) -> Path:
    src = SOURCES[dataset]
    lic = meta["data_licence"]
    page = f"https://data.mendeley.com/datasets/{src['id']}/{src['version']}"
    parts = [
        f"# {meta['name'].strip()} (Mendeley Data V{meta['version']})",
        "",
        f"- Dataset page: {page}",
        f"- API: {API}/{src['id']}?version={src['version']} (full response saved in `mendeley_metadata.json`)",
        f"- DOI: https://doi.org/{meta['doi']['id']}",
        f"- Published: {meta['publish_date']}",
        f"- Downloaded: {today} with `python -m tastoria_ml.data.freshness_sources`",
        "",
        "## License (verbatim from the Mendeley API `data_licence` field)",
        "",
        f"- {lic['short_name']} - {lic['full_name']} - {lic['url']}",
        f"- \"{lic['description']}\"",
        "",
        "## Citation",
        "",
        _citation(meta),
        "",
        "## Files",
        "",
        "| file | bytes | sha256 (checked locally = Mendeley `sha256_hash`) | URL |",
        "|---|---|---|---|",
    ]
    for r in records:
        parts.append(f"| {r['filename']} | {r['size']} | `{r['sha256']}` | {r['download_url']} |")
    parts.append("")
    parts.append("Extracted into `extracted/`.")
    if src["skipped"]:
        parts += ["", "## Not downloaded", ""]
        for s in src["skipped"]:
            parts.append(f"- {s['filename']} ({s['size']} bytes, sha256 `{s['sha256']}`): {s['reason']}.")
    if dataset == "agrifreshnet":
        parts += [
            "",
            "## Produce list (not published on the dataset page; read from the zip's folders)",
            "",
            "The dataset page says \"24 classes\". The zip has 24 folders, which are 8 produce x 3 freshness "
            "states, not 24 kinds of produce. Folder names carry the shelf-life range in days. The page says "
            "14,500 images; the zip holds 24 x 590 = 14,160. Most files are augmented copies (`aug_<n>_...`); "
            "some identical files appear under two freshness labels (`label_conflict` in the manifest).",
            "",
            _class_table(dataset, dest_dir),
        ]
    else:
        parts += [
            "",
            "## Classes",
            "",
            "No lot / capture-batch information is published, and file names (`_<n>_<random>.png`) carry none, "
            "so each image is its own `group_id`.",
            "",
            _class_table(dataset, dest_dir),
        ]
    p = dest_dir / "SOURCE.md"
    p.write_text("\n".join(parts) + "\n")
    return p


# ---------- manifest ----------


def _scan_dataset(dataset: str, ds_dir: Path) -> list[dict]:
    root = ds_dir / "extracted"
    if not root.is_dir():
        return []
    rows = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in IMAGE_EXT:
            continue
        folder = p.parent.name
        if dataset == "agrifreshnet":
            produce, label_raw, lo, hi = parse_agrifreshnet_folder(folder)
            label3 = AGRI_LABEL3[label_raw]
            key = f"agrifreshnet/{produce}/{_original_stem(p.name)}"
            aug = p.name.startswith("aug_")
        else:
            produce, label_raw = parse_spinach_folder(folder)
            label3 = SPINACH_LABEL3[label_raw]
            lo = hi = float("nan")
            key = f"local_spinach_leaf/{produce}/{p.stem}"
            aug = False
        rows.append(
            {
                "path": str(p.resolve()),
                "dataset": dataset,
                "produce": produce,
                "label_raw": label_raw,
                "label3": label3,
                "source_folder": folder,
                "shelf_life_min_days": lo,
                "shelf_life_max_days": hi,
                "is_augmented": aug,
                "_key": key,
            }
        )
    return rows


def _union_groups(df: pd.DataFrame) -> pd.Series:
    """Connected components over (name key) and (sha256): identical bytes always share a group."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for key, digest in zip(df["_key"], df["sha256"]):
        a, b = find("k:" + key), find("h:" + digest)
        if a != b:
            parent[b] = a
    members: dict[str, list[str]] = defaultdict(list)
    for key in df["_key"]:
        members[find("k:" + key)].append(key)
    name = {root: min(keys) for root, keys in members.items()}
    return df["_key"].map(lambda k: name[find("k:" + k)])


def build_manifest(raw_root: Path) -> pd.DataFrame:
    """One row per image under ``raw_root/<dataset>/extracted``; ``path`` is absolute."""
    rows = []
    for ds in SOURCES:
        rows += _scan_dataset(ds, Path(raw_root) / ds)
    df = pd.DataFrame(rows)
    if df.empty:
        raise FileNotFoundError(f"no images under {raw_root}/*/extracted")
    df["sha256"] = df.path.map(lambda p: sha256_of(Path(p)))
    df["group_id"] = _union_groups(df)
    n_labels = df.groupby("sha256").label3.transform("nunique")
    df["label_conflict"] = n_labels > 1
    assert set(df.label3) <= LABEL3
    cols = [
        "path", "dataset", "produce", "label_raw", "label3", "group_id", "is_augmented",
        "label_conflict", "shelf_life_min_days", "shelf_life_max_days", "source_folder", "sha256",
    ]
    return df[cols].reset_index(drop=True)


def main(argv: list[str] | None = None) -> int:
    repo = Path(__file__).resolve().parents[4]
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--raw-root", type=Path, default=repo / "data/raw/images/freshness")
    ap.add_argument("--out", type=Path, default=repo / "data/processed/freshness/manifest.csv")
    ap.add_argument("--skip-download", action="store_true")
    args = ap.parse_args(argv)
    if not args.skip_download:
        for ds in SOURCES:
            download(ds, args.raw_root / ds)  # type: ignore[arg-type]
    m = build_manifest(args.raw_root)
    for ds, src in SOURCES.items():
        n = int((m.dataset == ds).sum())
        if n != src["expected_images"]:
            raise ValueError(f"{ds}: {n} images, expected {src['expected_images']}")
    out = m.copy()
    out["path"] = out.path.map(lambda p: Path(p).resolve().relative_to(repo.resolve()).as_posix())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out, index=False)
    print(f"wrote {args.out}: {len(out)} rows")
    print(out.groupby(["dataset", "label3"]).size().to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
