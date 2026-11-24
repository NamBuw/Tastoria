"""Extract UECFood-100 (85/15 split) + YOLO v4 mi_tom crops into dish_stage, then delete zip.

Run on host 153 after dataset100.zip download completes.
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
from PIL import Image, ImageDraw, ImageOps

from tastoria_ml.calorie.dish_taxonomy import BY_ID, CANONICAL_DISHES, UEC100_TO_CANONICAL
from tastoria_ml.cv.phash import hamming, phash


def _phash(im: Image.Image) -> int:
    g = im.convert("L")
    g.thumbnail((256, 256))
    return int(phash(np.asarray(g)))


def _decode(data: bytes, max_side: int = 384) -> Image.Image:
    im = Image.open(io.BytesIO(data))
    im.load()
    im = ImageOps.exif_transpose(im).convert("RGB")
    if max(im.size) > max_side:
        im.thumbnail((max_side, max_side), Image.Resampling.BILINEAR)
    return Image.frombytes("RGB", im.size, im.tobytes())


def run(
    uec_zip: Path,
    work_dir: Path,
    yolo_v4_dir: Path,
    exclude_dir: Path | None = None,
    seed: int = 0,
) -> dict:
    img_root = work_dir / "images"
    for sp in ("train", "val"):
        for d in CANONICAL_DISHES:
            (img_root / sp / d.dish_id).mkdir(parents=True, exist_ok=True)

    ref_hashes: list[int] = []
    if exclude_dir and exclude_dir.is_dir():
        for p in sorted(exclude_dir.iterdir()):
            if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                with Image.open(p) as im:
                    ref_hashes.append(_phash(im))
    # Include existing val images in dish_stage to prevent cross-split leakage
    val_root = img_root / "val"
    if val_root.is_dir():
        for p in val_root.rglob("*.jpg"):
            try:
                with Image.open(p) as im:
                    ref_hashes.append(_phash(im))
            except Exception:
                pass
    ref_arr = np.asarray(ref_hashes, dtype=np.uint64)

    counts = {"uec_train": 0, "uec_val": 0, "mitom_train": 0, "mitom_val": 0, "dropped": 0}
    seen_train: set[int] = set()
    samples_uec: dict[str, list[Path]] = defaultdict(list)

    def _save(sp: str, cid: str, tag: str, rgb: Image.Image, local_val_hashes: list[int]) -> None:
        h = _phash(rgb)
        if sp == "val":
            if ref_arr.size and int(hamming(ref_arr, h).min()) <= 4:
                counts["dropped"] += 1
                return
            local_val_hashes.append(h)
        else:
            if h in seen_train:
                counts["dropped"] += 1
                return
            if ref_arr.size and int(hamming(ref_arr, h).min()) <= 4:
                counts["dropped"] += 1
                return
            if local_val_hashes and int(hamming(np.asarray(local_val_hashes, dtype=np.uint64), h).min()) <= 4:
                counts["dropped"] += 1
                return
            seen_train.add(h)
        out = img_root / sp / cid / f"{tag}.jpg"
        rgb.save(out, "JPEG", quality=88)
        if tag.startswith("uec"):
            counts[f"uec_{sp}"] += 1
            if sp == "val" and len(samples_uec[cid]) < 4:
                samples_uec[cid].append(out)
        else:
            counts[f"mitom_{sp}"] += 1

    # 1. Extract UECFood-100 (85/15 split per category)
    rng = random.Random(seed)
    by_cat: dict[int, list[str]] = defaultdict(list)
    with zipfile.ZipFile(uec_zip) as zf:
        for name in sorted(zf.namelist()):
            if not name.lower().endswith((".jpg", ".jpeg", ".png")):
                continue
            parts = Path(name).parts
            # Expected UECFOOD100/<cat_id>/<img_id>.jpg
            cat_tok = None
            for part in parts[:-1]:
                if part.isdigit() and int(part) in UEC100_TO_CANONICAL:
                    cat_tok = int(part)
                    break
            if cat_tok is not None:
                by_cat[cat_tok].append(name)

        local_val_hashes: list[int] = []
        # Split first, process val before train!
        split_items: list[tuple[str, str, int, str]] = []
        for cat_id, names in sorted(by_cat.items()):
            names_shuf = list(names)
            rng.shuffle(names_shuf)
            n_val = max(1, int(round(len(names_shuf) * 0.15)))
            cid = UEC100_TO_CANONICAL[cat_id]
            for i, zname in enumerate(names_shuf):
                sp = "val" if i < n_val else "train"
                split_items.append((sp, cid, cat_id, zname))

        for sp_target in ("val", "train"):
            for sp, cid, cat_id, zname in split_items:
                if sp != sp_target:
                    continue
                try:
                    rgb = _decode(zf.read(zname))
                    stem = Path(zname).stem
                    _save(sp, cid, f"uec_{cat_id}_{stem}", rgb, local_val_hashes)
                except Exception:
                    counts["dropped"] += 1

    # Delete zip archive immediately
    uec_zip.unlink(missing_ok=True)
    shutil.rmtree(uec_zip.parent, ignore_errors=True)

    # 2. Extract mi_tom crops/images from yolo_v4 (using existing vision_classes index of mi_tom)
    import yaml

    ds = yaml.safe_load((yolo_v4_dir / "dataset.yaml").read_text(encoding="utf-8"))
    raw_names = ds["names"]
    names_map = {int(k): v for k, v in raw_names.items()} if isinstance(raw_names, dict) else {i: v for i, v in enumerate(raw_names)}
    mitom_cls = next((k for k, v in names_map.items() if v == "mi_tom"), None)
    if mitom_cls is not None:
        mitom_val_hashes: list[int] = []
        for sp in ("val", "train"):
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
                    # Save whole image + tight padded crops around mi_tom packs (max 2 per img)
                    rgb_copy = rgb.copy()
                    rgb_copy.thumbnail((384, 384), Image.Resampling.BILINEAR)
                    _save(sp, "mi_tom", f"mtw_{lbl.stem}", rgb_copy, mitom_val_hashes)
                    for bi, toks in enumerate(mitom_boxes[:2]):
                        xc, yc, bw, bh = (float(x) for x in toks[1:5])
                        x1 = max(0, int((xc - bw * 0.65) * W))
                        y1 = max(0, int((yc - bh * 0.65) * H))
                        x2 = min(W, int((xc + bw * 0.65) * W))
                        y2 = min(H, int((yc + bh * 0.65) * H))
                        if x2 - x1 >= 32 and y2 - y1 >= 32:
                            crop = rgb.crop((x1, y1, x2, y2))
                            crop.thumbnail((384, 384), Image.Resampling.BILINEAR)
                            _save(sp, "mi_tom", f"mtc_{lbl.stem}_{bi}", crop, mitom_val_hashes)

    # Save UEC100 contact sheet (36 sample new Asian classes)
    keys = [k for k in sorted(samples_uec) if k in BY_ID][:36]
    if keys:
        tile, label_w = 104, 190
        canvas = Image.new("RGB", (label_w + 4 * tile, len(keys) * tile), (24, 24, 24))
        draw = ImageDraw.Draw(canvas)
        for ri, cid in enumerate(keys):
            y0 = ri * tile
            draw.text((8, y0 + 40), cid[:24], fill=(240, 240, 240))
            for ci, p in enumerate(samples_uec[cid][:4]):
                try:
                    with Image.open(p) as im:
                        canvas.paste(ImageOps.fit(im.convert("RGB"), (tile - 4, tile - 4)), (label_w + ci * tile + 2, y0 + 2))
                except Exception:
                    pass
        canvas.save(work_dir / "qa_uec100.png", "PNG")

    return counts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--uec-zip", type=Path, required=True)
    ap.add_argument("--work-dir", type=Path, required=True)
    ap.add_argument("--yolo-v4-dir", type=Path, required=True)
    ap.add_argument("--exclude-dir", type=Path, default=None)
    a = ap.parse_args()
    print(json.dumps(run(a.uec_zip, a.work_dir, a.yolo_v4_dir, exclude_dir=a.exclude_dir), indent=2))


if __name__ == "__main__":
    main()
