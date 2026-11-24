"""Track C multi-stage automated data cleaning pipeline for Tastoria yolo_v4 (F6).

Stage 1 (pure CPU):
  - Explicit defect purges: rf_tofu_oo (100%), rau_muong from rf_water_spinach &
    rf_nhan_dien_rau (retaining rf_nhan_dien_rau bap_cai), rf_robo1 0-box hard
    negatives, lvis_v1_neg banned tokens (pizza/dining_table/sandwich), and
    banned path/id tokens (infographic/nutrition/watermark/bbq/grilled/cooked_rib/
    buffet/dolma/pad_thai).
  - Pixel geometry & EXIF gate: black-corner detection (rf_robo1/rf_viet_hoang/v3det),
    EXIF orientation in (None, 1) verification, outer-8% uniform-border / white-bg
    routing flags (NOT blind hard drops on rpc_checkout or rf_food_start).
  - Box geometry gate: strip group_of=True on countable:true (EXPECTED_COUNTABLE_19),
    strip whole-basket countable boxes (v3det >=0.92, single-box >=0.94), and strip
    tiny/degenerate boxes (min_side_px < 16 or norm_area < 0.001) on v3det & rf_*
    train/val only (preserving rf_aicook & mendeley_bd small produce).

Stage 2 (sequential GPU under ~5.6 GB VRAM in hac_env; lazy-imported):
  - Stage 2A: google/siglip2-base-patch16-384 zero-shot screener (with automatic
    fallback to locally cached openai/clip-vit-base-patch32) scoring both full
    images and box crops. Unloads model before Stage 2B.
  - Stage 2B: 5CD-AI/Vintern-1B-v2 borderline VLM QA using focused single-concept
    binary Yes/No prompts (never compound negative prompts) with the verified
    language_model.generate wrapper stripping return_dict=None / output_hidden_states=None.

Run (GPU cleaning):
  PYTHONPATH=/home/namnx/NamBuw/Tastoria/ml/src \\
    /home/namnx/.venvs/hac_env/bin/python -m tastoria_ml.cv.track_c_filter
"""

from __future__ import annotations

import argparse
import gc
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import yaml
from PIL import Image

from tastoria_ml.cv.classes import REPO, VISION_CLASSES

OUT_DIR = REPO / "data" / "processed" / "cv" / "yolo_v4"
CLEANING_MANIFEST_PATH = OUT_DIR / "cleaning_manifest.json"
DECISIONS_PATH = OUT_DIR / "track_c_decisions.json"

EXPECTED_COUNTABLE_19: frozenset[str] = frozenset(
    {
        "trung",
        "dau_phu",
        "ca_chua",
        "ca_rot",
        "khoai_tay",
        "bap_cai",
        "sup_lo",
        "bi_do",
        "bi_dao",
        "su_su",
        "muop",
        "muop_dang",
        "mi_tom",
        "do_hop",
        "sua",
        "sua_chua",
        "chanh",
        "bim_bim",
        "nuoc_ngot",
    }
)

# Proposed/packaged classes that are legitimately baked, dairy, or packaged rather than raw produce/meat.
NON_RAW_PACKAGED_CLASSES: frozenset[str] = frozenset(
    {
        "mi_tom",
        "xuc_xich",
        "do_hop",
        "sua",
        "sua_chua",
        "bim_bim",
        "banh_ngot",
        "banh_quy",
        "keo",
        "nuoc_ngot",
        "banh_mi",
    }
)

# Classes where outdoor farm-vine attachment is a known defect (v3det gourds/produce).
VINE_CHECK_CLASSES: frozenset[str] = frozenset({"muop", "su_su", "bi_do", "bi_dao", "muop_dang"})

# Critical weak VN classes routed through VLM crop/image verification when uncertain or audited.
CRITICAL_WEAK_CLASSES: frozenset[str] = frozenset(
    {"dau_phu", "rau_muong", "gia_do", "muop", "su_su", "rau_cai"}
)

BANNED_PATH_TOKENS: tuple[str, ...] = (
    "infographic",
    "nutrition",
    "watermark",
    "bbq",
    "grilled",
    "cooked_rib",
    "buffet",
    "dolma",
    "pad_thai",
)

LVIS_NEG_BANNED_TOKENS: tuple[str, ...] = ("pizza", "dining_table", "sandwich") + BANNED_PATH_TOKENS

BANNED_LVIS_COCATS: frozenset[str] = frozenset(
    {"pizza", "sandwich", "burrito", "taco", "lasagna", "hamburger", "hot_dog", "hotdog"}
)
LVIS_ANN_DIR = REPO / "data" / "raw" / "images" / "lvis_v1" / "ann"
_LVIS_COCATS_CACHE: dict[tuple[str, str], dict[int, frozenset[str]]] = {}


def _load_lvis_cocats(lvis_split: str, ann_dir: Path | None = None) -> dict[int, frozenset[str]]:
    """Lazily load and cache {image_id: frozenset(category_names)} from LVIS JSON."""
    base = (ann_dir or LVIS_ANN_DIR).resolve()
    cache_key = (str(base), lvis_split)
    if cache_key in _LVIS_COCATS_CACHE:
        return _LVIS_COCATS_CACHE[cache_key]
    json_path = base / f"lvis_v1_{lvis_split}.json"
    if not json_path.is_file():
        _LVIS_COCATS_CACHE[cache_key] = {}
        return {}
    data = json.loads(json_path.read_text(encoding="utf-8"))
    cats = {int(c["id"]): str(c["name"]) for c in data.get("categories", [])}
    by_img: dict[int, set[str]] = defaultdict(set)
    for ann in data.get("annotations", []):
        cid = int(ann["category_id"])
        cname = cats.get(cid)
        if cname:
            by_img[int(ann["image_id"])].add(cname)
    frozen = {iid: frozenset(names) for iid, names in by_img.items()}
    _LVIS_COCATS_CACHE[cache_key] = frozen
    return frozen

STAGE2_SOURCES: frozenset[str] = frozenset(
    {
        "rf_robo1",
        "rf_viet_hoang",
        "rf_food_start",
        "v3det",
        "lvis_v1",
        "openimages_v7_ood",
        "lvis_v1_neg",
        "rf_nhan_dien_rau",
        "rf_water_spinach",
    }
)

SINGLE_BOX_BASKET_SOURCES: frozenset[str] = frozenset(
    {"mendeley_bd", "rpc_checkout", "omorros_kitchen", "dfv16"}
)

SCENE_PROMPTS: tuple[tuple[str, str], ...] = (
    ("raw_grocery", "a photo of raw uncooked fresh grocery food ingredients"),
    ("cooked_meal", "a photo of a cooked prepared meal or fried dish served on a plate or bowl"),
    ("infographic_text", "a graphic poster, nutrition infographic, text diagram, or photo with large overlaid title text or labels"),
    ("single_lab_leaf", "a single isolated plant leaf on a plain studio background"),
    ("outdoor_vine", "vegetables growing outdoors on a farm plant or vine"),
)


def _load_class_english_names() -> dict[str, str]:
    raw = yaml.safe_load(VISION_CLASSES.read_text(encoding="utf-8"))
    rows = list(raw["classes"]) + list(raw.get("proposed_classes") or [])
    out: dict[str, str] = {}
    for r in rows:
        out[str(r["id"])] = str(r.get("name_en") or r["id"]).replace("(raw)", "").strip()
    return out


def has_black_corners(im: Image.Image, patch: int = 5, thresh: float = 2.0) -> bool:
    """Detect Roboflow baked rotation augmentation black corner triangles."""
    w, h = im.size
    if w < patch or h < patch:
        return False
    arr = np.asarray(im.convert("RGB"), dtype=np.float32)
    corners = (
        arr[:patch, :patch],
        arr[:patch, w - patch :],
        arr[h - patch :, :patch],
        arr[h - patch :, w - patch :],
    )
    return min(float(c.mean()) for c in corners) < thresh


def border_metrics(im: Image.Image, frac: float = 0.08) -> tuple[float, float]:
    """Return ``(border_std, white_frac)`` on the outer ``frac`` border strip."""
    rgb = np.asarray(im.convert("RGB"), dtype=np.float32)
    h, w = rgb.shape[:2]
    bw = max(1, int(round(w * frac)))
    bh = max(1, int(round(h * frac)))
    mask = np.zeros((h, w), dtype=bool)
    mask[:bh, :] = True
    mask[max(0, h - bh) :, :] = True
    mask[:, :bw] = True
    mask[:, max(0, w - bw) :] = True
    pixels = rgb[mask]
    if pixels.size == 0:
        return 0.0, 0.0
    border_std = float(pixels.std())
    white_frac = float(np.mean(np.all(pixels >= 240.0, axis=-1)))
    return border_std, white_frac


def check_exif_orientation(im: Image.Image) -> int | None:
    """Return EXIF orientation tag (0x0112), or None if absent/unreadable."""
    try:
        val = im.getexif().get(0x0112)
        return int(val) if val is not None else None
    except Exception:
        return None


def is_tiny_box(bw_px: float, bh_px: float, w_img: int, h_img: int) -> bool:
    """Return True when box min-side < 16 px or normalized area < 0.001."""
    if min(bw_px, bh_px) < 16.0:
        return True
    area_norm = (bw_px / float(max(w_img, 1))) * (bh_px / float(max(h_img, 1)))
    return area_norm < 0.001


def is_whole_basket_countable(
    cls_id: str,
    w_norm: float,
    h_norm: float,
    source: str,
    n_boxes: int,
    countable_classes: frozenset[str] = EXPECTED_COUNTABLE_19,
) -> bool:
    """Detect frame-spanning whole-basket/buffet boxes on countable:true classes."""
    if cls_id not in countable_classes:
        return False
    if source == "v3det":
        return w_norm >= 0.92 and h_norm >= 0.92
    if n_boxes == 1 and source in SINGLE_BOX_BASKET_SOURCES:
        return w_norm >= 0.94 and h_norm >= 0.94
    return False


def _box_norm_wh(box: dict[str, Any], img_w: int, img_h: int) -> tuple[float, float, float, float]:
    """Return ``(bw_px, bh_px, w_norm, h_norm)`` from pixel xywh or normalized dict."""
    if "bbox" in box:
        _, _, bw, bh = (float(v) for v in box["bbox"])
        if bw <= 1.0 and bh <= 1.0 and img_w > 10 and img_h > 10 and box.get("normalized"):
            return bw * img_w, bh * img_h, bw, bh
        return bw, bh, bw / float(max(img_w, 1)), bh / float(max(img_h, 1))
    w_norm = float(box.get("w", 0.0))
    h_norm = float(box.get("h", 0.0))
    return w_norm * img_w, h_norm * img_h, w_norm, h_norm


def stage1_filter_record(
    rec: dict[str, Any],
    *,
    countable_classes: frozenset[str] = EXPECTED_COUNTABLE_19,
    check_pixels: bool = True,
    lvis_ann_dir: Path | None = None,
) -> dict[str, Any]:
    """Run deterministic Stage 1 CPU geometry/border/exif/defect filtering on one record."""
    source = str(rec.get("source") or rec.get("source_name") or "")
    split = str(rec.get("split") or rec.get("split_hint") or "train")
    oid = str(rec.get("original_id") or rec.get("id") or "")
    file_str = str(rec.get("file") or "")
    ood_labels = [str(x) for x in (rec.get("ood_labels") or [])]
    orig_boxes = list(rec.get("boxes") or [])
    img_w = int(rec.get("width") or 0)
    img_h = int(rec.get("height") or 0)

    stats = {
        "group_of_countable_dropped": 0,
        "whole_basket_countable_dropped": 0,
        "tiny_boxes_dropped": 0,
        "rau_muong_leaf_boxes_dropped": 0,
        "exif_non_unit": 0,
    }
    flags: list[str] = []

    def _reject(reason: str) -> dict[str, Any]:
        return {
            "keep": False,
            "reason": reason,
            "boxes": [],
            "flags": flags,
            "stats": stats,
        }

    # 1. Explicit source/token purges (F7)
    if source == "rf_tofu_oo":
        return _reject("rf_tofu_oo_purged")

    low_id = f"{oid} {file_str}".lower()
    if source == "lvis_v1_neg":
        low_ood = " ".join(ood_labels).lower()
        if any(tok in low_id or tok in low_ood for tok in LVIS_NEG_BANNED_TOKENS):
            return _reject("lvis_v1_neg_banned_token")

    if any(tok in low_id for tok in BANNED_PATH_TOKENS):
        return _reject("banned_path_token")

    if source == "rf_robo1" and (len(orig_boxes) == 0 or bool(rec.get("is_neg")) or bool(rec.get("is_hard_neg"))):
        return _reject("rf_robo1_hard_neg_purged")

    if source == "lvis_v1":
        rec_cats = rec.get("lvis_categories")
        if rec_cats is not None:
            if any(str(c) in BANNED_LVIS_COCATS for c in rec_cats):
                return _reject("lvis_v1_banned_cocat")
        elif "/" in oid:
            lvis_split, raw_iid = oid.split("/", 1)
            if lvis_split in {"train", "val"} and raw_iid.isdigit():
                img_cats = _load_lvis_cocats(lvis_split, ann_dir=lvis_ann_dir).get(int(raw_iid))
                if img_cats and any(cat_name in BANNED_LVIS_COCATS for cat_name in img_cats):
                    return _reject("lvis_v1_banned_cocat")

    # 2. Pixel checks (EXIF, black corners, outer-8% border routing signals)
    path_val = rec.get("path")
    if check_pixels and path_val is not None:
        img_path = Path(path_val)
        if not img_path.is_file():
            return _reject("missing_image")
        try:
            with Image.open(img_path) as im_raw:
                orient = check_exif_orientation(im_raw)
                if orient not in (None, 1):
                    stats["exif_non_unit"] += 1
                    return _reject("exif_non_unit")
                if img_w <= 0 or img_h <= 0:
                    img_w, img_h = im_raw.size
                if source in {"rf_robo1", "rf_viet_hoang", "v3det"} and has_black_corners(im_raw):
                    reason = "rf_robo1_black_corners" if source == "rf_robo1" else f"{source}_black_corners"
                    return _reject(reason)
                if source in STAGE2_SOURCES or source in {"rpc_checkout", "rf_food_start"}:
                    b_std, w_frac = border_metrics(im_raw)
                    if b_std < 10.0:
                        flags.append("uniform_border")
                    if w_frac >= 0.85:
                        flags.append("white_bg")
        except Exception:
            return _reject("corrupt_image")
    elif rec.get("has_black_corners") and source in {"rf_robo1", "rf_viet_hoang", "v3det"}:
        reason = "rf_robo1_black_corners" if source == "rf_robo1" else f"{source}_black_corners"
        return _reject(reason)

    if img_w <= 0:
        img_w = 640
    if img_h <= 0:
        img_h = 640

    # 3. Box-level filters
    had_orig_boxes = len(orig_boxes) > 0
    kept_boxes: list[dict[str, Any]] = []
    n_orig = len(orig_boxes)
    apply_tiny_gate = split in {"train", "val"} and (source == "v3det" or source.startswith("rf_"))

    for b in orig_boxes:
        cls_id = str(b.get("cls") or "")
        is_group_of = bool(b.get("group_of", False))

        if source in {"rf_water_spinach", "rf_nhan_dien_rau"} and cls_id == "rau_muong":
            stats["rau_muong_leaf_boxes_dropped"] += 1
            continue

        if is_group_of and cls_id in countable_classes:
            stats["group_of_countable_dropped"] += 1
            continue

        bw_px, bh_px, w_norm, h_norm = _box_norm_wh(b, img_w, img_h)
        if is_whole_basket_countable(cls_id, w_norm, h_norm, source, n_orig, countable_classes):
            stats["whole_basket_countable_dropped"] += 1
            continue

        if apply_tiny_gate and is_tiny_box(bw_px, bh_px, img_w, img_h):
            stats["tiny_boxes_dropped"] += 1
            continue

        kept_boxes.append(b)

    # Never convert a boxed image into a false-negative 0-box image!
    if had_orig_boxes and not kept_boxes:
        if stats["rau_muong_leaf_boxes_dropped"] > 0 and source in {"rf_water_spinach", "rf_nhan_dien_rau"}:
            return _reject("single_leaf_rau_muong_purged")
        if stats["whole_basket_countable_dropped"] > 0:
            return _reject("whole_basket_countable_purged")
        if stats["group_of_countable_dropped"] > 0:
            return _reject("group_of_countable_purged")
        return _reject("all_boxes_purged")

    if source in STAGE2_SOURCES:
        flags.append("route_stage2")

    return {
        "keep": True,
        "reason": None,
        "boxes": kept_boxes,
        "flags": flags,
        "stats": stats,
    }


class ZeroShotScreenerProtocol(Protocol):
    backend_name: str

    def score_scene_batch(self, images: list[Image.Image], prompts: list[str]) -> list[dict[str, float]]:
        ...

    def score_pair_batch(
        self, images: list[Image.Image], pos_prompts: list[str], neg_prompts: list[str]
    ) -> list[float]:
        ...

    def unload(self) -> None:
        ...


class VLMVerifierProtocol(Protocol):
    backend_name: str

    def ask_yes_no_batch(self, items: list[tuple[Image.Image, str]]) -> list[bool]:
        ...

    def unload(self) -> None:
        ...


class SigLIP2ZeroShotScreener:
    """Stage 2A GPU screener using google/siglip2-base-patch16-384 (fallback: CLIP)."""

    def __init__(
        self,
        *,
        model_id: str = "google/siglip2-base-patch16-384",
        fallback_model_id: str = "openai/clip-vit-base-patch32",
        device: str = "cuda",
    ) -> None:
        import torch
        from transformers import AutoModel, AutoProcessor

        self._torch = torch
        self.device = device if torch.cuda.is_available() else "cpu"
        dtype = torch.float16 if self.device == "cuda" else torch.float32
        self.is_siglip2 = True
        try:
            self.processor = AutoProcessor.from_pretrained(model_id)
            self.model = AutoModel.from_pretrained(model_id, dtype=dtype).to(self.device).eval()
            self.backend_name = model_id
        except Exception:
            self.is_siglip2 = False
            self.processor = AutoProcessor.from_pretrained(fallback_model_id, local_files_only=True)
            self.model = (
                AutoModel.from_pretrained(fallback_model_id, dtype=dtype, local_files_only=True)
                .to(self.device)
                .eval()
            )
            self.backend_name = fallback_model_id

    def _forward_probs(self, images: list[Image.Image], prompts: list[str]) -> np.ndarray:
        kwargs: dict[str, Any] = {
            "text": prompts,
            "images": images,
            "padding": "max_length" if self.is_siglip2 else True,
            "truncation": True,
            "return_tensors": "pt",
        }
        if self.is_siglip2:
            kwargs["max_length"] = 64
        inputs = self.processor(**kwargs).to(self.device)
        with self._torch.no_grad():
            logits = self.model(**inputs).logits_per_image.float()
            probs = self._torch.softmax(logits, dim=-1)
        return probs.detach().cpu().numpy()

    def score_scene_batch(
        self, images: list[Image.Image], prompts: list[str], *, batch_size: int = 32
    ) -> list[dict[str, float]]:
        keys = [k for k, _ in SCENE_PROMPTS]
        out: list[dict[str, float]] = []
        for i in range(0, len(images), batch_size):
            chunk = images[i : i + batch_size]
            probs = self._forward_probs(chunk, prompts)
            for row in probs:
                out.append({keys[j]: float(row[j]) for j in range(len(keys))})
        return out

    def score_pair_batch(
        self,
        images: list[Image.Image],
        pos_prompts: list[str],
        neg_prompts: list[str],
        *,
        batch_size: int = 32,
    ) -> list[float]:
        """Return P(pos_prompt) vs neg_prompt for each image in ``images``."""
        scores: list[float] = []
        # Group identical prompt pairs for vectorized batching
        by_pair: dict[tuple[str, str], list[int]] = defaultdict(list)
        for idx, (p, n) in enumerate(zip(pos_prompts, neg_prompts)):
            by_pair[(p, n)].append(idx)
        res = [0.5] * len(images)
        for (p_txt, n_txt), idxs in by_pair.items():
            for i in range(0, len(idxs), batch_size):
                sub_idxs = idxs[i : i + batch_size]
                sub_imgs = [images[j] for j in sub_idxs]
                probs = self._forward_probs(sub_imgs, [p_txt, n_txt])
                for k, orig_i in enumerate(sub_idxs):
                    res[orig_i] = float(probs[k, 0])
        scores.extend(res)
        return scores

    def unload(self) -> None:
        model = getattr(self, "model", None)
        proc = getattr(self, "processor", None)
        self.model = None
        self.processor = None
        del model, proc
        gc.collect()
        if self._torch.cuda.is_available():
            self._torch.cuda.empty_cache()


class VinternVLMVerifier:
    """Stage 2B borderline QA using 5CD-AI/Vintern-1B-v2 within <= 3.5 GB VRAM."""

    def __init__(
        self,
        *,
        model_id: str = "5CD-AI/Vintern-1B-v2",
        device: str = "cuda",
        batch_size: int = 24,
    ) -> None:
        import torch
        import torchvision.transforms as T
        from torchvision.transforms.functional import InterpolationMode
        from transformers import AutoModel, AutoTokenizer

        self._torch = torch
        self.device = device if torch.cuda.is_available() else "cpu"
        self.batch_size = batch_size
        self.backend_name = model_id
        self.tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True, local_files_only=True)
        self.model = (
            AutoModel.from_pretrained(
                model_id,
                dtype=torch.bfloat16 if self.device == "cuda" else torch.float32,
                low_cpu_mem_usage=True,
                trust_remote_code=True,
                local_files_only=True,
            )
            .eval()
            .to(self.device)
        )

        # Verified fix for transformers 4.57.6 duplicate return_dict / output_hidden_states=None
        orig_generate = self.model.language_model.generate

        def _patched_generate(*args: Any, **kwargs: Any) -> Any:
            if kwargs.get("return_dict") is None:
                kwargs.pop("return_dict", None)
            if kwargs.get("output_hidden_states") is None:
                kwargs.pop("output_hidden_states", None)
            return orig_generate(*args, **kwargs)

        self.model.language_model.generate = _patched_generate

        self._transform = T.Compose(
            [
                T.Lambda(lambda img: img.convert("RGB") if img.mode != "RGB" else img),
                T.Resize((448, 448), interpolation=InterpolationMode.BICUBIC),
                T.ToTensor(),
                T.Normalize(mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225)),
            ]
        )

    def _to_pixel_values(self, im: Image.Image):
        pv = self._transform(im).unsqueeze(0)
        if self.device == "cuda":
            return pv.to(dtype=self._torch.bfloat16, device=self.device)
        return pv

    @staticmethod
    def _parse_yes_no(resp: str) -> bool:
        low = resp.strip().lower()
        first = re.split(r"[\s.,!?;:]+", low)[0] if low else ""
        if first in {"yes", "có", "true"}:
            return True
        if first in {"no", "không", "false"}:
            return False
        return "yes" in low and "no" not in low

    def ask_yes_no_batch(self, items: list[tuple[Image.Image, str]]) -> list[bool]:
        if not items:
            return []
        gen_cfg = {"max_new_tokens": 12, "do_sample": False}
        results: list[bool] = []
        bs = max(1, self.batch_size)
        for i in range(0, len(items), bs):
            chunk = items[i : i + bs]
            pvs = self._torch.cat([self._to_pixel_values(im) for im, _ in chunk], dim=0)
            num_patches_list = [1] * len(chunk)
            questions = [f"<image>\n{q}" for _, q in chunk]
            try:
                answers = self.model.batch_chat(
                    self.tokenizer,
                    pvs,
                    num_patches_list=num_patches_list,
                    questions=questions,
                    generation_config=gen_cfg,
                )
            except Exception:
                answers = []
                for idx_c, (im_c, q_c) in enumerate(chunk):
                    ans = self.model.chat(
                        self.tokenizer,
                        self._to_pixel_values(im_c),
                        f"<image>\n{q_c}",
                        gen_cfg,
                    )
                    answers.append(ans)
            for ans in answers:
                results.append(self._parse_yes_no(str(ans)))
        return results

    def unload(self) -> None:
        model = getattr(self, "model", None)
        tok = getattr(self, "tokenizer", None)
        self.model = None
        self.tokenizer = None
        del model, tok
        gc.collect()
        if self._torch.cuda.is_available():
            self._torch.cuda.empty_cache()


def _crop_box(im: Image.Image, box: dict[str, Any], pad: float = 0.08) -> Image.Image:
    w, h = im.size
    if "bbox" in box:
        bx, by, bw, bh = (float(v) for v in box["bbox"])
        if bw <= 1.0 and bh <= 1.0 and box.get("normalized"):
            bx, by, bw, bh = bx * w, by * h, bw * w, bh * h
    else:
        xc, yc, wn, hn = (
            float(box.get("xc", 0.5)),
            float(box.get("yc", 0.5)),
            float(box.get("w", 1.0)),
            float(box.get("h", 1.0)),
        )
        bx, by, bw, bh = (xc - wn / 2.0) * w, (yc - hn / 2.0) * h, wn * w, hn * h
    px = bw * pad
    py = bh * pad
    x0 = max(0, int(round(bx - px)))
    y0 = max(0, int(round(by - py)))
    x1 = min(w, max(x0 + 4, int(round(bx + bw + px))))
    y1 = min(h, max(y0 + 4, int(round(by + bh + py))))
    return im.crop((x0, y0, x1, y1)).convert("RGB")


def _record_key(rec: dict[str, Any]) -> str:
    src = str(rec.get("source") or rec.get("source_name") or "unknown")
    rid = str(rec.get("id") or rec.get("original_id") or rec.get("stem") or "")
    return f"{src}|{rid}"


@dataclass
class TrackCThresholds:
    reject_bad_high: float = 0.68
    reject_raw_below: float = 0.35
    cooked_minus_raw_reject: float = 0.35
    unconditional_cooked_reject: float = 0.80
    prepared_dish_reject: float = 0.72
    prepared_dish_unconditional: float = 0.85
    accept_raw_high: float = 0.72
    max_bad_for_auto_accept: float = 0.25
    ood_cooked_reject: float = 0.62
    ood_info_reject: float = 0.55
    crop_cooked_reject: float = 0.68
    crop_match_min: float = 0.25
    fried_tofu_reject: float = 0.65
    watermark_auto_reject: float = 0.92
    watermark_vlm_route: float = 0.10
    text_graphic_vlm_route: float = 0.025
    info_watermark_vlm_route: float = 0.04
    scene_clean_reject: float = 0.12
    scene_clean_vlm_route: float = 0.65
    crop_sem_reject: float = 0.22
    crop_sem_vlm_route: float = 0.82
    packaged_ok_reject: float = 0.25
    packaged_xuc_xich_reject: float = 0.40


def _crop_sem_prompts(cls_id: str, en_name: str) -> tuple[str, str]:
    if cls_id == "muop":
        return (
            "a photo of a fresh green edible angled luffa or ridge gourd vegetable",
            "a photo of a dried brown fibrous bath loofah sponge, purple yam, sweet potato, or smooth green zucchini",
        )
    if cls_id == "su_su":
        return (
            "a photo of fresh green pear-shaped chayote squash vegetable",
            "a photo of an insect, grasshopper, animal, person, or unrelated non-vegetable object",
        )
    if cls_id == "gia_do":
        return (
            "a close-up photo of fresh raw white mung bean sprouts",
            "a photo of people at a market stall, cooked soup or noodle dish, or background without bean sprouts",
        )
    if cls_id == "dau_phu":
        return (
            "a photo of raw uncooked fresh white tofu bean curd block",
            "a photo of cooked fried brown tofu, spicy stew, cheese platter, or unrelated object",
        )
    if cls_id == "rau_cai":
        return (
            "a photo of fresh raw leafy green bok choy, napa cabbage, or mustard greens",
            "a photo of rabbits, animals, people, children playing, or unrelated non-vegetable scene",
        )
    if cls_id == "rau_muong":
        return (
            "a photo of fresh raw green water spinach morning glory vegetable stems and leaves",
            "a photo of a cooked stir-fry dish, animal, or unrelated non-vegetable object",
        )
    return (
        f"a close-up photo of fresh raw {en_name} grocery food",
        "a photo of a wild animal, insect, person, child, retail flyer, or cooked dish",
    )


def run_track_c(
    records: list[dict[str, Any]],
    *,
    screener: ZeroShotScreenerProtocol | None = None,
    vlm: VLMVerifierProtocol | None = None,
    screener_factory: Any = None,
    vlm_factory: Any = None,
    dry_run: bool = False,
    skip_stage2: bool = False,
    thresholds: TrackCThresholds = TrackCThresholds(),
    out_dir: Path = OUT_DIR,
) -> dict[str, Any]:
    """Execute Stage 1 CPU gate + sequential Stage 2A (SigLIP2) & Stage 2B (Vintern-1B-v2)."""
    class_en = _load_class_english_names()

    purged_defects: Counter[str] = Counter()
    source_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"input": 0, "kept": 0, "quarantined": 0})
    decisions: dict[str, dict[str, Any]] = {}
    s1_boxes_by_key: dict[str, list[dict[str, Any]]] = {}
    stage2_candidates: list[tuple[int, dict[str, Any], dict[str, Any]]] = []

    for idx, rec in enumerate(records):
        src = str(rec.get("source") or rec.get("source_name") or "unknown")
        source_stats[src]["input"] += 1
        key = _record_key(rec)
        s1 = stage1_filter_record(rec, check_pixels=True)
        for k, v in s1["stats"].items():
            if v > 0:
                purged_defects[k] += int(v)

        if not s1["keep"]:
            reason = str(s1["reason"] or "stage1_rejected")
            purged_defects[reason] += 1
            source_stats[src]["quarantined"] += 1
            decisions[key] = {
                "source": src,
                "id": str(rec.get("id") or rec.get("original_id") or ""),
                "split": str(rec.get("split") or rec.get("split_hint") or "train"),
                "path": str(rec.get("path") or ""),
                "keep": False,
                "stage": "stage1",
                "reason": reason,
                "kept_boxes": [],
                "orig_boxes": rec.get("boxes") or [],
                "flags": s1["flags"],
            }
            continue

        s1_boxes_by_key[key] = s1["boxes"]
        if src in STAGE2_SOURCES and not skip_stage2:
            stage2_candidates.append((idx, rec, s1))
        else:
            source_stats[src]["kept"] += 1
            decisions[key] = {
                "source": src,
                "id": str(rec.get("id") or rec.get("original_id") or ""),
                "split": str(rec.get("split") or rec.get("split_hint") or "train"),
                "path": str(rec.get("path") or ""),
                "keep": True,
                "stage": "stage1",
                "reason": None,
                "kept_boxes": s1["boxes"],
                "flags": s1["flags"],
            }

    stage2a_backend = "none"
    stage2b_backend = "none"

    if stage2_candidates and not skip_stage2:
        # ---- Stage 2A: Zero-shot Screener ----
        active_screener = screener
        owns_screener = False
        if active_screener is None:
            active_screener = screener_factory() if screener_factory else SigLIP2ZeroShotScreener()
            owns_screener = True
        stage2a_backend = str(getattr(active_screener, "backend_name", "custom_screener"))

        prompt_texts = [p for _, p in SCENE_PROMPTS]
        pil_imgs: list[Image.Image] = []
        valid_cands: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
        for item in stage2_candidates:
            _, rec, _ = item
            try:
                with Image.open(rec["path"]) as im_raw:
                    pil_imgs.append(im_raw.convert("RGB"))
                valid_cands.append(item)
            except Exception:
                key = _record_key(rec)
                src = str(rec.get("source") or rec.get("source_name") or "")
                source_stats[src]["quarantined"] += 1
                purged_defects["stage2_unreadable"] += 1
                decisions[key] = {
                    "source": src,
                    "id": str(rec.get("id") or ""),
                    "split": str(rec.get("split") or "train"),
                    "path": str(rec.get("path") or ""),
                    "keep": False,
                    "stage": "stage2a",
                    "reason": "stage2_unreadable",
                    "kept_boxes": [],
                    "orig_boxes": rec.get("boxes") or [],
                }

        scene_scores = active_screener.score_scene_batch(pil_imgs, prompt_texts) if valid_cands else []

        # Dedicated overlaid text / retail flyer / coupon / blog poster score
        text_graphic_scores = (
            active_screener.score_pair_batch(
                pil_imgs,
                ["a graphic poster, blog article cover, retail store flyer, price advertisement, coupon, nutrition chart, or diagram with overlaid text"] * len(pil_imgs),
                ["a clean natural photograph without overlaid title text, flyer, or diagram"] * len(pil_imgs),
            )
            if valid_cands
            else []
        )

        # Dedicated stock-photo watermark score
        watermark_scores = (
            active_screener.score_pair_batch(
                pil_imgs,
                ["a stock photograph with visible watermark text, repeating watermark grid, or agency logo such as iStock, Shutterstock, Alamy, 123RF, or Dreamstime"] * len(pil_imgs),
                ["a clean unwatermarked photograph without any stock agency logo or watermark text"] * len(pil_imgs),
            )
            if valid_cands
            else []
        )

        # Prepared dish / sashimi / sandwich / salad / bento / hotpot vs raw ingredients score
        prep_idxs: list[int] = []
        prep_imgs: list[Image.Image] = []
        prep_pos: list[str] = []
        prep_neg: list[str] = []

        # Packaged/bakery vs savory cooked restaurant meal score for only_packaged items
        pkg_idxs: list[int] = []
        pkg_imgs: list[Image.Image] = []
        pkg_pos: list[str] = []
        pkg_neg: list[str] = []
        # Scene cleanliness (wildlife/screens/wedding/bakery-case off-topic screen) for v3det & lvis_v1
        clean_idxs: list[int] = []
        clean_imgs: list[Image.Image] = []
        clean_pos: list[str] = []
        clean_neg: list[str] = []

        for c_i, ((_, rec, s1), im) in enumerate(zip(valid_cands, pil_imgs)):
            src = str(rec.get("source") or rec.get("source_name") or "")
            boxes = s1["boxes"]
            cls_set = {str(b.get("cls") or "") for b in boxes}
            only_packaged = bool(boxes) and cls_set <= NON_RAW_PACKAGED_CLASSES

            if not only_packaged and (
                scene_scores[c_i]["cooked_meal"] >= 0.15
                or bool(cls_set & {"ca", "tom", "thit_bo"})
            ):
                prep_idxs.append(c_i)
                prep_imgs.append(im)
                prep_pos.append(
                    "a photo of a prepared restaurant dish, sashimi or sushi platter, sandwich, burger, salad, bento box, hotpot, or plated cooked meal"
                )
                prep_neg.append(
                    "a photo of raw uncooked whole produce, raw meat cuts, or fresh uncooked fish and seafood ingredients"
                )

            if only_packaged:
                pkg_idxs.append(c_i)
                pkg_imgs.append(im)
                if "xuc_xich" in cls_set:
                    pkg_pos.append("a photo of raw uncooked sausages or sealed packaged meat links")
                    pkg_neg.append(
                        "a photo of a pepperoni pizza, pizza slice, hotdog in a bun with fries, grilled sausage plate, pancakes with sausage, or restaurant meal"
                    )
                else:
                    pkg_pos.append(
                        "a photo of a sealed packaged grocery product (bottle, can, carton, box, bag, yogurt cup), baked bread, pastry, cake, cookie, or candy"
                    )
                    pkg_neg.append(
                        "a photo of a savory cooked restaurant meal, pizza, hotdog, ranch dip bowl, charcuterie cheese meat platter, fried chicken, steak, seafood, or soup"
                    )

            if src in {"v3det", "lvis_v1"}:
                clean_idxs.append(c_i)
                clean_imgs.append(im)
                if src == "v3det" and not boxes:
                    clean_pos.append("a clean natural photograph of an indoor home kitchen, refrigerator, or pantry")
                    clean_neg.append("a photo of an outdoor street party, wedding, people outdoors, or bakery dessert display case")
                elif only_packaged:
                    clean_pos.append("a clean photograph of bread, pastry, cake, cookie, yogurt, candy, chips, sausage, or packaged drinks")
                    clean_neg.append("a photo of wild animals, people's portraits without food, computer screens, or empty non-food scenes")
                else:
                    clean_pos.append(
                        "a clean natural photograph of fresh raw grocery produce, meat, fish, eggs, or tofu without wildlife, outdoor street scenes, people's portraits, or computer screens"
                    )
                    clean_neg.append(
                        "a photo of wild animals, bears, insects, grasshoppers, rabbits, children playing, people holding babies, or computer screens"
                    )

        prep_probs = active_screener.score_pair_batch(prep_imgs, prep_pos, prep_neg) if prep_imgs else []
        prepared_dish_by_cand: dict[int, float] = {ci: float(p) for ci, p in zip(prep_idxs, prep_probs)}

        pkg_probs = active_screener.score_pair_batch(pkg_imgs, pkg_pos, pkg_neg) if pkg_imgs else []
        packaged_ok_by_cand: dict[int, float] = {ci: float(p) for ci, p in zip(pkg_idxs, pkg_probs)}

        clean_probs = active_screener.score_pair_batch(clean_imgs, clean_pos, clean_neg) if clean_imgs else []
        scene_clean_by_cand: dict[int, float] = {ci: float(p) for ci, p in zip(clean_idxs, clean_probs)}

        # Box-crop rawness + semantic class-match scoring for boxed Stage 2 candidates
        crop_imgs: list[Image.Image] = []
        crop_pos: list[str] = []
        crop_neg: list[str] = []
        crop_meta: list[tuple[int, int, str]] = []  # (cand_idx, box_idx, kind)

        sem_imgs: list[Image.Image] = []
        sem_pos: list[str] = []
        sem_neg: list[str] = []
        sem_meta: list[tuple[int, int, str]] = []  # (cand_idx, box_idx, cls_id)

        for c_i, ((_, rec, s1), im) in enumerate(zip(valid_cands, pil_imgs)):
            src = str(rec.get("source") or rec.get("source_name") or "")
            for b_i, b in enumerate(s1["boxes"]):
                cid = str(b.get("cls") or "")
                en = class_en.get(cid, cid)
                if cid == "dau_phu":
                    crop_imgs.append(_crop_box(im, b))
                    crop_pos.append("a photo of raw uncooked fresh white tofu block")
                    crop_neg.append("a photo of deep fried golden brown tofu, cooked spicy tofu dish, or cheese platter")
                    crop_meta.append((c_i, b_i, "tofu_raw"))
                elif cid not in NON_RAW_PACKAGED_CLASSES:
                    crop_imgs.append(_crop_box(im, b))
                    crop_pos.append(f"a photo of raw uncooked fresh {en}")
                    crop_neg.append(f"a photo of cooked fried grilled or prepared {en} dish on a plate")
                    crop_meta.append((c_i, b_i, "raw_crop"))

                if (src == "v3det" or cid in CRITICAL_WEAK_CLASSES) and cid not in NON_RAW_PACKAGED_CLASSES:
                    sem_imgs.append(_crop_box(im, b, pad=0.10))
                    p_pos, p_neg = _crop_sem_prompts(cid, en)
                    sem_pos.append(p_pos)
                    sem_neg.append(p_neg)
                    sem_meta.append((c_i, b_i, cid))

        crop_probs = (
            active_screener.score_pair_batch(crop_imgs, crop_pos, crop_neg) if crop_imgs else []
        )
        crop_scores_by_cand: dict[int, list[tuple[int, str, float]]] = defaultdict(list)
        for (c_i, b_i, kind), p_raw in zip(crop_meta, crop_probs):
            crop_scores_by_cand[c_i].append((b_i, kind, float(p_raw)))

        sem_probs = (
            active_screener.score_pair_batch(sem_imgs, sem_pos, sem_neg) if sem_imgs else []
        )
        crop_sem_by_cand: dict[int, list[tuple[int, str, float]]] = defaultdict(list)
        for (c_i, b_i, cid), p_sem in zip(sem_meta, sem_probs):
            crop_sem_by_cand[c_i].append((b_i, cid, float(p_sem)))

        # Unload Stage 2A cleanly BEFORE Stage 2B!
        if owns_screener or hasattr(active_screener, "unload"):
            active_screener.unload()

        # Triage Stage 2A -> Auto-Reject / Auto-Accept / Borderline Stage 2B
        # Each vlm_queue entry has list of (question_key, prompt_str, box_dict_or_None)
        vlm_queue: list[
            tuple[int, dict[str, Any], dict[str, Any], dict[str, float], list[tuple[str, str, dict[str, Any] | None]]]
        ] = []

        for c_i, ((_, rec, s1), sc) in enumerate(zip(valid_cands, scene_scores)):
            src = str(rec.get("source") or rec.get("source_name") or "unknown")
            key = _record_key(rec)
            boxes = s1["boxes"]
            cls_set = {str(b.get("cls") or "") for b in boxes}
            only_packaged = bool(boxes) and cls_set <= NON_RAW_PACKAGED_CLASSES
            is_ood = src in {"openimages_v7_ood", "lvis_v1_neg"} or not boxes
            has_vine_cls = bool(cls_set & VINE_CHECK_CLASSES)
            has_weak_cls = bool(cls_set & CRITICAL_WEAK_CLASSES)
            c_scores = crop_scores_by_cand.get(c_i, [])
            min_crop_raw = min((p for _, _, p in c_scores), default=1.0)
            mean_crop_raw = float(np.mean([p for _, _, p in c_scores])) if c_scores else 1.0
            sem_scores = crop_sem_by_cand.get(c_i, [])
            min_crop_sem = min((p for _, _, p in sem_scores), default=1.0)
            worst_sem_box: dict[str, Any] | None = None
            if sem_scores:
                worst_b_idx = min(sem_scores, key=lambda x: x[2])[0]
                if 0 <= worst_b_idx < len(boxes):
                    worst_sem_box = boxes[worst_b_idx]

            tg_score = float(text_graphic_scores[c_i]) if c_i < len(text_graphic_scores) else 0.0
            wm_score = float(watermark_scores[c_i]) if c_i < len(watermark_scores) else 0.0
            sc_clean = scene_clean_by_cand.get(c_i)
            pkg_ok = packaged_ok_by_cand.get(c_i)
            prep_dish = prepared_dish_by_cand.get(c_i)

            cooked = sc["cooked_meal"]
            info = sc["infographic_text"]
            leaf = sc["single_lab_leaf"]
            vine = sc["outdoor_vine"]
            raw = sc["raw_grocery"]
            max_bad = max(cooked, info, leaf, vine if has_vine_cls else 0.0)

            score_bundle: dict[str, float] = {
                **sc,
                "text_graphic": tg_score,
                "watermark": wm_score,
                "min_crop_raw": min_crop_raw,
                "mean_crop_raw": mean_crop_raw,
                "min_crop_sem": min_crop_sem,
            }
            if sc_clean is not None:
                score_bundle["scene_clean"] = sc_clean
            if pkg_ok is not None:
                score_bundle["packaged_ok"] = pkg_ok
            if prep_dish is not None:
                score_bundle["prepared_dish"] = prep_dish

            # High-confidence Stage 2A auto-rejects
            reject_reason: str | None = None
            if info >= thresholds.ood_info_reject or tg_score >= 0.65 or (info >= 0.45 and "uniform_border" in s1["flags"]):
                reject_reason = f"{src}_stage2a_infographic"
            elif wm_score >= thresholds.watermark_auto_reject:
                reject_reason = f"{src}_stage2a_watermark"
            elif sc_clean is not None and sc_clean < thresholds.scene_clean_reject:
                reject_reason = f"{src}_stage2a_off_topic"
            elif leaf >= thresholds.reject_bad_high and raw < 0.25:
                reject_reason = f"{src}_stage2a_single_leaf"
            elif vine >= 0.90 and raw < 0.05:
                # Universal outdoor farm/vineyard landscape reject (e.g. v3det vineyard/tree vines)
                reject_reason = f"{src}_stage2a_outdoor_vine"
            elif has_vine_cls and vine >= thresholds.reject_bad_high and raw < 0.25:
                reject_reason = f"{src}_stage2a_outdoor_vine"
            elif is_ood and cooked >= thresholds.ood_cooked_reject:
                reject_reason = f"{src}_stage2a_cooked_ood"
            elif only_packaged and (
                (
                    pkg_ok is not None
                    and pkg_ok < (thresholds.packaged_xuc_xich_reject if "xuc_xich" in cls_set else thresholds.packaged_ok_reject)
                    and (cooked >= thresholds.reject_bad_high or "xuc_xich" in cls_set)
                )
                or ("xuc_xich" in cls_set and cooked >= 0.50)
                or (cooked >= 0.85 and (pkg_ok is None or pkg_ok < 0.95))
                or (src in {"lvis_v1", "rf_viet_hoang"} and cooked >= 0.92)
            ):
                reject_reason = f"{src}_stage2a_cooked_packaged"
            elif not only_packaged and "xuc_xich" in cls_set and cooked >= 0.50:
                reject_reason = f"{src}_stage2a_cooked_packaged"
            elif not only_packaged and (
                (cooked >= thresholds.reject_bad_high and raw < thresholds.reject_raw_below)
                or (cooked - raw >= thresholds.cooked_minus_raw_reject and cooked >= 0.60)
                or cooked >= thresholds.unconditional_cooked_reject
            ):
                reject_reason = f"{src}_stage2a_cooked_meal"
            elif not only_packaged and prep_dish is not None and (
                prep_dish >= thresholds.prepared_dish_unconditional
                or (prep_dish >= thresholds.prepared_dish_reject and raw < 0.55)
            ):
                reject_reason = f"{src}_stage2a_prepared_dish"
            elif not only_packaged and "dau_phu" in cls_set and min_crop_raw < (1.0 - thresholds.fried_tofu_reject):
                if len(boxes) == 1 or mean_crop_raw < 0.35:
                    reject_reason = f"{src}_stage2a_cooked_fried_tofu"
            elif not only_packaged and c_scores and mean_crop_raw < 0.25 and "rau_muong" not in cls_set:
                reject_reason = f"{src}_stage2a_cooked_crop"
            elif not only_packaged and c_scores and mean_crop_raw < (1.0 - thresholds.crop_cooked_reject) and cooked > 0.45:
                reject_reason = f"{src}_stage2a_cooked_crop"
            elif sem_scores and min_crop_sem < thresholds.crop_sem_reject:
                reject_reason = f"{src}_stage2a_crop_mismatch"

            if reject_reason is not None:
                source_stats[src]["quarantined"] += 1
                purged_defects[reject_reason] += 1
                decisions[key] = {
                    "source": src,
                    "id": str(rec.get("id") or ""),
                    "split": str(rec.get("split") or "train"),
                    "path": str(rec.get("path") or ""),
                    "keep": False,
                    "stage": "stage2a",
                    "reason": reject_reason,
                    "kept_boxes": [],
                    "orig_boxes": rec.get("boxes") or [],
                    "stage2a_scores": score_bundle,
                    "flags": s1["flags"],
                }
                continue

            # Determine Stage 2B VLM verification questions
            questions: list[tuple[str, str, dict[str, Any] | None]] = []
            if (
                info >= 0.12
                or tg_score >= 0.03
                or ("white_bg" in s1["flags"] and src == "rf_robo1")
                or ("uniform_border" in s1["flags"] and src == "rf_robo1")
            ):
                questions.append(
                    (
                        "is_infographic",
                        "Does this image contain large overlaid title text, a text banner, a diagram, or an infographic? Answer only Yes or No.",
                        None,
                    )
                )
            if (
                (
                    src in {"rf_robo1", "rf_viet_hoang", "rf_food_start", "v3det"}
                    and boxes
                    and (
                        wm_score >= (0.08 if src == "rf_viet_hoang" else thresholds.watermark_vlm_route)
                        or tg_score >= thresholds.text_graphic_vlm_route
                        or info >= thresholds.info_watermark_vlm_route
                        or src == "v3det"
                    )
                )
                or (src == "lvis_v1" and (wm_score >= 0.30 or tg_score >= 0.03 or info >= 0.05))
                or wm_score >= 0.50
            ):
                questions.append(
                    (
                        "is_watermark",
                        "Is there a repeating stock watermark logo (like 123RF, iStock, Shutterstock, Alamy), camera icon, or website text on this image? Answer only Yes or No.",
                        None,
                    )
                )
            if not only_packaged and (
                (0.22 <= cooked < thresholds.unconditional_cooked_reject)
                or (is_ood and 0.30 <= cooked < thresholds.ood_cooked_reject)
                or (has_weak_cls and cooked >= 0.15)
                or (src == "v3det" and cooked >= 0.15)
                or (c_scores and min_crop_raw < 0.65)
                or (prep_dish is not None and prep_dish >= 0.25)
            ):
                if "dau_phu" in cls_set:
                    questions.append(
                        (
                            "is_cooked_tofu",
                            "Is this tofu fried, browned, or cooked in a sauce dish rather than raw uncooked white tofu? Answer only Yes or No.",
                            None,
                        )
                    )
                else:
                    questions.append(
                        (
                            "is_cooked",
                            "Is the food in this image cooked, fried, or grilled? Answer only Yes or No.",
                            None,
                        )
                    )
                    if cooked >= 0.22 or (c_scores and min_crop_raw < 0.65):
                        questions.append(
                            (
                                "is_pan_or_grill",
                                "Is this food being cooked in a frying pan or on a grill? Answer only Yes or No.",
                                None,
                            )
                        )
            if (
                not only_packaged
                and bool(cls_set & {"ca", "tom"})
                and prep_dish is not None
                and prep_dish >= 0.08
            ):
                questions.append(
                    (
                        "is_sushi_or_sashimi",
                        "Is this a Japanese sushi or sashimi dish? Answer only Yes or No.",
                        None,
                    )
                )
            if (
                boxes
                and src in {"rf_robo1", "rf_viet_hoang", "rf_food_start", "v3det"}
                and (tg_score >= 0.03 or info >= 0.05)
            ):
                questions.append(
                    (
                        "is_cartoon",
                        "Is this a cartoon drawing, illustration, or clipart instead of a real photograph? Answer only Yes or No.",
                        None,
                    )
                )
            if (
                not only_packaged
                and src in {"lvis_v1", "rf_viet_hoang", "v3det"}
                and (
                    cooked >= 0.07
                    or (prep_dish is not None and prep_dish >= 0.05)
                    or min_crop_raw < 0.50
                    or bool(cls_set & {"ca_chua", "nam", "banh_mi", "xuc_xich", "sup_lo", "toi"})
                )
            ):
                questions.append(
                    (
                        "is_pizza_or_hotdog",
                        "Does this image show a pizza or a hotdog? Answer only Yes or No.",
                        None,
                    )
                )
                questions.append(
                    (
                        "is_sandwich_or_burger",
                        "Does this image show a sandwich or burger? Answer only Yes or No.",
                        None,
                    )
                )
            if (
                src in {"lvis_v1", "v3det"}
                and (
                    (sc_clean is not None and sc_clean < 0.75)
                    or bool(cls_set & {"sup_lo", "ca"})
                )
            ):
                questions.append(
                    (
                        "is_underwater_or_aquarium",
                        "Does this image show an underwater scene, fish tank, or aquarium? Answer only Yes or No.",
                        None,
                    )
                )
            if "xuc_xich" in cls_set:
                if not any(qk == "is_pizza_or_hotdog" for qk, _, _ in questions):
                    questions.append(
                        (
                            "is_pizza_or_hotdog",
                            "Does this image show a pizza or a hotdog? Answer only Yes or No.",
                            None,
                        )
                    )
                questions.append(
                    (
                        "is_savory_cooked",
                        "Is this a cooked meal plate with sausages, toast, or eggs? Answer only Yes or No.",
                        None,
                    )
                )
            elif only_packaged and (
                cooked >= 0.60
                or (cooked >= 0.25 and (pkg_ok is None or pkg_ok < 0.90))
            ):
                questions.append(
                    (
                        "is_pizza_or_hotdog",
                        "Does this image show a pizza, hotdog in a bun, or cooked meat platter? Answer only Yes or No.",
                        None,
                    )
                )
                questions.append(
                    (
                        "is_savory_cooked",
                        "Is this a savory cooked meat dish, soup, dip bowl, or charcuterie platter? Answer only Yes or No.",
                        None,
                    )
                )
            if has_vine_cls and vine >= 0.30:
                questions.append(
                    (
                        "is_vine",
                        "Is this vegetable still growing hanging on an outdoor farm plant or vine? Answer only Yes or No.",
                        None,
                    )
                )
            if leaf >= 0.30:
                questions.append(
                    (
                        "is_single_leaf",
                        "Does this image show only a single isolated leaf on a plain studio background? Answer only Yes or No.",
                        None,
                    )
                )
            if "rau_muong" in cls_set and not any(qk == "is_cooked" for qk, _, _ in questions):
                questions.append(
                    (
                        "is_cooked",
                        "Is the food in this image cooked, fried, or grilled? Answer only Yes or No.",
                        None,
                    )
                )

            # Mandatory Stage 2B semantic verification on ALL v3det Stage-2A survivors
            if src == "v3det":
                if not boxes:
                    questions.append(
                        (
                            "is_kitchen_fridge",
                            "Is this photo taken inside a home kitchen, pantry, or in front of a refrigerator? Answer only Yes or No.",
                            None,
                        )
                    )
                else:
                    if "muop" in cls_set:
                        muop_box = next((b for b in boxes if str(b.get("cls") or "") == "muop"), boxes[0])
                        questions.append(
                            (
                                "is_bath_sponge",
                                "Is this a dried brown fibrous bath loofah scrub sponge or purple sweet potato? Answer only Yes or No.",
                                muop_box,
                            )
                        )
                        questions.append(
                            (
                                "is_zucchini",
                                "Is this a smooth-skinned cylindrical zucchini/courgette rather than a ridged angled luffa? Answer only Yes or No.",
                                muop_box,
                            )
                        )
                    if "gia_do" in cls_set:
                        gd_box = next((b for b in boxes if str(b.get("cls") or "") == "gia_do"), boxes[0])
                        questions.append(
                            (
                                "is_missing_sprouts",
                                "Does this cropped image show people, empty crates, or cooked noodles without raw white bean sprouts? Answer only Yes or No.",
                                gd_box,
                            )
                        )
                    if (sc_clean is not None and sc_clean < thresholds.scene_clean_vlm_route) or (
                        sem_scores and min_crop_sem < thresholds.crop_sem_vlm_route
                    ):
                        questions.append(
                            (
                                "is_non_food_crop",
                                "Does this photo mainly show people, animals, insects, or indoor clutter rather than fresh vegetables or meat? Answer only Yes or No.",
                                worst_sem_box,
                            )
                        )

            if not questions and (raw >= thresholds.accept_raw_high or only_packaged) and max_bad < thresholds.max_bad_for_auto_accept:
                source_stats[src]["kept"] += 1
                decisions[key] = {
                    "source": src,
                    "id": str(rec.get("id") or ""),
                    "split": str(rec.get("split") or "train"),
                    "path": str(rec.get("path") or ""),
                    "keep": True,
                    "stage": "stage2a",
                    "reason": None,
                    "kept_boxes": boxes,
                    "stage2a_scores": score_bundle,
                    "flags": s1["flags"],
                }
            elif not questions:
                if raw >= 0.35 and cooked < 0.35 and info < 0.25:
                    source_stats[src]["kept"] += 1
                    decisions[key] = {
                        "source": src,
                        "id": str(rec.get("id") or ""),
                        "split": str(rec.get("split") or "train"),
                        "path": str(rec.get("path") or ""),
                        "keep": True,
                        "stage": "stage2a",
                        "reason": None,
                        "kept_boxes": boxes,
                        "stage2a_scores": score_bundle,
                        "flags": s1["flags"],
                    }
                else:
                    if not only_packaged:
                        questions.append(
                            (
                                "is_cooked",
                                "Is the food in this image cooked, fried, or grilled? Answer only Yes or No.",
                                None,
                            )
                        )
                    else:
                        questions.append(
                            (
                                "is_infographic",
                                "Is this image a nutrition facts chart, infographic, or text diagram rather than a real photo? Answer only Yes or No.",
                                None,
                            )
                        )
                    vlm_queue.append((c_i, rec, s1, score_bundle, questions))
            else:
                vlm_queue.append((c_i, rec, s1, score_bundle, questions))

        # ---- Stage 2B: Vintern-1B-v2 Borderline VLM QA ----
        if vlm_queue:
            active_vlm = vlm
            owns_vlm = False
            if active_vlm is None:
                active_vlm = vlm_factory() if vlm_factory else VinternVLMVerifier()
                owns_vlm = True
            stage2b_backend = str(getattr(active_vlm, "backend_name", "custom_vlm"))

            flat_items: list[tuple[Image.Image, str]] = []
            flat_map: list[tuple[int, str]] = []
            pil_by_ci = {c_i: im for c_i, im in enumerate(pil_imgs)}
            for q_idx, (c_i, rec, s1, score_bundle, questions) in enumerate(vlm_queue):
                im = pil_by_ci[c_i]
                for q_key, q_txt, q_box in questions:
                    q_img = _crop_box(im, q_box, pad=0.12) if q_box is not None else im
                    flat_items.append((q_img, q_txt))
                    flat_map.append((q_idx, q_key))

            flat_ans = active_vlm.ask_yes_no_batch(flat_items)
            if owns_vlm or hasattr(active_vlm, "unload"):
                active_vlm.unload()

            ans_by_q: dict[int, dict[str, bool]] = defaultdict(dict)
            for (q_idx, q_key), ans in zip(flat_map, flat_ans):
                ans_by_q[q_idx][q_key] = bool(ans)

            for q_idx, (c_i, rec, s1, score_bundle, _) in enumerate(vlm_queue):
                src = str(rec.get("source") or rec.get("source_name") or "unknown")
                key = _record_key(rec)
                v_ans = ans_by_q.get(q_idx, {})
                cls_set_q = {str(b.get("cls") or "") for b in s1["boxes"]}
                only_pkg_q = bool(s1["boxes"]) and cls_set_q <= NON_RAW_PACKAGED_CLASSES

                bad_reason: str | None = None
                if v_ans.get("is_infographic") or v_ans.get("is_cartoon"):
                    bad_reason = f"{src}_stage2b_infographic"
                elif v_ans.get("is_watermark"):
                    bad_reason = f"{src}_stage2b_watermark"
                elif v_ans.get("is_cooked_tofu"):
                    bad_reason = f"{src}_stage2b_cooked_tofu"
                elif v_ans.get("is_cooked") or v_ans.get("is_pan_or_grill") or v_ans.get("is_sushi_or_sashimi"):
                    bad_reason = f"{src}_stage2b_cooked"
                elif v_ans.get("is_pizza_or_hotdog") or v_ans.get("is_sandwich_or_burger") or v_ans.get("is_savory_cooked"):
                    bad_reason = (
                        f"{src}_stage2b_cooked_packaged"
                        if (only_pkg_q or "xuc_xich" in cls_set_q)
                        else f"{src}_stage2b_cooked"
                    )
                elif v_ans.get("is_underwater_or_aquarium"):
                    bad_reason = f"{src}_stage2b_off_topic"
                elif v_ans.get("is_vine"):
                    bad_reason = f"{src}_stage2b_vine"
                elif v_ans.get("is_single_leaf"):
                    bad_reason = f"{src}_stage2b_single_leaf"
                elif v_ans.get("is_bath_sponge"):
                    bad_reason = f"{src}_stage2b_bath_sponge"
                elif v_ans.get("is_zucchini"):
                    bad_reason = f"{src}_stage2b_wrong_gourd"
                elif v_ans.get("is_missing_sprouts"):
                    bad_reason = f"{src}_stage2b_missing_sprouts"
                elif v_ans.get("is_non_food_crop"):
                    bad_reason = f"{src}_stage2b_non_food_crop"
                elif "is_kitchen_fridge" in v_ans and not v_ans["is_kitchen_fridge"]:
                    bad_reason = f"{src}_stage2b_non_kitchen"

                if bad_reason is not None:
                    source_stats[src]["quarantined"] += 1
                    purged_defects[bad_reason] += 1
                    decisions[key] = {
                        "source": src,
                        "id": str(rec.get("id") or ""),
                        "split": str(rec.get("split") or "train"),
                        "path": str(rec.get("path") or ""),
                        "keep": False,
                        "stage": "stage2b",
                        "reason": bad_reason,
                        "kept_boxes": [],
                        "orig_boxes": rec.get("boxes") or [],
                        "stage2a_scores": score_bundle,
                        "vlm_answers": v_ans,
                        "flags": s1["flags"],
                    }
                else:
                    source_stats[src]["kept"] += 1
                    decisions[key] = {
                        "source": src,
                        "id": str(rec.get("id") or ""),
                        "split": str(rec.get("split") or "train"),
                        "path": str(rec.get("path") or ""),
                        "keep": True,
                        "stage": "stage2b",
                        "reason": None,
                        "kept_boxes": s1["boxes"],
                        "stage2a_scores": score_bundle,
                        "vlm_answers": v_ans,
                        "flags": s1["flags"],
                    }

    # Class-coverage floor safeguard: ensure no present 37-class drops to 0 if a non-cooked raw candidate exists
    kept_cls_counts: Counter[str] = Counter()
    for d in decisions.values():
        if d["keep"]:
            for b in d["kept_boxes"]:
                kept_cls_counts[str(b.get("cls") or "")] += 1

    # Check if any class present in Stage-1-surviving candidates ended up with 0 kept boxes
    stage1_cls_cands: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for k, d in decisions.items():
        s1_boxes = s1_boxes_by_key.get(k) or []
        if not d["keep"] and d["stage"].startswith("stage2") and s1_boxes:
            scores = d.get("stage2a_scores") or {}
            raw_sc = float(scores.get("raw_grocery", 0.0))
            cooked_sc = float(scores.get("cooked_meal", 0.0))
            prep_sc = float(scores.get("prepared_dish", 0.0))
            v_ans = d.get("vlm_answers") or {}
            if any(
                v_ans.get(k_ans)
                for k_ans in (
                    "is_cooked",
                    "is_pan_or_grill",
                    "is_sushi_or_sashimi",
                    "is_cooked_tofu",
                    "is_savory_cooked",
                    "is_pizza_or_hotdog",
                    "is_sandwich_or_burger",
                    "is_underwater_or_aquarium",
                    "is_infographic",
                    "is_cartoon",
                    "is_watermark",
                    "is_single_leaf",
                    "is_bath_sponge",
                    "is_zucchini",
                    "is_missing_sprouts",
                    "is_non_food_crop",
                    "is_vine",
                )
            ) or ("is_kitchen_fridge" in v_ans and not v_ans["is_kitchen_fridge"]):
                continue
            reason_low = str(d.get("reason") or "").lower()
            if any(
                tok in reason_low
                for tok in (
                    "cooked",
                    "savory",
                    "prepared",
                    "watermark",
                    "off_topic",
                    "infographic",
                    "single_leaf",
                    "bath_sponge",
                    "wrong_gourd",
                    "missing_sprouts",
                    "non_food_crop",
                    "non_kitchen",
                    "vine",
                    "outdoor_vine",
                    "crop_mismatch",
                )
            ):
                continue
            if cooked_sc >= thresholds.reject_bad_high or prep_sc >= thresholds.prepared_dish_reject:
                continue
            for b in s1_boxes:
                stage1_cls_cands[str(b.get("cls") or "")].append((raw_sc, k))

    rescued_classes: list[str] = []
    for cls_id, cands in stage1_cls_cands.items():
        if kept_cls_counts[cls_id] == 0 and cands:
            cands.sort(reverse=True)
            best_key = cands[0][1]
            if best_key in decisions and not decisions[best_key]["keep"]:
                d = decisions[best_key]
                old_reason = str(d.get("reason") or "")
                d["keep"] = True
                d["kept_boxes"] = [b for b in (s1_boxes_by_key.get(best_key) or [])]
                d["reason"] = f"rescued_class_floor:{cls_id}"
                src = d["source"]
                source_stats[src]["kept"] += 1
                source_stats[src]["quarantined"] = max(0, source_stats[src]["quarantined"] - 1)
                if old_reason in purged_defects and purged_defects[old_reason] > 0:
                    purged_defects[old_reason] -= 1
                for b in d["kept_boxes"]:
                    kept_cls_counts[str(b.get("cls") or "")] += 1
                rescued_classes.append(cls_id)

    kept_images = sum(v["kept"] for v in source_stats.values())
    quarantined_images = sum(v["quarantined"] for v in source_stats.values())

    manifest = {
        "version": 4,
        "dataset": "yolo_v4",
        "dry_run": dry_run,
        "stage2_enabled": not skip_stage2,
        "stage2a_backend": stage2a_backend,
        "stage2b_backend": stage2b_backend,
        "total_input_images": len(records),
        "kept_images": kept_images,
        "quarantined_images": quarantined_images,
        "rescued_class_floor": sorted(rescued_classes),
        "kept_boxes_per_class": dict(sorted(kept_cls_counts.items())),
        "sources": dict(sorted(source_stats.items())),
        "quarantined_sources": dict(sorted(source_stats.items())),
        "purged_defects": dict(sorted((k, v) for k, v in purged_defects.items() if v > 0)),
        "contact_sheets": [],
    }

    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "cleaning_manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (out_dir / "track_c_decisions.json").write_text(
            json.dumps(decisions, ensure_ascii=False), encoding="utf-8"
        )

    return {"manifest": manifest, "decisions": decisions}


def gather_all_source_records() -> list[dict[str, Any]]:
    """Collect all raw source records (M1 + legacy) for Track C cleaning."""
    from tastoria_ml.cv import build_yolo as v1
    from tastoria_ml.cv import build_yolo_v2 as v2
    from tastoria_ml.cv import build_yolo_v3 as v3
    from tastoria_ml.cv import dfv16, hf_kaggle_ingest, lvis, openimages, roboflow_ingest, rpc, v3det

    rows = v2.all_class_rows()
    order = [c["id"] for c in rows]
    full = {cid: i for i, cid in enumerate(order)}
    all_recs: list[dict[str, Any]] = []

    # OpenImages V7 positives
    for r in v1.openimages_records(full):
        all_recs.append(
            {
                "id": r.original_id,
                "source": r.source,
                "source_name": r.source,
                "split": r.split,
                "path": r.path,
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

    # Mendeley BD expanded
    for r in v3.bd_v3_records(full):
        all_recs.append(
            {
                "id": r.original_id,
                "source": r.source,
                "source_name": r.source,
                "split": r.split,
                "path": r.path,
                "boxes": [
                    {"cls": order[b.cls], "xc": b.xc, "yc": b.yc, "w": b.w, "h": b.h, "group_of": b.group_of}
                    for b in r.boxes
                ],
                "is_neg": r.is_hard_neg,
            }
        )

    # LVIS v1 positives
    for im in lvis.records():
        all_recs.append(
            {
                "id": f"{im['lvis_split']}/{im['id']}",
                "source": "lvis_v1",
                "source_name": "lvis_v1",
                "split": im["split"],
                "path": im["path"],
                "width": im["width"],
                "height": im["height"],
                "boxes": im["boxes"],
                "is_neg": False,
            }
        )

    # LVIS clean OOD negatives
    for im in lvis.neg_records():
        all_recs.append(im)

    # RPC checkout
    for im in rpc.records():
        all_recs.append(
            {
                "id": im["id"],
                "source": "rpc_checkout",
                "source_name": "rpc_checkout",
                "split": im["split"],
                "path": im["path"],
                "width": im["width"],
                "height": im["height"],
                "boxes": im["boxes"],
                "is_neg": False,
            }
        )

    # Omorros kitchen heldout
    for im in v2.omorros_records():
        all_recs.append(
            {
                "id": im["id"],
                "source": "omorros_kitchen",
                "source_name": "omorros_kitchen",
                "split": "heldout",
                "path": im["path"],
                "width": im["width"],
                "height": im["height"],
                "boxes": im["boxes"],
                "is_neg": False,
            }
        )

    # M1 DFV16
    all_recs.extend(dfv16.records())

    # M1 OpenImages V7 OOD
    all_recs.extend(openimages.ood_records())

    # Roboflow subsets
    all_recs.extend(roboflow_ingest.records())

    # V3Det
    all_recs.extend(v3det.records())

    # Optional external datasets if ingested
    for im in hf_kaggle_ingest.records():
        sp = im.get("split_hint") or im.get("split") or "train"
        if sp == "test":
            sp = "heldout"
        all_recs.append(
            {
                **im,
                "split": sp,
                "source": im["source"],
                "source_name": im["source"],
                "is_neg": bool(im.get("is_neg", not im.get("boxes"))),
            }
        )

    return all_recs


def main() -> None:
    ap = argparse.ArgumentParser(description="Run Tastoria Track C data cleaning pipeline.")
    ap.add_argument("--dry-run", action="store_true", help="Do not write cleaning_manifest.json or decisions")
    ap.add_argument("--skip-stage2", action="store_true", help="Run Stage 1 CPU gates only")
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = ap.parse_args()

    recs = gather_all_source_records()
    res = run_track_c(recs, dry_run=args.dry_run, skip_stage2=args.skip_stage2, out_dir=args.out_dir)
    print(json.dumps(res["manifest"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
