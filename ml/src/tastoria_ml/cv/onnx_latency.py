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

import argparse
import json
import multiprocessing as mp
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from tastoria_ml.cv.classes import REPO

RUNS = REPO / "ml" / "runs" / "detect"
YOLO_DIR = REPO / "data" / "processed" / "cv" / "yolo"
YOLO_V2_DIR = REPO / "data" / "processed" / "cv" / "yolo_v2"
OUT = REPO / "data" / "processed" / "cv" / "detector"
OUT_V2 = REPO / "ml" / "runs" / "research" / "p1_detection" / "detector_runs"


def resolve_yolo_dir(dataset: str | Path = "yolo", yolo_dir: str | Path | None = None) -> Path:
    if yolo_dir is not None:
        return Path(yolo_dir)
    if str(dataset) == "yolo":
        return YOLO_DIR
    if str(dataset) == "yolo_v2":
        return YOLO_V2_DIR
    p = Path(dataset)
    if p.exists():
        return p
    raise ValueError(f"Unknown dataset '{dataset}' and path does not exist")


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


def _check_output_shape(shape: tuple | list, mode: str, expected_nc: int | None = None) -> None:
    if mode == "e2e":
        if len(shape) != 3 or tuple(shape) != (1, 300, 6):
            raise ValueError(f"Expected e2e ONNX output shape (1, 300, 6), got {tuple(shape)}")
    else:
        if len(shape) != 3 or shape[0] != 1 or shape[2] != 8400:
            raise ValueError(f"Expected raw ONNX output shape (1, 4+nc, 8400), got {tuple(shape)}")
        if expected_nc is not None and shape[1] != 4 + expected_nc:
            raise ValueError(f"Expected raw channel dim 4+{expected_nc}={4 + expected_nc}, got {shape[1]}")


def _latency_summary(vals_sec: list[float] | np.ndarray) -> dict[str, float]:
    ms = np.asarray(vals_sec, dtype=float) * 1000.0
    return {
        "p50": float(np.percentile(ms, 50)),
        "p95": float(np.percentile(ms, 95)),
        "p99": float(np.percentile(ms, 99)),
        "mean": float(np.mean(ms)),
    }


def _make_session(onnx_path: Path, threads: int):
    import onnxruntime as ort

    so = ort.SessionOptions()
    so.intra_op_num_threads = threads
    so.inter_op_num_threads = 1
    so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    so.add_session_config_entry("session.intra_op.allow_spinning", "0")
    so.add_session_config_entry("session.inter_op.allow_spinning", "0")
    return ort.InferenceSession(str(onnx_path), so, providers=["CPUExecutionProvider"]), ort.__version__


def bench(
    onnx_path: Path,
    imgsz: int,
    mode: str,
    n: int = 100,
    threads: int = 2,
    yolo_dir: Path = YOLO_DIR,
    expected_nc: int | None = None,
) -> dict:
    import cv2

    sess, ort_ver = _make_session(onnx_path, threads)
    name = sess.get_inputs()[0].name
    files = sorted((yolo_dir / "images" / "val").glob("*.jpg"))
    rng = np.random.default_rng(0)
    files = [files[i] for i in rng.choice(len(files), min(n, len(files)), replace=False)]
    ims = [cv2.cvtColor(cv2.imread(str(f)), cv2.COLOR_BGR2RGB) for f in files]
    for a in ims[:5]:
        sess.run(None, {name: letterbox(a, imgsz)})
    t_pre, t_model, t_post = [], [], []
    out_shape: tuple[int, ...] = ()
    for a in ims:
        t0 = time.perf_counter()
        x = letterbox(a, imgsz)
        t1 = time.perf_counter()
        out = sess.run(None, {name: x})[0]
        t2 = time.perf_counter()
        postprocess(out, mode)
        t3 = time.perf_counter()
        out_shape = tuple(out.shape)
        t_pre.append(t1 - t0)
        t_model.append(t2 - t1)
        t_post.append(t3 - t2)
    _check_output_shape(out_shape, mode, expected_nc=expected_nc)
    tot = np.array(t_pre) + np.array(t_model) + np.array(t_post)
    return {
        "onnx": str(onnx_path.relative_to(REPO)) if onnx_path.is_relative_to(REPO) else str(onnx_path),
        "onnx_bytes": onnx_path.stat().st_size,
        "output_shape": list(out_shape),
        "mode": mode,
        "concurrency": 1,
        "imgsz": imgsz,
        "threads": threads,
        "n": len(ims),
        "letterbox_ms": _latency_summary(t_pre),
        "model_ms": _latency_summary(t_model),
        "post_ms": _latency_summary(t_post),
        "total_ms": _latency_summary(tot),
        "onnxruntime": ort_ver,
    }


def _concurrent_worker(args) -> dict:
    onnx_str, file_strs, imgsz, mode, threads, barrier = args
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
    import cv2

    sess, ort_ver = _make_session(Path(onnx_str), threads)
    name = sess.get_inputs()[0].name
    ims = [cv2.cvtColor(cv2.imread(f), cv2.COLOR_BGR2RGB) for f in file_strs]
    for a in ims[:5]:
        sess.run(None, {name: letterbox(a, imgsz)})
    barrier.wait()
    t_start = time.perf_counter()
    t_pre, t_model, t_post = [], [], []
    out_shape: tuple[int, ...] = ()
    for a in ims:
        t0 = time.perf_counter()
        x = letterbox(a, imgsz)
        t1 = time.perf_counter()
        out = sess.run(None, {name: x})[0]
        t2 = time.perf_counter()
        postprocess(out, mode)
        t3 = time.perf_counter()
        out_shape = tuple(out.shape)
        t_pre.append(t1 - t0)
        t_model.append(t2 - t1)
        t_post.append(t3 - t2)
    t_end = time.perf_counter()
    return {
        "t_pre": t_pre,
        "t_model": t_model,
        "t_post": t_post,
        "wall_s": t_end - t_start,
        "output_shape": list(out_shape),
        "ort": ort_ver,
    }


def bench_concurrent(
    onnx_path: Path,
    imgsz: int,
    mode: str,
    concurrency: int = 5,
    n: int = 100,
    threads: int = 2,
    yolo_dir: Path = YOLO_DIR,
    expected_nc: int | None = None,
) -> dict:
    """Benchmark ``concurrency`` simultaneous CPU onnxruntime worker processes (each ``n`` images)."""
    if concurrency <= 1:
        return bench(onnx_path, imgsz, mode, n=n, threads=threads, yolo_dir=yolo_dir, expected_nc=expected_nc)

    files = sorted((yolo_dir / "images" / "val").glob("*.jpg"))
    rng = np.random.default_rng(0)
    files = [str(files[i]) for i in rng.choice(len(files), min(n, len(files)), replace=False)]

    ctx = mp.get_context("spawn")
    with ctx.Manager() as mgr:
        barrier = mgr.Barrier(concurrency)
        t0 = time.perf_counter()
        with ProcessPoolExecutor(max_workers=concurrency, mp_context=ctx) as ex:
            results = list(
                ex.map(
                    _concurrent_worker,
                    [(str(onnx_path), files, imgsz, mode, threads, barrier) for _ in range(concurrency)],
                )
            )
        wall_s = time.perf_counter() - t0

    t_pre = [x for r in results for x in r["t_pre"]]
    t_model = [x for r in results for x in r["t_model"]]
    t_post = [x for r in results for x in r["t_post"]]
    tot = np.array(t_pre) + np.array(t_model) + np.array(t_post)
    out_shape = tuple(results[0]["output_shape"])
    _check_output_shape(out_shape, mode, expected_nc=expected_nc)
    max_worker_wall = max(r["wall_s"] for r in results)
    total_images = len(tot)
    return {
        "onnx": str(onnx_path.relative_to(REPO)) if onnx_path.is_relative_to(REPO) else str(onnx_path),
        "onnx_bytes": onnx_path.stat().st_size,
        "output_shape": list(out_shape),
        "mode": mode,
        "concurrency": concurrency,
        "imgsz": imgsz,
        "threads": threads,
        "n_per_worker": len(files),
        "n_total": total_images,
        "letterbox_ms": _latency_summary(t_pre),
        "model_ms": _latency_summary(t_model),
        "post_ms": _latency_summary(t_post),
        "total_ms": _latency_summary(tot),
        "worker_wall_s": round(max_worker_wall, 3),
        "total_wall_s": round(wall_s, 3),
        "throughput_img_s": round(total_images / max(max_worker_wall, 1e-9), 2),
        "onnxruntime": results[0]["ort"],
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--dataset", default="yolo", choices=["yolo", "yolo_v2"])
    ap.add_argument("--yolo-dir", default=None)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--concurrency", type=int, nargs="+", default=[1])
    a = ap.parse_args(argv)
    ydir = resolve_yolo_dir(a.dataset, a.yolo_dir)
    dest_out = OUT_V2 if ydir == YOLO_V2_DIR else OUT
    dest_out.mkdir(parents=True, exist_ok=True)
    cpu = subprocess.check_output(["bash", "-c", "lscpu | grep 'Model name' | head -1"], text=True).split(":")[-1].strip()
    for run in a.runs:
        meta = json.loads((dest_out / f"{run}.json").read_text())
        imgsz = meta["imgsz"]
        modes = ["raw", "e2e"] if "26" in meta["model"] else ["raw"]
        res = {
            "run": run,
            "dataset": ydir.name,
            "model": meta["model"],
            "cpu": cpu,
            "load_avg_at_start": open("/proc/loadavg").read().split()[:3],
            "note": "shared server, other jobs running; not the target VPS",
        }
        for mode in modes:
            onnx_p = export(run, imgsz, mode)
            res[mode] = bench(onnx_p, imgsz, mode, n=a.n, threads=a.threads, yolo_dir=ydir)
            for c in a.concurrency:
                if c > 1:
                    res[f"{mode}_c{c}"] = bench_concurrent(
                        onnx_p, imgsz, mode, concurrency=c, n=a.n, threads=a.threads, yolo_dir=ydir
                    )
        (dest_out / f"{run}_latency2.json").write_text(json.dumps(res, indent=2))
        print(run, {m: (res[m]["model_ms"], res[m]["total_ms"]) for m in modes}, flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
