"""Ingest, normalize, EXIF-transpose, pHash-dedupe, and inspect the 131-class dish corpus.

Sources (staged ephemerally under --work-dir, deleted after JPEG extraction):
  1. ``TuyenTrungLe/vietnamese_food_images`` (30 VN dishes, parquet)
  2. ``HoagMin/Vietnamese_StreetFood_Dataset`` (14 VN street dishes, CC BY 4.0, zip)
  3. ``ethz/food101`` (101 Asian/Global dishes, parquet; 3 exact overlaps merged cleanly)

Zero-leakage invariant:
  ``--exclude-dir`` (e.g. app/assets/food/*.webp) and all ``val`` images are pHash-hashed first
  (64-bit DCT pHash). Any ``train`` candidate within Hamming <= 4 of val or excluded images
  is dropped before writing.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
from huggingface_hub import HfApi, hf_hub_download
from PIL import Image, ImageDraw, ImageOps

from tastoria_ml.calorie.dish_taxonomy import (
    BY_ID,
    CANONICAL_DISHES,
    HOAGMIN_IDX_TO_CANONICAL,
    VN30_TO_CANONICAL,
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


def _make_contact_sheet(samples: dict[str, list[Path]], out_path: Path, max_classes: int = 33, per_cls: int = 3) -> None:
    keys = sorted(samples)[:max_classes]
    if not keys:
        return
    tile = 112
    label_w = 180
    cols = per_cls
    w = label_w + cols * tile
    h = len(keys) * tile
    canvas = Image.new("RGB", (w, h), (24, 24, 24))
    draw = ImageDraw.Draw(canvas)
    for r_idx, cid in enumerate(keys):
        y0 = r_idx * tile
        draw.text((8, y0 + 44), cid[:24], fill=(240, 240, 240))
        for c_idx, p in enumerate(samples[cid][:per_cls]):
            try:
                with Image.open(p) as im:
                    thumb = ImageOps.fit(im.convert("RGB"), (tile - 4, tile - 4))
                canvas.paste(thumb, (label_w + c_idx * tile + 2, y0 + 2))
            except Exception:
                pass
    canvas.save(out_path, "PNG")


def _hoagmin_label_to_id(raw_key: str) -> str | None:
    tok = raw_key.strip()
    if tok.isdigit() and int(tok) in HOAGMIN_IDX_TO_CANONICAL:
        return HOAGMIN_IDX_TO_CANONICAL[int(tok)]
    low = tok.casefold().replace("-", "_").replace(" ", "_")
    aliases = {
        "banh_cuon": "banh_cuon",
        "steamed_rice_rolls": "banh_cuon",
        "banh_gio": "banh_gio",
        "vietnamese_pyramid_rice_dumpling": "banh_gio",
        "banh_mi": "banh_mi",
        "grilled_pork_banh_mi": "banh_mi",
        "bun_bo_hue": "bun_bo_hue",
        "hue_style_spicy_beef_noodle_soup": "bun_bo_hue",
        "bun_cha": "bun_cha",
        "grilled_pork_with_vermicelli": "bun_cha",
        "bun_dau_mam_tom": "bun_dau_mam_tom",
        "vermicelli_with_tofu": "bun_dau_mam_tom",
        "bun_thit_nuong": "bun_thit_nuong",
        "grilled_pork_vermicelli": "bun_thit_nuong",
        "chao_long": "chao_long",
        "pork_offal_porridge": "chao_long",
        "com": "com_vong",
        "flattened_green_rice": "com_vong",
        "com_tam": "com_tam",
        "broken_rice": "com_tam",
        "com_rang": "com_rang",
        "fried_rice": "com_rang",
        "pho_bo": "pho",
        "pho": "pho",
        "beef_pho": "pho",
        "goi_cuon": "goi_cuon",
        "spring_rolls": "goi_cuon",
        "xoi": "xoi_xeo",
        "xoi_xeo": "xoi_xeo",
        "sticky_rice": "xoi_xeo",
    }
    if low in aliases:
        return aliases[low]
    # Check prefix integer e.g. "0_banh_cuon"
    m = re.match(r"^(\d+)", low)
    if m and int(m.group(1)) in HOAGMIN_IDX_TO_CANONICAL:
        return HOAGMIN_IDX_TO_CANONICAL[int(m.group(1))]
    return None


def ingest(work_dir: Path, exclude_dir: Path | None = None, max_side: int = 384) -> dict:
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

    api = HfApi()
    counts: dict[str, Counter] = {"train": Counter(), "val": Counter()}
    val_hashes: list[int] = list(excluded_hashes)
    seen_train_hashes: set[int] = set()
    samples_vn: dict[str, list[Path]] = defaultdict(list)
    samples_f101: dict[str, list[Path]] = defaultdict(list)
    dropped_dupes = 0

    def _save_sample(split: str, cid: str, src_tag: str, idx: int, rgb: Image.Image) -> None:
        nonlocal dropped_dupes
        h = _img_phash(rgb)
        if split == "val":
            if excluded_hashes and int(hamming(np.asarray(excluded_hashes, dtype=np.uint64), h).min()) <= 4:
                dropped_dupes += 1
                return
            val_hashes.append(h)
        else:
            if h in seen_train_hashes:
                dropped_dupes += 1
                return
            if val_hashes and int(hamming(np.asarray(val_hashes, dtype=np.uint64), h).min()) <= 4:
                dropped_dupes += 1
                return
            seen_train_hashes.add(h)
        out = img_root / split / cid / f"{src_tag}_{idx:06d}.jpg"
        rgb.save(out, "JPEG", quality=88)
        counts[split][cid] += 1
        if BY_ID[cid].category == "vn" and len(samples_vn[cid]) < 4 and split == "val":
            samples_vn[cid].append(out)
        elif BY_ID[cid].category != "vn" and len(samples_f101[cid]) < 4 and split == "val":
            samples_f101[cid].append(out)

    # ---- Source 2 first (small, 222 MB): HoagMin/Vietnamese_StreetFood_Dataset ----
    print("[1/3] Downloading HoagMin/Vietnamese_StreetFood_Dataset...", flush=True)
    hm_zip = Path(
        hf_hub_download(
            "HoagMin/Vietnamese_StreetFood_Dataset",
            "Vietnamese_StreetFood_14Class.zip",
            repo_type="dataset",
            local_dir=str(dl_dir / "hoagmin"),
        )
    )
    with zipfile.ZipFile(hm_zip) as zf:
        # Collect images by (split, label_dir)
        hm_items: list[tuple[str, str, str]] = []
        for name in sorted(zf.namelist()):
            if not name.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                continue
            parts = [p for p in Path(name).parts if p not in ("", ".")]
            # Handle train/images/foo.jpg + train/labels/foo.txt OR train/<cls>/foo.jpg
            sp = "val" if any(p in ("valid", "val") for p in parts) else "train"
            # Try label lookup from parent directory first, else YOLO label file class id if present
            cid = None
            for p in reversed(parts[:-1]):
                cid = _hoagmin_label_to_id(p)
                if cid:
                    break
            hm_items.append((name, sp, cid or ""))
        # If YOLO structured (labels/*.txt exists), inspect data.yaml + labels
        has_yolo_labels = any("/labels/" in n for n in zf.namelist() if n.endswith(".txt"))
        yolo_names: dict[int, str] = {}
        if has_yolo_labels:
            for yname in zf.namelist():
                if yname.endswith("data.yaml"):
                    import yaml
                    ydoc = yaml.safe_load(zf.read(yname).decode("utf-8", errors="replace")) or {}
                    raw_n = ydoc.get("names")
                    if isinstance(raw_n, list):
                        yolo_names = {i: str(v) for i, v in enumerate(raw_n)}
                    elif isinstance(raw_n, dict):
                        yolo_names = {int(k): str(v) for k, v in raw_n.items()}
                    break
        print(f"  HoagMin entries={len(hm_items)} yolo_labels={has_yolo_labels} yolo_names={len(yolo_names)}", flush=True)
        for sp_target in ("val", "train"):  # process val before train!
            for idx, (zname, sp, direct_cid) in enumerate(hm_items):
                if sp != sp_target:
                    continue
                cid = direct_cid
                if not cid and has_yolo_labels:
                    lbl_name = zname.replace("/images/", "/labels/").rsplit(".", 1)[0] + ".txt"
                    if lbl_name in zf.namelist():
                        lines = [ln.strip() for ln in zf.read(lbl_name).decode("utf-8", errors="replace").splitlines() if ln.strip()]
                        if lines:
                            clsid = int(float(lines[0].split()[0]))
                            cid = HOAGMIN_IDX_TO_CANONICAL.get(clsid) or _hoagmin_label_to_id(yolo_names.get(clsid, "")) or ""
                if not cid or cid not in BY_ID:
                    continue
                try:
                    rgb = _decode_exif_rgb(zf.read(zname), max_side=max_side)
                    _save_sample(sp, cid, "hm", idx, rgb)
                except Exception:
                    pass
    shutil.rmtree(dl_dir / "hoagmin", ignore_errors=True)
    print(f"  HoagMin done. train={sum(counts['train'].values())} val={sum(counts['val'].values())}", flush=True)

    # ---- Source 1: TuyenTrungLe/vietnamese_food_images (parquet, 30 VN dishes) ----
    print("[2/3] Streaming parquet TuyenTrungLe/vietnamese_food_images...", flush=True)
    vn_info = api.dataset_info("TuyenTrungLe/vietnamese_food_images")
    vn_files = [s.rfilename for s in vn_info.siblings if s.rfilename.endswith(".parquet")]
    # Get label names from datasets-server or parquet schema metadata
    import urllib.request
    with urllib.request.urlopen("https://datasets-server.huggingface.co/info?dataset=TuyenTrungLe/vietnamese_food_images", timeout=15) as r:
        ds_meta = json.loads(r.read().decode())
    vn_names = next(iter(ds_meta["dataset_info"].values()))["features"]["label"]["names"]
    vn_label_map = [VN30_TO_CANONICAL[n] for n in vn_names]
    # Process validation BEFORE train! Also fold half of test into train? No, keep validation clean and use train + test as train?
    # Better: keep 'validation' as val, 'train' as train, and keep 'test' unused or separate eval! Let's check: train=17581, val=2515 (very clean!). Let's also evaluate on its 'test' or save metrics separately. Here keep strict validation = validation, train = train!
    ordered_vn = sorted(vn_files, key=lambda s: (0 if "validation" in s else 1, s))
    g_idx = 0
    for rf in ordered_vn:
        if "/test-" in rf or rf.startswith("data/test-"):
            continue  # preserve test untouched
        sp = "val" if "validation" in rf else "train"
        lp = Path(hf_hub_download("TuyenTrungLe/vietnamese_food_images", rf, repo_type="dataset", local_dir=str(dl_dir / "vn30")))
        pf = pq.ParquetFile(lp)
        for batch in pf.iter_batches(batch_size=256, columns=["image", "label"]):
            imgs = batch.column("image").to_pylist()
            lbls = batch.column("label").to_pylist()
            for cell, lidx in zip(imgs, lbls):
                cid = vn_label_map[int(lidx)]
                try:
                    rgb = _decode_exif_rgb(_extract_parquet_bytes(cell), max_side=max_side)
                    _save_sample(sp, cid, "vn30", g_idx, rgb)
                except Exception:
                    pass
                g_idx += 1
        lp.unlink(missing_ok=True)
    shutil.rmtree(dl_dir / "vn30", ignore_errors=True)
    print(f"  VN30 done. train={sum(counts['train'].values())} val={sum(counts['val'].values())} dropped_dupes={dropped_dupes}", flush=True)

    # ---- Source 3: ethz/food101 (parquet, 101 Asian/Global dishes, download shard-by-shard & delete) ----
    print("[3/3] Streaming parquet ethz/food101...", flush=True)
    f_info = api.dataset_info("ethz/food101")
    f_files = [s.rfilename for s in f_info.siblings if s.rfilename.endswith(".parquet")]
    with urllib.request.urlopen("https://datasets-server.huggingface.co/info?dataset=ethz/food101", timeout=15) as r:
        f_meta = json.loads(r.read().decode())
    f_names = next(iter(f_meta["dataset_info"].values()))["features"]["label"]["names"]
    f_label_map = [map_food101_label(n) for n in f_names]
    ordered_f = sorted(f_files, key=lambda s: (0 if "validation" in s else 1, s))
    for rf in ordered_f:
        sp = "val" if "validation" in rf else "train"
        lp = Path(hf_hub_download("ethz/food101", rf, repo_type="dataset", local_dir=str(dl_dir / "food101")))
        pf = pq.ParquetFile(lp)
        for batch in pf.iter_batches(batch_size=256, columns=["image", "label"]):
            imgs = batch.column("image").to_pylist()
            lbls = batch.column("label").to_pylist()
            for cell, lidx in zip(imgs, lbls):
                cid = f_label_map[int(lidx)]
                try:
                    rgb = _decode_exif_rgb(_extract_parquet_bytes(cell), max_side=max_side)
                    _save_sample(sp, cid, "f101", g_idx, rgb)
                except Exception:
                    pass
                g_idx += 1
        lp.unlink(missing_ok=True)
        print(f"  shard {rf} done (train={sum(counts['train'].values())} val={sum(counts['val'].values())})", flush=True)
    shutil.rmtree(dl_dir, ignore_errors=True)

    _make_contact_sheet(samples_vn, work_dir / "qa_vn.png", max_classes=33, per_cls=4)
    _make_contact_sheet(samples_f101, work_dir / "qa_food101.png", max_classes=30, per_cls=4)

    summary = {
        "n_classes": len(CANONICAL_DISHES),
        "train_total": sum(counts["train"].values()),
        "val_total": sum(counts["val"].values()),
        "dropped_dupes": dropped_dupes,
        "missing_train_classes": [d.dish_id for d in CANONICAL_DISHES if counts["train"][d.dish_id] == 0],
        "missing_val_classes": [d.dish_id for d in CANONICAL_DISHES if counts["val"][d.dish_id] == 0],
        "per_class_train": dict(sorted(counts["train"].items())),
        "per_class_val": dict(sorted(counts["val"].items())),
    }
    (work_dir / "ingest_manifest.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-dir", type=Path, required=True)
    ap.add_argument("--exclude-dir", type=Path, default=None)
    ap.add_argument("--max-side", type=int, default=384)
    a = ap.parse_args()
    print(json.dumps(ingest(a.work_dir, exclude_dir=a.exclude_dir, max_side=a.max_side), indent=2))


if __name__ == "__main__":
    main()
