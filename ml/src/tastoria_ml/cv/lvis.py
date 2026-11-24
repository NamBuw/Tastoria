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
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from tastoria_ml.cv.classes import REPO

ROOT = REPO / "data" / "raw" / "images" / "lvis_v1"
ANN = ROOT / "ann"
IMAGES = ROOT / "images"
SOURCE = "lvis_v1"
SPLIT_FILES = {"train": "lvis_v1_train.json", "val": "lvis_v1_val.json"}
CAP = {"train": 600, "val": 150}
MAX_SIDE = 1024
JPEG_QUALITY = 88

NEG_CLEAN_IMAGES = ROOT / "images_neg_clean"
NEG_CLEAN_ANN = ROOT / "annotations_neg.json"
PRAWN_AUDIT_DIR = ROOT / "prawn_audit"
PRAWN_AUDIT_JSON = ROOT / "prawn_audit.json"

LVIS_OOD_CATS_CLEAN: tuple[str, ...] = (
    "apple",
    "banana",
    "orange_(fruit)",
    "pear",
    "cucumber",
    "pineapple",
    "watermelon",
    "radish",
    "zucchini",
    "avocado",
    "celery",
    "edible_corn",
    "eggplant",
)

LVIS_LOOKALIKE_NEG: tuple[str, ...] = (
    "tomato",
    "carrot",
    "potato",
    "lemon",
    "lime",
    "chili_(vegetable)",
    "garlic",
)

COOKED_OR_DINING_EXCL: tuple[str, ...] = (
    "pizza",
    "sandwich",
    "hamburger",
    "taco",
    "burrito",
    "lasagna",
    "soup",
    "salad",
    "stew",
    "omelet",
    "tortilla",
    "French_toast",
    "toast_(food)",
    "pancake",
    "waffle",
    "boiled_egg",
    "egg_roll",
    "patty_(food)",
    "rib_(food)",
    "steak_(food)",
    "cake",
    "birthday_cake",
    "chocolate_cake",
    "wedding_cake",
    "pie",
    "cupcake",
    "doughnut",
    "cookie",
    "dining_table",
    "kitchen_table",
    "table",
    "tablecloth",
    "place_mat",
    "plate",
    "paper_plate",
    "salad_plate",
    "platter",
    "bowl",
    "soup_bowl",
    "sugar_bowl",
    "dish",
    "fork",
    "knife",
    "steak_knife",
    "spoon",
    "soupspoon",
    "wooden_spoon",
    "chopstick",
    "napkin",
    "cup",
    "teacup",
    "mug",
    "wineglass",
    "flute_glass",
    "shot_glass",
    "glass_(drink_container)",
    "frying_pan",
    "pan_(for_cooking)",
    "saucepan",
    "stove",
    "hotplate",
    "saucer",
    "toaster_oven",
    "toaster",
    "microwave_oven",
    "oven",
    "food_processor",
    "prawn",
    "crab_(animal)",
    "crabmeat",
    "crawfish",
    "octopus_(animal)",
    "octopus_(food)",
    "squid_(food)",
    "fish_(food)",
)

# Populated ONLY after visual contact-sheet inspection of prawn_audit_sheet.jpg
RAW_PRAWN_ALLOWLIST: tuple[int, ...] = ()


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


def _is_commercial_lvis(lic_name: str) -> bool:
    low = (lic_name or "").strip().lower()
    return bool(low) and ("noncommercial" not in low) and ("-nc" not in low)


def _download_resized(url: str, dst: Path) -> tuple[int, int] | None:
    from PIL import Image

    if dst.exists():
        try:
            with Image.open(dst) as im:
                return im.size
        except Exception:
            dst.unlink(missing_ok=True)
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        with Image.open(io.BytesIO(r.content)) as im_raw:
            im = im_raw.convert("RGB")
            im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
            w, h = im.size
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_suffix(".part")
            im.save(tmp, "JPEG", quality=JPEG_QUALITY)
            tmp.rename(dst)
        return w, h
    except Exception:  # noqa: BLE001
        return None


def fetch_neg_clean(
    *,
    target_total: int = 500,
    workers: int = 16,
    force: bool = False,
    train_json: Path | None = None,
) -> dict:
    """Select and download clean raw-produce OOD images (excluding pizza/cooked/dining & mapped classes)."""
    if NEG_CLEAN_ANN.exists() and not force:
        d = json.loads(NEG_CLEAN_ANN.read_text(encoding="utf-8"))
        return {k: v for k, v in d.items() if k != "records"}

    src_json = train_json or (ANN / "lvis_v1_train.json")
    if not src_json.exists():
        raise FileNotFoundError(f"LVIS train JSON not found: {src_json}")

    existing_ids: set[int] = set()
    for fn in ("train-selected.json", "val-selected.json"):
        p = ANN / fn
        if p.exists():
            existing_ids.update(im["id"] for im in json.loads(p.read_text(encoding="utf-8"))["images"])

    lab = label_map()
    d = json.loads(src_json.read_text(encoding="utf-8"))
    name_to_cid = {c["name"]: c["id"] for c in d["categories"]}
    mapped_cids = {name_to_cid[n] for n in lab if n in name_to_cid}
    excl_cids = {name_to_cid[n] for n in COOKED_OR_DINING_EXCL if n in name_to_cid} | mapped_cids
    ood_cids = {n: name_to_cid[n] for n in LVIS_OOD_CATS_CLEAN if n in name_to_cid}
    ood_cid_to_name = {cid: n for n, cid in ood_cids.items()}
    lookalike_neg_cids = {name_to_cid[n] for n in LVIS_LOOKALIKE_NEG if n in name_to_cid}

    excluded_imgs: set[int] = set(existing_ids)
    ood_by_cat: dict[str, set[int]] = defaultdict(set)
    for ann in d["annotations"]:
        iid = ann["image_id"]
        cid = ann["category_id"]
        if cid in excl_cids:
            excluded_imgs.add(iid)
        elif cid in ood_cid_to_name:
            ood_by_cat[ood_cid_to_name[cid]].add(iid)

    imgs = {im["id"]: im for im in d["images"]}
    lic_names = {x["id"]: x["name"] for x in d["licenses"]}

    eligible_by_cat: dict[str, list[tuple[int, int, int]]] = {}
    for oname, iids in ood_by_cat.items():
        ranked: list[tuple[int, int, int]] = []
        for iid in iids:
            if iid in excluded_imgs:
                continue
            im = imgs.get(iid)
            if not im or not im.get("coco_url"):
                continue
            ne = set(im.get("not_exhaustive_category_ids", []))
            if ne & excl_cids:
                continue
            neg = set(im.get("neg_category_ids", []))
            score = len(neg & lookalike_neg_cids)
            lic_name = lic_names.get(im.get("license"), "")
            comm_flag = 1 if _is_commercial_lvis(lic_name) else 0
            ranked.append((comm_flag, score, iid))
        ranked.sort(
            key=lambda x: (-x[0], -x[1], hashlib.sha1(f"lvis_neg_clean:{oname}:{x[2]}".encode()).hexdigest())
        )
        eligible_by_cat[oname] = ranked

    per_cat_cap = max(1, target_total // max(1, len(LVIS_OOD_CATS_CLEAN)))
    chosen_ids: set[int] = set()
    chosen_meta: list[dict] = []

    for oname in LVIS_OOD_CATS_CLEAN:
        cnt = 0
        for comm_flag, _score, iid in eligible_by_cat.get(oname, []):
            if cnt >= per_cat_cap:
                break
            if iid in chosen_ids:
                continue
            chosen_ids.add(iid)
            im = imgs[iid]
            lic_name = lic_names.get(im.get("license"), "")
            chosen_meta.append({
                "id": iid,
                "ood_cat": oname,
                "coco_url": im["coco_url"],
                "flickr_url": im.get("flickr_url", ""),
                "license_name": lic_name,
                "is_commercial_ok": bool(comm_flag),
            })
            cnt += 1

    if len(chosen_meta) < target_total:
        for oname in LVIS_OOD_CATS_CLEAN:
            for comm_flag, _score, iid in eligible_by_cat.get(oname, []):
                if len(chosen_meta) >= target_total:
                    break
                if iid in chosen_ids:
                    continue
                chosen_ids.add(iid)
                im = imgs[iid]
                lic_name = lic_names.get(im.get("license"), "")
                chosen_meta.append({
                    "id": iid,
                    "ood_cat": oname,
                    "coco_url": im["coco_url"],
                    "flickr_url": im.get("flickr_url", ""),
                    "license_name": lic_name,
                    "is_commercial_ok": bool(comm_flag),
                })

    NEG_CLEAN_IMAGES.mkdir(parents=True, exist_ok=True)

    def _task(m: dict) -> dict | None:
        fn = f"{m['id']:012d}.jpg"
        wh = _download_resized(m["coco_url"], NEG_CLEAN_IMAGES / fn)
        if wh is None:
            return None
        w, h = wh
        return {
            "id": f"lvis_v1_neg/train/{m['id']}",
            "coco_id": m["id"],
            "stem": f"{m['id']:012d}",
            "source_name": "lvis_v1_neg",
            "split": "train",
            "split_hint": "train",
            "file": f"images_neg_clean/{fn}",
            "width": w,
            "height": h,
            "license": m["license_name"],
            "is_commercial_ok": m["is_commercial_ok"],
            "url": m["flickr_url"] or m["coco_url"],
            "is_neg": True,
            "ood_labels": [m["ood_cat"]],
            "boxes": [],
        }

    with ThreadPoolExecutor(max_workers=workers) as ex:
        out_records = [r for r in ex.map(_task, chosen_meta) if r is not None]

    kept_files = {Path(r["file"]).name for r in out_records}
    for old_file in NEG_CLEAN_IMAGES.iterdir():
        if old_file.is_file() and old_file.name not in kept_files:
            old_file.unlink(missing_ok=True)

    ood_counts = Counter(r["ood_labels"][0] for r in out_records)
    comm_cnt = sum(1 for r in out_records if r["is_commercial_ok"])
    is_comm_top: bool | str
    if out_records and comm_cnt == len(out_records):
        is_comm_top = True
    elif comm_cnt == 0:
        is_comm_top = False
    else:
        is_comm_top = "mixed"

    manifest = {
        "schema_version": "m1_v1",
        "source": "lvis_v1_neg",
        "source_name": "lvis_v1_neg",
        "license": "CC BY 4.0 (LVIS ann) / COCO Flickr (per-image)",
        "is_commercial_ok": is_comm_top,
        "url": "https://www.lvisdataset.org/",
        "categories": ["__neg__"],
        "images": len(out_records),
        "neg_images": len(out_records),
        "splits": {"train": len(out_records)} if out_records else {},
        "boxes_per_class": {},
        "ood_images_per_label": dict(sorted(ood_counts.items())),
        "commercial_ok_images": comm_cnt,
        "records": out_records,
    }
    NEG_CLEAN_ANN.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    print(f"[lvis_neg_clean] ready: {len(out_records)}/{len(chosen_meta)} (comm_ok={comm_cnt})", flush=True)
    return {k: v for k, v in manifest.items() if k != "records"}


def neg_records(*, commercial_only: bool = False) -> list[dict]:
    """Clean pizza-free LVIS OOD negative records."""
    if not NEG_CLEAN_ANN.exists():
        return []
    d = json.loads(NEG_CLEAN_ANN.read_text(encoding="utf-8"))
    out: list[dict] = []
    for r in d["records"]:
        if commercial_only and not r.get("is_commercial_ok", False):
            continue
        p = ROOT / r["file"]
        if p.exists():
            out.append({**r, "source": "lvis_v1_neg", "path": p})
    return out


def audit_prawn(
    *,
    workers: int = 16,
    include_nc: bool = True,
    force: bool = False,
    train_json: Path | None = None,
    val_json: Path | None = None,
) -> dict:
    """Filter exhaustive LVIS prawn images excluding cooked/dining categories for visual audit."""
    if PRAWN_AUDIT_JSON.exists() and not force:
        d = json.loads(PRAWN_AUDIT_JSON.read_text(encoding="utf-8"))
        return {k: v for k, v in d.items() if k != "records"}

    split_paths = {
        "train": train_json or (ANN / "lvis_v1_train.json"),
        "val": val_json or (ANN / "lvis_v1_val.json"),
    }
    candidates: list[dict] = []
    stats_by_split: dict[str, dict[str, int]] = {}

    for split, json_path in split_paths.items():
        if not json_path.exists():
            continue
        d = json.loads(json_path.read_text(encoding="utf-8"))
        cats = {c["id"]: c["name"] for c in d["categories"]}
        name_to_cid = {n: cid for cid, n in cats.items()}
        prawn_cid = name_to_cid.get("prawn")
        if prawn_cid is None:
            continue
        excl_cids = {
            name_to_cid[n]
            for n in COOKED_OR_DINING_EXCL
            if n in name_to_cid and name_to_cid[n] != prawn_cid
        }

        prawn_boxes: dict[int, list[dict]] = defaultdict(list)
        all_cats_by_img: dict[int, set[int]] = defaultdict(set)
        for a in d["annotations"]:
            iid = a["image_id"]
            cid = a["category_id"]
            all_cats_by_img[iid].add(cid)
            if cid == prawn_cid:
                prawn_boxes[iid].append({"cat": "prawn", "cls": "tom", "bbox": [float(v) for v in a["bbox"]]})

        imgs = {im["id"]: im for im in d["images"]}
        lic_names = {x["id"]: x["name"] for x in d["licenses"]}
        n_total = len(prawn_boxes)
        n_exhaustive = 0
        n_clean = 0
        n_comm = 0

        for iid in sorted(prawn_boxes):
            im = imgs[iid]
            ne = set(im.get("not_exhaustive_category_ids", []))
            if prawn_cid in ne:
                continue
            n_exhaustive += 1
            if (all_cats_by_img[iid] | ne) & excl_cids:
                continue
            n_clean += 1
            lic_name = lic_names.get(im.get("license"), "")
            is_comm = _is_commercial_lvis(lic_name)
            if is_comm:
                n_comm += 1
            elif not include_nc:
                continue
            candidates.append({
                "coco_id": iid,
                "lvis_split": split,
                "split": our_split(iid, split),
                "coco_url": im["coco_url"],
                "flickr_url": im.get("flickr_url", ""),
                "orig_w": int(im["width"]),
                "orig_h": int(im["height"]),
                "license_name": lic_name,
                "is_commercial_ok": is_comm,
                "co_categories": sorted(cats[c] for c in all_cats_by_img[iid] if c != prawn_cid),
                "boxes": prawn_boxes[iid],
            })
        stats_by_split[split] = {
            "total": n_total,
            "exhaustive": n_exhaustive,
            "non_tableware": n_clean,
            "commercial_ok_non_tableware": n_comm,
        }

    PRAWN_AUDIT_DIR.mkdir(parents=True, exist_ok=True)

    def _dl_prawn(c: dict) -> dict | None:
        fn = f"{c['coco_id']:012d}.jpg"
        wh = _download_resized(c["coco_url"], PRAWN_AUDIT_DIR / fn)
        if wh is None:
            return None
        w, h = wh
        sx = w / float(c["orig_w"])
        sy = h / float(c["orig_h"])
        scaled = [
            {**b, "bbox": [b["bbox"][0] * sx, b["bbox"][1] * sy, b["bbox"][2] * sx, b["bbox"][3] * sy]}
            for b in c["boxes"]
        ]
        return {
            "id": f"lvis_v1_prawn/{c['lvis_split']}/{c['coco_id']}",
            "coco_id": c["coco_id"],
            "stem": f"{c['coco_id']:012d}",
            "source_name": "lvis_v1_prawn",
            "lvis_split": c["lvis_split"],
            "split": c["split"],
            "split_hint": c["split"],
            "file": f"prawn_audit/{fn}",
            "width": w,
            "height": h,
            "license": c["license_name"],
            "is_commercial_ok": c["is_commercial_ok"],
            "url": c["flickr_url"] or c["coco_url"],
            "is_neg": False,
            "ood_labels": [],
            "co_categories": c["co_categories"],
            "boxes": scaled,
        }

    with ThreadPoolExecutor(max_workers=workers) as ex:
        out_records = [r for r in ex.map(_dl_prawn, candidates) if r is not None]

    manifest = {
        "schema_version": "m1_v1",
        "source": "lvis_v1_prawn_audit",
        "source_name": "lvis_v1_prawn",
        "license": "CC BY 4.0 (LVIS ann) / COCO Flickr (per-image)",
        "is_commercial_ok": "mixed",
        "url": "https://www.lvisdataset.org/",
        "categories": ["tom"] if out_records else [],
        "images": len(out_records),
        "neg_images": 0,
        "splits": dict(Counter(r["split_hint"] for r in out_records)),
        "boxes_per_class": {"tom": sum(len(r["boxes"]) for r in out_records)} if out_records else {},
        "stats_by_split": stats_by_split,
        "records": out_records,
    }
    PRAWN_AUDIT_JSON.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    print(f"[lvis_prawn_audit] stats={stats_by_split}, downloaded={len(out_records)}", flush=True)
    return {k: v for k, v in manifest.items() if k != "records"}


def prawn_contact_sheet(out_path: Path, *, cols: int = 5, rows: int = 5, tile_size: int = 384) -> Path:
    """Render visual audit contact sheet for all LVIS non-tableware prawn candidates."""
    from tastoria_ml.cv.hf_kaggle_ingest import render_contact_sheet

    if not PRAWN_AUDIT_JSON.exists():
        audit_prawn()
    d = json.loads(PRAWN_AUDIT_JSON.read_text(encoding="utf-8"))
    recs = [{**r, "path": ROOT / r["file"]} for r in d["records"] if (ROOT / r["file"]).exists()]
    return render_contact_sheet(
        recs,
        out_path,
        title="LVIS v1 prawn audit (non-tableware candidates -> tom?)",
        cols=cols,
        rows=rows,
        tile_size=tile_size,
        seed=0,
        target_cls="tom",
    )


def prawn_records(*, commercial_only: bool = True) -> list[dict]:
    """Return ONLY visually verified raw uncooked LVIS prawn records in RAW_PRAWN_ALLOWLIST."""
    if not RAW_PRAWN_ALLOWLIST or not PRAWN_AUDIT_JSON.exists():
        return []
    allow = set(RAW_PRAWN_ALLOWLIST)
    d = json.loads(PRAWN_AUDIT_JSON.read_text(encoding="utf-8"))
    out: list[dict] = []
    for r in d["records"]:
        if int(r["coco_id"]) not in allow:
            continue
        if commercial_only and not r.get("is_commercial_ok", False):
            continue
        p = ROOT / r["file"]
        if p.exists():
            out.append({**r, "source": "lvis_v1", "path": p})
    return out


def export_annotations() -> dict:
    """Write standardized m1_v1 data/raw/images/lvis_v1/annotations.json without altering ann/*-selected.json."""
    recs = records()
    out_records: list[dict] = []
    cls_counts: Counter = Counter()
    split_counts: Counter = Counter()
    comm_cnt = 0
    for r in recs:
        lic_name = r.get("license_name", "")
        is_comm = _is_commercial_lvis(lic_name)
        if is_comm:
            comm_cnt += 1
        sp = r["split"]
        split_counts[sp] += 1
        for b in r["boxes"]:
            cls_counts[b["cls"]] += 1
        out_records.append({
            "id": f"lvis_v1/{r['lvis_split']}/{r['id']}",
            "coco_id": r["id"],
            "stem": f"{r['id']:012d}",
            "source_name": "lvis_v1",
            "split": sp,
            "split_hint": sp,
            "file": f"images/{r['id']:012d}.jpg",
            "width": r["width"],
            "height": r["height"],
            "license": lic_name,
            "is_commercial_ok": is_comm,
            "url": r.get("flickr_url") or r.get("coco_url") or "",
            "is_neg": False,
            "ood_labels": [],
            "boxes": r["boxes"],
        })

    is_comm_top: bool | str
    if out_records and comm_cnt == len(out_records):
        is_comm_top = True
    elif comm_cnt == 0:
        is_comm_top = False
    else:
        is_comm_top = "mixed"

    manifest = {
        "schema_version": "m1_v1",
        "source": SOURCE,
        "source_name": SOURCE,
        "license": "CC BY 4.0 (LVIS ann) / COCO Flickr (per-image)",
        "is_commercial_ok": is_comm_top,
        "url": "https://www.lvisdataset.org/",
        "categories": sorted(cls_counts.keys()),
        "images": len(out_records),
        "neg_images": 0,
        "splits": dict(split_counts),
        "boxes_per_class": dict(sorted(cls_counts.items())),
        "commercial_ok_images": comm_cnt,
        "records": out_records,
    }
    (ROOT / "annotations.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return {k: v for k, v in manifest.items() if k != "records"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "step",
        choices=["select", "images", "all", "neg-clean", "audit-prawn", "export-annotations"],
    )
    a = ap.parse_args()
    if a.step in ("select", "all"):
        print(json.dumps(select(), indent=1))
    if a.step in ("images", "all"):
        fetch_images()
    if a.step == "neg-clean":
        print(json.dumps(fetch_neg_clean(), indent=2))
    if a.step == "audit-prawn":
        print(json.dumps(audit_prawn(), indent=2))
    if a.step == "export-annotations":
        print(json.dumps(export_annotations(), indent=2))


if __name__ == "__main__":
    main()
