"""Choose the serving confidence threshold of a detector on the VALIDATION split (design v2 §7: "ngưỡng conf chọn
trên val"), with exactly the post-processing the worker runs (tastoria.modules.scan.detector).

    uv run --package tastoria-backend python backend/scripts/choose_conf_threshold.py \
        --onnx ml/runs/detect/yolo26n_640_none/weights/best.onnx \
        --images data/processed/cv/yolo/images/val --out data/processed/cv/detector/yolo26n_640_none_serving.json

Matching: per image and class, predictions sorted by confidence are matched greedily to an unmatched ground-truth
box with IoU ≥ 0.5 (the mAP50 rule). For each threshold t on a 0.01 grid: per-class precision, recall, F1; the
macro F1 is the mean over classes (ultralytics' "all classes" F1 curve). The threshold with the highest macro F1 is
written with the per-class numbers at that threshold. The test split is not read. CPU only.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from tastoria.modules.scan.detector import decode, letterbox  # noqa: E402

IOU_MATCH = 0.5
NMS_IOU = 0.7
GRID = np.round(np.arange(0.05, 0.951, 0.01), 2)


def _iou(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    ix = np.clip(np.minimum(a[2], b[:, 2]) - np.maximum(a[0], b[:, 0]), 0, None)
    iy = np.clip(np.minimum(a[3], b[:, 3]) - np.maximum(a[1], b[:, 1]), 0, None)
    inter = ix * iy
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1]) - inter)


def _labels(img: Path) -> list[tuple[int, np.ndarray]]:
    p = Path(str(img).replace("/images/", "/labels/")).with_suffix(".txt")
    out = []
    if p.exists():
        for line in p.read_text().split("\n"):
            if line.strip():
                c, cx, cy, w, h = line.split()[:5]
                cx, cy, w, h = map(float, (cx, cy, w, h))
                out.append((int(c), np.array([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2])))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--onnx", required=True)
    ap.add_argument("--images", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--threads", type=int, default=4)
    a = ap.parse_args()
    so = ort.SessionOptions()
    so.intra_op_num_threads = a.threads
    so.inter_op_num_threads = 1
    sess = ort.InferenceSession(a.onnx, so, providers=["CPUExecutionProvider"])
    meta = sess.get_modelmeta().custom_metadata_map
    names = eval(meta["names"])  # noqa: S307 — ultralytics writes a dict literal of our own export
    nc = len(names)
    size = int(sess.get_inputs()[0].shape[2])
    files = sorted(Path(a.images).glob("*.jpg"))
    # per class: list of (confidence, is_tp) for every prediction, and number of ground-truth boxes
    preds: list[list[tuple[float, bool]]] = [[] for _ in range(nc)]
    n_gt = np.zeros(nc, int)
    t0 = time.time()
    for f in files:
        with Image.open(f) as im:
            img = im.convert("RGB")
        x, lb = letterbox(img, size)
        boxes = decode(sess.run(None, {"images": x})[0], lb, conf=float(GRID[0]), iou=NMS_IOU)
        gts = _labels(f)
        for c in range(nc):
            g = np.array([b for k, b in gts if k == c]).reshape(-1, 4)
            n_gt[c] += len(g)
            used = np.zeros(len(g), bool)
            for b in (b for b in boxes if b.class_index == c):  # already sorted by confidence
                tp = False
                if len(g):
                    ious = _iou(np.array([b.x1, b.y1, b.x2, b.y2]), g)
                    ious[used] = -1
                    j = int(ious.argmax())
                    if ious[j] >= IOU_MATCH:
                        used[j] = True
                        tp = True
                preds[c].append((b.confidence, tp))
    elapsed = time.time() - t0

    def at(t: float) -> dict[str, dict[str, float]]:
        res = {}
        for c in range(nc):
            tp = sum(1 for s, ok in preds[c] if s >= t and ok)
            fp = sum(1 for s, ok in preds[c] if s >= t and not ok)
            p = tp / (tp + fp) if tp + fp else 0.0
            r = tp / n_gt[c] if n_gt[c] else 0.0
            f1 = 2 * p * r / (p + r) if p + r else 0.0
            res[names[c]] = {"precision": p, "recall": r, "f1": f1, "tp": tp, "fp": fp, "gt": int(n_gt[c])}
        return res

    curve = [(float(t), float(np.mean([v["f1"] for v in at(t).values()]))) for t in GRID]
    best_t, best_f1 = max(curve, key=lambda x: (x[1], -x[0]))
    out = {
        "conf": best_t,
        "iou": NMS_IOU,
        "imgsz": size,
        "selection": "argmax macro-F1 over classes, validation split, IoU >= 0.5 greedy matching, grid 0.05..0.95",
        "split": str(a.images),
        "n_images": len(files),
        "macro_f1": best_f1,
        "per_class_at_conf": at(best_t),
        "f1_curve": [{"conf": t, "macro_f1": round(f, 4)} for t, f in curve],
        "onnx": Path(a.onnx).name,
        "seconds": round(elapsed, 1),
        "note": "public data only (Open Images V7 + Mendeley Bangladesh); Open Images labels are not exhaustive, so "
        "precision is a lower bound. Re-run on the team's fridge validation split before the final report.",
    }
    Path(a.out).write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"conf": best_t, "macro_f1": round(best_f1, 4), "n_images": len(files), "s": round(elapsed)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
