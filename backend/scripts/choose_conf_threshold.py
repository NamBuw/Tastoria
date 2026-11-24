"""Choose the serving confidence threshold of a detector on the VALIDATION split (design v2 §7: "ngưỡng conf chọn
trên val"), with the exact post-processing the worker runs (tastoria.modules.scan.detector).

    uv run --package tastoria-backend python backend/scripts/choose_conf_threshold.py \
        --onnx ml/runs/detect/yolo26n_640_none/weights/best.onnx \
        --images data/processed/cv/yolo/images/val --out data/processed/cv/detector/yolo26n_640_none_serving.json

Matching: per image and class, predictions sorted by confidence are matched greedily to an unmatched ground-truth
box with IoU >= 0.5 (the mAP50 rule). For each threshold t on a 0.01 grid: per-class precision, recall, F_beta; the
macro score is the mean over covered classes (gt > 0). With --per-class, selects F_beta per class over t >= min_conf
(preferring the highest threshold within 1e-4 of peak F_beta) and disables classes failing --dead-min-tp /
--dead-min-score via threshold 1.0. The test and heldout splits are never read. CPU only.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from tastoria.modules.scan.detector import decode, letterbox  # noqa: E402

IOU_MATCH = 0.5
NMS_IOU = 0.7
GRID = np.round(np.arange(0.05, 0.951, 0.01), 2)

_WORKER_SESS: Any = None
_WORKER_CFG: tuple[int, float, float, float | None] | None = None


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


def _init_worker(onnx_path: str, threads: int, min_conf: float, nms_iou: float, ag_iou: float | None) -> None:
    global _WORKER_SESS, _WORKER_CFG
    so = ort.SessionOptions()
    so.intra_op_num_threads = threads
    so.inter_op_num_threads = 1
    so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    so.add_session_config_entry("session.intra_op.allow_spinning", "0")
    so.add_session_config_entry("session.inter_op.allow_spinning", "0")
    _WORKER_SESS = ort.InferenceSession(onnx_path, so, providers=["CPUExecutionProvider"])
    size = int(_WORKER_SESS.get_inputs()[0].shape[2])
    _WORKER_CFG = (size, min_conf, nms_iou, ag_iou)


def _infer_one(img_str: str) -> tuple[str, list[tuple[int, float, tuple[float, float, float, float]]]]:
    assert _WORKER_SESS is not None and _WORKER_CFG is not None
    size, min_conf, nms_iou, ag_iou = _WORKER_CFG
    f = Path(img_str)
    with Image.open(f) as im:
        img = im.convert("RGB")
    x, lb = letterbox(img, size)
    inp_name = _WORKER_SESS.get_inputs()[0].name
    raw = _WORKER_SESS.run(None, {inp_name: x})[0]
    boxes = decode(raw, lb, conf=min_conf, iou=nms_iou, agnostic_iou=ag_iou)
    return str(f), [(b.class_index, b.confidence, (b.x1, b.y1, b.x2, b.y2)) for b in boxes]


def _f_beta(p: float, r: float, beta: float) -> float:
    b2 = beta * beta
    denom = b2 * p + r
    return (1.0 + b2) * p * r / denom if denom > 0.0 else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--onnx", required=True)
    ap.add_argument("--images", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--iou", type=float, default=NMS_IOU)
    ap.add_argument("--agnostic-iou", type=float, default=None)
    ap.add_argument("--beta", type=float, default=1.0)
    ap.add_argument("--per-class", action="store_true")
    ap.add_argument("--min-conf", type=float, default=0.05)
    ap.add_argument("--dead-min-tp", type=int, default=0)
    ap.add_argument("--dead-min-score", type=float, default=0.0)
    ap.add_argument("--workers", type=int, default=1)
    a = ap.parse_args()

    so = ort.SessionOptions()
    so.intra_op_num_threads = a.threads
    so.inter_op_num_threads = 1
    sess = ort.InferenceSession(a.onnx, so, providers=["CPUExecutionProvider"])
    meta = sess.get_modelmeta().custom_metadata_map
    names = ast.literal_eval(meta["names"])  # ultralytics writes a dict literal of our own export
    nc = len(names)
    size = int(sess.get_inputs()[0].shape[2])
    inp_name = sess.get_inputs()[0].name
    files = sorted(Path(a.images).glob("*.jpg"))
    decode_floor = min(float(GRID[0]), float(a.min_conf))

    # per class: list of (confidence, is_tp) for every prediction, and number of ground-truth boxes
    preds: list[list[tuple[float, bool]]] = [[] for _ in range(nc)]
    n_gt = np.zeros(nc, int)
    t0 = time.time()

    if a.workers > 1:
        del sess
        worker_threads = 2
        with ProcessPoolExecutor(
            max_workers=a.workers,
            initializer=_init_worker,
            initargs=(a.onnx, worker_threads, decode_floor, a.iou, a.agnostic_iou),
        ) as ex:
            results = ex.map(_infer_one, [str(f) for f in files], chunksize=16)
            for f_str, boxes in results:
                gts = _labels(Path(f_str))
                for c in range(nc):
                    g = np.array([b for k, b in gts if k == c]).reshape(-1, 4)
                    n_gt[c] += len(g)
                    used = np.zeros(len(g), bool)
                    for ci, sc, xy in boxes:
                        if ci != c:
                            continue
                        tp = False
                        if len(g):
                            ious = _iou(np.array(xy), g)
                            ious[used] = -1
                            j = int(ious.argmax())
                            if ious[j] >= IOU_MATCH:
                                used[j] = True
                                tp = True
                        preds[c].append((sc, tp))
    else:
        for f in files:
            with Image.open(f) as im:
                img = im.convert("RGB")
            x, lb = letterbox(img, size)
            raw = sess.run(None, {inp_name: x})[0]
            boxes = decode(raw, lb, conf=decode_floor, iou=a.iou, agnostic_iou=a.agnostic_iou)
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

    def at_class(c: int, t: float) -> dict[str, Any]:
        tp = sum(1 for s, ok in preds[c] if s >= t and ok)
        fp = sum(1 for s, ok in preds[c] if s >= t and not ok)
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / n_gt[c] if n_gt[c] else 0.0
        f1 = 2 * p * r / (p + r) if p + r else 0.0
        fb = _f_beta(p, r, a.beta)
        return {"precision": p, "recall": r, "f1": f1, "f_beta": fb, "tp": tp, "fp": fp, "gt": int(n_gt[c])}

    def at(t: float) -> dict[str, dict[str, Any]]:
        return {names[c]: at_class(c, t) for c in range(nc)}

    covered = [c for c in range(nc) if n_gt[c] > 0]
    eval_classes = covered if covered else list(range(nc))
    grid_eval = [float(t) for t in GRID if float(t) >= a.min_conf - 1e-9]
    curve = [(float(t), float(np.mean([at_class(c, float(t))["f_beta"] for c in eval_classes]))) for t in GRID]
    curve_allowed = [(t, s) for t, s in curve if t >= a.min_conf - 1e-9]
    best_t, best_score = max(curve_allowed, key=lambda x: (x[1], x[0]))

    out: dict[str, Any] = {
        "conf": best_t,
        "iou": a.iou,
        "imgsz": size,
        "beta": a.beta,
        "selection": f"argmax macro-F{a.beta:g} over covered classes on validation split, IoU >= 0.5 greedy",
        "split": str(a.images),
        "n_images": len(files),
        "macro_f1": float(np.mean([at_class(c, best_t)["f1"] for c in eval_classes])),
        f"macro_f{a.beta:g}": best_score,
        "per_class_at_conf": at(best_t),
        "f1_curve": [{"conf": t, "macro_f1": round(f, 4)} for t, f in curve],
        "onnx": Path(a.onnx).name,
        "seconds": round(elapsed, 1),
        "note": "validation split calibration only; never inspect test/heldout during threshold selection.",
    }
    if a.agnostic_iou is not None:
        out["agnostic_iou"] = a.agnostic_iou

    if a.per_class:
        class_conf: dict[str, float] = {}
        disabled: list[str] = []
        per_class_cal: dict[str, dict[str, Any]] = {}
        for c in range(nc):
            cname = names[c]
            rows = [(t, at_class(c, t)) for t in grid_eval]
            peak_fb = max(r["f_beta"] for _, r in rows) if rows else 0.0
            # Tie-break within 1e-4 of peak F_beta toward the higher confidence threshold.
            cand = [(t, r) for t, r in rows if r["f_beta"] >= peak_fb - 1e-4]
            chosen_t, chosen_r = max(cand, key=lambda x: x[0])
            if n_gt[c] == 0 or chosen_r["tp"] < a.dead_min_tp or chosen_r["f_beta"] < a.dead_min_score:
                class_conf[cname] = 1.0
                disabled.append(cname)
                per_class_cal[cname] = {**chosen_r, "threshold": 1.0, "disabled": True}
            else:
                class_conf[cname] = chosen_t
                per_class_cal[cname] = {**chosen_r, "threshold": chosen_t, "disabled": False}
        out["class_conf"] = class_conf
        out["disabled_classes"] = disabled
        out["per_class_calibrated"] = per_class_cal
        out["selection"] = (
            f"per-class argmax F{a.beta:g} on val (t >= {a.min_conf:.2f}, tie -> higher t, "
            f"dead gate tp>={a.dead_min_tp} & score>={a.dead_min_score})"
        )

    Path(a.out).write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary: dict[str, Any] = {
        "conf": best_t,
        "score": round(best_score, 4),
        "n_images": len(files),
        "s": round(elapsed),
    }
    if a.per_class:
        summary["disabled_classes"] = out["disabled_classes"]
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
