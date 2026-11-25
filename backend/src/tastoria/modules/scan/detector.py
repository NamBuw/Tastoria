"""Detector inference: letterbox, the exported YOLO26 head, NMS (pure numpy around one onnxruntime call).

The registered ONNX (ultralytics 8.4 `export(format="onnx")`, metadata `end2end: False`) has one input
`images` [1, 3, S, S] (RGB, float 0..1, letterboxed with gray 114) and one output [1, 4 + C, N]: per anchor the box
centre/size (cx, cy, w, h) in input pixels and C class scores already passed through the sigmoid. It is the
one-to-many head, so overlapping anchors repeat the same object (measured: the top 15 anchors of one image were two
objects); non-maximum suppression is required. Post-processing mirrors ultralytics `non_max_suppression` with
`multi_label=False, agnostic=False`: best class per anchor, score ≥ conf, per-class greedy NMS at IoU > iou,
at most `max_det` boxes, then the inverse letterbox to the original image, clipped and normalised to [0, 1].

The confidence threshold is part of the model version (`metrics.serving.conf`), chosen on the validation split
(backend/scripts/choose_conf_threshold.py) and locked before the test split is looked at.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image

from tastoria.core.health import metrics

PAD_VALUE = 114
MAX_DETECTIONS_PER_PHOTO = 64


@dataclass(frozen=True)
class Letterbox:
    scale: float
    pad_x: int
    pad_y: int
    width: int  # original image
    height: int


@dataclass(frozen=True)
class Box:
    class_index: int
    confidence: float
    x1: float  # normalised to the original image, 0 <= x1 < x2 <= 1
    y1: float
    x2: float
    y2: float


def letterbox(img: Image.Image, size: int) -> tuple[np.ndarray, Letterbox]:
    """RGB image -> input tensor [1, 3, size, size] float32 and the geometry to map boxes back."""
    w, h = img.size
    s = size / max(w, h)
    nw, nh = max(1, round(w * s)), max(1, round(h * s))
    resized = np.asarray(img.convert("RGB").resize((nw, nh), Image.BILINEAR))
    canvas = np.full((size, size, 3), PAD_VALUE, np.uint8)
    py, px = (size - nh) // 2, (size - nw) // 2
    canvas[py : py + nh, px : px + nw] = resized
    x = canvas.transpose(2, 0, 1)[None].astype(np.float32) / 255.0
    return x, Letterbox(s, px, py, w, h)


def nms(boxes: np.ndarray, scores: np.ndarray, iou: float) -> np.ndarray:
    """Greedy NMS on xyxy boxes; indices kept, highest score first. Suppresses IoU > iou (ultralytics/torchvision)."""
    order = np.argsort(-scores, kind="stable")
    keep: list[int] = []
    x1, y1, x2, y2 = boxes.T
    areas = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    while order.size:
        i = order[0]
        keep.append(int(i))
        rest = order[1:]
        xx1 = np.maximum(x1[i], x1[rest])
        yy1 = np.maximum(y1[i], y1[rest])
        xx2 = np.minimum(x2[i], x2[rest])
        yy2 = np.minimum(y2[i], y2[rest])
        inter = np.clip(xx2 - xx1, 0, None) * np.clip(yy2 - yy1, 0, None)
        union = areas[i] + areas[rest] - inter
        ov = np.where(union > 0, inter / np.maximum(union, 1e-12), 0.0)
        order = rest[ov <= iou]
    return np.asarray(keep, dtype=np.int64)


def _class_thresh_array(nc: int, default_conf: float, mapping: dict[int, float] | None) -> np.ndarray:
    thresh = np.full(nc, default_conf, dtype=np.float32)
    if mapping:
        for ci, t in mapping.items():
            if 0 <= ci < nc:
                thresh[ci] = float(t)
    return thresh


def decode(
    output: np.ndarray,
    lb: Letterbox,
    *,
    conf: float,
    iou: float,
    max_det: int = 300,
    agnostic_iou: float | None = None,
    class_conf: dict[int, float] | None = None,
    class_count_conf: dict[int, float] | None = None,
) -> list[Box]:
    """Raw head output [1, 4 + C, N] (or [4 + C, N]) -> boxes on the original image, best first."""
    out = np.asarray(output, dtype=np.float32)
    if out.ndim == 3:
        out = out[0]
    scores_all = out[4:]
    nc = scores_all.shape[0]
    if out.shape[1] == 0 or nc == 0:
        return []
    pres_thresh = _class_thresh_array(nc, conf, class_conf)
    if class_count_conf is not None or class_conf is not None:
        thresh = pres_thresh.copy()
        if class_count_conf is not None:
            for ci, tc in class_count_conf.items():
                if 0 <= ci < nc:
                    thresh[ci] = 1.0 if pres_thresh[ci] >= 1.0 else min(pres_thresh[ci], max(1e-6, float(tc)))
        valid = (pres_thresh[:, None] < 1.0) & (scores_all >= thresh[:, None])
        masked = np.where(valid, scores_all, -1.0)
        cls = masked.argmax(axis=0)
        best = masked[cls, np.arange(out.shape[1])]
        m = best >= 0.0
    else:
        cls = scores_all.argmax(axis=0)
        best = scores_all[cls, np.arange(out.shape[1])]
        m = best >= conf
    if not m.any():
        return []
    cx, cy, bw, bh = out[0, m], out[1, m], out[2, m], out[3, m]
    xyxy = np.stack([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], axis=1)
    sc, cl = best[m], cls[m]
    # per-class NMS through a coordinate offset per class (as ultralytics): boxes of different classes never overlap
    offset = cl[:, None].astype(np.float32) * 7680.0
    keep = nms(xyxy + offset, sc, iou)
    # Apply hysteresis presence gate before cross-class NMS so unconfirmed candidates never suppress valid boxes.
    if class_count_conf is not None and keep.size:
        confirmed: dict[int, float] = {}
        for k in keep:
            ci = int(cl[k])
            score = float(sc[k])
            if score > confirmed.get(ci, -1.0):
                confirmed[ci] = score
        keep = np.asarray(
            [k for k in keep if confirmed.get(int(cl[k]), -1.0) >= float(pres_thresh[int(cl[k])])],
            dtype=np.int64,
        )
        if not keep.size:
            return []
    if agnostic_iou is not None and keep.size > 1:
        keep = keep[nms(xyxy[keep], sc[keep], agnostic_iou)]
    keep = keep[:max_det]
    res = []
    for k in keep:
        bx = xyxy[k]
        x1 = (bx[0] - lb.pad_x) / lb.scale
        y1 = (bx[1] - lb.pad_y) / lb.scale
        x2 = (bx[2] - lb.pad_x) / lb.scale
        y2 = (bx[3] - lb.pad_y) / lb.scale
        x1, x2 = float(np.clip(x1, 0, lb.width)) / lb.width, float(np.clip(x2, 0, lb.width)) / lb.width
        y1, y2 = float(np.clip(y1, 0, lb.height)) / lb.height, float(np.clip(y2, 0, lb.height)) / lb.height
        if x2 - x1 <= 1e-6 or y2 - y1 <= 1e-6:
            continue  # degenerate after clipping (box entirely in the padding)
        res.append(Box(int(cl[k]), float(min(max(sc[k], 0.0), 1.0)), x1, y1, x2, y2))
    res.sort(key=lambda b: -b.confidence)
    return res


def preprocess(img: Image.Image, version: str | None) -> Image.Image:
    """Whole-image preprocessing named by model_versions.preprocess_version (arms of the 2×2 ablation,
    docs/reports/xu-ly-anh/ket-qua-so-bo.md §5). Crops for the freshness classifier never go through this."""
    arm = (version or "none").strip()
    if arm == "none":
        return img
    from tastoria_ml.cv.preprocess import apply_arm  # same numpy code as training

    return Image.fromarray(apply_arm(np.asarray(img.convert("RGB")), arm))


class Detector:
    """One deployed detector version: an onnxruntime session + its serving parameters."""

    def __init__(
        self,
        session,  # noqa: ANN001
        *,
        conf: float,
        iou: float,
        preprocess_version: str | None = None,
        agnostic_iou: float | None = None,
        class_conf: dict[int, float] | None = None,
        class_count_conf: dict[int, float] | None = None,
        zoom_rescue: dict[str, Any] | None = None,
    ) -> None:
        self.session = session
        self.conf = conf
        self.iou = iou
        self.preprocess_version = preprocess_version
        self.agnostic_iou = agnostic_iou
        self.class_conf = class_conf
        self.class_count_conf = class_count_conf
        self.zoom_rescue = dict(zoom_rescue) if isinstance(zoom_rescue, dict) else None
        inp = session.get_inputs()[0]
        self.input_name = inp.name
        self.size = int(inp.shape[2])

    def _run_raw(self, img: Image.Image) -> tuple[np.ndarray, Letterbox]:
        x, lb = letterbox(img, self.size)
        t0 = time.perf_counter()
        outcome = "ok"
        try:
            out = self.session.run(None, {self.input_name: x})[0]
        except Exception:
            outcome = "error"
            raise
        finally:
            metrics.observe_onnx("detector", time.perf_counter() - t0, outcome=outcome)
        return out, lb

    def _guarded_zoom_rescue(self, img_p: Image.Image, raw_full: np.ndarray) -> list[Box]:
        cfg = self.zoom_rescue
        if not cfg or not cfg.get("enabled"):
            return []
        out = np.asarray(raw_full, dtype=np.float32)
        if out.ndim == 3:
            out = out[0]
        if out.shape[0] <= 4 or out.shape[1] == 0:
            return []
        full_max = out[4:].max(axis=1)
        nc = int(full_max.shape[0])
        pres_thresh = _class_thresh_array(nc, self.conf, self.class_conf)
        full_min = float(cfg.get("full_min", 0.08))
        if not np.any((pres_thresh < 1.0) & (full_max >= full_min)):
            return []
        crop_frac = float(cfg.get("crop_frac", 0.60))
        conf_floor = float(cfg.get("conf_floor", 0.62))
        conf_delta = float(cfg.get("conf_delta", 0.12))
        min_crop_area = float(cfg.get("min_crop_area", 0.025))
        max_crop_area = float(cfg.get("max_crop_area", 0.85))
        w, h = img_p.size
        cw, ch = max(1, round(w * crop_frac)), max(1, round(h * crop_frac))
        if cw < 32 or ch < 32 or (cw >= w and ch >= h):
            return []
        x0, y0 = (w - cw) // 2, (h - ch) // 2
        crop = img_p.crop((x0, y0, x0 + cw, y0 + ch))
        raw_zoom, lb_zoom = self._run_raw(crop)
        rescue_cc = {
            c: (1.0 if pres_thresh[c] >= 1.0 else max(conf_floor, min(0.95, float(pres_thresh[c]) + conf_delta)))
            for c in range(nc)
        }
        z_boxes = decode(
            raw_zoom,
            lb_zoom,
            conf=max(conf_floor, self.conf),
            iou=self.iou,
            max_det=MAX_DETECTIONS_PER_PHOTO,
            agnostic_iou=self.agnostic_iou,
            class_conf=rescue_cc,
            class_count_conf=self.class_count_conf,
        )
        rescued: list[Box] = []
        for b in z_boxes:
            if b.class_index >= nc or float(full_max[b.class_index]) < full_min:
                continue
            crop_area = (b.x2 - b.x1) * (b.y2 - b.y1)
            if not (min_crop_area <= crop_area <= max_crop_area):
                continue
            fx1 = float(np.clip((x0 + b.x1 * cw) / w, 0.0, 1.0))
            fy1 = float(np.clip((y0 + b.y1 * ch) / h, 0.0, 1.0))
            fx2 = float(np.clip((x0 + b.x2 * cw) / w, 0.0, 1.0))
            fy2 = float(np.clip((y0 + b.y2 * ch) / h, 0.0, 1.0))
            if fx2 - fx1 <= 1e-6 or fy2 - fy1 <= 1e-6:
                continue
            rescued.append(Box(b.class_index, b.confidence, fx1, fy1, fx2, fy2))
        rescued.sort(key=lambda b: -b.confidence)
        return rescued[:MAX_DETECTIONS_PER_PHOTO]

    def detect(self, img: Image.Image) -> list[Box]:
        img_p = preprocess(img, self.preprocess_version)
        raw_full, lb_full = self._run_raw(img_p)
        boxes = decode(
            raw_full,
            lb_full,
            conf=self.conf,
            iou=self.iou,
            max_det=MAX_DETECTIONS_PER_PHOTO,
            agnostic_iou=self.agnostic_iou,
            class_conf=self.class_conf,
            class_count_conf=self.class_count_conf,
        )
        if boxes or not (self.zoom_rescue and self.zoom_rescue.get("enabled")):
            return boxes
        return self._guarded_zoom_rescue(img_p, raw_full)
