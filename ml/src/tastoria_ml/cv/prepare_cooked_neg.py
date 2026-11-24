"""Assemble clean, zero-leakage cooked-dish 0-box hard-negative training images in /dev/shm.

Sources (strictly ``train``-only):
  1. ``shalev396/calorie-lens-data`` (Nutrition5k overhead/train, CC BY 4.0) — filtered against
     intact raw/baked contract classes (bread, bagel, muffin, cake, cookie, pastry, pizza,
     hard-boiled/deviled egg, whole tomato, citrus, raw spinach, cucumber salad).
  2. Local Track C cooked-quarantined ``train`` images (Tier 1 ``openimages_v7_ood`` +
     ``lvis_v1_neg`` + Tier 2 ``rf_{viet_hoang,robo1,food_start}`` excluding images containing
     boxes in NON_RAW_PACKAGED_CLASSES or ``trung``).
  3. Optional local VN/Asian cooked dish folder (e.g. ``/dev/shm/dish_stage/images/train``),
     excluding ``banh_mi`` so intact bread detection is preserved.

Zero-leakage invariant:
  Computes 64-bit DCT pHash (256px L-channel) and drops every candidate within Hamming <= 4
  of any image in ``yolo_v4/{val,test,heldout}``, ``app/assets/food/*.webp``, or ``yolo_v4/train``.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import random
import shutil
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
from huggingface_hub import HfApi, hf_hub_download
from PIL import Image, ImageOps

from tastoria_ml.cv.phash import hamming, phash

NON_RAW_BANNED_ING = (
    "bread",
    "bagel",
    "croissant",
    "cake",
    "muffin",
    "brownie",
    "cookie",
    "cracker",
    "pastry",
    "pizza",
    "doughnut",
    "donut",
    "hard boiled egg",
    "cherry tomatoes",
    "tomato",
    "apple",
    "banana",
    "orange",
    "lemon",
    "lime",
    "spinach (raw)",
    "cucumber",
)
TRACK_C_BANNED_BOX_CLS = {
    "banh_mi",
    "banh_ngot",
    "banh_quy",
    "bim_bim",
    "do_hop",
    "keo",
    "mi_tom",
    "nuoc_ngot",
    "sua",
    "sua_chua",
    "trung",
}
COMMERCIAL_NEG_SOURCES = {"openimages_v7_ood", "lvis_v1_neg", "rf_viet_hoang", "rf_robo1", "rf_food_start"}
COOKED_REASONS = {"stage2a_cooked_meal", "stage2a_cooked_ood", "prepared_dish", "stage2b_cooked"}


def _l256_phash(img: Image.Image) -> int:
    g = img.convert("L")
    g.thumbnail((256, 256))
    return int(phash(np.asarray(g)))


def _upright_rgb(im: Image.Image, max_side: int = 1024) -> Image.Image:
    im = ImageOps.exif_transpose(im).convert("RGB")
    if max(im.size) > max_side:
        im.thumbnail((max_side, max_side), Image.Resampling.BILINEAR)
    return Image.frombytes("RGB", im.size, im.tobytes())


def prepare(
    out_dir: Path,
    *,
    yolo_v4_dir: Path,
    food_assets_dir: Path,
    decisions_json: Path | None = None,
    vn_dish_train_dir: Path | None = None,
    max_n5k: int = 1500,
    max_vn_dishes: int = 450,
    seed: int = 0,
) -> dict:
    out_dir = Path(out_dir)
    img_dir = out_dir / "images"
    lbl_dir = out_dir / "labels"
    img_dir.mkdir(parents=True, exist_ok=True)
    lbl_dir.mkdir(parents=True, exist_ok=True)
    stage_dl = out_dir / "_dl_n5k"
    stage_dl.mkdir(parents=True, exist_ok=True)

    # Build strict exclusion pHash bank: all val/test/heldout + food_assets + yolo_v4/train
    ref_hashes: list[int] = []
    for sp in ("test", "heldout", "val", "train"):
        d = yolo_v4_dir / "images" / sp
        if d.is_dir():
            for p in sorted(d.glob("*.jpg")):
                try:
                    with Image.open(p) as im:
                        ref_hashes.append(_l256_phash(im))
                except Exception:
                    pass
    if food_assets_dir.is_dir():
        for p in sorted(food_assets_dir.iterdir()):
            if p.suffix.lower() in {".webp", ".jpg", ".jpeg", ".png"}:
                try:
                    with Image.open(p) as im:
                        ref_hashes.append(_l256_phash(im))
                except Exception:
                    pass
    ref_arr = np.asarray(ref_hashes, dtype=np.uint64)
    added_hashes: list[int] = []
    kept_paths: list[str] = []
    stats = {"n5k": 0, "track_c": 0, "vn_dishes": 0, "dropped_phash_or_err": 0}

    def _accept(stem: str, im: Image.Image, tag: str) -> bool:
        h = _l256_phash(im)
        if ref_arr.size and int(hamming(ref_arr, h).min()) <= 4:
            stats["dropped_phash_or_err"] += 1
            return False
        if added_hashes and int(hamming(np.asarray(added_hashes, dtype=np.uint64), h).min()) <= 4:
            stats["dropped_phash_or_err"] += 1
            return False
        added_hashes.append(h)
        dst_img = img_dir / f"{stem}.jpg"
        dst_lbl = lbl_dir / f"{stem}.txt"
        im.save(dst_img, "JPEG", quality=90)
        dst_lbl.write_text("", encoding="utf-8")
        kept_paths.append(str(dst_img))
        stats[tag] += 1
        return True

    # 1. Nutrition5k overhead/train (CC BY 4.0)
    api = HfApi()
    dishes_pq = Path(hf_hub_download("shalev396/calorie-lens-data", "dishes.parquet", repo_type="dataset", local_dir=str(stage_dl)))
    items_pq = Path(hf_hub_download("shalev396/calorie-lens-data", "items.parquet", repo_type="dataset", local_dir=str(stage_dl)))
    dt = pq.read_table(dishes_pq).to_pylist()
    it = pq.read_table(items_pq).to_pylist()
    bad_dishes: set[str] = set()
    for row in it:
        nm = str(row.get("name") or row.get("ingr_name") or "").casefold()
        if any(b in nm for b in NON_RAW_BANNED_ING):
            bad_dishes.add(str(row.get("dish_id")))
    valid_n5k_ids = {
        str(r["dish_id"])
        for r in dt
        if r.get("split") == "train" and float(r.get("total_calories") or r.get("calories") or 0) > 0 and str(r["dish_id"]) not in bad_dishes
    }
    print(f"[cooked_neg] N5k valid train dishes after raw-contract filter: {len(valid_n5k_ids)}", flush=True)

    ov_files = sorted(s.rfilename for s in api.dataset_info("shalev396/calorie-lens-data").siblings if "overhead/train-" in s.rfilename and s.rfilename.endswith(".parquet"))
    for rf in ov_files:
        if stats["n5k"] >= max_n5k:
            break
        lp = Path(hf_hub_download("shalev396/calorie-lens-data", rf, repo_type="dataset", local_dir=str(stage_dl)))
        pf = pq.ParquetFile(lp)
        cols = [c for c in ("dish_id", "image") if c in pf.schema_arrow.names]
        for batch in pf.iter_batches(batch_size=128, columns=cols):
            dids = batch.column("dish_id").to_pylist() if "dish_id" in cols else [""] * len(batch)
            imgs = batch.column("image").to_pylist()
            for did, cell in zip(dids, imgs):
                if stats["n5k"] >= max_n5k:
                    break
                if valid_n5k_ids and str(did) not in valid_n5k_ids:
                    continue
                try:
                    raw = cell["bytes"] if isinstance(cell, dict) and cell.get("bytes") else cell
                    with Image.open(io.BytesIO(raw)) as im:
                        rgb = _upright_rgb(im)
                    _accept(f"n5k__{did}", rgb, "n5k")
                except Exception:
                    stats["dropped_phash_or_err"] += 1
        lp.unlink(missing_ok=True)
    shutil.rmtree(stage_dl, ignore_errors=True)

    # 2. Local Track C cooked-quarantined train images
    if decisions_json and decisions_json.is_file():
        dec = json.loads(decisions_json.read_text(encoding="utf-8"))
        for k, rec in sorted(dec.items()):
            if rec.get("split") != "train" or rec.get("keep") is not False:
                continue
            src = rec.get("source")
            reason = str(rec.get("reason") or "")
            if src not in COMMERCIAL_NEG_SOURCES:
                continue
            if not any(r in reason for r in COOKED_REASONS):
                continue
            if src == "lvis_v1_neg" and "NonCommercial" in str(rec.get("license") or ""):
                continue
            raw_cls = {b.get("cls") for b in (rec.get("kept_boxes") or rec.get("raw_boxes") or [])}
            if raw_cls & TRACK_C_BANNED_BOX_CLS:
                continue
            p = Path(rec["path"])
            if not p.is_file():
                continue
            try:
                with Image.open(p) as im:
                    rgb = _upright_rgb(im)
                _accept(f"tc__{src}__{p.stem}", rgb, "track_c")
            except Exception:
                stats["dropped_phash_or_err"] += 1

    # 3. Optional local VN cooked dishes (excluding banh_mi)
    if vn_dish_train_dir and vn_dish_train_dir.is_dir():
        rng = random.Random(seed)
        cands = []
        for cdir in sorted(vn_dish_train_dir.iterdir()):
            if not cdir.is_dir() or cdir.name == "banh_mi":
                continue
            for p in sorted(cdir.glob("*.jpg"))[:35]:
                cands.append((cdir.name, p))
        rng.shuffle(cands)
        for cid, p in cands:
            if stats["vn_dishes"] >= max_vn_dishes:
                break
            try:
                with Image.open(p) as im:
                    rgb = _upright_rgb(im)
                _accept(f"vn__{cid}__{p.stem}", rgb, "vn_dishes")
            except Exception:
                stats["dropped_phash_or_err"] += 1

    manifest_path = out_dir / "cooked_neg_manifest.txt"
    manifest_path.write_text("\n".join(kept_paths) + "\n", encoding="utf-8")
    stats["total"] = len(kept_paths)
    (out_dir / "stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--yolo-v4-dir", type=Path, required=True)
    ap.add_argument("--food-assets-dir", type=Path, required=True)
    ap.add_argument("--decisions-json", type=Path, default=None)
    ap.add_argument("--vn-dish-train-dir", type=Path, default=None)
    ap.add_argument("--max-n5k", type=int, default=1500)
    ap.add_argument("--max-vn-dishes", type=int, default=450)
    a = ap.parse_args()
    print(
        json.dumps(
            prepare(
                a.out_dir,
                yolo_v4_dir=a.yolo_v4_dir,
                food_assets_dir=a.food_assets_dir,
                decisions_json=a.decisions_json,
                vn_dish_train_dir=a.vn_dish_train_dir,
                max_n5k=a.max_n5k,
                max_vn_dishes=a.max_vn_dishes,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
