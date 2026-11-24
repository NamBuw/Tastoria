"""Build the cleaned, expanded 37-class YOLO dataset under data/processed/cv/yolo_v4/ (F7).

Combines clean yolo_v3 sources with M1 ingests (dfv16, openimages_v7/ood,
lvis_v1/images_neg_clean, Track-C-filtered v3det, Track-C-filtered rf_*),
purges all audited defects (rf_tofu_oo, single-leaf rau_muong, rf_robo1 0-box
hard negatives, OpenImages countable group_of boxes, whole-basket countable boxes,
tiny degenerate boxes on v3det/rf_*, cooked/vine/infographic Track C rejects),
deduplicates across splits using 64-bit l256 DCT pHash (Hamming <= 4 in order
test -> heldout -> val -> train), and materializes hardlinked Ultralytics YAML,
manifest_v4.csv, dataset_stats_v4.json, and cleaning_manifest.json.

Run: ``python -m tastoria_ml.cv.build_yolo_v4``
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from tastoria_ml.cv import build_yolo as v1
from tastoria_ml.cv import build_yolo_v2 as v2
from tastoria_ml.cv import build_yolo_v3 as v3
from tastoria_ml.cv import dfv16, hf_kaggle_ingest, lvis, openimages, roboflow_ingest, rpc, v3det
from tastoria_ml.cv.phash import dedupe, hamming
from tastoria_ml.cv.track_c_filter import (
    CLEANING_MANIFEST_PATH,
    DECISIONS_PATH,
    EXPECTED_COUNTABLE_19,
    stage1_filter_record,
)
from tastoria_ml.cv.yolo_format import Box, from_corners_norm, write_label

OUT = v1.OUT
YOLO = OUT / "yolo_v4"
SPLITS = ("test", "heldout", "val", "train")

PRIORITY_HARD_NEG_SOURCES: frozenset[str] = frozenset(
    {"dfv16", "openimages_v7_ood", "lvis_v1_neg", "mendeley_bd"}
)


@dataclass
class V4Record:
    split: str
    source: str
    original_id: str
    path: Path
    license: str
    author: str = ""
    url: str = ""
    group: str = ""
    boxes: list[Box] = field(default_factory=list)
    is_hard_neg: bool = False
    license_flag: str = "ok"
    track_c_key: str = ""


def _link_or_copy(src: Path, dst: Path) -> None:
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _box_dict_to_yolo(
    b: dict[str, Any], full: dict[str, int], img_w: int, img_h: int
) -> Box | None:
    cid = str(b.get("cls") or "")
    if cid not in full:
        return None
    cls_idx = full[cid]
    group_of = bool(b.get("group_of", False))
    if "bbox" in b:
        bx, by, bw, bh = (float(v) for v in b["bbox"])
        if b.get("normalized"):
            return from_corners_norm(
                cls_idx,
                bx,
                by,
                bx + bw,
                by + bh,
                group_of=group_of,
            )
        if img_w <= 0 or img_h <= 0:
            return None
        return from_corners_norm(
            cls_idx,
            bx / float(img_w),
            by / float(img_h),
            (bx + bw) / float(img_w),
            (by + bh) / float(img_h),
            group_of=group_of,
        )
    xc = float(b.get("xc", 0.0))
    yc = float(b.get("yc", 0.0))
    w = float(b.get("w", 0.0))
    h = float(b.get("h", 0.0))
    return from_corners_norm(
        cls_idx,
        xc - w / 2.0,
        yc - h / 2.0,
        xc + w / 2.0,
        yc + h / 2.0,
        group_of=group_of,
    )


def _load_decisions(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _collect_raw_candidates(
    full: dict[str, int], order: list[str]
) -> list[dict[str, Any]]:
    """Gather all candidate records in standardized dict format for filtering & building."""
    cands: list[dict[str, Any]] = []

    # 1. OpenImages V7 positives (keep group_of flag so Stage 1 / V4 strips countable group_of)
    for r in v1.openimages_records(full):
        cands.append(
            {
                "split": r.split,
                "source": r.source,
                "id": r.original_id,
                "original_id": r.original_id,
                "path": r.path,
                "license": r.license,
                "license_flag": "ok",
                "author": r.author,
                "url": r.url,
                "group": r.group,
                "boxes": [
                    {
                        "cls": order[b.cls],
                        "xc": b.xc,
                        "yc": b.yc,
                        "w": b.w,
                        "h": b.h,
                        "group_of": b.group_of,
                    }
                    for b in r.boxes
                ],
                "is_neg": False,
            }
        )

    # 2. Mendeley BD expanded (37-class map + unmapped hard-neg frames)
    for r in v3.bd_v3_records(full):
        cands.append(
            {
                "split": r.split,
                "source": r.source,
                "id": r.original_id,
                "original_id": r.original_id,
                "path": r.path,
                "license": r.license,
                "license_flag": "ok",
                "author": r.author,
                "url": r.url,
                "group": r.group,
                "boxes": [
                    {
                        "cls": order[b.cls],
                        "xc": b.xc,
                        "yc": b.yc,
                        "w": b.w,
                        "h": b.h,
                        "group_of": b.group_of,
                    }
                    for b in r.boxes
                ],
                "is_neg": r.is_hard_neg,
            }
        )

    # 3. LVIS v1 positives
    for im in lvis.records():
        cands.append(
            {
                "split": im["split"],
                "source": "lvis_v1",
                "id": f"{im['lvis_split']}/{im['id']}",
                "original_id": f"{im['lvis_split']}/{im['id']}",
                "path": im["path"],
                "width": im["width"],
                "height": im["height"],
                "license": im["license_name"],
                "license_flag": v2.lvis_license_flag(im["license_name"]),
                "author": "",
                "url": im["flickr_url"] or im["coco_url"],
                "group": str(im["id"]),
                "boxes": im["boxes"],
                "is_neg": False,
            }
        )

    # 4. LVIS v1 clean OOD negatives (M1 F4)
    for im in lvis.neg_records():
        lic = im.get("license", "")
        cands.append(
            {
                "split": "train",
                "source": "lvis_v1_neg",
                "id": str(im.get("id") or f"neg/{im.get('coco_id', '')}"),
                "original_id": f"neg/{im.get('coco_id', im.get('stem', ''))}",
                "path": im["path"],
                "width": im.get("width", 0),
                "height": im.get("height", 0),
                "license": lic,
                "license_flag": v2.lvis_license_flag(lic),
                "author": "",
                "url": im.get("url", ""),
                "group": str(im.get("coco_id", im.get("stem", ""))),
                "ood_labels": im.get("ood_labels", []),
                "boxes": [],
                "is_neg": True,
            }
        )

    # 5. RPC checkout (non_commercial)
    for im in rpc.records():
        cands.append(
            {
                "split": im["split"],
                "source": "rpc_checkout",
                "id": im["id"],
                "original_id": im["id"],
                "path": im["path"],
                "width": im["width"],
                "height": im["height"],
                "license": "CC BY-NC-SA 4.0",
                "license_flag": "non_commercial",
                "author": "Wei et al. 2019",
                "url": "https://huggingface.co/datasets/benjamintli/retail-product-checkout",
                "group": im["id"],
                "boxes": im["boxes"],
                "is_neg": False,
            }
        )

    # 6. Omorros kitchen (heldout only)
    for im in v2.omorros_records():
        cands.append(
            {
                "split": "heldout",
                "source": "omorros_kitchen",
                "id": im["id"],
                "original_id": im["id"],
                "path": im["path"],
                "width": im["width"],
                "height": im["height"],
                "license": "CC BY 4.0",
                "license_flag": "ok",
                "author": "Oriol Morros Vilaseca 2026",
                "url": "https://huggingface.co/datasets/omorros/kitchen-fruit-vegetable-detection",
                "group": im["id"],
                "boxes": im["boxes"],
                "is_neg": False,
            }
        )

    # 7. DFV16 (M1 F2: train/val/heldout, never test)
    for im in dfv16.records():
        sp = im.get("split_hint") or im.get("split") or "train"
        if sp == "test":
            sp = "heldout"
        cands.append(
            {
                "split": sp,
                "source": "dfv16",
                "id": im["id"],
                "original_id": im["id"],
                "path": im["path"],
                "width": im.get("width", 0),
                "height": im.get("height", 0),
                "license": im.get("license", "CC BY 4.0"),
                "license_flag": "ok" if im.get("is_commercial_ok", True) else "non_commercial",
                "author": "DFV16 (Zenodo 22783222)",
                "url": im.get("url", ""),
                "group": im.get("stem", im["id"]),
                "ood_labels": im.get("ood_labels", []),
                "boxes": im.get("boxes", []),
                "is_neg": bool(im.get("is_neg", not im.get("boxes"))),
            }
        )

    # 8. OpenImages V7 OOD negatives (M1 F3: train/val only)
    for im in openimages.ood_records():
        sp = im.get("split_hint") or im.get("split") or "train"
        if sp not in ("train", "val"):
            sp = "train"
        cands.append(
            {
                "split": sp,
                "source": "openimages_v7_ood",
                "id": im["id"],
                "original_id": im["id"],
                "path": im["path"],
                "width": im.get("width", 0),
                "height": im.get("height", 0),
                "license": im.get("license", "CC BY 2.0"),
                "license_flag": "ok" if im.get("is_commercial_ok", True) else "non_commercial",
                "author": "",
                "url": im.get("url", ""),
                "group": im.get("stem", im["id"]),
                "ood_labels": im.get("ood_labels", []),
                "boxes": [],
                "is_neg": True,
            }
        )

    # 9. Roboflow subsets (train/val only, never test)
    for im in roboflow_ingest.records():
        sp = im.get("split_hint") or im.get("split") or "train"
        if sp not in ("train", "val"):
            sp = "train"
        src = im["source"]
        cands.append(
            {
                "split": sp,
                "source": src,
                "id": im["id"],
                "original_id": im["id"],
                "path": im["path"],
                "width": im.get("width", 0),
                "height": im.get("height", 0),
                "license": im.get("license", "CC BY 4.0"),
                "license_flag": "ok" if im.get("is_commercial_ok", True) else "non_commercial",
                "author": "",
                "url": im.get("url", ""),
                "group": im.get("stem", im["id"]),
                "ood_labels": im.get("ood_labels", []),
                "boxes": im.get("boxes", []),
                "is_neg": bool(im.get("is_neg", not im.get("boxes"))),
                "has_black_corners": bool(im.get("has_black_corners", False)),
            }
        )

    # 10. V3Det (train/val only, non_commercial)
    for im in v3det.records():
        sp = im.get("split_hint") or im.get("split") or "train"
        if sp not in ("train", "val"):
            sp = "train"
        cands.append(
            {
                "split": sp,
                "source": "v3det",
                "id": im["id"],
                "original_id": im["id"],
                "path": im["path"],
                "width": im.get("width", 0),
                "height": im.get("height", 0),
                "license": im.get("license", "CC BY 4.0 (ann) / Flickr ToU"),
                "license_flag": "non_commercial",
                "author": "",
                "url": im.get("url", ""),
                "group": im["id"],
                "ood_labels": im.get("ood_labels", []),
                "boxes": im.get("boxes", []),
                "is_neg": bool(im.get("is_neg", not im.get("boxes"))),
            }
        )

    # 11. Optional external datasets if ingested
    for im in hf_kaggle_ingest.records():
        sp = im.get("split_hint") or im.get("split") or "train"
        if sp == "test":
            sp = "heldout"
        cands.append(
            {
                "split": sp,
                "source": im["source"],
                "id": im["id"],
                "original_id": im["id"],
                "path": im["path"],
                "width": im.get("width", 0),
                "height": im.get("height", 0),
                "license": im.get("license", ""),
                "license_flag": "ok" if im.get("is_commercial_ok", False) else "non_commercial",
                "author": "",
                "url": im.get("url", ""),
                "group": im.get("stem", im["id"]),
                "ood_labels": im.get("ood_labels", []),
                "boxes": im.get("boxes", []),
                "is_neg": bool(im.get("is_neg", not im.get("boxes"))),
            }
        )

    return cands


def build_from_records(
    raw_candidates: list[dict[str, Any]],
    *,
    out_dir: Path = YOLO,
    decisions: dict[str, dict[str, Any]] | None = None,
    cleaning_base: dict[str, Any] | None = None,
    contact_sheets: list[str] | None = None,
    check_pixels: bool = True,
    bg_ratio: float = 0.18,
    phash_threshold: int = 4,
) -> dict[str, Any]:
    """Filter candidates, pHash-dedupe, materialize yolo_v4, and reconcile manifests."""
    rows = v2.all_class_rows()
    n_main = len(yaml.safe_load(v2.VISION_CLASSES.read_text(encoding="utf-8"))["classes"])
    order = [str(c["id"]) for c in rows]
    full = {cid: i for i, cid in enumerate(order)}

    purged_defects: Counter[str] = Counter()
    source_accounting: dict[str, dict[str, int]] = defaultdict(
        lambda: {"input": 0, "kept": 0, "quarantined": 0}
    )

    recs: list[V4Record] = []
    for raw in raw_candidates:
        src = str(raw.get("source") or raw.get("source_name") or "unknown")
        rid = str(raw.get("id") or raw.get("original_id") or "")
        key = f"{src}|{rid}"
        source_accounting[src]["input"] += 1

        # Apply Track C Stage 2 decision if present
        dec = decisions.get(key) if decisions else None
        if dec is not None and not dec.get("keep", True):
            reason = str(dec.get("reason") or "track_c_quarantined")
            purged_defects[reason] += 1
            source_accounting[src]["quarantined"] += 1
            continue

        # Always run Stage 1 CPU purity & geometry verification
        s1 = stage1_filter_record(raw, countable_classes=EXPECTED_COUNTABLE_19, check_pixels=check_pixels)
        for k, v in s1["stats"].items():
            if v > 0:
                purged_defects[k] += int(v)
        if not s1["keep"]:
            reason = str(s1["reason"] or "stage1_rejected")
            purged_defects[reason] += 1
            source_accounting[src]["quarantined"] += 1
            continue

        kept_box_dicts = s1["boxes"]
        img_w = int(raw.get("width") or 0)
        img_h = int(raw.get("height") or 0)
        if (img_w <= 0 or img_h <= 0) and any("bbox" in b for b in kept_box_dicts):
            from PIL import Image

            with Image.open(raw["path"]) as im_sz:
                img_w, img_h = im_sz.size

        had_orig = len(kept_box_dicts) > 0
        yolo_boxes = [
            b
            for b in (_box_dict_to_yolo(bd, full, img_w, img_h) for bd in kept_box_dicts)
            if b is not None
        ]
        if had_orig and not yolo_boxes:
            purged_defects["degenerate_yolo_boxes_purged"] += 1
            source_accounting[src]["quarantined"] += 1
            continue

        # Enforce split rules
        split = str(raw.get("split") or "train")
        if src == "omorros_kitchen":
            split = "heldout"
        elif (src == "v3det" or src.startswith("rf_")) and split not in ("train", "val"):
            split = "train"
        elif src == "dfv16" and split == "test":
            split = "heldout"

        # Enforce license rules
        lic = str(raw.get("license") or "")
        flag = str(raw.get("license_flag") or "ok")
        if src in {"rpc_checkout", "v3det"} or "NonCommercial" in lic or "BY-NC" in lic:
            flag = "non_commercial"
        elif src in {"mendeley_bd", "openimages_v7", "omorros_kitchen", "dfv16"} and "NC" not in lic:
            flag = "ok"

        if src == "rf_robo1" and len(yolo_boxes) == 0:
            purged_defects["rf_robo1_hard_neg_purged"] += 1
            source_accounting[src]["quarantined"] += 1
            continue

        source_accounting[src]["kept"] += 1
        recs.append(
            V4Record(
                split=split,
                source=src,
                original_id=str(raw.get("original_id") or rid),
                path=Path(raw["path"]),
                license=lic,
                author=str(raw.get("author") or ""),
                url=str(raw.get("url") or ""),
                group=str(raw.get("group") or rid),
                boxes=yolo_boxes,
                is_hard_neg=(len(yolo_boxes) == 0),
                license_flag=flag,
                track_c_key=key,
            )
        )

    # Verify all 37 classes are represented (strict classes_without_data == [])
    present = {b.cls for r in recs for b in r.boxes}
    missing_classes = [order[i] for i in range(len(order)) if i not in present]
    if missing_classes:
        raise RuntimeError(f"yolo_v4 missing boxes for class(es): {missing_classes}")

    # Deterministic split order: test -> heldout -> val -> train
    idx = sorted(range(len(recs)), key=lambda i: (SPLITS.index(recs[i].split), recs[i].source, recs[i].original_id))
    recs = [recs[i] for i in idx]

    with ThreadPoolExecutor(max_workers=8) as ex:
        hashes = list(ex.map(v1._hash, (r.path for r in recs)))

    n_test = sum(r.split == "test" for r in recs)
    keep = dedupe(hashes, threshold=phash_threshold, keep_first=n_test)
    dropped_dups = Counter(f"{recs[i].source}/{recs[i].split}" for i in set(range(len(recs))) - set(keep))

    # Train background cap (up to bg_ratio * boxed_train, prioritizing verified raw OOD backgrounds)
    boxed_train = [i for i in keep if recs[i].boxes and recs[i].split == "train"]
    bg_prio = [
        i
        for i in keep
        if not recs[i].boxes and recs[i].split == "train" and recs[i].source in PRIORITY_HARD_NEG_SOURCES
    ]
    bg_other = [
        i
        for i in keep
        if not recs[i].boxes and recs[i].split == "train" and recs[i].source not in PRIORITY_HARD_NEG_SOURCES
    ]
    max_bg = int(bg_ratio * len(boxed_train))
    rng = np.random.default_rng(0)
    bg_keep: set[int] = set()
    if len(bg_prio) <= max_bg:
        bg_keep.update(bg_prio)
        rem = max_bg - len(bg_prio)
        if rem > 0 and bg_other:
            bg_keep.update(rng.choice(bg_other, size=min(rem, len(bg_other)), replace=False).tolist())
    else:
        bg_keep.update(rng.choice(bg_prio, size=max_bg, replace=False).tolist())

    kept = [i for i in keep if recs[i].boxes or recs[i].split != "train" or i in bg_keep]

    # Verify 0 cross-split pHash leakage between (test|heldout) and (train|val)
    eval_hashes = np.array([hashes[i] for i in kept if recs[i].split in ("test", "heldout")], dtype=np.uint64)
    dev_hashes = np.array([hashes[i] for i in kept if recs[i].split in ("train", "val")], dtype=np.uint64)
    if eval_hashes.size > 0 and dev_hashes.size > 0:
        for eh in eval_hashes:
            min_d = int(hamming(dev_hashes, eh).min())
            if min_d <= phash_threshold:
                raise AssertionError(f"Cross-split pHash leakage detected: min hamming={min_d} <= {phash_threshold}")

    # Verify all 37 classes still have >= 1 box after pHash dedupe
    present_final = {b.cls for i in kept for b in recs[i].boxes}
    missing_final = [order[c] for c in range(len(order)) if c not in present_final]
    if missing_final:
        raise RuntimeError(f"yolo_v4 missing classes after dedupe: {missing_final}")

    # Materialize yolo_v4/ directory
    for s in SPLITS:
        for kind in ("images", "labels"):
            d = out_dir / kind / s
            d.mkdir(parents=True, exist_ok=True)
            for f in d.iterdir():
                f.unlink()
    (out_dir / "heldout").mkdir(parents=True, exist_ok=True)
    for f in (out_dir / "heldout").iterdir():
        f.unlink()

    boxes_cnt: dict[str, Counter[str]] = defaultdict(Counter)
    boxes_src: dict[str, Counter[str]] = defaultdict(Counter)
    images_cnt: Counter[str] = Counter()
    hard_neg_cnt: Counter[str] = Counter()
    heldout_lists: dict[str, list[str]] = defaultdict(list)

    manifest_path = out_dir / "manifest_v4.csv"
    with manifest_path.open("w", encoding="utf-8", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(
            [
                "split",
                "source",
                "original_id",
                "file",
                "license",
                "license_flag",
                "author",
                "url",
                "group",
                "phash",
                "n_boxes",
                "n_group_of",
                "countable_group_of_boxes",
                "group_of_per_class",
                "is_hard_neg",
                "boxes_per_class",
            ]
        )
        for i in kept:
            r = recs[i]
            safe_oid = re.sub(r"[^A-Za-z0-9._-]+", "_", r.original_id.replace("/", "__"))
            name = os.path.splitext(f"{r.source}__{safe_oid}")[0]
            dst = out_dir / "images" / r.split / f"{name}.jpg"
            if dst.exists():
                name = f"{name}__{hashes[i]:08x}"
                dst = out_dir / "images" / r.split / f"{name}.jpg"
            _link_or_copy(r.path, dst)
            (out_dir / "labels" / r.split / f"{name}.txt").write_text(
                write_label(r.boxes), encoding="utf-8"
            )

            per = Counter(order[b.cls] for b in r.boxes)
            gof_per = Counter(order[b.cls] for b in r.boxes if b.group_of)
            c_gof = sum(v for k, v in gof_per.items() if k in EXPECTED_COUNTABLE_19)
            is_bg = len(r.boxes) == 0

            images_cnt[r.split] += 1
            if is_bg:
                hard_neg_cnt[f"{r.source}/{r.split}"] += 1
            for k, v in per.items():
                boxes_cnt[r.split][k] += v
                boxes_src[f"{r.source}/{r.split}"][k] += v
            if r.split == "heldout":
                heldout_lists[r.source].append(f"./images/heldout/{name}.jpg")

            wr.writerow(
                [
                    r.split,
                    r.source,
                    r.original_id,
                    f"yolo_v4/images/{r.split}/{name}.jpg",
                    r.license,
                    r.license_flag,
                    r.author,
                    r.url,
                    r.group,
                    f"{hashes[i]:016x}",
                    len(r.boxes),
                    sum(b.group_of for b in r.boxes),
                    c_gof,
                    json.dumps(dict(sorted(gof_per.items())), ensure_ascii=False),
                    int(is_bg),
                    json.dumps(dict(sorted(per.items())), ensure_ascii=False),
                ]
            )

    for src, lst in heldout_lists.items():
        (out_dir / "heldout" / f"{src}.txt").write_text("\n".join(lst) + "\n", encoding="utf-8")

    ds = {
        "path": str(out_dir),
        "train": "images/train",
        "val": "images/val",
        "test": "images/test",
        "names": dict(enumerate(order)),
    }
    yaml_txt = yaml.safe_dump(ds, allow_unicode=True, sort_keys=False)
    (out_dir / "dataset.yaml").write_text(yaml_txt, encoding="utf-8")
    (out_dir / "data.yaml").write_text(yaml_txt, encoding="utf-8")
    ds_h = {**ds, "test": "images/heldout"}
    (out_dir / "dataset_heldout.yaml").write_text(
        yaml.safe_dump(ds_h, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    stats = {
        "classes_v4": order,
        "n_classes": len(order),
        "classes_without_data": [],
        "proposed_classes_with_data": [c for c in order if c in {r["id"] for r in rows[n_main:]}],
        "images_per_split": dict(images_cnt),
        "boxes_per_split_class": {s: dict(sorted(boxes_cnt[s].items())) for s in SPLITS},
        "boxes_per_source_split_class": {k: dict(sorted(v.items())) for k, v in sorted(boxes_src.items())},
        "hard_neg_bg_by_source_split": dict(sorted(hard_neg_cnt.items())),
        "total_train_bg_images": sum(v for k, v in hard_neg_cnt.items() if k.endswith("/train")),
        "candidates_per_source_split": dict(Counter(f"{r.source}/{r.split}" for r in recs)),
        "dropped_near_duplicates": dict(dropped_dups),
        "dropped_no_box_train": len(keep) - len(kept),
        "images_per_license_flag": dict(Counter(recs[i].license_flag for i in kept)),
        "phash_threshold": phash_threshold,
    }
    (out_dir / "dataset_stats_v4.json").write_text(
        json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Merge Track C cleaning_manifest with build-stage accounting
    merged_sources: dict[str, dict[str, int]] = {}
    base_sources = (cleaning_base or {}).get("sources") or {}
    for sname in sorted(set(base_sources) | set(source_accounting)):
        b_ent = base_sources.get(sname) or {}
        a_ent = source_accounting.get(sname) or {}
        merged_sources[sname] = {
            "input": int(b_ent.get("input") or a_ent.get("input") or 0),
            "kept": int(a_ent.get("kept", b_ent.get("kept", 0))),
            "quarantined": max(int(b_ent.get("quarantined", 0)), int(a_ent.get("quarantined", 0))),
        }

    merged_purged = dict((cleaning_base or {}).get("purged_defects") or {})
    for k, v in purged_defects.items():
        if v > 0:
            merged_purged[k] = max(int(merged_purged.get(k, 0)), int(v))

    sheets = list(contact_sheets) if contact_sheets is not None else list((cleaning_base or {}).get("contact_sheets") or [])
    cleaning_out = {
        "version": 4,
        "dataset": "yolo_v4",
        "stage2_enabled": bool((cleaning_base or {}).get("stage2_enabled", bool(decisions))),
        "stage2a_backend": str((cleaning_base or {}).get("stage2a_backend", "none")),
        "stage2b_backend": str((cleaning_base or {}).get("stage2b_backend", "none")),
        "kept_images": len(kept),
        "quarantined_images": sum(v["quarantined"] for v in merged_sources.values()),
        "rescued_class_floor": list((cleaning_base or {}).get("rescued_class_floor") or []),
        "sources": merged_sources,
        "quarantined_sources": merged_sources,
        "purged_defects": dict(sorted(merged_purged.items())),
        "dropped_near_duplicates": dict(dropped_dups),
        "contact_sheets": sheets,
    }
    (out_dir / "cleaning_manifest.json").write_text(
        json.dumps(cleaning_out, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return stats


def build(
    *,
    out_dir: Path = YOLO,
    decisions_path: Path = DECISIONS_PATH,
    cleaning_manifest_path: Path = CLEANING_MANIFEST_PATH,
    check_pixels: bool = True,
) -> dict[str, Any]:
    rows = v2.all_class_rows()
    order = [str(c["id"]) for c in rows]
    full = {cid: i for i, cid in enumerate(order)}

    raw_cands = _collect_raw_candidates(full, order)
    decisions = _load_decisions(decisions_path)
    cleaning_base = (
        json.loads(cleaning_manifest_path.read_text(encoding="utf-8"))
        if cleaning_manifest_path.is_file()
        else None
    )
    return build_from_records(
        raw_cands,
        out_dir=out_dir,
        decisions=decisions,
        cleaning_base=cleaning_base,
        check_pixels=check_pixels,
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Build Tastoria yolo_v4 dataset.")
    ap.add_argument("--out-dir", type=Path, default=YOLO)
    ap.add_argument("--decisions", type=Path, default=DECISIONS_PATH)
    ap.add_argument("--cleaning-manifest", type=Path, default=CLEANING_MANIFEST_PATH)
    args = ap.parse_args()
    res = build(
        out_dir=args.out_dir,
        decisions_path=args.decisions,
        cleaning_manifest_path=args.cleaning_manifest,
    )
    print(json.dumps(res, indent=2, ensure_ascii=False))
