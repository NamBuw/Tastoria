"""ONNX CPU latency of trained detectors: onnxruntime, 2 intra-op threads, 100 timed runs, p50 / p95.

For each run the best checkpoint is exported twice when the head allows it:
  * ``raw``  — ultralytics default export: raw head output, NMS done afterwards (here cv2.dnn.NMSBoxesBatched,
               IoU 0.7, the same IoU as evaluation) — this is what the backend worker runs today;
  * ``e2e``  — YOLO26 only, ``nms=False``: one-to-one head inside the graph, output (1, 300, 6), no NMS.
Stages timed per image: letterbox (from a decoded RGB array), model, post-processing (score ≥ conf, NMS for
raw). JPEG decoding is excluded. The images are 100 val images (seed 0), 5 warm-up runs.

The exported files stay in ml/runs/detect/<run>/weights/ (gitignored) — never under deploy/models.
Run: python -m tastoria_ml.cv.onnx_latency <run> [<run> ...]
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from tastoria_ml.cv.classes import REPO

RUNS = REPO / "ml" / "runs" / "detect"
YOLO_DIR = REPO / "data" / "processed" / "cv" / "yolo"
OUT = REPO / "data" / "processed" / "cv" / "detector"


def export(run: str, imgsz: int, mode: str) -> Path:
    from ultralytics import YOLO

    best = RUNS / run / "weights" / "best.pt"
    dst = best.with_name(f"best_{mode}_{imgsz}.onnx")
    if not dst.exists():
        # export from a copy: ultralytics writes <weights>.onnx next to the checkpoint, and an existing
        # best.onnx may be the file the backend registered (never overwrite it)
        tmp = RUNS / run / "weights" / f"_export_{mode}"
        tmp.mkdir(exist_ok=True)
        shutil.copy2(best, tmp / "best.pt")
        f = YOLO(str(tmp / "best.pt")).export(format="onnx", imgsz=imgsz, device="cpu",
                                              nms=False if mode == "e2e" else None)
        shutil.move(f, dst)
        shutil.rmtree(tmp)
    return dst


def letterbox(a: np.ndarray, s: int) -> np.ndarray:
    import cv2

    h, w = a.shape[:2]
    r = s / max(h, w)
    nh, nw = max(1, round(h * r)), max(1, round(w * r))
    im = cv2.resize(a, (nw, nh), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((s, s, 3), 114, np.uint8)
    y0, x0 = (s - nh) // 2, (s - nw) // 2
    canvas[y0 : y0 + nh, x0 : x0 + nw] = im
    return canvas.transpose(2, 0, 1)[None].astype(np.float32) / 255.0


def postprocess(out: np.ndarray, mode: str, conf: float = 0.25, iou: float = 0.7) -> int:
    import cv2

    if mode == "e2e":  # (1, 300, 6): x1 y1 x2 y2 score cls
        return int((out[0, :, 4] >= conf).sum())
    p = out[0].T  # (8400, 4 + nc)
    sc = p[:, 4:].max(1)
    k = sc >= conf
    if not k.any():
        return 0
    b, s, c = p[k, :4], sc[k], p[k, 4:].argmax(1)
    xywh = np.concatenate([b[:, :2] - b[:, 2:] / 2, b[:, 2:]], 1)
    keep = cv2.dnn.NMSBoxesBatched(xywh.tolist(), s.tolist(), c.tolist(), conf, iou)
    return len(keep)


def bench(onnx_path: Path, imgsz: int, mode: str, n: int = 100, threads: int = 2) -> dict:
    import cv2
    import onnxruntime as ort

    so = ort.SessionOptions()
    so.intra_op_num_threads = threads
    so.inter_op_num_threads = 1
    so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    sess = ort.InferenceSession(str(onnx_path), so, providers=["CPUExecutionProvider"])
    name = sess.get_inputs()[0].name
    files = sorted((YOLO_DIR / "images" / "val").glob("*.jpg"))
    rng = np.random.default_rng(0)
    files = [files[i] for i in rng.choice(len(files), n, replace=False)]
    ims = [cv2.cvtColor(cv2.imread(str(f)), cv2.COLOR_BGR2RGB) for f in files]
    for a in ims[:5]:
        sess.run(None, {name: letterbox(a, imgsz)})
    t_pre, t_model, t_post = [], [], []
    for a in ims:
        t0 = time.perf_counter()
        x = letterbox(a, imgsz)
        t1 = time.perf_counter()
        out = sess.run(None, {name: x})[0]
        t2 = time.perf_counter()
        postprocess(out, mode)
        t3 = time.perf_counter()
        t_pre.append(t1 - t0)
        t_model.append(t2 - t1)
        t_post.append(t3 - t2)
    q = lambda v: {"p50": float(np.percentile(v, 50) * 1000), "p95": float(np.percentile(v, 95) * 1000)}  # noqa: E731
    tot = np.array(t_pre) + np.array(t_model) + np.array(t_post)
    return {"onnx": str(onnx_path.relative_to(REPO)), "onnx_bytes": onnx_path.stat().st_size,
            "output_shape": list(out.shape), "mode": mode, "imgsz": imgsz, "threads": threads, "n": n,
            "letterbox_ms": q(t_pre), "model_ms": q(t_model), "post_ms": q(t_post), "total_ms": q(tot),
            "onnxruntime": ort.__version__}


def main(runs: list[str]) -> None:
    cpu = subprocess.check_output(["bash", "-c", "lscpu | grep 'Model name' | head -1"], text=True).split(":")[-1].strip()
    for run in runs:
        meta = json.loads((OUT / f"{run}.json").read_text())
        imgsz = meta["imgsz"]
        modes = ["raw", "e2e"] if "26" in meta["model"] else ["raw"]
        res = {"run": run, "model": meta["model"], "cpu": cpu,
               "load_avg_at_start": open("/proc/loadavg").read().split()[:3],
               "note": "shared server, other jobs running; not the target VPS"}
        for mode in modes:
            res[mode] = bench(export(run, imgsz, mode), imgsz, mode)
        (OUT / f"{run}_latency2.json").write_text(json.dumps(res, indent=2))
        print(run, {m: (res[m]["model_ms"], res[m]["total_ms"]) for m in modes}, flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
