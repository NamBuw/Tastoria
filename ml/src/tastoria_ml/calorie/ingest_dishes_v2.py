"""Ingest the expanded 310-class dish recognition corpus on host 153 /dev/shm.

Combines:
  1. ``jeandeanny/vn-food-combined-2026`` (103 Vietnamese dish classes, 40,432 images)
  2. ``kng-research/uecfood256`` (256 Asian & home-cooked dish classes, 31,395 images)
  3. ``ethz/food101`` (101 Global & Asian dish classes, 101,000 images)
  4. ``mi_tom`` crops & full images from ``yolo_v4``

Enforces strict 64-bit DCT pHash deduplication (Hamming > 4) between ``val`` / ``exclude_dir``
(e.g. ``app/assets/food/*.webp``) and ``train``.
"""

from __future__ import annotations

import argparse
import io
import json
import random
import shutil
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import yaml
from huggingface_hub import HfApi, hf_hub_download
from PIL import Image, ImageOps

from tastoria_ml.calorie.dish_taxonomy import (
    BY_ID,
    CANONICAL_DISHES,
    UEC256_TO_CANONICAL,
    VN103_TO_CANONICAL,
    map_food101_label,
)
from tastoria_ml.cv.phash import hamming, phash


def _img_phash(rgb_im: Image.Image) -> int:
    gray = rgb_im.convert("L")
    gray.thumbnail((256, 256))
    return int(phash(np.asarray(gray)))


def _decode_exif_rgb(data: bytes | Image.Image, max_side: int = 384) -> Image.Image:
    if isinstance(data, Image.Image):
        im = data
    else:
        im = Image.open(io.BytesIO(data))
    im.load()
    im = ImageOps.exif_transpose(im).convert("RGB")
    if max(im.size) > max_side:
        im.thumbnail((max_side, max_side), Image.Resampling.BILINEAR)
    return Image.frombytes("RGB", im.size, im.tobytes())


def _extract_parquet_bytes(cell) -> bytes:
    if isinstance(cell, dict):
        if cell.get("bytes"):
            return cell["bytes"]
        if cell.get("path") and Path(cell["path"]).is_file():
            return Path(cell["path"]).read_bytes()
    if isinstance(cell, (bytes, bytearray)):
        return bytes(cell)
    raise ValueError(f"Unsupported image cell: {type(cell)}")


def run_ingest(
    work_dir: Path,
    vn103_dir: Path,
    uec256_zip: Path,
    yolo_v4_dir: Path,
    exclude_dir: Path | None = None,
    max_side: int = 384,
    max_food101_train_per_cls: int = 650,
    seed: int = 0,
) -> dict:
    work_dir = Path(work_dir)
    img_root = work_dir / "images"
    dl_dir = work_dir / "_dl"
    dl_dir.mkdir(parents=True, exist_ok=True)
    for sp in ("train", "val"):
        for d in CANONICAL_DISHES:
            (img_root / sp / d.dish_id).mkdir(parents=True, exist_ok=True)

    excluded_hashes: list[int] = []
    if exclude_dir and exclude_dir.exists():
        for p in sorted(exclude_dir.iterdir()):
            if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                with Image.open(p) as im:
                    excluded_hashes.append(_img_phash(im.convert("RGB")))

    counts: dict[str, Counter] = {"train": Counter(), "val": Counter()}
    val_hashes: list[int] = list(excluded_hashes)
    val_hash_arr: np.ndarray | None = None
    seen_train_hashes: set[int] = set()
    dropped_dupes = 0

    def _refresh_val_arr() -> None:
        nonlocal val_hash_arr
        val_hash_arr = np.asarray(val_hashes, dtype=np.uint64) if val_hashes else None

    _refresh_val_arr()

    def _save_sample(split: str, cid: str, src_tag: str, idx: int, rgb: Image.Image) -> bool:
        nonlocal dropped_dupes
        h = _img_phash(rgb)
        if split == "val":
            if excluded_hashes and int(hamming(np.asarray(excluded_hashes, dtype=np.uint64), h).min()) <= 4:
                dropped_dupes += 1
                return False
            val_hashes.append(h)
        else:
            if h in seen_train_hashes:
                dropped_dupes += 1
                return False
            if val_hash_arr is not None and val_hash_arr.size > 0:
                if int(hamming(val_hash_arr, h).min()) <= 4:
                    dropped_dupes += 1
                    return False
            seen_train_hashes.add(h)
        out = img_root / split / cid / f"{src_tag}_{idx:06d}.jpg"
        rgb.save(out, "JPEG", quality=88)
        counts[split][cid] += 1
        return True

    # ---- 1. Extract VNFood-103 (validation first, then train + test into train or validation) ----
    print("[1/4] Extracting VNFood-103 parquets...", flush=True)
    pfiles = sorted(vn103_dir.rglob("*.parquet"))
    assert pfiles, f"No parquet files found under {vn103_dir}"
    schema = pq.read_schema(pfiles[0])
    meta = json.loads(schema.metadata[b"huggingface"].decode())
    vn103_names = meta["info"]["features"]["label"]["names"]
    vn103_label_map = [VN103_TO_CANONICAL[n] for n in vn103_names]

    # Process validation first so val_hashes are populated before train!
    val_pfiles = [p for p in pfiles if "validation-" in p.name]
    train_pfiles = [p for p in pfiles if "train-" in p.name or "test-" in p.name]
    g_idx = 0
    for sp, pf_list in (("val", val_pfiles), ("train", train_pfiles)):
        if sp == "train":
            _refresh_val_arr()
        for lp in pf_list:
            pf = pq.ParquetFile(lp)
            for batch in pf.iter_batches(batch_size=256, columns=["image", "label"]):
                imgs = batch.column("image").to_pylist()
                lbls = batch.column("label").to_pylist()
                for cell, lidx in zip(imgs, lbls):
                    cid = vn103_label_map[int(lidx)]
                    try:
                        rgb = _decode_exif_rgb(_extract_parquet_bytes(cell), max_side=max_side)
                        _save_sample(sp, cid, "vn103", g_idx, rgb)
                    except Exception:
                        pass
                    g_idx += 1
    _refresh_val_arr()
    print(f"  VN103 done: train={sum(counts['train'].values())} val={sum(counts['val'].values())} dupes={dropped_dupes}", flush=True)

    # ---- 2. Extract UECFood-256 (85/15 split per mapped category, val first then train) ----
    print("[2/4] Extracting UECFood-256 zip...", flush=True)
    rng = random.Random(seed)
    by_cat: dict[int, list[str]] = defaultdict(list)
    with zipfile.ZipFile(uec256_zip) as zf:
        for name in sorted(zf.namelist()):
            if not name.lower().endswith((".jpg", ".jpeg", ".png")):
                continue
            parts = Path(name).parts
            cat_tok = None
            for part in parts[:-1]:
                if part.isdigit() and int(part) in UEC256_TO_CANONICAL:
                    cat_tok = int(part)
                    break
            if cat_tok is not None:
                by_cat[cat_tok].append(name)

        split_items: list[tuple[str, str, int, str]] = []
        for cat_id, names in sorted(by_cat.items()):
            names_shuf = list(names)
            rng.shuffle(names_shuf)
            n_val = max(2, int(round(len(names_shuf) * 0.15)))
            cid = UEC256_TO_CANONICAL[cat_id]
            for i, zname in enumerate(names_shuf):
                sp = "val" if i < n_val else "train"
                split_items.append((sp, cid, cat_id, zname))

        u_idx = 0
        for sp_target in ("val", "train"):
            if sp_target == "train":
                _refresh_val_arr()
            for sp, cid, cat_id, zname in split_items:
                if sp != sp_target:
                    continue
                try:
                    rgb = _decode_exif_rgb(zf.read(zname), max_side=max_side)
                    _save_sample(sp, cid, f"uec{cat_id}", u_idx, rgb)
                except Exception:
                    pass
                u_idx += 1
    _refresh_val_arr()
    print(f"  UEC256 done: train={sum(counts['train'].values())} val={sum(counts['val'].values())} dupes={dropped_dupes}", flush=True)

    # ---- 3. Extract mi_tom crops/images from yolo_v4 ----
    print("[3/4] Extracting mi_tom from yolo_v4...", flush=True)
    if (yolo_v4_dir / "dataset.yaml").is_file():
        ds = yaml.safe_load((yolo_v4_dir / "dataset.yaml").read_text(encoding="utf-8"))
        raw_names = ds["names"]
        names_map = {int(k): v for k, v in raw_names.items()} if isinstance(raw_names, dict) else {i: v for i, v in enumerate(raw_names)}
        mitom_cls = next((k for k, v in names_map.items() if v == "mi_tom"), None)
        if mitom_cls is not None:
            m_idx = 0
            for sp in ("val", "train"):
                if sp == "train":
                    _refresh_val_arr()
                lbl_dir = yolo_v4_dir / "labels" / sp
                img_dir = yolo_v4_dir / "images" / sp
                for lbl in sorted(lbl_dir.glob("*.txt")):
                    lines = [ln.strip().split() for ln in lbl.read_text(encoding="utf-8").splitlines() if ln.strip()]
                    mitom_boxes = [ln for ln in lines if int(float(ln[0])) == mitom_cls]
                    if not mitom_boxes:
                        continue
                    ip = img_dir / f"{lbl.stem}.jpg"
                    if not ip.is_file():
                        continue
                    with Image.open(ip) as im:
                        rgb = ImageOps.exif_transpose(im).convert("RGB")
                        W, H = rgb.size
                        rgb_copy = rgb.copy()
                        rgb_copy.thumbnail((max_side, max_side), Image.Resampling.BILINEAR)
                        _save_sample(sp, "mi_tom", "mtw", m_idx, rgb_copy)
                        m_idx += 1
                        for bi, toks in enumerate(mitom_boxes[:2]):
                            xc, yc, bw, bh = (float(x) for x in toks[1:5])
                            x1 = max(0, int((xc - bw * 0.65) * W))
                            y1 = max(0, int((yc - bh * 0.65) * H))
                            x2 = min(W, int((xc + bw * 0.65) * W))
                            y2 = min(H, int((yc + bh * 0.65) * H))
                            if x2 - x1 >= 32 and y2 - y1 >= 32:
                                crop = rgb.crop((x1, y1, x2, y2))
                                crop.thumbnail((max_side, max_side), Image.Resampling.BILINEAR)
                                _save_sample(sp, "mi_tom", "mtc", m_idx, crop)
                                m_idx += 1
    _refresh_val_arr()
    print(f"  mi_tom done: train={counts['train']['mi_tom']} val={counts['val']['mi_tom']}", flush=True)

    # ---- 4. Stream ethz/food101 shard-by-shard (capped at max_food101_train_per_cls to save /dev/shm space & balance VN/Asian) ----
    print("[4/4] Streaming ethz/food101 shard-by-shard...", flush=True)
    api = HfApi()
    f_info = api.dataset_info("ethz/food101")
    f_files = [s.rfilename for s in f_info.siblings if s.rfilename.endswith(".parquet")]
    import urllib.request
    with urllib.request.urlopen("https://datasets-server.huggingface.co/info?dataset=ethz/food101", timeout=15) as r:
        f_meta = json.loads(r.read().decode())
    f_names = next(iter(f_meta["dataset_info"].values()))["features"]["label"]["names"]
    f_label_map = [map_food101_label(n) for n in f_names]
    ordered_f = sorted(f_files, key=lambda s: (0 if "validation" in s else 1, s))
    f101_counts: dict[str, Counter] = {"train": Counter(), "val": Counter()}
    f_idx = 0
    for rf in ordered_f:
        sp = "val" if "validation" in rf else "train"
        if sp == "train":
            _refresh_val_arr()
        lp = Path(hf_hub_download("ethz/food101", rf, repo_type="dataset", local_dir=str(dl_dir / "food101")))
        pf = pq.ParquetFile(lp)
        for batch in pf.iter_batches(batch_size=256, columns=["image", "label"]):
            imgs = batch.column("image").to_pylist()
            lbls = batch.column("label").to_pylist()
            for cell, lidx in zip(imgs, lbls):
                cid = f_label_map[int(lidx)]
                if cid not in BY_ID:
                    continue
                cap = 200 if sp == "val" else max_food101_train_per_cls
                if f101_counts[sp][cid] >= cap:
                    continue
                try:
                    rgb = _decode_exif_rgb(_extract_parquet_bytes(cell), max_side=max_side)
                    if _save_sample(sp, cid, "f101", f_idx, rgb):
                        f101_counts[sp][cid] += 1
                except Exception:
                    pass
                f_idx += 1
        lp.unlink(missing_ok=True)
    shutil.rmtree(dl_dir, ignore_errors=True)

    summary = {
        "n_classes": len(CANONICAL_DISHES),
        "total_train": int(sum(counts["train"].values())),
        "total_val": int(sum(counts["val"].values())),
        "dropped_dupes": dropped_dupes,
        "empty_train_classes": [d.dish_id for d in CANONICAL_DISHES if counts["train"][d.dish_id] == 0],
        "empty_val_classes": [d.dish_id for d in CANONICAL_DISHES if counts["val"][d.dish_id] == 0],
    }
    (work_dir / "ingest_v2_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-dir", type=Path, default=Path("/dev/shm/dish_v2_stage"))
    ap.add_argument("--vn103-dir", type=Path, default=Path("/dev/shm/hf_vn103"))
    ap.add_argument(
        "--uec256-zip",
        type=Path,
        default=Path("/dev/shm/hf_uec256/datasets--kng-research--uecfood256/snapshots/5dd3860447882fa13e5150af0037fe672c9dbe4d/dataset256.zip"),
    )
    ap.add_argument("--yolo-v4-dir", type=Path, default=Path("/home/namnx/NamBuw/Tastoria/data/processed/cv/yolo_v4"))
    ap.add_argument("--exclude-dir", type=Path, default=Path("/home/namnx/NamBuw/Tastoria/app/assets/food"))
    ap.add_argument("--max-food101-train", type=int, default=650)
    args = ap.parse_args()
    run_ingest(
        work_dir=args.work_dir,
        vn103_dir=args.vn103_dir,
        uec256_zip=args.uec256_zip,
        yolo_v4_dir=args.yolo_v4_dir,
        exclude_dir=args.exclude_dir,
        max_food101_train_per_cls=args.max_food101_train,
    )


if __name__ == "__main__":
    main()

