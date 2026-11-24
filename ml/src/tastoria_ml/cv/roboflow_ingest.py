"""Ingest and clean curated Roboflow Universe datasets for Tastoria yolo_v3.

Reads ROBOFLOW_API_KEY exclusively from the environment (never persisted to disk).
Stages large export zips in /dev/shm (or TASTORIA_STAGE_DIR) to protect root disk space,
collapses Roboflow augmented copies (`.rf.<hash>`) down to one color-preferred copy per
original base image, strips unmapped labels while retaining pure hard-negative OOD images
for mapped distractors, and writes resized (<= 1024 px) JPEGs + pixel xywh COCO boxes under
data/raw/images/roboflow/<source>/.

Run: ``ROBOFLOW_API_KEY=... python -m tastoria_ml.cv.roboflow_ingest``
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import urllib.request
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml
from PIL import Image, ImageOps

from tastoria_ml.cv.classes import REPO

ROOT = REPO / "data" / "raw" / "images" / "roboflow"
STAGE = Path(os.environ.get("TASTORIA_STAGE_DIR", "/dev/shm/tastoria_stage_m1/roboflow"))
MAX_SIDE = 1024
RF_HASH_RE = re.compile(r"\.rf\.[0-9a-fA-F]+$")
USER_AGENT = "tastoria-ml/1.0"


@dataclass(frozen=True)
class SourceSpec:
    name: str
    workspace: str
    project: str
    version: int
    fmt: str  # "yolov8" | "yolo26" | "coco"
    license: str
    url: str
    class_map: dict[str, str]
    distractors: tuple[str, ...] = ()
    max_images: int | None = None
    scarce_cap: int | None = None
    common_cap: int | None = None
    max_neg_images: int = 120
    exif_mode: str = "auto"  # "auto" | "transpose" | "raw"
    is_commercial_ok: bool = True


SCARCE_CLASSES = frozenset({
    "thit_lon",
    "thit_ga",
    "thit_bo",
    "dau_phu",
    "rau_cai",
    "rau_muong",
    "su_su",
    "muop",
    "gia_do",
    "hanh_la",
    "toi",
    "ot",
    "muop_dang",
})


SOURCES: tuple[SourceSpec, ...] = (
    SourceSpec(
        name="nhan_dien_rau",
        workspace="khai-pha-du-lieu",
        project="nhan-dien-rau-p2y8s",
        version=6,
        fmt="coco",
        license="CC BY 4.0",
        url="https://universe.roboflow.com/khai-pha-du-lieu/nhan-dien-rau-p2y8s",
        class_map={
            "rau_muong": "rau_muong",
            "rau_cai_bap": "bap_cai",
        },
        distractors=("rau_mung_toi", "rau_xa_lach", "rau_ngai_cuu"),
        max_neg_images=100,
    ),
    SourceSpec(
        name="water_spinach",
        workspace="fishdetect-q6amf",
        project="water-spinach-disease-7a5pr",
        version=1,
        fmt="yolov8",
        license="CC BY 4.0",
        url="https://universe.roboflow.com/fishdetect-q6amf/water-spinach-disease-7a5pr",
        class_map={
            "Water Spinach Fresh": "rau_muong",
            "Water Spinach NonFresh": "rau_muong",
            "water-spinach-disease": "rau_muong",
        },
        max_images=700,
        max_neg_images=0,
    ),
    SourceSpec(
        name="viet_hoang",
        workspace="viet-hoang-food",
        project="food-ingredient-detection-mnc5n",
        version=1,
        fmt="yolov8",
        license="CC BY 4.0",
        url="https://universe.roboflow.com/viet-hoang-food/food-ingredient-detection-mnc5n",
        class_map={
            "pork": "thit_lon",
            "pork belly": "thit_lon",
            "pork rib": "thit_lon",
            "beef": "thit_bo",
            "chicken breast": "thit_ga",
            "chicken wing": "thit_ga",
            "bean sprout": "gia_do",
            "bok choy": "rau_cai",
            "spring onion": "hanh_la",
            "chilli": "ot",
            "jalepeno": "ot",
            "garlic": "toi",
            "lemon": "chanh",
            "fish": "ca",
            "salmon": "ca",
            "tuna": "ca",
            "shrimp": "tom",
            "egg": "trung",
            "cabbage": "bap_cai",
            "broccoli": "sup_lo",
            "cauliflower": "sup_lo",
            "tomato": "ca_chua",
            "carrot": "ca_rot",
            "potato": "khoai_tay",
            "pumpkin": "bi_do",
            "mushroom": "nam",
            "milk": "sua",
            "yogurt": "sua_chua",
            "bread": "banh_mi",
        },
        distractors=("onion", "bell pepper", "green pepper", "cucumber", "eggplant", "apple", "banana", "orange"),
        max_neg_images=150,
    ),
    SourceSpec(
        name="aicook",
        workspace="aicook",
        project="aicook-lcv4d",
        version=1,
        fmt="coco",
        license="MIT",
        url="https://universe.roboflow.com/aicook/aicook-lcv4d",
        class_map={
            "beef": "thit_bo",
            "ground_beef": "thit_bo",
            "chicken": "thit_ga",
            "chicken_breast": "thit_ga",
            "eggs": "trung",
            "shrimp": "tom",
            "lime": "chanh",
            "milk": "sua",
            "mushrooms": "nam",
            "tomato": "ca_chua",
            "carrot": "ca_rot",
            "potato": "khoai_tay",
            "green_beans": "dau_que",
            "bread": "banh_mi",
        },
        distractors=("onion", "apple", "banana"),
        max_neg_images=100,
    ),
    SourceSpec(
        name="tofu_oo",
        workspace="oo-workspace",
        project="tofu-detection",
        version=3,
        fmt="yolov8",
        license="CC BY 4.0",
        url="https://universe.roboflow.com/oo-workspace/tofu-detection",
        class_map={"Tofu": "dau_phu"},
        max_images=700,
        max_neg_images=0,
    ),
    SourceSpec(
        name="food_start",
        workspace="test-image-preprocessing",
        project="food-ingredient-detection-start",
        version=1,
        fmt="coco",
        license="CC BY 4.0",
        url="https://universe.roboflow.com/test-image-preprocessing/food-ingredient-detection-start",
        class_map={
            "chayote": "su_su",
            "pork belly": "thit_lon",
            "chicken breast": "thit_ga",
            "chicken thigh": "thit_ga",
            "chicken wing": "thit_ga",
            "tofu": "dau_phu",
            "bok choy": "rau_cai",
            "bitter gourd": "muop_dang",
            "chilli": "ot",
            "garlic": "toi",
            "lemon": "chanh",
            "broccoli": "sup_lo",
            "cauliflower": "sup_lo",
            "carrot": "ca_rot",
            "egg": "trung",
            "mushroom": "nam",
            "pumpkin": "bi_do",
            "shrimp": "tom",
            "tomato": "ca_chua",
            "salmon": "ca",
            "tuna": "ca",
        },
        distractors=("onion", "cucumber", "eggplant", "apple", "banana", "orange"),
        max_neg_images=120,
    ),
    SourceSpec(
        name="meat_thesis",
        workspace="thesis-6tgwg",
        project="meat-data-sets",
        version=3,
        fmt="yolo26",
        license="CC BY 4.0",
        url="https://universe.roboflow.com/thesis-6tgwg/meat-data-sets",
        class_map={
            "Pork Belly": "thit_lon",
            "Pork Leg": "thit_lon",
            "Pork Ribs": "thit_lon",
            "Beef": "thit_bo",
            "Shrimp": "tom",
            "Bangus": "ca",
            "Galungong": "ca",
            "Tilapia": "ca",
        },
        max_neg_images=0,
    ),
    SourceSpec(
        name="robo1",
        workspace="robo1-s-workspace",
        project="ingredients-b5dkh",
        version=1,
        fmt="yolov8",
        license="CC BY 4.0",
        url="https://universe.roboflow.com/robo1-s-workspace/ingredients-b5dkh",
        class_map={
            "pork": "thit_lon",
            "pork_belly": "thit_lon",
            "pork_hock": "thit_lon",
            "pork_shoulder": "thit_lon",
            "ground_pork": "thit_lon",
            "chicken": "thit_ga",
            "beef": "thit_bo",
            "beef_chuck": "thit_bo",
            "bok_choy": "rau_cai",
            "kangkong": "rau_muong",
            "kangkong_leaves": "rau_muong",
            "scallion": "hanh_la",
            "chilli": "ot",
            "long_green_pepper": "ot",
            "garlic": "toi",
            "bitter_gourd": "muop_dang",
            "lemon": "chanh",
            "lime": "chanh",
            "calamansi": "chanh",
            "cabbage": "bap_cai",
            "red_cabbage": "bap_cai",
            "carrot": "ca_rot",
            "egg": "trung",
            "fish": "ca",
            "milkfish": "ca",
            "tilapia": "ca",
            "potato": "khoai_tay",
            "pumpkin": "bi_do",
            "shrimp": "tom",
            "snake_beans": "dau_que",
            "string_beans": "dau_que",
            "tomato": "ca_chua",
        },
        distractors=(
            "bell_pepper",
            "red_bell_pepper",
            "green_bell_pepper",
            "onion",
            "red_onion",
            "white_onion",
            "yellow_onion",
            "cilantro",
            "eggplant",
        ),
        scarce_cap=600,
        common_cap=150,
        max_neg_images=300,
    ),
    SourceSpec(
        name="smartpantry",
        workspace="smartpantry",
        project="ingredients-yot0w",
        version=1,
        fmt="yolov8",
        license="CC BY 4.0",
        url="https://universe.roboflow.com/smartpantry/ingredients-yot0w",
        class_map={
            "pork": "thit_lon",
            "tofu": "dau_phu",
            "green_onion": "hanh_la",
            "chili": "ot",
            "cabbage": "bap_cai",
        },
        distractors=("okra",),
        scarce_cap=600,
        common_cap=150,
        max_neg_images=120,
        is_commercial_ok=True,
    ),
    SourceSpec(
        name="phcs",
        workspace="phcs-workspace-kultf",
        project="vegetables-ckjsc",
        version=1,
        fmt="yolov8",
        license="CC BY 4.0",
        url="https://universe.roboflow.com/phcs-workspace-kultf/vegetables-ckjsc",
        class_map={
            "tofu": "dau_phu",
            "winter_melon": "bi_dao",
            "bok_choy": "rau_cai",
            "bok choy": "rau_cai",
            "shrimp": "tom",
        },
        scarce_cap=600,
        common_cap=150,
        max_neg_images=0,
        is_commercial_ok=True,
    ),
)


def base_stem(filename: str) -> str:
    stem = Path(filename).stem
    return RF_HASH_RE.sub("", stem)


def our_split(source: str, stem: str) -> str:
    """Deterministic 15% val / 85% train by base image stem (never puts Roboflow in test)."""
    h = int(hashlib.sha1(f"{source}:{stem}".encode("utf-8")).hexdigest(), 16) % 20
    return "val" if h < 3 else "train"


def _is_color(img_path: Path) -> bool:
    try:
        with Image.open(img_path) as im:
            im = im.convert("RGB")
            im.thumbnail((64, 64))
            arr = np.asarray(im, dtype=np.int16)
            return float(np.abs(arr[..., 0] - arr[..., 1]).mean() + np.abs(arr[..., 1] - arr[..., 2]).mean()) > 3.0
    except Exception:
        return False


def _download_zip(spec: SourceSpec, api_key: str, zip_path: Path) -> None:
    meta_url = f"https://api.roboflow.com/{spec.workspace}/{spec.project}/{spec.version}/{spec.fmt}?api_key={api_key}"
    for attempt in range(8):
        with urllib.request.urlopen(urllib.request.Request(meta_url, headers={"User-Agent": USER_AGENT}), timeout=30) as r:
            d = json.loads(r.read().decode("utf-8"))
        link = (d.get("export") or {}).get("link")
        if link:
            break
        time.sleep(3)
    else:
        raise RuntimeError(f"Roboflow export link unavailable for {spec.name} after retries")

    zip_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = zip_path.with_suffix(".part")
    with urllib.request.urlopen(urllib.request.Request(link, headers={"User-Agent": USER_AGENT}), timeout=180) as resp:
        with tmp.open("wb") as f:
            shutil.copyfileobj(resp, f, length=1 << 20)
    tmp.rename(zip_path)


def _detect_auto_oriented(extract_dir: Path) -> bool:
    """Check README.roboflow.txt for 'Auto-orientation of pixel data'."""
    candidates = [extract_dir / "README.roboflow.txt", *sorted(extract_dir.glob("*/README.roboflow.txt"))]
    for p in candidates:
        if p.exists():
            txt = p.read_text(encoding="utf-8", errors="ignore").lower()
            if "auto-orientation of pixel data" in txt:
                return True
    return False


def _inverse_exif_box(
    bx: float,
    by: float,
    bw: float,
    bh: float,
    disp_w: int,
    disp_h: int,
    orient: int,
) -> tuple[float, float, float, float]:
    """Map display-space pixel xywh box back into raw-pixel orientation for EXIF 1..8."""
    if orient == 1:
        return bx, by, bw, bh
    if orient == 2:
        return float(disp_w) - (bx + bw), by, bw, bh
    if orient == 3:
        return float(disp_w) - (bx + bw), float(disp_h) - (by + bh), bw, bh
    if orient == 4:
        return bx, float(disp_h) - (by + bh), bw, bh
    if orient == 5:
        return by, bx, bh, bw
    if orient == 6:
        return by, float(disp_w) - (bx + bw), bh, bw
    if orient == 7:
        return float(disp_h) - (by + bh), float(disp_w) - (bx + bw), bh, bw
    if orient == 8:
        return float(disp_h) - (by + bh), bx, bh, bw
    raise ValueError(f"Unsupported EXIF orientation: {orient!r}")


def _load_oriented_rgb(
    im_raw: Image.Image,
    *,
    norm_boxes: bool,
    orig_w: int | None,
    orig_h: int | None,
    exif_mode: str = "auto",
    auto_oriented: bool = False,
) -> tuple[Image.Image, dict]:
    """Deterministically orient pixels to match box coordinate space.

    Returns ``(rgb_image, meta)`` where ``meta`` records ``exif_orientation``,
    ``exif_applied``, and ``exif_suspect``. Unknown EXIF tags outside ``1..8``
    are normalized to ``1`` with ``exif_applied=False`` and ``exif_suspect=True``.
    """
    try:
        raw_orient = int(im_raw.getexif().get(274, 1) or 1)
    except Exception:
        raw_orient = 1

    invalid_orient = raw_orient not in range(1, 9)
    orient = 1 if invalid_orient else raw_orient

    if exif_mode not in ("auto", "transpose", "raw"):
        raise ValueError(f"Unsupported exif_mode: {exif_mode!r}")

    if exif_mode == "raw":
        swapped_disp = bool(
            not norm_boxes
            and orig_w
            and orig_h
            and orig_w != orig_h
            and orient in (5, 6, 7, 8)
            and (im_raw.height, im_raw.width) == (orig_w, orig_h)
        )
        return im_raw.convert("RGB"), {
            "exif_orientation": orient,
            "exif_applied": False,
            "exif_suspect": invalid_orient or (bool(orient != 1 and not auto_oriented) and not swapped_disp),
        }

    if exif_mode == "transpose":
        if orient != 1:
            return ImageOps.exif_transpose(im_raw).convert("RGB"), {
                "exif_orientation": orient,
                "exif_applied": True,
                "exif_suspect": False,
            }
        return im_raw.convert("RGB"), {
            "exif_orientation": orient,
            "exif_applied": False,
            "exif_suspect": invalid_orient,
        }

    # exif_mode == "auto"
    if not norm_boxes:
        if orig_w and orig_h:
            if im_raw.size == (orig_w, orig_h):
                is_square_58 = (im_raw.width == im_raw.height) and (orient in (5, 6, 7, 8))
                return im_raw.convert("RGB"), {
                    "exif_orientation": orient,
                    "exif_applied": False,
                    "exif_suspect": invalid_orient
                    or bool((orient in (2, 3, 4) or is_square_58) and not auto_oriented),
                }
            if orient in (5, 6, 7, 8) and (im_raw.height, im_raw.width) == (orig_w, orig_h):
                return ImageOps.exif_transpose(im_raw).convert("RGB"), {
                    "exif_orientation": orient,
                    "exif_applied": True,
                    "exif_suspect": False,
                }
            if orient != 1 and not auto_oriented:
                return ImageOps.exif_transpose(im_raw).convert("RGB"), {
                    "exif_orientation": orient,
                    "exif_applied": True,
                    "exif_suspect": True,
                }
            return im_raw.convert("RGB"), {
                "exif_orientation": orient,
                "exif_applied": False,
                "exif_suspect": invalid_orient or bool(orient != 1),
            }
        if orient != 1 and not auto_oriented:
            return ImageOps.exif_transpose(im_raw).convert("RGB"), {
                "exif_orientation": orient,
                "exif_applied": True,
                "exif_suspect": False,
            }
        return im_raw.convert("RGB"), {
            "exif_orientation": orient,
            "exif_applied": False,
            "exif_suspect": invalid_orient,
        }

    # YOLO normalized boxes
    if auto_oriented:
        return im_raw.convert("RGB"), {
            "exif_orientation": orient,
            "exif_applied": False,
            "exif_suspect": invalid_orient or bool(orient != 1),
        }
    if orient != 1:
        return ImageOps.exif_transpose(im_raw).convert("RGB"), {
            "exif_orientation": orient,
            "exif_applied": True,
            "exif_suspect": True,
        }
    return im_raw.convert("RGB"), {
        "exif_orientation": orient,
        "exif_applied": False,
        "exif_suspect": invalid_orient,
    }


def _has_black_corners(im: Image.Image, patch: int = 5, thresh: float = 2.0) -> bool:
    """Detect Roboflow baked rotation augmentation black corner triangles."""
    w, h = im.size
    if w < patch or h < patch:
        return False
    arr = np.asarray(im, dtype=np.float32)
    corners = (
        arr[:patch, :patch],
        arr[:patch, w - patch :],
        arr[h - patch :, :patch],
        arr[h - patch :, w - patch :],
    )
    return min(float(c.mean()) for c in corners) < thresh


def _parse_coco_dir(extract_dir: Path, spec: SourceSpec) -> list[dict]:
    """Parse COCO JSON splits inside extracted Roboflow export -> candidate list (with pixel bbox or norm flag)."""
    auto_oriented = _detect_auto_oriented(extract_dir)
    cands: list[dict] = []
    for json_path in sorted(extract_dir.glob("*/_annotations.coco.json")):
        split_dir = json_path.parent
        d = json.loads(json_path.read_text(encoding="utf-8"))
        cats = {c["id"]: c["name"] for c in d.get("categories", [])}
        by_img: dict[int, list[dict]] = defaultdict(list)
        distractors_by_img: dict[int, set[str]] = defaultdict(set)
        for ann in d.get("annotations", []):
            cname = cats.get(ann["category_id"], "")
            if cname in spec.class_map:
                bb = ann.get("bbox")
                if not bb or len(bb) != 4:
                    continue
                by_img[ann["image_id"]].append({"cat": cname, "cls": spec.class_map[cname], "bbox": [float(v) for v in bb]})
            elif cname in spec.distractors:
                distractors_by_img[ann["image_id"]].add(cname)
        for im in d.get("images", []):
            img_path = split_dir / im["file_name"]
            if not img_path.exists():
                continue
            iid = im["id"]
            boxes = by_img.get(iid, [])
            ood_labels = sorted(distractors_by_img.get(iid, set()))
            is_neg = not boxes and bool(ood_labels)
            if not boxes and not is_neg:
                continue
            cands.append({
                "stem": base_stem(im["file_name"]),
                "src_path": img_path,
                "orig_w": int(im["width"]),
                "orig_h": int(im["height"]),
                "boxes": boxes,
                "is_neg": is_neg,
                "ood_labels": ood_labels,
                "norm_boxes": False,
                "auto_oriented": auto_oriented,
            })
    return cands


def _parse_yolo_dir(extract_dir: Path, spec: SourceSpec) -> list[dict]:
    auto_oriented = _detect_auto_oriented(extract_dir)
    data_yaml = yaml.safe_load((extract_dir / "data.yaml").read_text(encoding="utf-8"))
    raw_names = data_yaml["names"]
    names = [raw_names[i] for i in sorted(raw_names)] if isinstance(raw_names, dict) else list(raw_names)
    cands: list[dict] = []
    for img_path in sorted(extract_dir.glob("*/images/*")):
        if img_path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            continue
        lbl_path = img_path.parent.parent / "labels" / f"{img_path.stem}.txt"
        if not lbl_path.exists():
            continue
        boxes = []
        img_distractors: set[str] = set()
        for line in lbl_path.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) < 5:
                continue
            ci = int(float(parts[0]))
            if ci < 0 or ci >= len(names):
                continue
            cname = names[ci]
            if len(parts) == 5:
                xc, yc, bw, bh = (float(v) for v in parts[1:5])
                x, y, w, h = xc - bw / 2.0, yc - bh / 2.0, bw, bh
            else:
                coords = [float(v) for v in parts[1:]]
                xs, ys = coords[0::2], coords[1::2]
                if not xs or not ys:
                    continue
                x0, x1 = min(xs), max(xs)
                y0, y1 = min(ys), max(ys)
                x, y, w, h = x0, y0, x1 - x0, y1 - y0
            if cname in spec.class_map:
                if w > 0.002 and h > 0.002:
                    boxes.append({"cat": cname, "cls": spec.class_map[cname], "bbox": [x, y, w, h]})
            elif cname in spec.distractors:
                img_distractors.add(cname)
        ood_labels = sorted(img_distractors)
        is_neg = not boxes and bool(ood_labels)
        if not boxes and not is_neg:
            continue
        cands.append({
            "stem": base_stem(img_path.name),
            "src_path": img_path,
            "orig_w": None,
            "orig_h": None,
            "boxes": boxes,
            "is_neg": is_neg,
            "ood_labels": ood_labels,
            "norm_boxes": True,
            "auto_oriented": auto_oriented,
        })
    return cands


def _collapse_twins(cands: list[dict]) -> list[dict]:
    by_stem: dict[str, list[dict]] = defaultdict(list)
    for c in cands:
        by_stem[c["stem"]].append(c)
    unique: list[dict] = []
    for stem in sorted(by_stem):
        group = by_stem[stem]
        chosen = group[0]
        if len(group) > 1:
            for g in group:
                if g["boxes"] and _is_color(g["src_path"]):
                    chosen = g
                    break
        unique.append(chosen)
    return unique


def _select_candidates(unique: list[dict], spec: SourceSpec) -> list[dict]:
    pos = [c for c in unique if c["boxes"]]
    neg = [c for c in unique if c["is_neg"]]
    if spec.scarce_cap is not None:
        # Rare-class-first selection, prioritizing SCARCE_CLASSES then common classes with tight caps
        by_cls: dict[str, list[int]] = defaultdict(list)
        for i, c in enumerate(pos):
            for b in c["boxes"]:
                by_cls[b["cls"]].append(i)
        selected_idx: set[int] = set()
        # Sort scarce classes first (smallest count first), then common classes
        ordered_cls = sorted(
            by_cls,
            key=lambda cl: (0 if cl in SCARCE_CLASSES else 1, len(by_cls[cl])),
        )
        for cl in ordered_cls:
            cap = spec.scarce_cap if cl in SCARCE_CLASSES else (spec.common_cap or 150)
            idxs = by_cls[cl]
            already = sum(1 for i in idxs if i in selected_idx)
            need = max(0, cap - already)
            if need <= 0:
                continue
            rest = [i for i in idxs if i not in selected_idx]
            rest.sort(key=lambda i: hashlib.sha1(f"{spec.name}:{pos[i]['stem']}".encode()).hexdigest())
            selected_idx.update(rest[:need])
        pos = [pos[i] for i in sorted(selected_idx)]
    elif spec.max_images is not None and len(pos) > spec.max_images:
        pos = sorted(pos, key=lambda c: hashlib.sha1(f"{spec.name}:{c['stem']}".encode()).hexdigest())[: spec.max_images]

    if spec.max_neg_images == 0:
        neg = []
    elif len(neg) > spec.max_neg_images:
        neg = sorted(neg, key=lambda c: hashlib.sha1(f"{spec.name}:neg:{c['stem']}".encode()).hexdigest())[: spec.max_neg_images]
    return pos + neg


def _materialize_source(spec: SourceSpec, selected: list[dict]) -> dict:
    dst_root = ROOT / spec.name
    img_dir = dst_root / "images"
    if dst_root.exists():
        shutil.rmtree(dst_root)
    img_dir.mkdir(parents=True, exist_ok=True)
    out_records = []
    cls_counts = Counter()
    split_counts = Counter()
    orient_counts: Counter = Counter()
    black_corner_count = 0
    neg_count = 0

    for c in selected:
        try:
            with Image.open(c["src_path"]) as im_raw:
                im, exif_meta = _load_oriented_rgb(
                    im_raw,
                    norm_boxes=bool(c["norm_boxes"]),
                    orig_w=c.get("orig_w"),
                    orig_h=c.get("orig_h"),
                    exif_mode=spec.exif_mode,
                    auto_oriented=bool(c.get("auto_oriented", False)),
                )
                w0, h0 = im.size
                scale = min(1.0, MAX_SIDE / max(w0, h0))
                if scale < 1.0:
                    im = im.resize((max(1, round(w0 * scale)), max(1, round(h0 * scale))), Image.LANCZOS)
                w_new, h_new = im.size
                black_corners = _has_black_corners(im)
                safe_id = hashlib.sha1(c["stem"].encode("utf-8")).hexdigest()[:12]
                fn = f"{safe_id}.jpg"
                im.save(img_dir / fn, "JPEG", quality=90)
        except Exception:
            continue

        raw_swapped_disp = bool(
            spec.exif_mode == "raw"
            and not c["norm_boxes"]
            and c.get("orig_w")
            and c.get("orig_h")
            and c["orig_w"] != c["orig_h"]
            and (h0, w0) == (c["orig_w"], c["orig_h"])
            and exif_meta["exif_orientation"] in (5, 6, 7, 8)
        )
        boxes_px = []
        for b in c["boxes"]:
            bx, by, bw, bh = b["bbox"]
            if c["norm_boxes"]:
                px, py, pw, ph = bx * w_new, by * h_new, bw * w_new, bh * h_new
            elif raw_swapped_disp:
                rx, ry, rw, rh = _inverse_exif_box(
                    bx,
                    by,
                    bw,
                    bh,
                    int(c["orig_w"]),
                    int(c["orig_h"]),
                    exif_meta["exif_orientation"],
                )
                sx = w_new / float(w0)
                sy = h_new / float(h0)
                px, py, pw, ph = rx * sx, ry * sy, rw * sx, rh * sy
            else:
                sx = w_new / float(c["orig_w"] or w0)
                sy = h_new / float(c["orig_h"] or h0)
                px, py, pw, ph = bx * sx, by * sy, bw * sx, bh * sy
            if pw >= 2.0 and ph >= 2.0:
                boxes_px.append({"cat": b["cat"], "cls": b["cls"], "bbox": [px, py, pw, ph]})
                cls_counts[b["cls"]] += 1

        if c["boxes"] and not boxes_px:
            (img_dir / fn).unlink(missing_ok=True)
            continue

        split = "train" if not boxes_px else our_split(spec.name, c["stem"])
        split_counts[split] += 1
        orient_counts[exif_meta["exif_orientation"]] += 1
        if black_corners:
            black_corner_count += 1
        is_neg = not boxes_px
        if is_neg:
            neg_count += 1
        ood_labels = list(c.get("ood_labels") or [])
        if is_neg and not ood_labels:
            ood_labels = ["__neg__"]
        out_records.append({
            "id": f"{spec.name}/{safe_id}",
            "stem": c["stem"],
            "source_name": f"rf_{spec.name}",
            "split": split,
            "split_hint": split,
            "file": f"images/{fn}",
            "width": w_new,
            "height": h_new,
            "license": spec.license,
            "is_commercial_ok": spec.is_commercial_ok,
            "url": spec.url,
            "is_neg": is_neg,
            "ood_labels": ood_labels,
            "exif_orientation": exif_meta["exif_orientation"],
            "exif_applied": exif_meta["exif_applied"],
            "exif_suspect": exif_meta["exif_suspect"],
            "has_black_corners": black_corners,
            "boxes": boxes_px,
        })

    categories = sorted(cls_counts.keys()) + (["__neg__"] if neg_count else [])
    manifest = {
        "schema_version": "m1_v1",
        "source": spec.name,
        "source_name": f"rf_{spec.name}",
        "license": spec.license,
        "is_commercial_ok": spec.is_commercial_ok,
        "url": spec.url,
        "categories": categories,
        "images": len(out_records),
        "neg_images": neg_count,
        "splits": dict(split_counts),
        "boxes_per_class": dict(sorted(cls_counts.items())),
        "exif_orientations": {str(k): v for k, v in sorted(orient_counts.items())},
        "black_corner_images": black_corner_count,
        "records": out_records,
    }
    (dst_root / "annotations.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return {k: v for k, v in manifest.items() if k != "records"}


def ingest_source(spec: SourceSpec, api_key: str, *, force: bool = False) -> dict:
    ann_path = ROOT / spec.name / "annotations.json"
    if ann_path.exists() and not force:
        d = json.loads(ann_path.read_text(encoding="utf-8"))
        return {k: v for k, v in d.items() if k != "records"}
    if not api_key:
        raise RuntimeError(
            f"ROBOFLOW_API_KEY environment variable is required to download {spec.name} "
            "(never read from deploy/.env)"
        )

    stage_dir = STAGE / spec.name
    zip_path = STAGE / f"{spec.name}.zip"
    try:
        shutil.rmtree(stage_dir, ignore_errors=True)
        zip_path.unlink(missing_ok=True)
        stage_dir.mkdir(parents=True, exist_ok=True)
        print(f"[roboflow] downloading {spec.name} ({spec.workspace}/{spec.project} v{spec.version})...", flush=True)
        _download_zip(spec, api_key, zip_path)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(stage_dir)
        zip_path.unlink(missing_ok=True)
        cands = _parse_coco_dir(stage_dir, spec) if spec.fmt == "coco" else _parse_yolo_dir(stage_dir, spec)
        unique = _collapse_twins(cands)
        selected = _select_candidates(unique, spec)
        summary = _materialize_source(spec, selected)
        summary["raw_candidates"] = len(cands)
        summary["unique_stems"] = len(unique)
        print(f"[roboflow] {spec.name} done: {summary['images']} imgs (neg={summary['neg_images']}), classes={len(summary['boxes_per_class'])}", flush=True)
        return summary
    finally:
        shutil.rmtree(stage_dir, ignore_errors=True)
        zip_path.unlink(missing_ok=True)


def ingest_all(*, force: bool = False, only: set[str] | None = None, skip_missing_key: bool = False) -> dict:
    api_key = os.environ.get("ROBOFLOW_API_KEY", "").strip()
    ROOT.mkdir(parents=True, exist_ok=True)
    STAGE.mkdir(parents=True, exist_ok=True)
    summaries = {}
    try:
        for spec in SOURCES:
            if only and spec.name not in only:
                continue
            ann_path = ROOT / spec.name / "annotations.json"
            if ann_path.exists() and not force:
                d = json.loads(ann_path.read_text(encoding="utf-8"))
                summaries[spec.name] = {k: v for k, v in d.items() if k != "records"}
                continue
            if not api_key:
                if skip_missing_key:
                    summaries[spec.name] = {
                        "status": "skipped_missing_api_key",
                        "source_name": f"rf_{spec.name}",
                        "url": spec.url,
                    }
                    continue
                raise RuntimeError("ROBOFLOW_API_KEY environment variable is required")
            summaries[spec.name] = ingest_source(spec, api_key, force=force)
    finally:
        shutil.rmtree(STAGE, ignore_errors=True)
    return summaries


def records() -> list[dict]:
    """All ingested Roboflow images with pixel xywh boxes mapped to Tastoria class ids."""
    out: list[dict] = []
    if not ROOT.exists():
        return out
    spec_by_name = {s.name: s for s in SOURCES}
    for ann_path in sorted(ROOT.glob("*/annotations.json")):
        src_root = ann_path.parent
        src_dir = src_root / "images"
        d = json.loads(ann_path.read_text(encoding="utf-8"))
        src = d["source"]
        spec = spec_by_name.get(src)
        comm_default = d.get("is_commercial_ok", spec.is_commercial_ok if spec else True)
        for r in d["records"]:
            rel = Path(r["file"])
            p = src_root / rel if (src_root / rel).exists() else src_dir / rel.name
            if p.exists():
                boxes = r.get("boxes", [])
                out.append({
                    **r,
                    "source": f"rf_{src}",
                    "source_name": r.get("source_name", f"rf_{src}"),
                    "split_hint": r.get("split_hint", r.get("split", "train")),
                    "is_commercial_ok": r.get("is_commercial_ok", comm_default),
                    "is_neg": r.get("is_neg", not boxes),
                    "ood_labels": r.get("ood_labels", ["__neg__"] if not boxes else []),
                    "path": p,
                })
    return out


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--skip-missing-key", action="store_true")
    args = ap.parse_args()
    res = ingest_all(
        force=args.force,
        only=set(args.only) if args.only else None,
        skip_missing_key=args.skip_missing_key,
    )
    print(json.dumps(res, indent=2, ensure_ascii=False))
