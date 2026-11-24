"""Ingest Duhok-FruitVeg16 (DFV16, Zenodo 22783222, CC BY 4.0) for Tastoria M1.

Downloads ``DFV16_v1.0_YOLO_Detection.zip`` (~7.805 GB) into ``/dev/shm`` (or
``TASTORIA_STAGE_DIR``), verifies its MD5 checksum, streams image/label pairs
directly from the zip archive without extracting the full 7.8 GB payload to disk,
maps ``Tomato -> ca_chua``, ``Potato -> khoai_tay``, ``Lemon -> chanh`` while
preserving the 13 raw produce classes in ``ood_labels``, resizes images to
``<= 1024 px`` RGB JPEGs (``quality=88``), writes standardized ``m1_v1``
``annotations.json``, and deletes all staged temp files in ``finally:``.

Run: ``python -m tastoria_ml.cv.dfv16``
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path

import yaml
from PIL import Image

from tastoria_ml.cv.classes import REPO

ZENODO_URL = "https://zenodo.org/api/records/22783222/files/DFV16_v1.0_YOLO_Detection.zip/content"
DATASET_URL = "https://zenodo.org/records/22783222"
EXPECTED_MD5 = "9469e193fa705cb465bbb1c3efa638b4"
LICENSE = "CC BY 4.0"
SOURCE_NAME = "dfv16"
MAX_SIDE = 1024
JPEG_QUALITY = 88
MIN_ROOT_FREE_BYTES = 18 * (1024**3)
MIN_STAGE_FREE_BYTES = 10 * (1024**3)
USER_AGENT = "tastoria-ml/1.0"

ROOT = REPO / "data" / "raw" / "images" / "dfv16"
STAGE = Path(os.environ.get("TASTORIA_STAGE_DIR", "/dev/shm/tastoria_stage_m1/dfv16"))

CLASS_MAP: dict[str, str] = {
    "Tomato": "ca_chua",
    "Potato": "khoai_tay",
    "Lemon": "chanh",
}

OOD_CLASSES: tuple[str, ...] = (
    "Apple Red",
    "Apple Yellow",
    "Avocado",
    "Banana",
    "Corn",
    "Cucumber",
    "Eggplant",
    "Kiwi",
    "Mango",
    "Orange",
    "Pear",
    "Pepper Green",
    "Pomegranate",
)

SPLIT_MAP: dict[str, str] = {
    "train": "train",
    "val": "val",
    "valid": "val",
    "test": "heldout",
}


def _check_disk_guard(root_path: Path = ROOT, stage_path: Path = STAGE) -> None:
    root_probe = root_path if root_path.exists() else root_path.parent
    while not root_probe.exists() and root_probe != root_probe.parent:
        root_probe = root_probe.parent
    root_free = shutil.disk_usage(root_probe).free
    if root_free <= MIN_ROOT_FREE_BYTES:
        raise RuntimeError(
            f"Root disk free {root_free / (1024**3):.2f} GiB <= 18 GiB floor; aborting DFV16 ingest"
        )
    stage_probe = stage_path if stage_path.exists() else stage_path.parent
    while not stage_probe.exists() and stage_probe != stage_probe.parent:
        stage_probe = stage_probe.parent
    stage_free = shutil.disk_usage(stage_probe).free
    if stage_free < MIN_STAGE_FREE_BYTES:
        raise RuntimeError(
            f"Stage dir {stage_probe} free {stage_free / (1024**3):.2f} GiB < 10 GiB needed for DFV16 zip"
        )


def _download_zip(url: str, dst: Path, *, expected_md5: str | None = EXPECTED_MD5) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and dst.stat().st_size > 0:
        if not expected_md5 or _md5_file(dst) == expected_md5:
            return dst
        dst.unlink()

    part = dst.with_suffix(".part")
    existing = part.stat().st_size if part.exists() else 0
    for attempt in range(8):
        headers = {"User-Agent": USER_AGENT}
        if existing > 0:
            headers["Range"] = f"bytes={existing}-"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                status = getattr(resp, "status", 200)
                mode = "ab" if (existing > 0 and status == 206) else "wb"
                if mode == "wb":
                    existing = 0
                with part.open(mode) as f:
                    while True:
                        chunk = resp.read(1 << 20)
                        if not chunk:
                            break
                        f.write(chunk)
                        existing += len(chunk)
            break
        except Exception as exc:
            if attempt == 7:
                raise RuntimeError(f"Failed downloading DFV16 after {attempt + 1} attempts: {exc}") from exc
            existing = part.stat().st_size if part.exists() else 0

    if expected_md5:
        got = _md5_file(part)
        if got != expected_md5:
            part.unlink(missing_ok=True)
            raise RuntimeError(f"DFV16 MD5 mismatch: expected {expected_md5}, got {got}")
    part.rename(dst)
    return dst


def _md5_file(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        while True:
            buf = f.read(4 << 20)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def _parse_yaml_names(raw: str) -> list[str]:
    d = yaml.safe_load(raw)
    raw_names = d["names"]
    if isinstance(raw_names, dict):
        return [raw_names[i] for i in sorted(raw_names)]
    return list(raw_names)


def ingest_zip(zip_path: Path, *, root: Path = ROOT, max_side: int = MAX_SIDE, quality: int = JPEG_QUALITY) -> dict:
    """Parse ``zip_path``, resize images <= ``max_side``, and write ``root/annotations.json``."""
    img_dir = root / "images"
    if root.exists():
        shutil.rmtree(root)
    img_dir.mkdir(parents=True, exist_ok=True)

    out_records: list[dict] = []
    cls_counts: Counter = Counter()
    ood_counts: Counter = Counter()
    split_counts: Counter = Counter()
    neg_count = 0
    non_unit_exif = 0

    with zipfile.ZipFile(zip_path) as zf:
        names_in_zip = zf.namelist()
        yaml_candidates = [n for n in names_in_zip if n.endswith("data.yaml")]
        if not yaml_candidates:
            raise ValueError(f"No data.yaml found inside {zip_path}")
        class_names = _parse_yaml_names(zf.read(yaml_candidates[0]).decode("utf-8"))

        # Map label paths by (split_key, stem)
        label_by_key: dict[tuple[str, str], str] = {}
        img_entries: list[tuple[str, str, str]] = []
        for entry in names_in_zip:
            parts = Path(entry).parts
            if len(parts) < 3:
                continue
            ext = Path(entry).suffix.lower()
            parent = parts[-2].lower()
            raw_split = parts[-3].lower()
            stem = Path(entry).stem
            if parent == "labels" and ext == ".txt":
                label_by_key[(raw_split, stem)] = entry
            elif parent == "images" and ext in {".jpg", ".jpeg", ".png", ".webp"}:
                if raw_split in SPLIT_MAP:
                    img_entries.append((raw_split, stem, entry))

        img_entries.sort(key=lambda t: (t[0], t[1]))
        ood_set = set(OOD_CLASSES)

        for raw_split, stem, img_entry in img_entries:
            split = SPLIT_MAP[raw_split]
            lbl_entry = label_by_key.get((raw_split, stem))
            if not lbl_entry:
                continue

            lbl_lines = zf.read(lbl_entry).decode("utf-8", errors="replace").splitlines()
            raw_boxes: list[dict] = []
            ood_found: set[str] = set()
            for line in lbl_lines:
                toks = line.split()
                if len(toks) < 5:
                    continue
                ci = int(float(toks[0]))
                if ci < 0 or ci >= len(class_names):
                    continue
                cname = class_names[ci]
                if len(toks) == 5:
                    xc, yc, bw, bh = (float(v) for v in toks[1:5])
                    x, y, w, h = xc - bw / 2.0, yc - bh / 2.0, bw, bh
                else:
                    coords = [float(v) for v in toks[1:]]
                    xs, ys = coords[0::2], coords[1::2]
                    if not xs or not ys:
                        continue
                    x, y = min(xs), min(ys)
                    w, h = max(xs) - x, max(ys) - y

                if cname in CLASS_MAP:
                    if w > 0.002 and h > 0.002:
                        raw_boxes.append({"cat": cname, "cls": CLASS_MAP[cname], "bbox": [x, y, w, h]})
                elif cname in ood_set:
                    ood_found.add(cname)

            if not raw_boxes and not ood_found:
                continue

            img_bytes = zf.read(img_entry)
            with Image.open(io.BytesIO(img_bytes)) as im_raw:
                try:
                    orient = int(im_raw.getexif().get(274, 1) or 1)
                except Exception:
                    orient = 1
                if orient != 1:
                    non_unit_exif += 1
                im = im_raw.convert("RGB")
                w0, h0 = im.size
                scale = min(1.0, max_side / max(w0, h0))
                if scale < 1.0:
                    im = im.resize((max(1, round(w0 * scale)), max(1, round(h0 * scale))), Image.LANCZOS)
                w_new, h_new = im.size
                safe_id = hashlib.sha1(f"{raw_split}:{stem}".encode("utf-8")).hexdigest()[:12]
                fn = f"{safe_id}.jpg"
                im.save(img_dir / fn, "JPEG", quality=quality)

            has_raw_mapped_box = bool(raw_boxes)
            boxes_px: list[dict] = []
            for b in raw_boxes:
                bx, by, bw, bh = b["bbox"]
                px, py, pw, ph = bx * w_new, by * h_new, bw * w_new, bh * h_new
                if pw >= 2.0 and ph >= 2.0:
                    boxes_px.append({"cat": b["cat"], "cls": b["cls"], "bbox": [px, py, pw, ph]})
                    cls_counts[b["cls"]] += 1

            if has_raw_mapped_box and not boxes_px:
                (img_dir / fn).unlink(missing_ok=True)
                continue

            is_neg = not boxes_px
            ood_labels = sorted(ood_found)
            if is_neg and not ood_labels:
                (img_dir / fn).unlink(missing_ok=True)
                continue

            if is_neg:
                neg_count += 1
            for ol in ood_labels:
                ood_counts[ol] += 1
            split_counts[split] += 1

            out_records.append({
                "id": f"{SOURCE_NAME}/{safe_id}",
                "stem": stem,
                "source_name": SOURCE_NAME,
                "split": split,
                "split_hint": split,
                "file": f"images/{fn}",
                "width": w_new,
                "height": h_new,
                "license": LICENSE,
                "is_commercial_ok": True,
                "url": DATASET_URL,
                "is_neg": is_neg,
                "ood_labels": ood_labels,
                "boxes": boxes_px,
            })

    categories = sorted(cls_counts.keys()) + (["__neg__"] if neg_count else [])
    manifest = {
        "schema_version": "m1_v1",
        "source": SOURCE_NAME,
        "source_name": SOURCE_NAME,
        "license": LICENSE,
        "is_commercial_ok": True,
        "url": DATASET_URL,
        "categories": categories,
        "images": len(out_records),
        "neg_images": neg_count,
        "splits": dict(split_counts),
        "boxes_per_class": dict(sorted(cls_counts.items())),
        "ood_images_per_label": dict(sorted(ood_counts.items())),
        "non_unit_exif_count": non_unit_exif,
        "records": out_records,
    }
    (root / "annotations.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return {k: v for k, v in manifest.items() if k != "records"}


def ingest(*, force: bool = False) -> dict:
    ann_path = ROOT / "annotations.json"
    if ann_path.exists() and not force:
        d = json.loads(ann_path.read_text(encoding="utf-8"))
        return {k: v for k, v in d.items() if k != "records"}

    _check_disk_guard(ROOT, STAGE)
    STAGE.mkdir(parents=True, exist_ok=True)
    zip_path = STAGE / "DFV16_v1.0_YOLO_Detection.zip"
    try:
        print(f"[dfv16] downloading {ZENODO_URL} -> {zip_path}...", flush=True)
        _download_zip(ZENODO_URL, zip_path, expected_md5=EXPECTED_MD5)
        print("[dfv16] ingesting zip -> resized JPEGs & annotations.json...", flush=True)
        summary = ingest_zip(zip_path, root=ROOT)
        print(
            f"[dfv16] done: {summary['images']} imgs (neg={summary['neg_images']}), splits={summary['splits']}",
            flush=True,
        )
        return summary
    finally:
        shutil.rmtree(STAGE, ignore_errors=True)


def records() -> list[dict]:
    """Return standardized m1_v1 records for DFV16."""
    ann_path = ROOT / "annotations.json"
    if not ann_path.exists():
        return []
    d = json.loads(ann_path.read_text(encoding="utf-8"))
    out: list[dict] = []
    for r in d["records"]:
        p = ROOT / r["file"]
        if p.exists():
            out.append({**r, "source": SOURCE_NAME, "path": p})
    return out


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    print(json.dumps(ingest(force=args.force), indent=2, ensure_ascii=False))
