"""Build the public-data YOLO dataset under data/processed/cv/yolo/ from the downloaded sources.

Sources (see data/raw/images/<src>/SOURCE.md):
  openimages_v7  split kept from Open Images (train / validation -> val / test);
  mendeley_bd    split by video (frames of one video stay together): val = VID_20250228_135247,
                 test = VID_20250228_124329 (the only two small videos that contain all mapped classes),
                 the other 8 videos train. The dataset's own train/valid/test folders are ignored because
                 they mix frames of the same video.

Labels are mapped with vision_classes.yaml; labels with no class are dropped (their objects are true
negatives for our class set). Images are deduplicated with a 64-bit pHash (Hamming ≤ 4) in the order
test -> val -> train, so a train image that copies a test image is removed. Class indices in the YOLO
files are the indices of the *trained* subset (``names`` in dataset.yaml), not of the full table.

Outputs:
  yolo/images/<split>/<src>__<id>.jpg   hard links to the raw images (no copy)
  yolo/labels/<split>/<src>__<id>.txt
  yolo/dataset.yaml                     ultralytics dataset file
  manifest.csv                          one row per kept image: split, source, original id, license,
                                        author, original URL, group, pHash, boxes per class
  dataset_stats.json                    images/boxes per class and split, dedupe counts

Run (training env): ``python -m tastoria_ml.cv.build_yolo``
"""

from __future__ import annotations

import csv
import json
import os
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from tastoria_ml.cv import openimages as oi
from tastoria_ml.cv.classes import REPO, load_classes, source_label_map, trained_classes
from tastoria_ml.cv.phash import dedupe, phash
from tastoria_ml.cv.yolo_format import Box, from_corners_norm, from_voc, write_label

OUT = REPO / "data" / "processed" / "cv"
YOLO = OUT / "yolo"
BD_ROOT = REPO / "data" / "raw" / "images" / "mendeley_bd_vegetables" / "extracted"
SOURCES = ("openimages_v7", "mendeley_bd")
SPLITS = ("test", "val", "train")
BD_SPLIT = {"VID_20250228_135247": "val", "VID_20250228_124329": "test"}
OI_SPLIT = {"train": "train", "validation": "val", "test": "test"}


@dataclass
class Record:
    split: str
    source: str
    original_id: str
    path: Path
    license: str
    author: str = ""
    url: str = ""
    group: str = ""
    boxes: list[Box] = field(default_factory=list)


def openimages_records(index: dict[str, int]) -> list[Record]:
    lab = source_label_map(load_classes(), "openimages_v7")
    mids = oi.label_mids()
    recs = []
    for split in oi.CAPS:
        meta = oi.read_metadata(split)
        boxes_by_img: dict[str, list[Box]] = defaultdict(list)
        for b in oi.read_boxes(split):
            vc = lab[mids[b["LabelName"]]]
            box = from_corners_norm(
                index[vc.id], float(b["XMin"]), float(b["YMin"]), float(b["XMax"]), float(b["YMax"]),
                group_of=b["IsGroupOf"] == "1",
            )
            if box:
                boxes_by_img[b["ImageID"]].append(box)
        for image_id in sorted(set((oi.META / f"{split}-selected.txt").read_text().split())):
            p = oi.IMAGES / split / f"{image_id}.jpg"
            if not p.exists() or image_id not in boxes_by_img:
                continue
            m = meta.get(image_id, {})
            recs.append(
                Record(
                    split=OI_SPLIT[split], source="openimages_v7", original_id=f"{split}/{image_id}", path=p,
                    license=m.get("License", ""), author=m.get("Author", ""), url=m.get("OriginalURL", ""),
                    group=image_id, boxes=boxes_by_img[image_id],
                )
            )
    return recs


def bd_records(index: dict[str, int]) -> list[Record]:
    lab = source_label_map(load_classes(), "mendeley_bd")
    recs = []
    for xml in sorted(BD_ROOT.glob("*/*/*/*.xml")):
        img = xml.with_suffix(".jpg")
        if not img.exists():
            continue
        root = ET.parse(xml).getroot()
        w = int(root.find("size/width").text)
        h = int(root.find("size/height").text)
        boxes = []
        for o in root.findall("object"):
            vc = lab.get(o.find("name").text)
            if vc is None:
                continue
            bb = o.find("bndbox")
            box = from_voc(index[vc.id], *(float(bb.find(k).text) for k in ("xmin", "ymin", "xmax", "ymax")), w, h)
            if box:
                boxes.append(box)
        video = re.search(r"(VID_\d+_\d+)", xml.name).group(1)
        recs.append(
            Record(
                split=BD_SPLIT.get(video, "train"), source="mendeley_bd",
                original_id=f"{xml.parent.name}/{img.name}", path=img, license="CC BY 4.0",
                author="Jahan et al. 2025", url="https://data.mendeley.com/datasets/gnc4s3z2mf/3",
                group=video, boxes=boxes,
            )
        )
    return recs


def _hash(path: Path) -> int:
    from PIL import Image

    with Image.open(path) as im:
        im = im.convert("L")
        im.thumbnail((256, 256))
        return phash(np.asarray(im))


def build() -> dict:
    classes = load_classes()
    trained = trained_classes(classes, SOURCES)
    index = {c.id: i for i, c in enumerate(trained)}
    recs = openimages_records(index) + bd_records(index)
    order = sorted(range(len(recs)), key=lambda i: (SPLITS.index(recs[i].split), recs[i].source, recs[i].original_id))
    recs = [recs[i] for i in order]
    hashes = [_hash(r.path) for r in recs]
    n_test = sum(r.split == "test" for r in recs)
    keep = dedupe(hashes, threshold=4, keep_first=n_test)
    dropped = Counter((recs[i].source, recs[i].split) for i in set(range(len(recs))) - set(keep))
    # background images (no mapped box: Mendeley frames of unmapped vegetables) are kept for 8% of train
    # (thiết kế v2 §7: 5–10% ảnh nền); val/test keep all of them
    boxed_train = [i for i in keep if recs[i].boxes and recs[i].split == "train"]
    bg_train = [i for i in keep if not recs[i].boxes and recs[i].split == "train"]
    rng = np.random.default_rng(0)
    n_bg = min(len(bg_train), int(0.08 * len(boxed_train)))
    bg_keep = set(rng.choice(bg_train, size=n_bg, replace=False).tolist()) if n_bg else set()
    kept = [i for i in keep if recs[i].boxes or recs[i].split != "train" or i in bg_keep]
    YOLO.mkdir(parents=True, exist_ok=True)
    for s in ("train", "val", "test"):
        for kind in ("images", "labels"):
            d = YOLO / kind / s
            d.mkdir(parents=True, exist_ok=True)
            for f in d.iterdir():
                f.unlink()
    stats: dict = {"images": Counter(), "boxes": defaultdict(Counter), "images_with": defaultdict(Counter)}
    with (OUT / "manifest.csv").open("w", encoding="utf-8", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["split", "source", "original_id", "file", "license", "author", "url", "group", "phash",
                     "n_boxes", "n_group_of", "boxes_per_class"])
        for i in kept:
            r = recs[i]
            name = f"{r.source}__{r.original_id.replace('/', '__')}"
            name = os.path.splitext(name)[0]
            img_dst = YOLO / "images" / r.split / f"{name}.jpg"
            os.link(r.path, img_dst)
            (YOLO / "labels" / r.split / f"{name}.txt").write_text(write_label(r.boxes), encoding="utf-8")
            per = Counter(trained[b.cls].id for b in r.boxes)
            stats["images"][r.split] += 1
            for k, v in per.items():
                stats["boxes"][r.split][k] += v
                stats["images_with"][r.split][k] += 1
            wr.writerow([r.split, r.source, r.original_id, f"yolo/images/{r.split}/{name}.jpg", r.license, r.author,
                         r.url, r.group, f"{hashes[i]:016x}", len(r.boxes), sum(b.group_of for b in r.boxes),
                         json.dumps(dict(sorted(per.items())), ensure_ascii=False)])
    ds = {
        "path": str(YOLO),
        "train": "images/train",
        "val": "images/val",
        "test": "images/test",
        "names": {i: c.id for i, c in enumerate(trained)},
    }
    import yaml

    (YOLO / "dataset.yaml").write_text(yaml.safe_dump(ds, allow_unicode=True, sort_keys=False), encoding="utf-8")
    out = {
        "classes_trained": [c.id for c in trained],
        "classes_without_public_data": [c.id for c in classes if c not in trained],
        "images_per_split": dict(stats["images"]),
        "boxes_per_split_class": {s: dict(sorted(v.items())) for s, v in stats["boxes"].items()},
        "images_per_split_class": {s: dict(sorted(v.items())) for s, v in stats["images_with"].items()},
        "candidates_per_source_split": dict(Counter(f"{r.source}/{r.split}" for r in recs)),
        "dropped_near_duplicates": {f"{k[0]}/{k[1]}": v for k, v in dropped.items()},
        "dropped_no_box_train": len(keep) - len(kept),
        "phash_threshold": 4,
    }
    (OUT / "dataset_stats.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


if __name__ == "__main__":
    print(json.dumps(build(), indent=2, ensure_ascii=False))
