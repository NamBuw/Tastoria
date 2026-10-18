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

from dataclasses import dataclass

import numpy as np
from PIL import Image

PAD_VALUE = 114


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


def decode(output: np.ndarray, lb: Letterbox, *, conf: float, iou: float, max_det: int = 300) -> list[Box]:
    """Raw head output [1, 4 + C, N] (or [4 + C, N]) -> boxes on the original image, best first."""
    out = np.asarray(output, dtype=np.float32)
    if out.ndim == 3:
        out = out[0]
    scores_all = out[4:]
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
    keep = nms(xyxy + offset, sc, iou)[:max_det]
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

    def __init__(self, session, *, conf: float, iou: float, preprocess_version: str | None = None) -> None:  # noqa: ANN001
        self.session = session
        self.conf = conf
        self.iou = iou
        self.preprocess_version = preprocess_version
        inp = session.get_inputs()[0]
        self.input_name = inp.name
        self.size = int(inp.shape[2])

    def detect(self, img: Image.Image) -> list[Box]:
        x, lb = letterbox(preprocess(img, self.preprocess_version), self.size)
        out = self.session.run(None, {self.input_name: x})[0]
        return decode(out, lb, conf=self.conf, iou=self.iou)
