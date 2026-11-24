"""Build expanded 41-class raw ingredient YOLO dataset (`yolo_v5`) combining:
  1. Cleaned 37-class ``yolo_v4`` base (preserving all exact splits, Track C purges, and pHash purity),
     with video ``VID_20250228_124538`` cleanly assigned to ``val`` for video-level ``cu_cai`` validation.
  2. Untapped local Mendeley BD boxes (Cucumber -> dua_chuot, Eggplant -> ca_tim, Capsicum -> ot_chuong,
     Radish -> cu_cai), merged onto existing mendeley_bd images so zero unlabeled produce remains.
  3. Untapped Omorros Kitchen held-out boxes (bell_pepper -> ot_chuong, cucumber -> dua_chuot), merged onto heldout.
  4. Verified cooked-dish 0-box negatives (Nutrition5k + Track C Tier 1/2) appended strictly to train.

Run: ``python -m tastoria_ml.cv.build_yolo_v5 --yolo-v4-dir ... --out-dir ...``
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import yaml
from PIL import Image, ImageOps

from tastoria_ml.cv import build_yolo as v1
from tastoria_ml.cv.phash import hamming, phash
from tastoria_ml.cv.siddhanxt_audit import SIDDHANXT_MAP
from tastoria_ml.cv.yolo_format import Box, from_corners_norm, from_voc, write_label

NEW_4_CLASSES: tuple[str, ...] = (
    "dua_chuot",
    "ca_tim",
    "ot_chuong",
    "cu_cai",
)

BD_EXTRA_VAL_VIDS: set[str] = {"VID_20250228_124538"}

MENDELEY_EXTRA_MAP: dict[str, str] = {
    "Cucumber": "dua_chuot",
    "Eggplant": "ca_tim",
    "Capsicum": "ot_chuong",
    "Radish": "cu_cai",
}

OMORROS_EXTRA_MAP: dict[str, str] = {
    "bell_pepper_green": "ot_chuong",
    "bell_pepper_red": "ot_chuong",
    "cucumber": "dua_chuot",
}


def _link_or_copy(src: Path, dst: Path) -> None:
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _l256_phash(img_path: Path) -> int:
    with Image.open(img_path) as im:
        g = ImageOps.exif_transpose(im).convert("L")
        g.thumbnail((256, 256))
        return int(phash(np.asarray(g)))


def build_v5(
    yolo_v4_dir: Path,
    out_dir: Path,
    *,
    bd_root: Path | None = None,
    omorros_root: Path | None = None,
    siddhanxt_dir: Path | None = None,
    cooked_neg_manifest: Path | None = None,
    food_assets_dir: Path | None = None,
    vision_classes_yaml: Path | None = None,
    siddhanxt_keep_set: set[str] | None = None,
) -> dict:
    yolo_v4_dir = Path(yolo_v4_dir)
    out_dir = Path(out_dir)

    # Canonical class list = 37 existing + 13 new (preserving indices 0..36 verbatim!)
    v4_ds = yaml.safe_load((yolo_v4_dir / "dataset.yaml").read_text(encoding="utf-8"))
    raw_names = v4_ds["names"]
    base_names = [raw_names[i] for i in sorted(raw_names)] if isinstance(raw_names, dict) else list(raw_names)
    if vision_classes_yaml and vision_classes_yaml.is_file():
        vdoc = yaml.safe_load(vision_classes_yaml.read_text(encoding="utf-8"))
        rows = list(vdoc["classes"]) + list(vdoc.get("proposed_classes") or [])
        all_names = [str(r["id"]) for r in rows]
        for c in NEW_4_CLASSES:
            if c not in all_names:
                all_names.append(c)
    else:
        all_names = list(base_names) + [c for c in NEW_4_CLASSES if c not in base_names]
    cid_to_idx = {c: i for i, c in enumerate(all_names)}
    n_classes = len(all_names)
    assert all_names[: len(base_names)] == base_names, "Base 37 class indices must remain invariant"

    for sp in ("test", "heldout", "val", "train"):
        (out_dir / "images" / sp).mkdir(parents=True, exist_ok=True)
        (out_dir / "labels" / sp).mkdir(parents=True, exist_ok=True)

    # 1. Copy/hardlink all clean yolo_v4 images + labels (preserving exact split boundaries,
    #    while assigning BD_EXTRA_VAL_VIDS to val for zero-leakage cu_cai validation)
    eval_hashes: list[int] = []
    train_hashes: set[int] = set()
    img_counts: Counter = Counter()
    box_counts: dict[str, Counter] = {sp: Counter() for sp in ("test", "heldout", "val", "train")}

    def _register_box_counts(sp: str, lbl_txt: str) -> None:
        for ln in lbl_txt.splitlines():
            toks = ln.strip().split()
            if toks:
                ci = int(float(toks[0]))
                if 0 <= ci < n_classes:
                    box_counts[sp][all_names[ci]] += 1

    # Load base yolo_v4
    for sp in ("test", "heldout", "val", "train"):
        src_imgs = sorted((yolo_v4_dir / "images" / sp).glob("*.jpg"))
        for ip in src_imgs:
            dst_sp = "val" if (sp == "train" and any(v in ip.name for v in BD_EXTRA_VAL_VIDS)) else sp
            dst_img = out_dir / "images" / dst_sp / ip.name
            dst_lbl = out_dir / "labels" / dst_sp / f"{ip.stem}.txt"
            _link_or_copy(ip, dst_img)
            src_lbl = yolo_v4_dir / "labels" / sp / f"{ip.stem}.txt"
            txt = src_lbl.read_text(encoding="utf-8") if src_lbl.is_file() else ""
            dst_lbl.write_text(txt, encoding="utf-8")
            img_counts[dst_sp] += 1
            h = _l256_phash(ip)
            if dst_sp in ("test", "heldout", "val"):
                eval_hashes.append(h)
            else:
                train_hashes.add(h)

    if food_assets_dir and food_assets_dir.is_dir():
        for p in sorted(food_assets_dir.iterdir()):
            if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                eval_hashes.append(_l256_phash(p))

    # 2. Merge untapped Mendeley BD boxes onto existing mendeley_bd frames OR add unrepresented BD frames
    bd_merged = 0
    if bd_root and bd_root.is_dir():
        # Index existing mendeley_bd images in out_dir by (split, original xml/img basename)
        existing_bd: dict[str, tuple[str, Path, Path]] = {}
        for sp in ("test", "heldout", "val", "train"):
            for ip in (out_dir / "images" / sp).glob("mendeley_bd__*.jpg"):
                # name format: mendeley_bd__<folder>__<stem>.jpg
                existing_bd[ip.stem] = (sp, ip, out_dir / "labels" / sp / f"{ip.stem}.txt")

        for xml in sorted(bd_root.rglob("*.xml")):
            ip = xml.with_suffix(".jpg")
            if not ip.is_file():
                continue
            root = ET.parse(xml).getroot()
            W = int(root.find("size/width").text)
            H = int(root.find("size/height").text)
            extra_boxes: list[Box] = []
            for o in root.findall("object"):
                cname = o.find("name").text
                cid = MENDELEY_EXTRA_MAP.get(cname)
                if cid is None:
                    continue
                bb = o.find("bndbox")
                b = from_voc(cid_to_idx[cid], *(float(bb.find(k).text) for k in ("xmin", "ymin", "xmax", "ymax")), W, H)
                if b:
                    extra_boxes.append(b)
            if not extra_boxes:
                continue
            key_stem = f"mendeley_bd__{xml.parent.name}__{ip.stem}"
            if key_stem in existing_bd:
                sp, _, lbl_p = existing_bd[key_stem]
                cur_txt = lbl_p.read_text(encoding="utf-8").strip()
                add_txt = write_label(extra_boxes).strip()
                merged = (cur_txt + "\n" + add_txt).strip() + "\n"
                lbl_p.write_text(merged, encoding="utf-8")
                bd_merged += 1
            else:
                # Only add if not colliding with eval hashes or existing train hashes
                m = re.search(r"(VID_\d+_\d+)", xml.name)
                vid = m.group(1) if m else ""
                sp = "val" if vid in BD_EXTRA_VAL_VIDS else v1.BD_SPLIT.get(vid, "train")
                h = _l256_phash(ip)
                if sp == "train" and eval_hashes and int(hamming(np.asarray(eval_hashes, dtype=np.uint64), h).min()) <= 4:
                    continue
                if sp == "train" and h in train_hashes:
                    continue
                dst_img = out_dir / "images" / sp / f"{key_stem}.jpg"
                dst_lbl = out_dir / "labels" / sp / f"{key_stem}.txt"
                _link_or_copy(ip, dst_img)
                dst_lbl.write_text(write_label(extra_boxes), encoding="utf-8")
                img_counts[sp] += 1
                if sp in ("test", "heldout", "val"):
                    eval_hashes.append(h)
                else:
                    train_hashes.add(h)
                bd_merged += 1

    # 3. Merge untapped Omorros Kitchen boxes into heldout
    ok_merged = 0
    if omorros_root and (omorros_root / "coco" / "annotations.json").is_file():
        d = json.loads((omorros_root / "coco" / "annotations.json").read_text(encoding="utf-8"))
        cats = {c["id"]: c["name"] for c in d["categories"]}
        by_img = defaultdict(list)
        for a in d["annotations"]:
            cname = cats.get(a["category_id"], "")
            cid = OMORROS_EXTRA_MAP.get(cname)
            if cid:
                by_img[a["image_id"]].append((cid, a["bbox"]))
        for im in d["images"]:
            extra = by_img.get(im["id"], [])
            if not extra:
                continue
            stem = im["file_name"].rsplit("/", 1)[-1].rsplit(".", 1)[0]
            lbl_p = out_dir / "labels" / "heldout" / f"omorros_kitchen__{stem}.txt"
            if lbl_p.is_file():
                W, H = int(im["width"]), int(im["height"])
                boxes = [b for cid, (x, y, w, h) in extra if (b := from_corners_norm(cid_to_idx[cid], x / W, y / H, (x + w) / W, (y + h) / H))]
                if boxes:
                    cur = lbl_p.read_text(encoding="utf-8").strip()
                    lbl_p.write_text(((cur + "\n" + write_label(boxes).strip()).strip() + "\n"), encoding="utf-8")
                    ok_merged += 1

    # 4. Add cleaned Siddhanxt produce detection dataset (val -> val, test -> heldout, train -> train)
    sid_counts = Counter()
    if siddhanxt_dir and (siddhanxt_dir / "data.yaml").is_file():
        sdoc = yaml.safe_load((siddhanxt_dir / "data.yaml").read_text(encoding="utf-8"))
        raw_sn = sdoc["names"]
        snames = {int(k): str(v) for k, v in raw_sn.items()} if isinstance(raw_sn, dict) else {i: str(v) for i, v in enumerate(raw_sn)}
        eval_arr = np.asarray(eval_hashes, dtype=np.uint64)

        for src_sp, dst_sp in (("test", "heldout"), ("val", "val"), ("train", "train")):
            img_src = siddhanxt_dir / "images" / src_sp
            lbl_src = siddhanxt_dir / "labels" / src_sp
            if not img_src.is_dir() or not lbl_src.is_dir():
                continue
            for lbl_p in sorted(lbl_src.glob("*.txt")):
                ip = img_src / f"{lbl_p.stem}.jpg"
                if not ip.is_file():
                    continue
                rel_key = f"{src_sp}/{ip.name}"
                if siddhanxt_keep_set is not None and rel_key not in siddhanxt_keep_set:
                    sid_counts["filtered_out"] += 1
                    continue
                boxes: list[Box] = []
                for ln in lbl_p.read_text(encoding="utf-8", errors="replace").splitlines():
                    toks = ln.strip().split()
                    if len(toks) < 5:
                        continue
                    old_cls = int(float(toks[0]))
                    cid = SIDDHANXT_MAP.get(snames.get(old_cls, ""))
                    if cid is None or cid not in cid_to_idx:
                        continue
                    xc, yc, bw, bh = (float(x) for x in toks[1:5])
                    # Drop degenerate tiny/invalid boxes
                    if bw <= 0.02 or bh <= 0.02 or bw * bh < 0.001:
                        continue
                    b = from_corners_norm(cid_to_idx[cid], xc - bw / 2, yc - bh / 2, xc + bw / 2, yc + bh / 2)
                    if b:
                        boxes.append(b)
                if not boxes:
                    continue
                try:
                    with Image.open(ip) as im:
                        im = ImageOps.exif_transpose(im).convert("RGB")
                        g = im.convert("L")
                        g.thumbnail((256, 256))
                        h = int(phash(np.asarray(g)))
                except Exception:
                    continue

                if dst_sp == "train":
                    if eval_arr.size and int(hamming(eval_arr, h).min()) <= 4:
                        sid_counts["dropped_eval_leak"] += 1
                        continue
                    if h in train_hashes:
                        sid_counts["dropped_train_dup"] += 1
                        continue
                    train_hashes.add(h)
                else:
                    if eval_arr.size and int(hamming(eval_arr, h).min()) <= 4:
                        sid_counts["dropped_eval_dup"] += 1
                        continue
                    eval_hashes.append(h)
                    eval_arr = np.asarray(eval_hashes, dtype=np.uint64)

                stem = f"siddhanxt__{src_sp}__{ip.stem}"
                dst_img = out_dir / "images" / dst_sp / f"{stem}.jpg"
                dst_lbl = out_dir / "labels" / dst_sp / f"{stem}.txt"
                _link_or_copy(ip, dst_img)
                dst_lbl.write_text(write_label(boxes), encoding="utf-8")
                img_counts[dst_sp] += 1
                sid_counts[f"kept_{dst_sp}"] += 1

    # 5. Append cooked-dish 0-box negatives strictly to train
    neg_added = 0
    if cooked_neg_manifest and cooked_neg_manifest.is_file():
        for ln in cooked_neg_manifest.read_text(encoding="utf-8").splitlines():
            p = Path(ln.strip())
            if not p.is_file():
                continue
            dst_img = out_dir / "images" / "train" / f"cneg__{p.stem}.jpg"
            dst_lbl = out_dir / "labels" / "train" / f"cneg__{p.stem}.txt"
            _link_or_copy(p, dst_img)
            dst_lbl.write_text("", encoding="utf-8")
            img_counts["train"] += 1
            neg_added += 1

    # Recount final boxes per split/class cleanly from disk labels
    for sp in ("test", "heldout", "val", "train"):
        for lbl in (out_dir / "labels" / sp).glob("*.txt"):
            _register_box_counts(sp, lbl.read_text(encoding="utf-8"))

    ds = {
        "path": str(out_dir.resolve()),
        "train": "images/train",
        "val": "images/val",
        "test": "images/test",
        "names": dict(enumerate(all_names)),
    }
    (out_dir / "dataset.yaml").write_text(yaml.safe_dump(ds, allow_unicode=True, sort_keys=False), encoding="utf-8")
    dsh = {**ds, "test": "images/heldout"}
    (out_dir / "dataset_heldout.yaml").write_text(yaml.safe_dump(dsh, allow_unicode=True, sort_keys=False), encoding="utf-8")

    stats = {
        "classes": all_names,
        "n_classes": n_classes,
        "images_per_split": dict(img_counts),
        "boxes_per_split_class": {sp: dict(sorted(box_counts[sp].items())) for sp in ("test", "heldout", "val", "train")},
        "bd_merged": bd_merged,
        "omorros_merged": ok_merged,
        "siddhanxt": dict(sid_counts),
        "cooked_neg_added_train": neg_added,
    }
    (out_dir / "dataset_stats_v5.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yolo-v4-dir", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--bd-root", type=Path, default=None)
    ap.add_argument("--omorros-root", type=Path, default=None)
    ap.add_argument("--siddhanxt-dir", type=Path, default=None)
    ap.add_argument("--cooked-neg-manifest", type=Path, default=None)
    ap.add_argument("--food-assets-dir", type=Path, default=None)
    ap.add_argument("--vision-classes-yaml", type=Path, default=None)
    a = ap.parse_args()
    print(
        json.dumps(
            build_v5(
                a.yolo_v4_dir,
                a.out_dir,
                bd_root=a.bd_root,
                omorros_root=a.omorros_root,
                siddhanxt_dir=a.siddhanxt_dir,
                cooked_neg_manifest=a.cooked_neg_manifest,
                food_assets_dir=a.food_assets_dir,
                vision_classes_yaml=a.vision_classes_yaml,
            ),
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
