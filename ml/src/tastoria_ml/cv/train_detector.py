"""Train / evaluate the public-data detector baseline (YOLO26n, ultralytics pinned 8.4.173).

Shared-GPU rules (thiết kế v2 §7, review:cv#11), enforced here:
  * before a job: ``nvidia-smi`` must report ≥ 10 GB free, otherwise the job does not start;
  * ``torch.cuda.set_per_process_memory_fraction(0.15)`` before any CUDA allocation;
  * fixed batch (16 at 640), never ``batch=-1``; one job at a time (a lock file in ml/runs/);
  * a watchdog polls ``nvidia-smi`` every 5 s and kills this process if free memory < 3 GB.

Commands (training env, from the repo root):
  python -m tastoria_ml.cv.train_detector train --name smoke --epochs 1
  python -m tastoria_ml.cv.train_detector train --name yolo26n_640_none --epochs 100 --patience 15
  python -m tastoria_ml.cv.train_detector prep-arm --arm gw      # preprocessed copy for the ablation
  python -m tastoria_ml.cv.train_detector train --name abl_gw --arm gw --epochs 40
  python -m tastoria_ml.cv.train_detector latency --name yolo26n_640_none

Metrics go to MLflow (sqlite ml/mlruns/mlflow.db, artifacts ml/mlruns/artifacts, both gitignored) and to
data/processed/cv/detector/<name>.json.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import signal
import subprocess
import threading
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from tastoria_ml.cv.classes import REPO

YOLO_DIR = REPO / "data" / "processed" / "cv" / "yolo"
ABL_DIR = REPO / "data" / "processed" / "cv" / "ablation"
OUT = REPO / "data" / "processed" / "cv" / "detector"
RUNS = REPO / "ml" / "runs" / "detect"
MLRUNS = REPO / "ml" / "mlruns"
LOCK = REPO / "ml" / "runs" / "gpu.lock"
ULTRALYTICS_VERSION = "8.4.173"
MIN_FREE_START_MB = 10 * 1024
MIN_FREE_RUN_MB = 3 * 1024
MEM_FRACTION = 0.15


# ------------------------------------------------------------------ GPU safety


def gpu_free_mb() -> tuple[int, int]:
    out = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"], text=True
    )
    used, total = (int(x) for x in out.strip().splitlines()[0].split(","))
    return total - used, total


def gpu_apps() -> str:
    return subprocess.check_output(
        ["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv"], text=True
    ).strip()


def _watchdog(stop: threading.Event, log: Path) -> None:
    with log.open("a") as f:
        while not stop.is_set():
            try:
                free, total = gpu_free_mb()
            except Exception as e:  # noqa: BLE001
                f.write(f"{time.strftime('%H:%M:%S')} nvidia-smi failed: {e}\n")
                free = MIN_FREE_RUN_MB + 1
            f.write(f"{time.strftime('%H:%M:%S')} free {free} MB of {total} MB\n")
            f.flush()
            if free < MIN_FREE_RUN_MB:
                f.write("free memory below 3 GB: stopping this job now\n")
                f.flush()
                os.kill(os.getpid(), signal.SIGKILL)
            stop.wait(5)


class GpuGuard:
    """Checks free memory, takes the one-job lock, caps memory and starts the watchdog."""

    def __init__(self, name: str):
        self.name = name

    def __enter__(self):
        free, total = gpu_free_mb()
        print(f"[gpu] free {free} MB / {total} MB\n{gpu_apps()}", flush=True)
        if free < MIN_FREE_START_MB:
            raise SystemExit(f"[gpu] only {free} MB free (< 10 GB): not starting")
        LOCK.parent.mkdir(parents=True, exist_ok=True)
        self._lock = LOCK.open("w")
        try:
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("[gpu] another Tastoria GPU job holds ml/runs/gpu.lock") from None
        import torch

        torch.cuda.set_per_process_memory_fraction(MEM_FRACTION)
        self._stop = threading.Event()
        log = RUNS / f"{self.name}.gpu.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        self._t = threading.Thread(target=_watchdog, args=(self._stop, log), daemon=True)
        self._t.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        fcntl.flock(self._lock, fcntl.LOCK_UN)
        self._lock.close()


# ------------------------------------------------------------------ ablation data


def _prep_one(args) -> None:
    from PIL import Image

    from tastoria_ml.cv.preprocess import apply_arm

    src, dst, arm = args
    if dst.exists():
        return
    with Image.open(src) as im:
        a = np.asarray(im.convert("RGB"))
    Image.fromarray(apply_arm(a, arm)).save(dst, "JPEG", quality=95)


def prep_arm(arm: str, workers: int = 12) -> Path:
    """Copy of the YOLO dataset with ``arm`` applied to every whole image (train, val and test alike)."""
    import yaml

    if arm == "none":
        return YOLO_DIR / "dataset.yaml"
    root = ABL_DIR / arm
    jobs = []
    for split in ("train", "val", "test"):
        (root / "images" / split).mkdir(parents=True, exist_ok=True)
        lab = root / "labels" / split
        if not lab.exists():
            lab.parent.mkdir(parents=True, exist_ok=True)
            lab.symlink_to(YOLO_DIR / "labels" / split, target_is_directory=True)
        for p in sorted((YOLO_DIR / "images" / split).glob("*.jpg")):
            jobs.append((p, root / "images" / split / p.name, arm))
    with ProcessPoolExecutor(workers) as ex:
        list(ex.map(_prep_one, jobs, chunksize=32))
    ds = yaml.safe_load((YOLO_DIR / "dataset.yaml").read_text())
    ds["path"] = str(root)
    (root / "dataset.yaml").write_text(yaml.safe_dump(ds, allow_unicode=True, sort_keys=False))
    return root / "dataset.yaml"


# ------------------------------------------------------------------ train + evaluate


def _disable_builtin_mlflow() -> None:
    import ultralytics.utils.callbacks.mlflow as ulm

    ulm.callbacks = {}


def _per_class(metrics, names: dict[int, str]) -> dict:
    box = metrics.box
    out = {}
    for j, ci in enumerate(box.ap_class_index):
        out[names[int(ci)]] = {
            "map50": float(box.ap50[j]),
            "map50_95": float(box.ap[j]),
            "precision": float(box.p[j]),
            "recall": float(box.r[j]),
        }
    return out


def _counts(split: str, names: dict[int, str]) -> dict:
    n_img, n_box = 0, {v: 0 for v in names.values()}
    for p in (YOLO_DIR / "labels" / split).glob("*.txt"):
        n_img += 1
        for line in p.read_text().splitlines():
            if line.strip():
                n_box[names[int(line.split()[0])]] += 1
    return {"images": n_img, "boxes": n_box}


def train(name: str, epochs: int, arm: str = "none", model: str = "yolo26n.pt", imgsz: int = 640,
          batch: int = 16, patience: int = 15, seed: int = 0, workers: int = 8) -> dict:
    assert batch > 0, "fixed batch only"
    import ultralytics
    from ultralytics import YOLO

    assert ultralytics.__version__ == ULTRALYTICS_VERSION, ultralytics.__version__
    data = prep_arm(arm) if arm != "none" else YOLO_DIR / "dataset.yaml"
    _disable_builtin_mlflow()
    with GpuGuard(name):
        t0 = time.time()
        m = YOLO(str(REPO / "ml" / "runs" / "weights" / model))
        m.train(data=str(data), epochs=epochs, imgsz=imgsz, batch=batch, patience=patience, seed=seed,
                deterministic=True, workers=workers, project=str(RUNS), name=name, exist_ok=True, device=0,
                plots=True, verbose=False, amp=True)
        train_s = time.time() - t0
        best = RUNS / name / "weights" / "best.pt"
        bm = YOLO(str(best))
        names = bm.names
        res = {}
        for split in ("val", "test"):
            mt = bm.val(data=str(data), split=split, imgsz=imgsz, batch=batch, device=0, plots=False,
                        verbose=False, project=str(RUNS), name=f"{name}_eval_{split}", exist_ok=True)
            res[split] = {
                "map50": float(mt.box.map50),
                "map50_95": float(mt.box.map),
                "precision": float(mt.box.mp),
                "recall": float(mt.box.mr),
                "per_class": _per_class(mt, names),
                "counts": _counts(split, names),
            }
        import torch

        peak = torch.cuda.max_memory_reserved() / 2**30
    import pandas as pd

    hist = pd.read_csv(RUNS / name / "results.csv")
    hist.columns = [c.strip() for c in hist.columns]
    best_epoch = int(hist.loc[hist["metrics/mAP50-95(B)"].idxmax(), "epoch"])
    summary = {
        "name": name,
        "data": "PUBLIC ONLY (Open Images V7 subset + Mendeley Bangladesh vegetables); not fridge photos",
        "model": model,
        "ultralytics": ULTRALYTICS_VERSION,
        "imgsz": imgsz,
        "batch": batch,
        "epochs_requested": epochs,
        "epochs_run": int(len(hist)),
        "best_epoch": best_epoch,
        "patience": patience,
        "seed": seed,
        "preprocess_arm": arm,
        "train_seconds": round(train_s, 1),
        "peak_cuda_reserved_gib": round(peak, 2),
        "memory_fraction": MEM_FRACTION,
        "eval": res,
        "weights": str(best.relative_to(REPO)),
    }
    _log_mlflow(summary, hist, RUNS / name)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    return summary


def _log_mlflow(summary: dict, hist, run_dir: Path) -> None:
    import mlflow

    MLRUNS.mkdir(parents=True, exist_ok=True)
    mlflow.set_tracking_uri(f"sqlite:///{MLRUNS / 'mlflow.db'}")
    exp = "tastoria-detector-public"
    if mlflow.get_experiment_by_name(exp) is None:
        mlflow.create_experiment(exp, artifact_location=(MLRUNS / "artifacts").as_uri())
    mlflow.set_experiment(exp)
    with mlflow.start_run(run_name=summary["name"]):
        mlflow.log_params({k: summary[k] for k in ("model", "ultralytics", "imgsz", "batch", "epochs_requested",
                                                   "patience", "seed", "preprocess_arm", "memory_fraction")})
        mlflow.set_tag("data", summary["data"])
        for _, row in hist.iterrows():
            step = int(row["epoch"])
            for k in ("metrics/mAP50(B)", "metrics/mAP50-95(B)", "train/box_loss", "val/box_loss"):
                if k in row:
                    mlflow.log_metric(k.replace("(B)", "").replace("/", "_"), float(row[k]), step=step)
        for split, r in summary["eval"].items():
            mlflow.log_metric(f"{split}_map50", r["map50"])
            mlflow.log_metric(f"{split}_map50_95", r["map50_95"])
            for c, v in r["per_class"].items():
                mlflow.log_metric(f"{split}_map50_{c}", v["map50"])
                mlflow.log_metric(f"{split}_map50_95_{c}", v["map50_95"])
        mlflow.log_dict(summary, "summary.json")
        for f in ("results.csv", "args.yaml"):
            if (run_dir / f).exists():
                mlflow.log_artifact(str(run_dir / f))


# ------------------------------------------------------------------ ONNX + CPU latency


def latency(name: str, n: int = 100, threads: int = 2, imgsz: int = 640) -> dict:
    import onnxruntime as ort
    from PIL import Image
    from ultralytics import YOLO

    best = RUNS / name / "weights" / "best.pt"
    onnx_path = best.with_suffix(".onnx")
    if not onnx_path.exists():
        YOLO(str(best)).export(format="onnx", imgsz=imgsz, device="cpu")
    so = ort.SessionOptions()
    so.intra_op_num_threads = threads
    so.inter_op_num_threads = 1
    so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    sess = ort.InferenceSession(str(onnx_path), so, providers=["CPUExecutionProvider"])
    inp = sess.get_inputs()[0]
    files = sorted((YOLO_DIR / "images" / "val").glob("*.jpg"))
    rng = np.random.default_rng(0)
    files = [files[i] for i in rng.choice(len(files), size=min(n, len(files)), replace=False)]

    def letterbox(p: Path) -> np.ndarray:
        with Image.open(p) as im:
            im = im.convert("RGB")
            s = imgsz / max(im.size)
            im = im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.BILINEAR)
            canvas = np.full((imgsz, imgsz, 3), 114, np.uint8)
            a = np.asarray(im)
            y0, x0 = (imgsz - a.shape[0]) // 2, (imgsz - a.shape[1]) // 2
            canvas[y0 : y0 + a.shape[0], x0 : x0 + a.shape[1]] = a
        return (canvas.transpose(2, 0, 1)[None].astype(np.float32) / 255.0)

    for p in files[:5]:  # warm-up
        sess.run(None, {inp.name: letterbox(p)})
    model_ms, e2e_ms = [], []
    for p in files:
        t0 = time.perf_counter()
        x = letterbox(p)
        t1 = time.perf_counter()
        sess.run(None, {inp.name: x})
        t2 = time.perf_counter()
        model_ms.append((t2 - t1) * 1000)
        e2e_ms.append((t2 - t0) * 1000)
    q = lambda v, k: float(np.percentile(v, k))  # noqa: E731
    cpu = subprocess.check_output(["bash", "-c", "lscpu | grep 'Model name' | head -1"], text=True).split(":")[-1].strip()
    out = {
        "name": name,
        "onnx": str(onnx_path.relative_to(REPO)),
        "onnx_bytes": onnx_path.stat().st_size,
        "onnxruntime": ort.__version__,
        "intra_op_num_threads": threads,
        "n_images": len(files),
        "imgsz": imgsz,
        "model_ms": {"p50": q(model_ms, 50), "p95": q(model_ms, 95), "mean": float(np.mean(model_ms))},
        "letterbox_plus_model_ms": {"p50": q(e2e_ms, 50), "p95": q(e2e_ms, 95)},
        "cpu": cpu,
        "note": "measured on the shared training server (other jobs running), not on the target VPS; "
        "post-processing (score threshold) not included",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}_latency.json").write_text(json.dumps(out, indent=2))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["train", "prep-arm", "latency", "gpu-check"])
    ap.add_argument("--name", default="smoke")
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--arm", default="none")
    ap.add_argument("--patience", type=int, default=15)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--model", default="yolo26n.pt")
    a = ap.parse_args()
    if a.cmd == "gpu-check":
        print(gpu_free_mb(), gpu_apps())
    elif a.cmd == "prep-arm":
        print(prep_arm(a.arm))
    elif a.cmd == "train":
        print(json.dumps(train(a.name, a.epochs, a.arm, a.model, patience=a.patience, seed=a.seed), indent=2))
    elif a.cmd == "latency":
        print(json.dumps(latency(a.name), indent=2))


if __name__ == "__main__":
    main()
