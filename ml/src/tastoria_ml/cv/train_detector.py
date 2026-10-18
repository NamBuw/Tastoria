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
# preprocessed copies of the dataset; for the 5-arm ablation they live in RAM-backed /dev/shm
# (TASTORIA_ABL_DIR) because the shared disk has < 6 GB above the 30 GB floor
ABL_DIR = Path(os.environ.get("TASTORIA_ABL_DIR", REPO / "data" / "processed" / "cv" / "ablation"))
OUT = REPO / "data" / "processed" / "cv" / "detector"
RUNS = REPO / "ml" / "runs" / "detect"
MLRUNS = REPO / "ml" / "mlruns"
LOCK = REPO / "ml" / "runs" / "gpu.lock"
ULTRALYTICS_VERSION = "8.4.173"
MIN_FREE_START_MB = 10 * 1024
MIN_FREE_RUN_MB = 3 * 1024
MEM_FRACTION = 0.15
MAX_JOBS = 3  # coordinator allows ≤ 3 concurrent jobs while ≥ 6 GB stays free
SLOT_MIN_FREE_MB = {0: 3 * 1024, 1: 6 * 1024, 2: 6 * 1024 + 512}
MIN_DISK_GB = 30
BATCH_FOR_IMGSZ = {640: 16, 960: 8}


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


def disk_free_gb(path: Path = REPO) -> float:
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize / 2**30


def mem_available_gb() -> float:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) / 2**20
    return 1e9


def _watchdog(stop: threading.Event, log: Path, min_free_mb: int, min_ram_gb: float = 4.0) -> None:
    """Kill this process when GPU free memory < ``min_free_mb``, disk free < MIN_DISK_GB or host
    MemAvailable < ``min_ram_gb`` (dataset copies in /dev/shm and the jobs must never push other users into OOM)."""
    n = 0
    with log.open("a") as f:
        while not stop.is_set():
            total = 0
            try:
                free, total = gpu_free_mb()
            except Exception as e:  # noqa: BLE001
                f.write(f"{time.strftime('%H:%M:%S')} nvidia-smi failed: {e}\n")
                free = min_free_mb + 1
            disk = disk_free_gb()
            ram = mem_available_gb()
            f.write(f"{time.strftime('%H:%M:%S')} free {free} MB of {total} MB, disk {disk:.1f} GB, "
                    f"ram avail {ram:.1f} GB\n")
            f.flush()
            if free < min_free_mb or disk < MIN_DISK_GB or ram < min_ram_gb:
                f.write(f"limit hit (gpu free < {min_free_mb} MB, disk < {MIN_DISK_GB} GB or "
                        f"ram < {min_ram_gb} GB): killing job\n")
                f.flush()
                os.kill(os.getpid(), signal.SIGKILL)
            n += 1
            stop.wait(5)


EX_TEMPFAIL = 75  # "try again later": the queue re-queues without counting a failure


def _tempfail(msg: str) -> None:
    print(msg, flush=True)
    raise SystemExit(EX_TEMPFAIL)


def free_slots() -> int:
    """Number of the MAX_JOBS slot locks nobody holds right now."""
    n = 0
    for k in range(MAX_JOBS):
        p = LOCK.parent / f"gpu.lock.{k}"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as fh:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(fh, fcntl.LOCK_UN)
                n += 1
            except BlockingIOError:
                pass
    return n


class GpuGuard:
    """Checks free memory and disk, takes one of MAX_JOBS slot locks, caps memory, starts the watchdog.

    Slot 0 (first job) is killed when GPU free memory < 3 GB. A job holding slot k ≥ 1 runs alongside
    others, so it is killed earlier (free < SLOT_MIN_FREE_MB[k], ≥ 6 GB): concurrent jobs only while the
    GPU keeps ≥ 6 GB free, and the most recent job goes first.
    """

    def __init__(self, name: str):
        self.name = name

    def __enter__(self):
        free, total = gpu_free_mb()
        print(f"[gpu] free {free} MB / {total} MB, disk {disk_free_gb():.1f} GB\n{gpu_apps()}", flush=True)
        if free < MIN_FREE_START_MB:
            _tempfail(f"[gpu] only {free} MB free (< 10 GB): not starting")
        if disk_free_gb() < MIN_DISK_GB:
            _tempfail(f"[disk] < {MIN_DISK_GB} GB free: not starting")
        LOCK.parent.mkdir(parents=True, exist_ok=True)
        self.slot = None
        for k in range(MAX_JOBS):
            fh = (LOCK.parent / f"gpu.lock.{k}").open("w")
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                fh.close()
                continue
            self.slot, self._lock = k, fh
            break
        if self.slot is None:
            _tempfail(f"[gpu] {MAX_JOBS} Tastoria GPU jobs already running")
        import torch

        torch.cuda.set_per_process_memory_fraction(MEM_FRACTION)
        self._stop = threading.Event()
        log = RUNS / f"{self.name}.gpu.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        min_free = SLOT_MIN_FREE_MB[self.slot]
        print(f"[gpu] slot {self.slot}, watchdog kill threshold {min_free} MB", flush=True)
        min_ram = 4.0 + 1.0 * self.slot  # newest job is killed first
        self._t = threading.Thread(target=_watchdog, args=(self._stop, log, min_free, min_ram), daemon=True)
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
    base, clip, grid = parse_arm(arm)
    with Image.open(src) as im:
        a = np.asarray(im.convert("RGB"))
    out = a if base == "id" else apply_arm(a, base, clip, grid)  # "id": identity, JPEG re-encode only
    Image.fromarray(out).save(dst, "JPEG", quality=95)


def parse_arm(arm: str) -> tuple[str, float, tuple[int, int]]:
    """``clahe@3.0x8`` -> ("clahe", 3.0, (8, 8)); plain ``clahe`` / ``gw_clahe`` use clip 2.0, tile 8."""
    base, _, par = arm.partition("@")
    clip, tile = (float(par.split("x")[0]), int(par.split("x")[1])) if par else (2.0, 8)
    return base, clip, (tile, tile)


def arm_data(arm: str) -> Path:
    """dataset.yaml for an arm. ``none`` and ``aug`` read the raw images (``aug`` changes training only)."""
    if arm in ("none", "aug"):
        return YOLO_DIR / "dataset.yaml"
    return ABL_DIR / arm / "dataset.yaml"


def arm_images(arm: str, split: str) -> Path:
    return arm_data(arm).parent / "images" / split


def prep_arm(arm: str, workers: int = 12) -> Path:
    """Copy of the YOLO dataset with ``arm`` applied to every whole image (train, val and test alike)."""
    import yaml

    if arm in ("none", "aug"):
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
    (root / "prep.done").write_text(f"{len(jobs)} images\n")
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


def _patch_illuminant_aug() -> None:
    """``aug`` arm: insert RandomIlluminant before ultralytics' RandomHSV in the *training* pipeline."""
    import ultralytics.data.augment as ua
    import ultralytics.data.dataset as ud

    from tastoria_ml.cv.colorcast import RandomIlluminant

    orig = ua.v8_transforms

    def v8_with_cast(dataset, imgsz, hyp):
        comp = orig(dataset, imgsz, hyp)
        k = next(i for i, t in enumerate(comp.transforms) if type(t).__name__ == "RandomHSV")
        comp.transforms.insert(k, RandomIlluminant(p=0.5))
        return comp

    ud.v8_transforms = v8_with_cast


def train(name: str, epochs: int, arm: str = "none", model: str = "yolo26n.pt", imgsz: int = 640,
          batch: int | None = None, patience: int = 15, seed: int = 0, workers: int = 8,
          copies: bool = False) -> dict:
    """``copies=True`` (all runs of the 5-arm ablation and the detector comparison): every arm, including
    ``none`` and ``aug``, reads a prepared q95 JPEG copy under ABL_DIR (``id`` = identity re-encode), so the
    arms differ only in the preprocessing, not in JPEG re-compression. The copy must exist (``prep-arm``):
    concurrent jobs never write it."""
    batch = batch or BATCH_FOR_IMGSZ[imgsz]
    assert batch > 0, "fixed batch only"
    import ultralytics
    from ultralytics import YOLO

    from tastoria_ml.cv import predict_dump

    assert ultralytics.__version__ == ULTRALYTICS_VERSION, ultralytics.__version__
    dir_arm = ("id" if arm in ("none", "aug") else arm) if copies else arm
    if copies:
        data = ABL_DIR / dir_arm / "dataset.yaml"
        if not (ABL_DIR / dir_arm / "prep.done").exists():
            raise SystemExit(f"{data} not prepared: run prep-arm --arm {dir_arm} first")
    else:
        data = prep_arm(arm) if arm not in ("none", "aug") else YOLO_DIR / "dataset.yaml"
    if arm == "aug":
        _patch_illuminant_aug()
    _disable_builtin_mlflow()
    run_dir = RUNS / name
    with GpuGuard(name):
        t0 = time.time()
        last = run_dir / "weights" / "last.pt"
        if last.exists() and not (run_dir / "train.done").exists():
            print(f"[train] resuming {last}", flush=True)
            YOLO(str(last)).train(resume=True, device=0, workers=workers)
        elif not (run_dir / "train.done").exists():
            m = YOLO(str(REPO / "ml" / "runs" / "weights" / model))
            m.train(data=str(data), epochs=epochs, imgsz=imgsz, batch=batch, patience=patience, seed=seed,
                    deterministic=True, workers=workers, project=str(RUNS), name=name, exist_ok=True, device=0,
                    plots=True, verbose=False, amp=True)
        (run_dir / "train.done").write_text("ok")
        train_s = time.time() - t0
        best = run_dir / "weights" / "best.pt"
        bm = YOLO(str(best))
        names = bm.names
        res = {}
        for split in ("val", "test"):
            mt = bm.val(data=str(data), split=split, imgsz=imgsz, batch=batch, device=0, plots=True,
                        verbose=False, project=str(RUNS), name=f"{name}_eval_{split}", exist_ok=True)
            res[split] = {
                "map50": float(mt.box.map50),
                "map50_95": float(mt.box.map),
                "precision": float(mt.box.mp),
                "recall": float(mt.box.mr),
                "per_class": _per_class(mt, names),
                "counts": _counts(split, names),
            }
        modes = ["nms", "e2e"] if "26" in model else ["nms"]
        for split in ("val", "test"):
            todo = [m for m in modes if not predict_dump.pred_path(name, split, m).exists()]
            if not todo:
                continue
            img_dir = (ABL_DIR / dir_arm / "images" / split) if copies else arm_images(arm, split)
            loaded = predict_dump.load_split(img_dir, "none")
            for mode in todo:
                predict_dump.dump(best, img_dir, predict_dump.pred_path(name, split, mode), imgsz, mode,
                                  batch=batch, loaded=loaded)
            del loaded
        import torch

        peak = torch.cuda.max_memory_reserved() / 2**30
    import pandas as pd

    hist = pd.read_csv(RUNS / name / "results.csv")
    hist.columns = [c.strip() for c in hist.columns]
    best_epoch = int(hist.loc[hist["metrics/mAP50-95(B)"].idxmax(), "epoch"])
    if "time" in hist:  # ultralytics' cumulative wall time per epoch survives a resume
        train_s = float(hist["time"].iloc[-1])
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
        "copies": str(ABL_DIR / dir_arm) if copies else None,
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
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--copies", action="store_true")
    a = ap.parse_args()
    if a.cmd == "gpu-check":
        print(gpu_free_mb(), gpu_apps())
    elif a.cmd == "prep-arm":
        print(prep_arm(a.arm))
    elif a.cmd == "train":
        print(json.dumps(train(a.name, a.epochs, a.arm, a.model, imgsz=a.imgsz, patience=a.patience, seed=a.seed,
                                    copies=a.copies), indent=2))
    elif a.cmd == "latency":
        print(json.dumps(latency(a.name), indent=2))


if __name__ == "__main__":
    main()
