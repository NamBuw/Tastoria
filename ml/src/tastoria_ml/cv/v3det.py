"""Selective V3Det subset for Tastoria's missing Vietnamese produce & tofu classes.

Only downloads the V3Det COCO annotation JSONs and ``image2url`` maps into /dev/shm
(or TASTORIA_STAGE_DIR), selects up to a balanced per-class cap of images containing our
scarce/zero-box target categories (strictly raw produce / bean curd, avoiding cooked-dish
categories), fetches ONLY those selected images via their public Flickr URLs, resizes them
to max_side <= 1024 JPEG, and cleans up all temporary files in /dev/shm.

Annotations & category tree: CC BY 4.0 (Wang et al., ICCV 2023 Oral).
Images: sourced from Bamboo / Flickr subject to Flickr Terms of Use.

Run: ``python -m tastoria_ml.cv.v3det``
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
import os
import random
import re
import shutil
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageOps

from tastoria_ml.cv.classes import REPO

ROOT = REPO / "data" / "raw" / "images" / "v3det"
IMAGES = ROOT / "images"
STAGE = Path(os.environ.get("TASTORIA_STAGE_DIR", "/dev/shm/tastoria_stage_m1/v3det"))
MAX_SIDE = 1024
JPEG_QUALITY = 88
SOURCE = "v3det"
LICENSE = "CC BY 4.0 (annotations) / Flickr ToU (images)"

ANN_URLS = {
    "train": "https://huggingface.co/datasets/yhcao/V3Det_Backup/resolve/main/v3det_2023_v1_train.json",
    "val": "https://huggingface.co/datasets/yhcao/V3Det_Backup/resolve/main/v3det_2023_v1_val.json",
}
URL_LIST_URLS = {
    "train": "https://raw.githubusercontent.com/V3Det/v3det_resource/main/resource/v3det_2023_v1_image2url_train.json",
    "val": "https://raw.githubusercontent.com/V3Det/v3det_resource/main/resource/v3det_2023_v1_image2url_val.json",
}

TARGET_CATS: dict[str, str] = {
    "loofah": "muop",
    "angled loofah": "muop",
    "Chayote": "su_su",
    "Mung bean sprouts": "gia_do",
    "bean sprouts": "gia_do",
    "Soybean sprouts": "gia_do",
    "bok choy": "rau_cai",
    "napa cabbage": "rau_cai",
    "Chinese cabbage": "rau_cai",
    "Big Chinese cabbage": "rau_cai",
    "Small Chinese cabbage": "rau_cai",
    "Chinese kale": "rau_cai",
    "oilseed rape greens": "rau_cai",
    "potherb mustard": "rau_cai",
    "mustard greens": "rau_cai",
    "Small greens": "rau_cai",
    "water spinach": "rau_muong",
    "bean curd": "dau_phu",
    "pork belly": "thit_lon",
    "sparerib": "thit_lon",
    "chicken wings": "thit_ga",
    "chicken leg thigh": "thit_ga",
    "beefsteak": "thit_bo",
    "prawn": "tom",
    "garlic": "toi",
    "Garlic": "toi",
    "chili": "ot",
    "Green chili peppers": "ot",
    "hot pepper": "ot",
    "green onion": "hanh_la",
    "leek": "hanh_la",
    "refrigerator": "__neg__",
}

# Only applied on images ALREADY selected for positive TARGET_CATS so co-occurring produce isn't silently unlabelled.
CO_OCCUR_CATS: dict[str, str] = {
    "tomato": "ca_chua",
    "carrot": "ca_rot",
    "potato": "khoai_tay",
    "head cabbage": "bap_cai",
    "red cabbage": "bap_cai",
    "broccoli": "sup_lo",
    "cauliflower": "sup_lo",
    "pumpkin": "bi_do",
    "winter melon": "bi_dao",
    "wax gourd": "bi_dao",
    "mushroom": "nam",
    "egg": "trung",
}

TRAIN_CAPS: dict[str, int] = {
    "muop": 500,
    "su_su": 500,
    "gia_do": 500,
    "rau_cai": 450,
    "rau_muong": 200,
    "dau_phu": 200,
    "thit_lon": 300,
    "thit_ga": 300,
    "thit_bo": 300,
    "tom": 250,
    "toi": 300,
    "ot": 250,
    "hanh_la": 250,
    "__neg__": 120,
}

VAL_CAPS: dict[str, int] = {k: max(25, v // 4) for k, v in TRAIN_CAPS.items()}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.flickr.com/",
}

_FLICKR_SIZE_RE = re.compile(r"(_[obcz])(\.(?:jpg|jpeg|png))$", re.IGNORECASE)


def _candidate_urls(url: str) -> list[str]:
    """Return primary URL plus Flickr size fallbacks (_o -> _b/_c/_z)."""
    urls = [url]
    m = _FLICKR_SIZE_RE.search(url)
    if m:
        ext = m.group(2)
        prefix = url[: m.start()]
        for suf in ("_b", "_c", "_z"):
            cand = f"{prefix}{suf}{ext}"
            if cand not in urls:
                urls.append(cand)
    return urls


def _fetch_file(url: str, dst: Path) -> Path:
    if dst.exists() and dst.stat().st_size > 0:
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".part")
    req = urllib.request.Request(url, headers={"User-Agent": "tastoria-ml/1.0"})
    with urllib.request.urlopen(req, timeout=180) as r, tmp.open("wb") as f:
        shutil.copyfileobj(r, f, length=1 << 20)
    tmp.rename(dst)
    return dst


def _scale_positive_boxes(
    raw_boxes: list[dict],
    sx: float,
    sy: float,
    w_new: int | None = None,
    h_new: int | None = None,
) -> tuple[list[dict], list[str]]:
    scaled_boxes: list[dict] = []
    ood_labels: set[str] = set()
    seen: set[tuple[str, float, float, float, float]] = set()
    max_w = float(w_new) if w_new is not None else None
    max_h = float(h_new) if h_new is not None else None
    for b in raw_boxes:
        if b["cls"] == "__neg__":
            ood_labels.add(b["cat"])
            continue
        bx, by, bw, bh = b["bbox"]
        x0 = max(0.0, bx * sx)
        y0 = max(0.0, by * sy)
        x1 = (bx + bw) * sx
        y1 = (by + bh) * sy
        if max_w is not None:
            x0 = min(x0, max_w)
            x1 = min(max_w, max(0.0, x1))
        if max_h is not None:
            y0 = min(y0, max_h)
            y1 = min(max_h, max(0.0, y1))
        nw = x1 - x0
        nh = y1 - y0
        if nw >= 2.0 and nh >= 2.0:
            key = (b["cls"], round(x0, 4), round(y0, 4), round(nw, 4), round(nh, 4))
            if key in seen:
                continue
            seen.add(key)
            scaled_boxes.append({**b, "bbox": [x0, y0, nw, nh]})
    return scaled_boxes, sorted(ood_labels)


def _format_record(rec: dict, dst_name: str, w_new: int, h_new: int, used_url: str, boxes: list[dict], ood_labels: list[str]) -> dict:
    is_neg = not boxes
    return {
        "id": rec["id"],
        "stem": dst_name.rsplit(".", 1)[0],
        "source_name": SOURCE,
        "split": rec["split"],
        "split_hint": rec["split"],
        "file": f"images/{dst_name}",
        "width": w_new,
        "height": h_new,
        "license": LICENSE,
        "is_commercial_ok": False,
        "url": used_url,
        "is_neg": is_neg,
        "ood_labels": ood_labels if ood_labels else (["__neg__"] if is_neg else []),
        "boxes": boxes,
    }


def _download_one(task: tuple[dict, Path]) -> tuple[dict, str]:
    rec, dst = task
    if dst.exists():
        try:
            with Image.open(dst) as im:
                w, h = im.size
            sx = w / float(rec["orig_w"] or w)
            sy = h / float(rec["orig_h"] or h)
            scaled_boxes, ood_labels = _scale_positive_boxes(rec["boxes"], sx, sy, w, h)
            if not scaled_boxes and not ood_labels:
                return rec, "empty_after_scale"
            return _format_record(rec, dst.name, w, h, rec["url"], scaled_boxes, ood_labels), "skip"
        except Exception:
            dst.unlink(missing_ok=True)

    last_err = "err"
    last_http: int | None = None
    for cand_url in _candidate_urls(rec["url"]):
        for attempt in range(4):
            try:
                req = urllib.request.Request(cand_url, headers=HEADERS)
                with urllib.request.urlopen(req, timeout=20) as r:
                    raw = r.read()
                if len(raw) < 1000:
                    last_err = "tiny_payload"
                    break
                with Image.open(io.BytesIO(raw)) as im_raw:
                    if im_raw.size == (rec["orig_w"], rec["orig_h"]):
                        im = im_raw.convert("RGB")
                    else:
                        im = ImageOps.exif_transpose(im_raw).convert("RGB")
                    w0, h0 = im.size
                    s = min(1.0, MAX_SIDE / max(w0, h0))
                    if s < 1.0:
                        im = im.resize((max(1, round(w0 * s)), max(1, round(h0 * s))), Image.LANCZOS)
                    w_new, h_new = im.size
                    tmp = dst.with_suffix(".part")
                    im.save(tmp, "JPEG", quality=JPEG_QUALITY)
                    tmp.rename(dst)
                sx = w_new / float(rec["orig_w"] or w0)
                sy = h_new / float(rec["orig_h"] or h0)
                scaled_boxes, ood_labels = _scale_positive_boxes(rec["boxes"], sx, sy, w_new, h_new)
                if not scaled_boxes and not ood_labels:
                    dst.unlink(missing_ok=True)
                    return rec, "empty_after_scale"
                return _format_record(rec, dst.name, w_new, h_new, cand_url, scaled_boxes, ood_labels), "ok"
            except urllib.error.HTTPError as e:
                last_http = e.code
                if e.code == 429 or e.code >= 500:
                    time.sleep(min(8.0, 0.75 * (2**attempt) + random.uniform(0.0, 0.3)))
                    continue
                if e.code in (403, 404, 410):
                    break  # try next Flickr size fallback URL
                break
            except Exception as e:
                last_err = type(e).__name__
                time.sleep(0.3 * (attempt + 1))
                continue
    if last_http is not None and last_err == "err":
        return rec, f"http_{last_http}"
    return rec, f"fail_{last_err}"


def extract(*, force: bool = False, max_workers: int = 4, cached_only: bool = False) -> dict:
    ann_out = ROOT / "annotations.json"
    if ann_out.exists() and not force:
        d = json.loads(ann_out.read_text(encoding="utf-8"))
        return {k: v for k, v in d.items() if k != "records"}

    ROOT.mkdir(parents=True, exist_ok=True)
    IMAGES.mkdir(parents=True, exist_ok=True)
    STAGE.mkdir(parents=True, exist_ok=True)
    all_kept: list[dict] = []
    status_counts: Counter = Counter()

    try:
        for split in ("val", "train"):
            print(f"[v3det] fetching {split} metadata...", flush=True)
            ann_path = _fetch_file(ANN_URLS[split], STAGE / f"v3det_2023_v1_{split}.json")
            url_path = _fetch_file(URL_LIST_URLS[split], STAGE / f"v3det_2023_v1_image2url_{split}.json")

            img2url = ast.literal_eval(url_path.read_text(encoding="utf-8"))
            d = json.loads(ann_path.read_text(encoding="utf-8"))
            cats = {c["id"]: c["name"] for c in d["categories"]}
            target_cids = {cid: TARGET_CATS[name] for cid, name in cats.items() if name in TARGET_CATS}
            co_cids = {cid: CO_OCCUR_CATS[name] for cid, name in cats.items() if name in CO_OCCUR_CATS}
            all_wanted = {**co_cids, **target_cids}

            by_img_target: dict[int, list[dict]] = defaultdict(list)
            by_img_co: dict[int, list[dict]] = defaultdict(list)
            img_has_target_cls: dict[str, set[int]] = defaultdict(set)

            for ann in d["annotations"]:
                cid = ann["category_id"]
                if cid not in all_wanted:
                    continue
                iid = ann["image_id"]
                box_entry = {
                    "cat": cats[cid],
                    "cls": all_wanted[cid],
                    "bbox": [float(v) for v in ann["bbox"]],
                }
                if cid in target_cids:
                    by_img_target[iid].append(box_entry)
                    img_has_target_cls[target_cids[cid]].add(iid)
                else:
                    by_img_co[iid].append(box_entry)

            caps = VAL_CAPS if split == "val" else TRAIN_CAPS
            chosen: set[int] = set()
            for cls_id in sorted(img_has_target_cls, key=lambda k: len(img_has_target_cls[k])):
                ids = sorted(img_has_target_cls[cls_id])
                already = sum(1 for i in ids if i in chosen)
                cap = caps.get(cls_id, 200)
                need = max(0, cap - already)
                if need <= 0:
                    continue
                rest = [i for i in ids if i not in chosen]
                rest.sort(key=lambda i: hashlib.sha1(f"{split}:{i}".encode()).hexdigest())
                chosen.update(rest[:need])

            imgs_by_id = {im["id"]: im for im in d["images"] if im["id"] in chosen}
            tasks = []
            for iid in sorted(chosen):
                im = imgs_by_id[iid]
                fn = im["file_name"]
                url = img2url.get(fn)
                if not url:
                    continue
                safe_name = f"{split}_{iid:07d}.jpg"
                dst_path = IMAGES / safe_name
                if cached_only and not dst_path.exists():
                    continue
                rec = {
                    "id": f"{split}/{iid}",
                    "split": split,
                    "orig_w": int(im["width"]),
                    "orig_h": int(im["height"]),
                    "url": url,
                    "boxes": by_img_target[iid] + by_img_co.get(iid, []),
                }
                tasks.append((rec, dst_path))

            del d, img2url, by_img_target, by_img_co, imgs_by_id
            ann_path.unlink(missing_ok=True)
            url_path.unlink(missing_ok=True)

            print(f"[v3det] downloading {len(tasks)} selected {split} images (workers={max_workers})...", flush=True)
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                for rec_out, st in ex.map(_download_one, tasks):
                    status_counts[f"{split}:{st}"] += 1
                    if st in ("ok", "skip"):
                        all_kept.append(rec_out)
    finally:
        shutil.rmtree(STAGE, ignore_errors=True)

    cls_counts: Counter = Counter()
    split_counts: Counter = Counter()
    ood_counts: Counter = Counter()
    neg_count = 0
    for r in all_kept:
        split_counts[r["split"]] += 1
        if r.get("is_neg"):
            neg_count += 1
        for b in r["boxes"]:
            cls_counts[b["cls"]] += 1
        for ol in r.get("ood_labels", []):
            ood_counts[ol] += 1

    categories = sorted(cls_counts.keys()) + (["__neg__"] if neg_count else [])
    manifest = {
        "schema_version": "m1_v1",
        "source": SOURCE,
        "source_name": SOURCE,
        "license": LICENSE,
        "is_commercial_ok": False,
        "url": "https://v3det.openxlab.org.cn/",
        "categories": categories,
        "images": len(all_kept),
        "neg_images": neg_count,
        "splits": dict(split_counts),
        "statuses": dict(status_counts),
        "boxes_per_class": dict(sorted(cls_counts.items())),
        "ood_images_per_label": dict(sorted(ood_counts.items())),
        "records": all_kept,
    }
    ann_out.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return {k: v for k, v in manifest.items() if k != "records"}


def records() -> list[dict]:
    ann_out = ROOT / "annotations.json"
    if not ann_out.exists():
        return []
    d = json.loads(ann_out.read_text(encoding="utf-8"))
    out: list[dict] = []
    for r in d["records"]:
        rel = Path(r["file"])
        p = ROOT / rel if (ROOT / rel).exists() else IMAGES / rel.name
        if p.exists():
            boxes = r.get("boxes", [])
            out.append({
                **r,
                "source": SOURCE,
                "source_name": r.get("source_name", SOURCE),
                "split_hint": r.get("split_hint", r.get("split", "train")),
                "license": r.get("license", LICENSE),
                "is_commercial_ok": r.get("is_commercial_ok", False),
                "is_neg": r.get("is_neg", not boxes),
                "ood_labels": r.get("ood_labels", ["__neg__"] if not boxes else []),
                "path": p,
            })
    return out


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--cached-only", action="store_true")
    args = ap.parse_args()
    print(
        json.dumps(
            extract(force=args.force, max_workers=args.workers, cached_only=args.cached_only),
            indent=2,
            ensure_ascii=False,
        )
    )
