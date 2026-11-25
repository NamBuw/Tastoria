"""CPU ONNXRuntime D-FINE multi-dish tray & plate detector (plate_detector.serving.v1)."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort
from PIL import Image

from tastoria.modules.meal_calorie.estimator import (
    ArtifactIntegrityError,
    make_cpu_session,
    onnx_infer_slot,
    sha256_file,
)

DEFAULT_PLATE_SIZE = 640
DEFAULT_PLATE_LABELS: dict[int, str] = {0: "dish_plate", 1: "bowl", 2: "drink_cup"}


@dataclass(frozen=True)
class DetectedPlate:
    label: str
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float


def _nms_xyxy(boxes: np.ndarray, scores: np.ndarray, iou_thr: float) -> list[int]:
    if len(boxes) == 0:
        return []
    order = np.argsort(-scores)
    keep: list[int] = []
    areas = np.maximum(0.0, boxes[:, 2] - boxes[:, 0]) * np.maximum(0.0, boxes[:, 3] - boxes[:, 1])
    while len(order) > 0:
        i = int(order[0])
        keep.append(i)
        if len(order) == 1:
            break
        rest = order[1:]
        xx1 = np.maximum(boxes[i, 0], boxes[rest, 0])
        yy1 = np.maximum(boxes[i, 1], boxes[rest, 1])
        xx2 = np.minimum(boxes[i, 2], boxes[rest, 2])
        yy2 = np.minimum(boxes[i, 3], boxes[rest, 3])
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        union = areas[i] + areas[rest] - inter + 1e-8
        order = rest[inter / union <= iou_thr]
    return keep


def decode_dfine(
    logits: np.ndarray,
    pred_boxes: np.ndarray,
    *,
    labels: dict[int, str] | None = None,
    conf_threshold: float = 0.35,
    nms_iou: float = 0.60,
    max_crops: int = 8,
) -> list[DetectedPlate]:
    """Decode D-FINE logits `(N, C)` + normalized `cxcywh` boxes `(N, 4)` into clamped `[0, 1]` detections."""
    l_arr = np.asarray(logits, dtype=np.float64)
    b_arr = np.asarray(pred_boxes, dtype=np.float64)
    if l_arr.ndim == 3:
        l_arr = l_arr[0]
    if b_arr.ndim == 3:
        b_arr = b_arr[0]
    if l_arr.ndim != 2 or b_arr.ndim != 2 or len(l_arr) != len(b_arr) or len(l_arr) == 0:
        return []
    if not (np.all(np.isfinite(l_arr)) and np.all(np.isfinite(b_arr))):
        return []

    probs = 1.0 / (1.0 + np.exp(-np.clip(l_arr, -30.0, 30.0)))
    cls_ids = probs.argmax(axis=1)
    scores = probs[np.arange(len(probs)), cls_ids]
    keep_mask = scores >= float(conf_threshold)
    if not np.any(keep_mask):
        return []

    sel_cls = cls_ids[keep_mask]
    sel_scores = scores[keep_mask]
    sel_cxcywh = b_arr[keep_mask]
    cx, cy, w, h = sel_cxcywh[:, 0], sel_cxcywh[:, 1], np.maximum(0.0, sel_cxcywh[:, 2]), np.maximum(0.0, sel_cxcywh[:, 3])
    xyxy = np.stack(
        [
            np.clip(cx - w * 0.5, 0.0, 1.0),
            np.clip(cy - h * 0.5, 0.0, 1.0),
            np.clip(cx + w * 0.5, 0.0, 1.0),
            np.clip(cy + h * 0.5, 0.0, 1.0),
        ],
        axis=1,
    )
    valid = (xyxy[:, 2] > xyxy[:, 0] + 1e-4) & (xyxy[:, 3] > xyxy[:, 1] + 1e-4)
    if not np.any(valid):
        return []
    xyxy, sel_scores, sel_cls = xyxy[valid], sel_scores[valid], sel_cls[valid]

    kept = _nms_xyxy(xyxy, sel_scores, float(nms_iou))[: max(1, int(max_crops))]
    lbl_map = labels or DEFAULT_PLATE_LABELS
    out: list[DetectedPlate] = []
    for k in kept:
        cid = int(sel_cls[k])
        bx = xyxy[k]
        out.append(
            DetectedPlate(
                label=str(lbl_map.get(cid, f"class_{cid}")),
                confidence=round(float(sel_scores[k]), 4),
                x1=round(float(bx[0]), 4),
                y1=round(float(bx[1]), 4),
                x2=round(float(bx[2]), 4),
                y2=round(float(bx[3]), 4),
            )
        )
    return out


class PlateDetector:
    """CPU ONNXRuntime wrapper for multi-dish tray/plate localization."""

    def __init__(self, session: ort.InferenceSession, *, serving: dict[str, Any]) -> None:
        self.session = session
        self.serving = serving
        inp = session.get_inputs()[0]
        self.input_name = inp.name
        shape = inp.shape
        self.size = int(shape[2]) if len(shape) == 4 and isinstance(shape[2], int) else DEFAULT_PLATE_SIZE
        raw_labels = serving.get("labels") or {}
        self.labels = {int(k): str(v) for k, v in raw_labels.items()} or dict(DEFAULT_PLATE_LABELS)
        self.conf_threshold = float(serving.get("conf_threshold", 0.35))
        self.nms_iou = float(serving.get("nms_iou", 0.60))
        self.max_crops = int(serving.get("max_crops", 8))

    def detect(self, img: Image.Image) -> tuple[list[DetectedPlate], float]:
        rgb = img.convert("RGB").resize((self.size, self.size), Image.Resampling.BILINEAR)
        x = (np.asarray(rgb, dtype=np.float32) / 255.0).transpose(2, 0, 1)[None, ...]
        with onnx_infer_slot("plate_detector"):
            t0 = time.perf_counter()
            outs = self.session.run(None, {self.input_name: x})
            latency_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        if len(outs) < 2:
            return [], latency_ms
        plates = decode_dfine(
            outs[0],
            outs[1],
            labels=self.labels,
            conf_threshold=self.conf_threshold,
            nms_iou=self.nms_iou,
            max_crops=self.max_crops,
        )
        return plates, latency_ms


def load_plate_detector(model_dir: Path, *, verify_sha256: bool = True) -> PlateDetector:
    model_dir = Path(model_dir)
    serving_path = model_dir / "serving.json"
    if not serving_path.exists():
        raise ArtifactIntegrityError(f"Missing serving.json in {model_dir}")
    serving = json.loads(serving_path.read_text(encoding="utf-8"))
    artifact_name = str(serving.get("artifact_file") or "model.onnx")
    onnx_path = model_dir / artifact_name
    if not onnx_path.exists():
        raise ArtifactIntegrityError(f"Missing ONNX artifact {onnx_path}")
    if verify_sha256:
        expected = serving.get("artifact_sha256")
        if not expected:
            raise ArtifactIntegrityError(f"Missing artifact_sha256 in {serving_path}")
        actual = sha256_file(onnx_path)
        if actual != expected:
            raise ArtifactIntegrityError(f"SHA-256 mismatch for {onnx_path}: expected {expected}, got {actual}")
    sess = make_cpu_session(onnx_path, intra_threads=2)
    return PlateDetector(sess, serving=serving)
