"""Dump raw detector predictions (conf ≥ 0.001, max 300 per image) for offline evaluation.

One ``.npz`` per (run, split, head mode) in ml/runs/preds/: image files, original (h, w), boxes in
original-pixel xyxy, scores, class ids, and the image index of every box. COCO evaluation, bootstrap,
counting and figures all read these files, so the GPU is needed only once per model.

Head modes: ``nms`` = one-to-many head + NMS (IoU 0.7, ultralytics default for val/predict);
``e2e`` = YOLO26 one-to-one head, NMS-free (``nms=False``).
Images are read with cv2 (BGR, as ultralytics does) and the ablation arm is applied to the whole image
before letterboxing, in a process pool, once per split.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from tastoria_ml.cv.classes import REPO

PREDS = REPO / "ml" / "runs" / "preds"


def pred_path(name: str, split: str, mode: str = "nms") -> Path:
    return PREDS / f"{name}__{split}__{mode}.npz"


def load_bgr(path: Path, arm: str = "none") -> np.ndarray:
    """Image as ultralytics reads it (cv2 BGR), with the ablation arm applied to the whole image."""
    import cv2

    im = cv2.imread(str(path))
    if arm in ("none", "aug"):
        return im
    from tastoria_ml.cv.preprocess import apply_arm
    from tastoria_ml.cv.train_detector import parse_arm

    base, clip, grid = parse_arm(arm)
    return np.ascontiguousarray(apply_arm(im[..., ::-1], base, clip, grid)[..., ::-1])


def _load(args):
    return load_bgr(*args)


def load_split(images_dir: Path, arm: str = "none", workers: int = 8) -> tuple[list[Path], list[np.ndarray]]:
    files = sorted(images_dir.glob("*.jpg"))
    if arm in ("none", "aug"):
        return files, [load_bgr(f) for f in files]
    import multiprocessing as mp

    with ProcessPoolExecutor(workers, mp_context=mp.get_context("fork")) as ex:
        ims = list(ex.map(_load, [(f, arm) for f in files], chunksize=16))
    return files, ims


def dump(weights: Path, images_dir: Path, out: Path, imgsz: int, mode: str = "nms", device=0,
         batch: int = 16, arm: str = "none", loaded=None) -> Path:
    from ultralytics import YOLO

    files, ims = loaded if loaded is not None else load_split(images_dir, arm)
    m = YOLO(str(weights))
    hw, boxes, scores, cls, idx = [], [], [], [], []
    nms_arg = False if mode == "e2e" else None
    for i0 in range(0, len(files), 64):
        res = m.predict(ims[i0 : i0 + 64], conf=0.001, iou=0.7, max_det=300, imgsz=imgsz, device=device,
                        verbose=False, nms=nms_arg, batch=batch)
        for j, r in enumerate(res):
            hw.append(r.orig_shape)
            b = r.boxes
            boxes.append(b.xyxy.cpu().numpy().astype(np.float32).reshape(-1, 4))
            scores.append(b.conf.cpu().numpy().astype(np.float32))
            cls.append(b.cls.cpu().numpy().astype(np.int16))
            idx.append(np.full(len(b), i0 + j, np.int32))
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out, files=np.array([f.name for f in files]), hw=np.array(hw, np.int32),
        boxes=np.concatenate(boxes), scores=np.concatenate(scores), cls=np.concatenate(cls),
        img=np.concatenate(idx), names=np.array([m.names[k] for k in sorted(m.names)]),
    )
    return out
