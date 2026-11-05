"""Build the v2 public-data YOLO dataset under data/processed/cv/yolo_v2/.

v2 = v1 sources (Open Images V7, Mendeley Bangladesh; same images and splits as build_yolo.py) plus
  lvis_v1          LVIS v1 subset (lvis.py): LVIS train -> train/val, LVIS val -> heldout
  rpc_checkout     RPC checkout photos (rpc.py): train/val/heldout by file-name hash
  omorros_kitchen  Kitchen Fruit & Vegetable Detection (120 home-kitchen photos): heldout only

Classes: ``classes`` + ``proposed_classes`` of data/kb/vision_classes.yaml, restricted to those with at least one
box in v2 (``names`` in dataset.yaml; indices are positions in that list, not in the full table).

Split rules
  * the frozen v1 ``test`` split is unchanged (same images; labels rewritten with v2 indices);
  * new external data goes only to train / val, plus a separate ``heldout`` split per source for evaluating the
    newly covered classes (yolo_v2/heldout/<source>.txt lists the images);
  * pHash dedupe (64 bit, Hamming ≤ 4) in the order test -> heldout -> val -> train; test is always kept, so a
    near-duplicate of a test image is removed from every other split, and a held-out image is never duplicated
    in train/val.

Outputs: yolo_v2/{images,labels}/{train,val,test,heldout}/, yolo_v2/dataset.yaml, yolo_v2/heldout/*.txt,
manifest_v2.csv, dataset_stats_v2.json (box counts per class and split; v1 counts for comparison).

Run: ``python -m tastoria_ml.cv.build_yolo_v2``
"""

from __future__ import annotations

import csv
import json
import os
from collections import Counter, defaultdict

import numpy as np
import yaml

from tastoria_ml.cv import build_yolo as v1
from tastoria_ml.cv.classes import VISION_CLASSES
from tastoria_ml.cv.phash import dedupe
from tastoria_ml.cv.yolo_format import Box, from_corners_norm, write_label

OUT = v1.OUT
YOLO = OUT / "yolo_v2"
SPLITS = ("test", "heldout", "val", "train")

LICENSE_FLAGS = {
    "openimages_v7": "ok",
    "mendeley_bd": "ok",
    "omorros_kitchen": "ok",
    "rpc_checkout": "non_commercial",
}


def all_class_rows() -> list[dict]:
    raw = yaml.safe_load(VISION_CLASSES.read_text(encoding="utf-8"))
    return list(raw["classes"]) + list(raw.get("proposed_classes") or [])


def _xywh(cls: int, x: float, y: float, w: float, h: float, W: int, H: int) -> Box | None:
    return from_corners_norm(cls, x / W, y / H, (x + w) / W, (y + h) / H)


def lvis_license_flag(name: str) -> str:
    return "non_commercial" if "NonCommercial" in name else "ok"


def build() -> dict:
    from tastoria_ml.cv import lvis, rpc

    rows = all_class_rows()
    n_main = len(yaml.safe_load(VISION_CLASSES.read_text(encoding="utf-8"))["classes"])
    order = [c["id"] for c in rows]
    full = {cid: i for i, cid in enumerate(order)}  # temporary index over the full table
    recs: list[v1.Record] = []
    flags: list[str] = []
    # v1 sources, same splits as v1
    for r in v1.openimages_records(full) + v1.bd_records(full):
        recs.append(r)
        flags.append(LICENSE_FLAGS[r.source])
    for im in lvis.records():
        boxes = [b for b in (_xywh(full[x["cls"]], *x["bbox"], im["width"], im["height"]) for x in im["boxes"]) if b]
        recs.append(v1.Record(split=im["split"], source="lvis_v1", original_id=f"{im['lvis_split']}/{im['id']}",
                              path=im["path"], license=im["license_name"], url=im["flickr_url"] or im["coco_url"],
                              group=str(im["id"]), boxes=boxes))
        flags.append(lvis_license_flag(im["license_name"]))
    for im in rpc.records():
        boxes = [b for b in (_xywh(full[x["cls"]], *x["bbox"], im["width"], im["height"]) for x in im["boxes"]) if b]
        recs.append(v1.Record(split=im["split"], source="rpc_checkout", original_id=im["id"], path=im["path"],
                              license="CC BY-NC-SA 4.0", author="Wei et al. 2019",
                              url="https://huggingface.co/datasets/benjamintli/retail-product-checkout",
                              group=im["id"], boxes=boxes))
        flags.append("non_commercial")
    for im in omorros_records():
        boxes = [b for b in (_xywh(full[x["cls"]], *x["bbox"], im["width"], im["height"]) for x in im["boxes"]) if b]
        recs.append(v1.Record(split="heldout", source="omorros_kitchen", original_id=im["id"], path=im["path"],
                              license="CC BY 4.0", author="Oriol Morros Vilaseca 2026",
                              url="https://huggingface.co/datasets/omorros/kitchen-fruit-vegetable-detection",
                              group=im["id"], boxes=boxes))
        flags.append("ok")

    # classes with data -> final indices
    present = sorted({b.cls for r in recs for b in r.boxes})
    names = [order[i] for i in present]
    remap = {old: new for new, old in enumerate(present)}
    for r in recs:
        r.boxes = [Box(remap[b.cls], b.xc, b.yc, b.w, b.h, b.group_of) for b in r.boxes]

    idx = sorted(range(len(recs)), key=lambda i: (SPLITS.index(recs[i].split), recs[i].source, recs[i].original_id))
    recs = [recs[i] for i in idx]
    flags = [flags[i] for i in idx]
    hashes = [v1._hash(r.path) for r in recs]
    n_test = sum(r.split == "test" for r in recs)
    keep = dedupe(hashes, threshold=4, keep_first=n_test)
    dropped = Counter(f"{recs[i].source}/{recs[i].split}" for i in set(range(len(recs))) - set(keep))
    # background (no box) train images: 8 % of boxed train, as in v1
    boxed_train = [i for i in keep if recs[i].boxes and recs[i].split == "train"]
    bg_train = [i for i in keep if not recs[i].boxes and recs[i].split == "train"]
    rng = np.random.default_rng(0)
    n_bg = min(len(bg_train), int(0.08 * len(boxed_train)))
    bg_keep = set(rng.choice(bg_train, size=n_bg, replace=False).tolist()) if n_bg else set()
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
    boxes = defaultdict(Counter)
    boxes_src = defaultdict(Counter)
    images = Counter()
    heldout_lists: dict[str, list[str]] = defaultdict(list)
    with (OUT / "manifest_v2.csv").open("w", encoding="utf-8", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["split", "source", "original_id", "file", "license", "license_flag", "author", "url", "group",
                     "phash", "n_boxes", "n_group_of", "boxes_per_class"])
        for i in kept:
            r = recs[i]
            name = os.path.splitext(f"{r.source}__{r.original_id.replace('/', '__')}")[0]
            dst = YOLO / "images" / r.split / f"{name}.jpg"
            os.link(r.path, dst)
            (YOLO / "labels" / r.split / f"{name}.txt").write_text(write_label(r.boxes), encoding="utf-8")
            per = Counter(names[b.cls] for b in r.boxes)
            images[r.split] += 1
            for k, v in per.items():
                boxes[r.split][k] += v
                boxes_src[f"{r.source}/{r.split}"][k] += v
            if r.split == "heldout":
                heldout_lists[r.source].append(f"./images/heldout/{name}.jpg")
            wr.writerow([r.split, r.source, r.original_id, f"yolo_v2/images/{r.split}/{name}.jpg", r.license,
                         flags[i], r.author, r.url, r.group, f"{hashes[i]:016x}", len(r.boxes),
                         sum(b.group_of for b in r.boxes), json.dumps(dict(sorted(per.items())), ensure_ascii=False)])
    for src, lst in heldout_lists.items():
        (YOLO / "heldout" / f"{src}.txt").write_text("\n".join(lst) + "\n", encoding="utf-8")
    ds = {"path": str(YOLO), "train": "images/train", "val": "images/val", "test": "images/test",
          "names": dict(enumerate(names))}
    (YOLO / "dataset.yaml").write_text(yaml.safe_dump(ds, allow_unicode=True, sort_keys=False), encoding="utf-8")
    ds_h = {**ds, "test": "images/heldout"}
    (YOLO / "dataset_heldout.yaml").write_text(yaml.safe_dump(ds_h, allow_unicode=True, sort_keys=False),
                                               encoding="utf-8")
    v1_stats = json.loads((OUT / "dataset_stats.json").read_text(encoding="utf-8"))
    out = {
        "classes_v2": names,
        "classes_without_data": [c for c in order if c not in names],
        "proposed_classes_with_data": [c for c in names if c in {r["id"] for r in rows[n_main:]}],
        "images_per_split": dict(images),
        "boxes_per_split_class": {s: dict(sorted(boxes[s].items())) for s in SPLITS},
        "boxes_per_source_split_class": {k: dict(sorted(v.items())) for k, v in sorted(boxes_src.items())},
        "v1_boxes_per_split_class": v1_stats["boxes_per_split_class"],
        "candidates_per_source_split": dict(Counter(f"{r.source}/{r.split}" for r in recs)),
        "dropped_near_duplicates": dict(dropped),
        "dropped_no_box_train": len(keep) - len(kept),
        "images_per_license_flag": dict(Counter(flags[i] for i in kept)),
        "phash_threshold": 4,
    }
    (OUT / "dataset_stats_v2.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def omorros_records() -> list[dict]:
    root = v1.REPO / "data" / "raw" / "images" / "omorros_kitchen"
    d = json.loads((root / "coco" / "annotations.json").read_text())
    cats = {c["id"]: c["name"] for c in d["categories"]}
    lab = {}
    for c in all_class_rows():
        for x in (c.get("public_data") or {}).get("omorros_kitchen", []):
            lab[x] = c["id"]
    by = defaultdict(list)
    for a in d["annotations"]:
        n = cats[a["category_id"]]
        if n in lab:
            by[a["image_id"]].append({"cls": lab[n], "bbox": a["bbox"]})
    out = []
    for im in d["images"]:
        p = root / im["file_name"]
        if p.exists():
            out.append({"id": im["file_name"].rsplit("/", 1)[-1].rsplit(".", 1)[0], "path": p,
                        "width": im["width"], "height": im["height"], "boxes": by.get(im["id"], [])})
    return out


if __name__ == "__main__":
    print(json.dumps(build(), indent=2, ensure_ascii=False))
