"""Build the v3 expanded YOLO dataset under data/processed/cv/yolo_v3/.

v3 combines all v2 sources cleanly plus four targeted upgrades for Tastoria's gaps:
  1. Expanded Mendeley Bangladesh label map covering all 37 classes (recovering
     5,329 Green Chilli -> ot, 1,509 Spring Onion -> hanh_la, and 6,247 Lemon -> chanh
     boxes already on disk, while retaining unmapped Capsicum / Cucumber / Coriander /
     Eggplant 0-box frames as verified hard-negative backgrounds).
  2. Curated Roboflow Universe subsets (nhan_dien_rau, water_spinach, viet_hoang, aicook,
     tofu_oo, food_start, meat_thesis, robo1), collapsed by .rf.<hash> base stem and
     restricted to train/val (never test).
  3. Selective V3Det produce/tofu subset (muop, su_su, gia_do, rau_cai, rau_muong,
     dau_phu, toi, ot, hanh_la), restricted to train/val.
  4. LVIS pure OOD hard-negative images (onion, bell_pepper, apple, orange_(fruit),
     banana, cucumber) downloaded from already-present lvis_v1_train.json where Tastoria
     classes are absent / explicitly negative-verified.

Classes: all 37 classes of data/kb/vision_classes.yaml, keeping DB vision_classes 1:1
compatibility with zero backend code changes.

Run: ``python -m tastoria_ml.cv.build_yolo_v3``
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import requests
import yaml
from PIL import Image

from tastoria_ml.cv import build_yolo as v1
from tastoria_ml.cv import build_yolo_v2 as v2
from tastoria_ml.cv import lvis, roboflow_ingest, rpc, v3det
from tastoria_ml.cv.phash import dedupe
from tastoria_ml.cv.yolo_format import Box, from_voc, write_label

OUT = v1.OUT
YOLO = OUT / "yolo_v3"
SPLITS = ("test", "heldout", "val", "train")

MENDELEY_V3_MAP: dict[str, str] = {
    "Bitter Gourd": "muop_dang",
    "Bottle gourd": "bi_dao",
    "Cabbage": "bap_cai",
    "Carrots": "ca_rot",
    "Cauliflower": "sup_lo",
    "Green Beans": "dau_que",
    "Green Chilli": "ot",
    "Lemon": "chanh",
    "Potato": "khoai_tay",
    "Pumpkin": "bi_do",
    "Spring Onion": "hanh_la",
    "Tomato": "ca_chua",
}

LVIS_OOD_CATS = ("onion", "bell_pepper", "apple", "orange_(fruit)", "banana", "cucumber")
LVIS_LOOKALIKE_NEG = ("tomato", "carrot", "potato", "lemon", "lime", "chili_(vegetable)", "garlic")
LVIS_NEG_IMAGES = lvis.ROOT / "images_neg"
LVIS_NEG_META = lvis.ANN / "neg-selected.json"


@dataclass
class V3Record:
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


def bd_v3_records(full: dict[str, int]) -> list[V3Record]:
    recs: list[V3Record] = []
    for xml in sorted(v1.BD_ROOT.glob("*/*/*/*.xml")):
        img = xml.with_suffix(".jpg")
        if not img.exists():
            continue
        root = ET.parse(xml).getroot()
        w = int(root.find("size/width").text)
        h = int(root.find("size/height").text)
        boxes: list[Box] = []
        raw_names = []
        for o in root.findall("object"):
            cname = o.find("name").text
            raw_names.append(cname)
            cid = MENDELEY_V3_MAP.get(cname)
            if cid is None:
                continue
            bb = o.find("bndbox")
            box = from_voc(
                full[cid], *(float(bb.find(k).text) for k in ("xmin", "ymin", "xmax", "ymax")), w, h
            )
            if box:
                boxes.append(box)
        video = re.search(r"(VID_\d+_\d+)", xml.name).group(1)
        is_hard = not boxes and any(n in {"Capsicum", "Cucumber", "Coriander leaves", "Eggplant"} for n in raw_names)
        recs.append(
            V3Record(
                split=v1.BD_SPLIT.get(video, "train"),
                source="mendeley_bd",
                original_id=f"{xml.parent.name}/{img.name}",
                path=img,
                license="CC BY 4.0",
                author="Jahan et al. 2025",
                url="https://data.mendeley.com/datasets/gnc4s3z2mf/3",
                group=video,
                boxes=boxes,
                is_hard_neg=is_hard,
                license_flag="ok",
            )
        )
    return recs


def fetch_lvis_neg(*, target_total: int = 400, workers: int = 16) -> list[dict]:
    """Select and download up to 400 pure OOD hard-negative images from local lvis_v1_train.json."""
    train_json = lvis.ANN / "lvis_v1_train.json"
    if not train_json.exists():
        return []

    LVIS_NEG_IMAGES.mkdir(parents=True, exist_ok=True)
    if LVIS_NEG_META.exists():
        meta = json.loads(LVIS_NEG_META.read_text(encoding="utf-8"))
        existing = [m for m in meta if (LVIS_NEG_IMAGES / f"{m['id']:012d}.jpg").exists()]
        if len(existing) >= min(target_total, len(meta)) and existing:
            return existing

    # Exclude any COCO image already in LVIS positive selection
    existing_ids: set[int] = set()
    for fn in ("train-selected.json", "val-selected.json"):
        p = lvis.ANN / fn
        if p.exists():
            existing_ids.update(im["id"] for im in json.loads(p.read_text())["images"])

    lab = lvis.label_map()
    d = json.loads(train_json.read_text(encoding="utf-8"))
    name_to_cid = {c["name"]: c["id"] for c in d["categories"]}
    mapped_cids = {name_to_cid[n] for n in lab if n in name_to_cid}
    ood_cids = {n: name_to_cid[n] for n in LVIS_OOD_CATS if n in name_to_cid}
    ood_cid_to_name = {cid: n for n, cid in ood_cids.items()}
    lookalike_neg_cids = {name_to_cid[n] for n in LVIS_LOOKALIKE_NEG if n in name_to_cid}

    pos_mapped_imgs: set[int] = set()
    ood_by_cat: dict[str, set[int]] = defaultdict(set)
    for ann in d["annotations"]:
        iid = ann["image_id"]
        cid = ann["category_id"]
        if cid in mapped_cids:
            pos_mapped_imgs.add(iid)
        elif cid in ood_cid_to_name:
            ood_by_cat[ood_cid_to_name[cid]].add(iid)

    imgs = {im["id"]: im for im in d["images"]}
    lic_names = {x["id"]: x["name"] for x in d["licenses"]}

    eligible_by_cat: dict[str, list[tuple[int, int]]] = {}
    for oname, iids in ood_by_cat.items():
        ranked = []
        for iid in iids:
            if iid in existing_ids or iid in pos_mapped_imgs:
                continue
            im = imgs.get(iid)
            if not im or not im.get("coco_url"):
                continue
            ne = set(im.get("not_exhaustive_category_ids", []))
            if ne & mapped_cids:
                continue
            neg = set(im.get("neg_category_ids", []))
            score = len(neg & lookalike_neg_cids)
            ranked.append((score, iid))
        # Prefer highest lookalike negative verification score, tie-break deterministically by hash
        ranked.sort(
            key=lambda x: (-x[0], hashlib.sha1(f"lvis_neg:{oname}:{x[1]}".encode()).hexdigest())
        )
        eligible_by_cat[oname] = ranked

    per_cat_cap = max(1, target_total // max(1, len(LVIS_OOD_CATS)))
    chosen_ids: set[int] = set()
    chosen_meta: list[dict] = []
    # Round 1: per-cat cap
    for oname in LVIS_OOD_CATS:
        cnt = 0
        for _score, iid in eligible_by_cat.get(oname, []):
            if cnt >= per_cat_cap:
                break
            if iid in chosen_ids:
                continue
            chosen_ids.add(iid)
            im = imgs[iid]
            chosen_meta.append({
                "id": iid,
                "ood_cat": oname,
                "coco_url": im["coco_url"],
                "license_name": lic_names.get(im["license"], ""),
            })
            cnt += 1
    # Top up up to target_total if any category was short
    if len(chosen_meta) < target_total:
        for oname in LVIS_OOD_CATS:
            for _score, iid in eligible_by_cat.get(oname, []):
                if len(chosen_meta) >= target_total:
                    break
                if iid in chosen_ids:
                    continue
                chosen_ids.add(iid)
                im = imgs[iid]
                chosen_meta.append({
                    "id": iid,
                    "ood_cat": oname,
                    "coco_url": im["coco_url"],
                    "license_name": lic_names.get(im["license"], ""),
                })

    def _dl(m: dict) -> dict | None:
        dst = LVIS_NEG_IMAGES / f"{m['id']:012d}.jpg"
        if dst.exists():
            return m
        try:
            r = requests.get(m["coco_url"], timeout=30)
            r.raise_for_status()
            im = Image.open(io.BytesIO(r.content)).convert("RGB")
            im.thumbnail((1024, 1024))
            tmp = dst.with_suffix(".part")
            im.save(tmp, "JPEG", quality=90)
            tmp.rename(dst)
            return m
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=workers) as ex:
        kept_meta = [m for m in ex.map(_dl, chosen_meta) if m is not None]
    LVIS_NEG_META.write_text(json.dumps(kept_meta, indent=2), encoding="utf-8")
    print(f"[lvis_neg] ready: {len(kept_meta)}/{len(chosen_meta)} OOD hard-negative images", flush=True)
    return kept_meta


def build(*, with_lvis_neg: bool = True) -> dict:
    rows = v2.all_class_rows()
    n_main = len(yaml.safe_load(v2.VISION_CLASSES.read_text(encoding="utf-8"))["classes"])
    order = [c["id"] for c in rows]
    full = {cid: i for i, cid in enumerate(order)}

    recs: list[V3Record] = []

    # 1. Open Images V7 (same split/labels as v1/v2)
    for r in v1.openimages_records(full):
        recs.append(
            V3Record(
                split=r.split,
                source=r.source,
                original_id=r.original_id,
                path=r.path,
                license=r.license,
                author=r.author,
                url=r.url,
                group=r.group,
                boxes=list(r.boxes),
                is_hard_neg=False,
                license_flag="ok",
            )
        )

    # 2. Mendeley BD with expanded 37-class map (ot, hanh_la, chanh + hard-neg unmapped frames)
    recs.extend(bd_v3_records(full))

    # 3. LVIS v1
    for im in lvis.records():
        boxes = [b for b in (v2._xywh(full[x["cls"]], *x["bbox"], im["width"], im["height"]) for x in im["boxes"]) if b]
        recs.append(
            V3Record(
                split=im["split"],
                source="lvis_v1",
                original_id=f"{im['lvis_split']}/{im['id']}",
                path=im["path"],
                license=im["license_name"],
                url=im["flickr_url"] or im["coco_url"],
                group=str(im["id"]),
                boxes=boxes,
                is_hard_neg=False,
                license_flag=v2.lvis_license_flag(im["license_name"]),
            )
        )

    # 4. LVIS pure OOD hard negatives (train only)
    if with_lvis_neg:
        for m in fetch_lvis_neg():
            p = LVIS_NEG_IMAGES / f"{m['id']:012d}.jpg"
            if p.exists():
                recs.append(
                    V3Record(
                        split="train",
                        source="lvis_v1_neg",
                        original_id=f"neg/{m['id']}",
                        path=p,
                        license=m.get("license_name", ""),
                        url=m.get("coco_url", ""),
                        group=str(m["id"]),
                        boxes=[],
                        is_hard_neg=True,
                        license_flag=v2.lvis_license_flag(m.get("license_name", "")),
                    )
                )

    # 5. RPC checkout (same as v2)
    for im in rpc.records():
        boxes = [b for b in (v2._xywh(full[x["cls"]], *x["bbox"], im["width"], im["height"]) for x in im["boxes"]) if b]
        recs.append(
            V3Record(
                split=im["split"],
                source="rpc_checkout",
                original_id=im["id"],
                path=im["path"],
                license="CC BY-NC-SA 4.0",
                author="Wei et al. 2019",
                url="https://huggingface.co/datasets/benjamintli/retail-product-checkout",
                group=im["id"],
                boxes=boxes,
                is_hard_neg=False,
                license_flag="non_commercial",
            )
        )

    # 6. Omorros kitchen held-out (untouched 120 images, heldout only)
    for im in v2.omorros_records():
        boxes = [b for b in (v2._xywh(full[x["cls"]], *x["bbox"], im["width"], im["height"]) for x in im["boxes"]) if b]
        recs.append(
            V3Record(
                split="heldout",
                source="omorros_kitchen",
                original_id=im["id"],
                path=im["path"],
                license="CC BY 4.0",
                author="Oriol Morros Vilaseca 2026",
                url="https://huggingface.co/datasets/omorros/kitchen-fruit-vegetable-detection",
                group=im["id"],
                boxes=boxes,
                is_hard_neg=False,
                license_flag="ok",
            )
        )

    # 7. Roboflow curated subsets (train/val only, NEVER test)
    for im in roboflow_ingest.records():
        boxes = [
            b
            for b in (
                v2._xywh(full[x["cls"]], *x["bbox"], im["width"], im["height"])
                for x in im["boxes"]
                if x["cls"] in full
            )
            if b
        ]
        sp = im["split"] if im["split"] in ("train", "val") else "train"
        recs.append(
            V3Record(
                split=sp,
                source=im["source"],
                original_id=im["id"],
                path=im["path"],
                license=im.get("license", "CC BY 4.0"),
                url=im.get("url", ""),
                group=im.get("stem", im["id"]),
                boxes=boxes,
                is_hard_neg=(len(boxes) == 0),
                license_flag="ok",
            )
        )

    # 8. V3Det selective produce/tofu subset (train/val only, NEVER test)
    for im in v3det.records():
        boxes = [
            b
            for b in (
                v2._xywh(full[x["cls"]], *x["bbox"], im["width"], im["height"])
                for x in im["boxes"]
                if x["cls"] in full
            )
            if b
        ]
        sp = im["split"] if im["split"] in ("train", "val") else "train"
        if not boxes:
            continue
        recs.append(
            V3Record(
                split=sp,
                source="v3det",
                original_id=im["id"],
                path=im["path"],
                license="CC BY 4.0 (ann) / Flickr ToU",
                url=im.get("url", ""),
                group=im["id"],
                boxes=boxes,
                is_hard_neg=False,
                license_flag="ok",
            )
        )

    # Remap classes present -> contiguous indices matching order of vision_classes.yaml
    present = sorted({b.cls for r in recs for b in r.boxes})
    names = [order[i] for i in present]
    remap = {old: new for new, old in enumerate(present)}
    for r in recs:
        r.boxes = [Box(remap[b.cls], b.xc, b.yc, b.w, b.h, b.group_of) for b in r.boxes]

    # Sort test -> heldout -> val -> train and dedupe with pHash <= 4
    idx = sorted(range(len(recs)), key=lambda i: (SPLITS.index(recs[i].split), recs[i].source, recs[i].original_id))
    recs = [recs[i] for i in idx]
    with ThreadPoolExecutor(max_workers=8) as ex:
        hashes = list(ex.map(v1._hash, (r.path for r in recs)))
    n_test = sum(r.split == "test" for r in recs)
    keep = dedupe(hashes, threshold=4, keep_first=n_test)
    dropped = Counter(f"{recs[i].source}/{recs[i].split}" for i in set(range(len(recs))) - set(keep))

    # Keep up to 18% of boxed train count as 0-box negative backgrounds, prioritizing explicit hard negatives first
    boxed_train = [i for i in keep if recs[i].boxes and recs[i].split == "train"]
    bg_hard = [i for i in keep if not recs[i].boxes and recs[i].split == "train" and recs[i].is_hard_neg]
    bg_other = [i for i in keep if not recs[i].boxes and recs[i].split == "train" and not recs[i].is_hard_neg]
    max_bg = int(0.18 * len(boxed_train))
    rng = np.random.default_rng(0)
    bg_keep: set[int] = set()
    if len(bg_hard) <= max_bg:
        bg_keep.update(bg_hard)
        rem = max_bg - len(bg_hard)
        if rem > 0 and bg_other:
            bg_keep.update(rng.choice(bg_other, size=min(rem, len(bg_other)), replace=False).tolist())
    else:
        bg_keep.update(rng.choice(bg_hard, size=max_bg, replace=False).tolist())

    kept = [i for i in keep if recs[i].boxes or recs[i].split != "train" or i in bg_keep]

    for s in SPLITS:
        for kind in ("images", "labels"):
            d = YOLO / kind / s
            d.mkdir(parents=True, exist_ok=True)
            for f in d.iterdir():
                f.unlink()
    (YOLO / "heldout").mkdir(parents=True, exist_ok=True)
    for f in (YOLO / "heldout").iterdir():
        f.unlink()

    boxes_cnt = defaultdict(Counter)
    boxes_src = defaultdict(Counter)
    images_cnt = Counter()
    hard_neg_cnt = Counter()
    heldout_lists: dict[str, list[str]] = defaultdict(list)

    with (OUT / "manifest_v3.csv").open("w", encoding="utf-8", newline="") as f:
        wr = csv.writer(f)
        wr.writerow([
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
            "is_hard_neg",
            "boxes_per_class",
        ])
        for i in kept:
            r = recs[i]
            safe_oid = re.sub(r"[^A-Za-z0-9._-]+", "_", r.original_id.replace("/", "__"))
            name = os.path.splitext(f"{r.source}__{safe_oid}")[0]
            dst = YOLO / "images" / r.split / f"{name}.jpg"
            if dst.exists():
                name = f"{name}__{hashes[i]:08x}"
                dst = YOLO / "images" / r.split / f"{name}.jpg"
            os.link(r.path, dst)
            (YOLO / "labels" / r.split / f"{name}.txt").write_text(write_label(r.boxes), encoding="utf-8")
            per = Counter(names[b.cls] for b in r.boxes)
            images_cnt[r.split] += 1
            if not r.boxes:
                hard_neg_cnt[f"{r.source}/{r.split}"] += 1
            for k, v in per.items():
                boxes_cnt[r.split][k] += v
                boxes_src[f"{r.source}/{r.split}"][k] += v
            if r.split == "heldout":
                heldout_lists[r.source].append(f"./images/heldout/{name}.jpg")
            wr.writerow([
                r.split,
                r.source,
                r.original_id,
                f"yolo_v3/images/{r.split}/{name}.jpg",
                r.license,
                r.license_flag,
                r.author,
                r.url,
                r.group,
                f"{hashes[i]:016x}",
                len(r.boxes),
                sum(b.group_of for b in r.boxes),
                int(r.is_hard_neg and not r.boxes),
                json.dumps(dict(sorted(per.items())), ensure_ascii=False),
            ])

    for src, lst in heldout_lists.items():
        (YOLO / "heldout" / f"{src}.txt").write_text("\n".join(lst) + "\n", encoding="utf-8")

    ds = {
        "path": str(YOLO),
        "train": "images/train",
        "val": "images/val",
        "test": "images/test",
        "names": dict(enumerate(names)),
    }
    (YOLO / "dataset.yaml").write_text(yaml.safe_dump(ds, allow_unicode=True, sort_keys=False), encoding="utf-8")
    ds_h = {**ds, "test": "images/heldout"}
    (YOLO / "dataset_heldout.yaml").write_text(yaml.safe_dump(ds_h, allow_unicode=True, sort_keys=False), encoding="utf-8")

    out = {
        "classes_v3": names,
        "n_classes": len(names),
        "classes_without_data": [c for c in order if c not in names],
        "proposed_classes_with_data": [c for c in names if c in {r["id"] for r in rows[n_main:]}],
        "images_per_split": dict(images_cnt),
        "boxes_per_split_class": {s: dict(sorted(boxes_cnt[s].items())) for s in SPLITS},
        "boxes_per_source_split_class": {k: dict(sorted(v.items())) for k, v in sorted(boxes_src.items())},
        "hard_neg_bg_by_source_split": dict(sorted(hard_neg_cnt.items())),
        "total_train_bg_images": sum(v for k, v in hard_neg_cnt.items() if k.endswith("/train")),
        "candidates_per_source_split": dict(Counter(f"{r.source}/{r.split}" for r in recs)),
        "dropped_near_duplicates": dict(dropped),
        "dropped_no_box_train": len(keep) - len(kept),
        "images_per_license_flag": dict(Counter(recs[i].license_flag for i in kept)),
        "phash_threshold": 4,
    }
    (OUT / "dataset_stats_v3.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--no-lvis-neg", action="store_true")
    args = ap.parse_args()
    print(json.dumps(build(with_lvis_neg=not args.no_lvis_neg), indent=2, ensure_ascii=False))
