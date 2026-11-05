"""LVIS v1 subset for the v2 detector data (data/raw/images/lvis_v1/, see SOURCE.md there).

Only the annotation JSONs (dl.fbaipublicfiles.com/LVIS) and the COCO 2017 images that carry a mapped label are
downloaded (images.cocodataset.org, one file per image), not the 20 GB COCO archives.

LVIS is *federated*: an image is exhaustively labelled only for the categories in its positive set; any other
category may be present without a box. We therefore
  * drop an image when one of its mapped categories is listed in ``not_exhaustive_category_ids``
    (some instances of that category have no box);
  * accept that objects of *other* Tastoria classes in a kept image may be unlabelled (recorded in SOURCE.md).

Selection: rare classes first, at most ``CAP[split]`` images per Tastoria class (an image counts for every class
it has). LVIS train -> our train/val (val = 10 % by a hash of the image id); LVIS val (= COCO val2017) -> our
per-source held-out set.

Run: ``python -m tastoria_ml.cv.lvis {select,images,all}``
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import random
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import requests

from tastoria_ml.cv.classes import REPO

ROOT = REPO / "data" / "raw" / "images" / "lvis_v1"
ANN = ROOT / "ann"
IMAGES = ROOT / "images"
SOURCE = "lvis_v1"
SPLIT_FILES = {"train": "lvis_v1_train.json", "val": "lvis_v1_val.json"}
CAP = {"train": 600, "val": 150}
MAX_SIDE = 1024


def label_map() -> dict[str, str]:
    """LVIS category name -> Tastoria class id, over ``classes`` and ``proposed_classes``."""
    from tastoria_ml.cv.build_yolo_v2 import all_class_rows

    out: dict[str, str] = {}
    for c in all_class_rows():
        for lab in (c.get("public_data") or {}).get(SOURCE, []):
            if lab in out:
                raise ValueError(f"{lab} mapped twice")
            out[lab] = c["id"]
    return out


def our_split(image_id: int, lvis_split: str) -> str:
    if lvis_split == "val":
        return "heldout"
    h = int(hashlib.sha1(str(image_id).encode()).hexdigest(), 16) % 10
    return "val" if h == 0 else "train"


def select(seed: int = 0) -> dict:
    lab = label_map()
    rng = random.Random(seed)
    report = {}
    for split, fn in SPLIT_FILES.items():
        d = json.loads((ANN / fn).read_text())
        cats = {c["id"]: c["name"] for c in d["categories"]}
        missing = set(lab) - set(cats.values())
        if missing:
            raise ValueError(f"not LVIS categories: {sorted(missing)}")
        wanted = {cid for cid, n in cats.items() if n in lab}
        boxes: dict[int, list] = defaultdict(list)
        for a in d["annotations"]:
            if a["category_id"] in wanted:
                boxes[a["image_id"]].append({"cat": cats[a["category_id"]], "bbox": a["bbox"]})
        imgs = {im["id"]: im for im in d["images"]}
        dropped_ne = 0
        by_class: dict[str, set[int]] = defaultdict(set)
        for iid, bs in boxes.items():
            ne = {cats[c] for c in imgs[iid].get("not_exhaustive_category_ids", [])}
            if any(b["cat"] in ne for b in bs):
                dropped_ne += 1
                continue
            for b in bs:
                by_class[lab[b["cat"]]].add(iid)
        chosen: set[int] = set()
        for c in sorted(by_class, key=lambda k: len(by_class[k])):
            ids = sorted(by_class[c])
            already = sum(i in chosen for i in ids)
            rest = [i for i in ids if i not in chosen]
            rng.shuffle(rest)
            chosen.update(rest[: max(0, CAP[split] - already)])
        sel = []
        for iid in sorted(chosen):
            im = imgs[iid]
            sel.append({
                "id": iid, "lvis_split": split, "split": our_split(iid, split), "coco_url": im["coco_url"],
                "flickr_url": im.get("flickr_url", ""), "license": im["license"], "width": im["width"],
                "height": im["height"], "boxes": boxes[iid],
            })
        (ANN / f"{split}-selected.json").write_text(json.dumps({"licenses": d["licenses"], "images": sel}))
        report[split] = {
            "images": len(sel), "dropped_not_exhaustive": dropped_ne,
            "images_per_class": {c: len(v & chosen) for c, v in sorted(by_class.items())},
            "available_per_class": {c: len(v) for c, v in sorted(by_class.items())},
        }
    (ANN / "selection_report.json").write_text(json.dumps(report, indent=2))
    return report


def _download(im: dict) -> str:
    from PIL import Image

    dst = IMAGES / f"{im['id']:012d}.jpg"
    if dst.exists():
        return "skip"
    try:
        r = requests.get(im["coco_url"], timeout=60)
        r.raise_for_status()
        pic = Image.open(io.BytesIO(r.content))
        pic.load()
        if max(pic.size) > MAX_SIDE:  # COCO images are ≤ 640 px; kept as downloaded otherwise
            raise ValueError("unexpected size")
        tmp = dst.with_suffix(".part")
        tmp.write_bytes(r.content)
        tmp.rename(dst)
        return "ok"
    except Exception as e:  # noqa: BLE001 - counted and skipped
        return f"fail {type(e).__name__}"


def fetch_images(workers: int = 16) -> dict:
    IMAGES.mkdir(parents=True, exist_ok=True)
    out = {}
    for split in SPLIT_FILES:
        sel = json.loads((ANN / f"{split}-selected.json").read_text())["images"]
        with ThreadPoolExecutor(workers) as ex:
            res = list(ex.map(_download, sel))
        st: dict[str, int] = {}
        for r in res:
            st[r] = st.get(r, 0) + 1
        out[split] = st
    print(out)
    return out


def records() -> list[dict]:
    """Downloaded images with their boxes (pixel xywh) and Tastoria class ids."""
    lab = label_map()
    out = []
    for split in SPLIT_FILES:
        d = json.loads((ANN / f"{split}-selected.json").read_text())
        lic = {x["id"]: x["name"] for x in d["licenses"]}
        for im in d["images"]:
            p = IMAGES / f"{im['id']:012d}.jpg"
            if p.exists():
                out.append({**im, "path": p, "license_name": lic.get(im["license"], ""),
                            "boxes": [{**b, "cls": lab[b["cat"]]} for b in im["boxes"]]})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["select", "images", "all"])
    a = ap.parse_args()
    if a.step in ("select", "all"):
        print(json.dumps(select(), indent=1))
    if a.step in ("images", "all"):
        fetch_images()


if __name__ == "__main__":
    main()
