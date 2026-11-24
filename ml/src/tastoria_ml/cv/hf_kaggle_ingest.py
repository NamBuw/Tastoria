"""Standardized HuggingFace / Kaggle / GitHub bbox ingest adapter & pure-PIL contact-sheet renderer.

Provides:
  - ``HFKaggleSpec`` dataclass + ``vision_classes.yaml`` validation
  - ``parse_voc_dir``, ``parse_coco_json``, ``parse_hf_parquet`` emitting ``m1_v1`` manifests
  - ``records(commercial_only=...)`` for M2 ``build_yolo_v4.py``
  - ``render_contact_sheet(...)`` pure-PIL visual audit sheet generator (used across F4 & F5)
  - ``credential_status()`` (boolean env/file presence check only; never reads ``deploy/.env``)

Note: Unlicensed datasets (e.g., ``hmrankit/refrigerator-contents``) and unboxed
classification-only datasets are intentionally NOT registered for bbox ingestion.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import random
import shutil
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from PIL import Image, ImageDraw, ImageFont, ImageOps

from tastoria_ml.cv.classes import REPO, VISION_CLASSES

ROOT = REPO / "data" / "raw" / "images" / "hf_kaggle"
STAGE = Path(os.environ.get("TASTORIA_STAGE_DIR", "/dev/shm/tastoria_stage_m1/hf_kaggle"))
MAX_SIDE = 1024
JPEG_QUALITY = 88
MIN_ROOT_FREE_BYTES = 18 * (1024**3)


@dataclass(frozen=True)
class HFKaggleSpec:
    source_name: str
    platform: Literal["hf", "github", "zenodo", "kaggle"]
    repo_id: str
    license: str
    is_commercial_ok: bool
    url: str
    class_map: dict[str, str]
    ood_neg_labels: tuple[str, ...] = ()
    exclude_co_labels: tuple[str, ...] = ()
    split_policy: Literal["hash_train_val", "preserve_heldout_only"] = "hash_train_val"
    max_images: int | None = None


# Intentionally empty until verified, licensed, boxed external HF/Kaggle datasets are vetted.
REGISTRY: tuple[HFKaggleSpec, ...] = ()


def valid_tastoria_classes() -> set[str]:
    raw = yaml.safe_load(VISION_CLASSES.read_text(encoding="utf-8"))
    rows = list(raw["classes"]) + list(raw.get("proposed_classes") or [])
    return {c["id"] for c in rows}


def validate_spec(spec: HFKaggleSpec) -> None:
    valid = valid_tastoria_classes() | {"__neg__"}
    for orig, cls_id in spec.class_map.items():
        if cls_id not in valid:
            raise ValueError(f"{spec.source_name}: label {orig!r} maps to unknown class {cls_id!r}")


def check_disk_guard(root_path: Path = ROOT) -> None:
    probe = root_path if root_path.exists() else root_path.parent
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    free = shutil.disk_usage(probe).free
    if free <= MIN_ROOT_FREE_BYTES:
        raise RuntimeError(f"Root disk free {free / (1024**3):.2f} GiB <= 18 GiB floor")


def credential_status() -> dict[str, bool]:
    """Return boolean availability of external dataset credentials without reading deploy/.env."""
    rf_present = bool(os.environ.get("ROBOFLOW_API_KEY", "").strip())
    kg_paths = (
        Path.home() / ".kaggle" / "kaggle.json",
        Path.home() / ".config" / "kaggle" / "kaggle.json",
    )
    kg_present = any(p.exists() and p.stat().st_size > 0 for p in kg_paths)
    return {"roboflow_api_key": rf_present, "kaggle_json": kg_present}


def _assign_split(spec: HFKaggleSpec, stem: str) -> str:
    if spec.split_policy == "preserve_heldout_only":
        return "heldout"
    h = int(hashlib.sha1(f"{spec.source_name}:{stem}".encode("utf-8")).hexdigest(), 16) % 20
    return "val" if h < 3 else "train"


def _save_resized_rgb(
    im_raw: Image.Image,
    dst: Path,
    *,
    expected_wh: tuple[int, int] | None = None,
    max_side: int = MAX_SIDE,
    quality: int = JPEG_QUALITY,
) -> tuple[int, int, float, float]:
    """Orient (if needed), resize <= max_side, save JPEG, and return (w_new, h_new, sx, sy)."""
    try:
        raw_orient = int(im_raw.getexif().get(274, 1) or 1)
    except Exception:
        raw_orient = 1
    orient = raw_orient if raw_orient in range(1, 9) else 1

    if expected_wh is None:
        im = ImageOps.exif_transpose(im_raw).convert("RGB") if orient != 1 else im_raw.convert("RGB")
    elif im_raw.size != expected_wh and (im_raw.height, im_raw.width) == expected_wh:
        im = ImageOps.exif_transpose(im_raw).convert("RGB")
    elif im_raw.size == expected_wh and (
        orient in (2, 3, 4) or (im_raw.width == im_raw.height and orient in (5, 6, 7, 8))
    ):
        im = ImageOps.exif_transpose(im_raw).convert("RGB")
    else:
        im = im_raw.convert("RGB")

    w0, h0 = im.size
    scale = min(1.0, max_side / max(w0, h0))
    if scale < 1.0:
        im = im.resize((max(1, round(w0 * scale)), max(1, round(h0 * scale))), Image.LANCZOS)
    w_new, h_new = im.size
    dst.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst, "JPEG", quality=quality)
    base_w, base_h = expected_wh if expected_wh else (w0, h0)
    return w_new, h_new, w_new / float(base_w), h_new / float(base_h)


def _finalize_manifest(spec: HFKaggleSpec, out_root: Path, out_records: list[dict]) -> dict:
    cls_counts: Counter = Counter()
    split_counts: Counter = Counter()
    ood_counts: Counter = Counter()
    neg_count = 0
    for r in out_records:
        split_counts[r["split_hint"]] += 1
        if r["is_neg"]:
            neg_count += 1
        for b in r["boxes"]:
            cls_counts[b["cls"]] += 1
        for ol in r.get("ood_labels", []):
            ood_counts[ol] += 1

    categories = sorted(cls_counts.keys()) + (["__neg__"] if neg_count else [])
    manifest = {
        "schema_version": "m1_v1",
        "source": spec.source_name,
        "source_name": spec.source_name,
        "platform": spec.platform,
        "repo_id": spec.repo_id,
        "license": spec.license,
        "is_commercial_ok": spec.is_commercial_ok,
        "url": spec.url,
        "categories": categories,
        "images": len(out_records),
        "neg_images": neg_count,
        "splits": dict(split_counts),
        "boxes_per_class": dict(sorted(cls_counts.items())),
        "ood_images_per_label": dict(sorted(ood_counts.items())),
        "records": out_records,
    }
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "annotations.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return {k: v for k, v in manifest.items() if k != "records"}


def parse_voc_dir(root: Path, spec: HFKaggleSpec, *, out_root: Path | None = None) -> dict:
    """Ingest Pascal VOC XML + images directory into ``m1_v1`` format."""
    validate_spec(spec)
    dst_root = out_root or (ROOT / spec.source_name)
    check_disk_guard(dst_root)
    if dst_root.exists():
        shutil.rmtree(dst_root)
    img_dir = dst_root / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

    xml_files = sorted(root.rglob("*.xml"))
    if spec.max_images is not None:
        xml_files = xml_files[: spec.max_images]

    excl = set(spec.exclude_co_labels)
    ood_set = set(spec.ood_neg_labels)
    out_records: list[dict] = []

    for xml_path in xml_files:
        tree = ET.parse(xml_path).getroot()
        fn_node = tree.find("filename")
        cand_imgs = []
        if fn_node is not None and fn_node.text:
            cand_imgs.append(xml_path.parent / fn_node.text)
            cand_imgs.append(root / "images" / fn_node.text)
            cand_imgs.append(root / fn_node.text)
        for ext in (".jpg", ".jpeg", ".png", ".webp"):
            cand_imgs.append(xml_path.with_suffix(ext))
        img_path = next((p for p in cand_imgs if p.exists() and p.is_file()), None)
        if img_path is None:
            continue

        sz = tree.find("size")
        xml_w = int(float(sz.find("width").text)) if sz is not None and sz.find("width") is not None else None
        xml_h = int(float(sz.find("height").text)) if sz is not None and sz.find("height") is not None else None

        raw_boxes: list[dict] = []
        ood_found: set[str] = set()
        excluded = False
        for obj in tree.findall("object"):
            name_el = obj.find("name")
            if name_el is None or not name_el.text:
                continue
            cname = name_el.text.strip()
            if cname in excl:
                excluded = True
                break
            if cname in spec.class_map:
                bb = obj.find("bndbox")
                if bb is None:
                    continue
                xmin = float(bb.find("xmin").text)
                ymin = float(bb.find("ymin").text)
                xmax = float(bb.find("xmax").text)
                ymax = float(bb.find("ymax").text)
                if xmax > xmin and ymax > ymin:
                    raw_boxes.append({
                        "cat": cname,
                        "cls": spec.class_map[cname],
                        "bbox": [xmin, ymin, xmax - xmin, ymax - ymin],
                    })
            elif cname in ood_set:
                ood_found.add(cname)

        if excluded or (not raw_boxes and not ood_found):
            continue

        stem = xml_path.stem
        safe_id = hashlib.sha1(f"{spec.source_name}:{stem}".encode("utf-8")).hexdigest()[:12]
        dst_fn = f"{safe_id}.jpg"
        with Image.open(img_path) as im_raw:
            exp_wh = (xml_w, xml_h) if (xml_w and xml_h) else None
            w_new, h_new, sx, sy = _save_resized_rgb(im_raw, img_dir / dst_fn, expected_wh=exp_wh)

        boxes_px = []
        for b in raw_boxes:
            if b["cls"] == "__neg__":
                ood_found.add(b["cat"])
                continue
            x, y, w, h = b["bbox"]
            px, py, pw, ph = x * sx, y * sy, w * sx, h * sy
            if pw >= 2.0 and ph >= 2.0:
                boxes_px.append({"cat": b["cat"], "cls": b["cls"], "bbox": [px, py, pw, ph]})

        is_neg = not boxes_px
        ood_labels = sorted(ood_found)
        if is_neg and not ood_labels:
            (img_dir / dst_fn).unlink(missing_ok=True)
            continue

        split = _assign_split(spec, stem)
        out_records.append({
            "id": f"{spec.source_name}/{safe_id}",
            "stem": stem,
            "source_name": spec.source_name,
            "split": split,
            "split_hint": split,
            "file": f"images/{dst_fn}",
            "width": w_new,
            "height": h_new,
            "license": spec.license,
            "is_commercial_ok": spec.is_commercial_ok,
            "url": spec.url,
            "is_neg": is_neg,
            "ood_labels": ood_labels,
            "boxes": boxes_px,
        })

    return _finalize_manifest(spec, dst_root, out_records)


def parse_coco_json(
    json_path: Path,
    img_dir: Path,
    spec: HFKaggleSpec,
    *,
    out_root: Path | None = None,
) -> dict:
    """Ingest COCO JSON + image directory into ``m1_v1`` format."""
    validate_spec(spec)
    dst_root = out_root or (ROOT / spec.source_name)
    check_disk_guard(dst_root)
    if dst_root.exists():
        shutil.rmtree(dst_root)
    out_img_dir = dst_root / "images"
    out_img_dir.mkdir(parents=True, exist_ok=True)

    d = json.loads(json_path.read_text(encoding="utf-8"))
    cats = {c["id"]: c["name"] for c in d.get("categories", [])}
    excl = set(spec.exclude_co_labels)
    ood_set = set(spec.ood_neg_labels)

    by_img_boxes: dict[int, list[dict]] = defaultdict(list)
    by_img_ood: dict[int, set[str]] = defaultdict(set)
    excluded_imgs: set[int] = set()

    for ann in d.get("annotations", []):
        iid = ann["image_id"]
        cname = cats.get(ann["category_id"], "")
        if cname in excl:
            excluded_imgs.add(iid)
            continue
        if cname in spec.class_map:
            bb = ann.get("bbox")
            if bb and len(bb) == 4:
                by_img_boxes[iid].append({"cat": cname, "cls": spec.class_map[cname], "bbox": [float(v) for v in bb]})
        elif cname in ood_set:
            by_img_ood[iid].add(cname)

    images = d.get("images", [])
    if spec.max_images is not None:
        images = images[: spec.max_images]

    out_records: list[dict] = []
    for im_meta in images:
        iid = im_meta["id"]
        if iid in excluded_imgs:
            continue
        raw_boxes = by_img_boxes.get(iid, [])
        ood_found = set(by_img_ood.get(iid, set()))
        if not raw_boxes and not ood_found:
            continue
        src_img = img_dir / im_meta["file_name"]
        if not src_img.exists():
            continue

        stem = Path(im_meta["file_name"]).stem
        safe_id = hashlib.sha1(f"{spec.source_name}:{stem}".encode("utf-8")).hexdigest()[:12]
        dst_fn = f"{safe_id}.jpg"
        exp_wh = (int(im_meta["width"]), int(im_meta["height"])) if im_meta.get("width") and im_meta.get("height") else None
        with Image.open(src_img) as im_raw:
            w_new, h_new, sx, sy = _save_resized_rgb(im_raw, out_img_dir / dst_fn, expected_wh=exp_wh)

        boxes_px = []
        for b in raw_boxes:
            if b["cls"] == "__neg__":
                ood_found.add(b["cat"])
                continue
            x, y, w, h = b["bbox"]
            px, py, pw, ph = x * sx, y * sy, w * sx, h * sy
            if pw >= 2.0 and ph >= 2.0:
                boxes_px.append({"cat": b["cat"], "cls": b["cls"], "bbox": [px, py, pw, ph]})

        is_neg = not boxes_px
        ood_labels = sorted(ood_found)
        if is_neg and not ood_labels:
            (out_img_dir / dst_fn).unlink(missing_ok=True)
            continue

        split = _assign_split(spec, stem)
        out_records.append({
            "id": f"{spec.source_name}/{safe_id}",
            "stem": stem,
            "source_name": spec.source_name,
            "split": split,
            "split_hint": split,
            "file": f"images/{dst_fn}",
            "width": w_new,
            "height": h_new,
            "license": spec.license,
            "is_commercial_ok": spec.is_commercial_ok,
            "url": spec.url,
            "is_neg": is_neg,
            "ood_labels": ood_labels,
            "boxes": boxes_px,
        })

    return _finalize_manifest(spec, dst_root, out_records)


def parse_hf_parquet(
    parquet_paths: list[Path],
    spec: HFKaggleSpec,
    *,
    out_root: Path | None = None,
    image_col: str = "image",
    objects_col: str = "objects",
    id_col: str = "image_id",
) -> dict:
    """Stream HF Parquet shards row-group-by-row-group into ``m1_v1`` format."""
    import pyarrow.parquet as pq  # optional dependency

    validate_spec(spec)
    dst_root = out_root or (ROOT / spec.source_name)
    check_disk_guard(dst_root)
    if dst_root.exists():
        shutil.rmtree(dst_root)
    out_img_dir = dst_root / "images"
    out_img_dir.mkdir(parents=True, exist_ok=True)

    excl = set(spec.exclude_co_labels)
    ood_set = set(spec.ood_neg_labels)
    out_records: list[dict] = []

    for pq_path in parquet_paths:
        pf = pq.ParquetFile(pq_path)
        for rg_idx in range(pf.num_row_groups):
            tbl = pf.read_row_group(rg_idx)
            for row in tbl.to_pylist():
                if spec.max_images is not None and len(out_records) >= spec.max_images:
                    break
                objs = row.get(objects_col) or {}
                cats = objs.get("category") or objs.get("categories") or []
                bboxes = objs.get("bbox") or []
                if any(str(c) in excl for c in cats):
                    continue
                raw_boxes = []
                ood_found: set[str] = set()
                for c, bb in zip(cats, bboxes):
                    cname = str(c)
                    if cname in spec.class_map:
                        raw_boxes.append({"cat": cname, "cls": spec.class_map[cname], "bbox": [float(v) for v in bb]})
                    elif cname in ood_set:
                        ood_found.add(cname)
                if not raw_boxes and not ood_found:
                    continue

                img_val = row.get(image_col)
                img_bytes = img_val.get("bytes") if isinstance(img_val, dict) else img_val
                if not img_bytes:
                    continue
                stem = str(row.get(id_col) or hashlib.sha1(img_bytes).hexdigest()[:12])
                safe_id = hashlib.sha1(f"{spec.source_name}:{stem}".encode("utf-8")).hexdigest()[:12]
                dst_fn = f"{safe_id}.jpg"
                with Image.open(io.BytesIO(img_bytes)) as im_raw:
                    w_new, h_new, sx, sy = _save_resized_rgb(im_raw, out_img_dir / dst_fn, expected_wh=None)

                boxes_px = []
                for b in raw_boxes:
                    if b["cls"] == "__neg__":
                        ood_found.add(b["cat"])
                        continue
                    x, y, w, h = b["bbox"]
                    px, py, pw, ph = x * sx, y * sy, w * sx, h * sy
                    if pw >= 2.0 and ph >= 2.0:
                        boxes_px.append({"cat": b["cat"], "cls": b["cls"], "bbox": [px, py, pw, ph]})

                is_neg = not boxes_px
                ood_labels = sorted(ood_found)
                if is_neg and not ood_labels:
                    (out_img_dir / dst_fn).unlink(missing_ok=True)
                    continue
                split = _assign_split(spec, stem)
                out_records.append({
                    "id": f"{spec.source_name}/{safe_id}",
                    "stem": stem,
                    "source_name": spec.source_name,
                    "split": split,
                    "split_hint": split,
                    "file": f"images/{dst_fn}",
                    "width": w_new,
                    "height": h_new,
                    "license": spec.license,
                    "is_commercial_ok": spec.is_commercial_ok,
                    "url": spec.url,
                    "is_neg": is_neg,
                    "ood_labels": ood_labels,
                    "boxes": boxes_px,
                })

    return _finalize_manifest(spec, dst_root, out_records)


def records(*, commercial_only: bool = False) -> list[dict]:
    """Return standardized ``m1_v1`` records across ingested ``data/raw/images/hf_kaggle/*`` sources."""
    out: list[dict] = []
    if not ROOT.exists():
        return out
    for ann_path in sorted(ROOT.glob("*/annotations.json")):
        src_root = ann_path.parent
        d = json.loads(ann_path.read_text(encoding="utf-8"))
        for r in d["records"]:
            if commercial_only and not r.get("is_commercial_ok", False):
                continue
            p = src_root / r["file"]
            if p.exists():
                out.append({**r, "source": r.get("source_name", d["source_name"]), "path": p})
    return out


def render_contact_sheet(
    recs: list[dict],
    out_path: Path,
    *,
    title: str,
    cols: int = 4,
    rows: int = 4,
    tile_size: int = 384,
    seed: int = 0,
    target_cls: str | None = None,
    show_neg: bool = False,
) -> Path:
    """Pure-PIL contact-sheet renderer with scaled bbox overlays and license/class labels."""
    rng = random.Random(seed)
    filtered: list[dict] = []
    for r in recs:
        p = Path(r["path"]) if "path" in r else None
        if p is None or not p.exists():
            continue
        boxes = r.get("boxes") or []
        if target_cls == "__neg__" or show_neg:
            if not boxes:
                filtered.append(r)
        elif target_cls is not None:
            if any(b.get("cls") == target_cls or b.get("cat") == target_cls for b in boxes):
                filtered.append(r)
        else:
            filtered.append(r)

    max_tiles = cols * rows
    if target_cls is None and not show_neg and filtered:
        # Stratified round-robin sampling by (source_name, primary class)
        buckets: dict[str, list[dict]] = defaultdict(list)
        for r in filtered:
            boxes = r.get("boxes") or []
            key_cls = boxes[0]["cls"] if boxes else "__neg__"
            key_src = r.get("source_name") or r.get("source") or "src"
            buckets[f"{key_src}|{key_cls}"].append(r)
        for b in buckets.values():
            rng.shuffle(b)
        keys = sorted(buckets.keys())
        rng.shuffle(keys)
        chosen: list[dict] = []
        while len(chosen) < max_tiles:
            progressed = False
            for k in keys:
                if buckets[k]:
                    chosen.append(buckets[k].pop())
                    progressed = True
                    if len(chosen) >= max_tiles:
                        break
            if not progressed:
                break
    else:
        pool = list(filtered)
        rng.shuffle(pool)
        chosen = pool[:max_tiles]

    banner_h = 38
    header_h = 26
    sheet_w = cols * tile_size
    actual_rows = max(1, (len(chosen) + cols - 1) // cols) if chosen else 1
    sheet_h = banner_h + actual_rows * tile_size
    canvas = Image.new("RGB", (sheet_w, sheet_h), (18, 18, 22))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    draw.rectangle([0, 0, sheet_w, banner_h], fill=(32, 36, 46))
    draw.text((10, 12), f"{title}  ({len(chosen)}/{len(filtered)} matching, seed={seed})", fill=(245, 245, 245), font=font)

    body_h = tile_size - header_h
    for idx, r in enumerate(chosen):
        row_i, col_i = divmod(idx, cols)
        tx = col_i * tile_size
        ty = banner_h + row_i * tile_size
        draw.rectangle([tx, ty, tx + tile_size - 1, ty + header_h - 1], fill=(42, 46, 58))

        try:
            with Image.open(r["path"]) as im_raw:
                im = im_raw.convert("RGB")
        except Exception:
            continue

        iw, ih = im.size
        scale = min(tile_size / float(iw), body_h / float(ih))
        nw, nh = max(1, round(iw * scale)), max(1, round(ih * scale))
        im_res = im.resize((nw, nh), Image.LANCZOS)
        ox = tx + (tile_size - nw) // 2
        oy = ty + header_h + (body_h - nh) // 2
        canvas.paste(im_res, (ox, oy))

        boxes = r.get("boxes") or []
        if not boxes:
            draw.rectangle([tx + 1, ty + header_h, tx + tile_size - 2, ty + tile_size - 2], outline=(255, 210, 40), width=3)
        else:
            for b in boxes:
                bx, by, bw, bh = b["bbox"]
                # If record width/height differs from opened file, rescale
                rw = float(r.get("width") or iw)
                rh = float(r.get("height") or ih)
                sx_r = iw / rw if rw else 1.0
                sy_r = ih / rh if rh else 1.0
                x0 = ox + bx * sx_r * scale
                y0 = oy + by * sy_r * scale
                x1 = x0 + bw * sx_r * scale
                y1 = y0 + bh * sy_r * scale
                is_target = (target_cls is None) or (b.get("cls") == target_cls) or (b.get("cat") == target_cls)
                color = (255, 65, 65) if is_target else (0, 225, 255)
                draw.rectangle([x0, y0, x1, y1], outline=color, width=2)
                lbl_txt = b.get("cls") or b.get("cat") or ""
                if lbl_txt:
                    draw.rectangle([x0, max(ty + header_h, y0 - 13), min(tx + tile_size - 2, x0 + len(lbl_txt) * 6 + 6), y0], fill=color)
                    draw.text((x0 + 2, max(ty + header_h, y0 - 12)), lbl_txt, fill=(0, 0, 0), font=font)

        src = r.get("source_name") or r.get("source") or "?"
        comm = "Comm" if r.get("is_commercial_ok") else "NC"
        if boxes:
            cls_tag = ",".join(sorted({str(b.get("cls") or b.get("cat")) for b in boxes}))[:18]
        else:
            cls_tag = "OOD:" + ",".join(r.get("ood_labels") or ["__neg__"])[:16]
        id_tail = str(r.get("id", r.get("stem", "")))[-10:]
        hdr = f"{src[:10]}|{cls_tag}|{comm}|{id_tail}"
        draw.text((tx + 5, ty + 7), hdr[:56], fill=(235, 240, 250), font=font)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, "JPEG", quality=88)
    return out_path
