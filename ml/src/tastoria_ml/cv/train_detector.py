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
import hashlib
import json
import math
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from tastoria_ml.cv.classes import REPO

YOLO_DIR = REPO / "data" / "processed" / "cv" / "yolo"
YOLO_V2_DIR = REPO / "data" / "processed" / "cv" / "yolo_v2"
YOLO_V3_DIR = REPO / "data" / "processed" / "cv" / "yolo_v3"
YOLO_V4_DIR = REPO / "data" / "processed" / "cv" / "yolo_v4"
# preprocessed copies of the dataset; for the 5-arm ablation they live in RAM-backed /dev/shm
# (TASTORIA_ABL_DIR) because the shared disk has < 6 GB above the 30 GB floor
ABL_DIR = Path(os.environ.get("TASTORIA_ABL_DIR", REPO / "data" / "processed" / "cv" / "ablation"))
OUT = REPO / "data" / "processed" / "cv" / "detector"
OUT_V2 = REPO / "ml" / "runs" / "research" / "p1_detection" / "detector_runs"
OUT_V4 = REPO / "ml" / "runs" / "research" / "m4_detection" / "detector_runs"
OVERSAMPLE_DIR = REPO / "ml" / "runs" / "oversample"
RUNS = REPO / "ml" / "runs" / "detect"
MLRUNS = REPO / "ml" / "mlruns"
LOCK = REPO / "ml" / "runs" / "gpu.lock"
ULTRALYTICS_VERSION = "8.4.173"
ULTRALYTICS_MIN_VERSION = (8, 4, 173)
MIN_FREE_START_MB = 10 * 1024
MIN_FREE_RUN_MB = 3 * 1024
MEM_FRACTION = 0.15
MAX_JOBS = 3  # coordinator allows ≤ 3 concurrent jobs while ≥ 6 GB stays free
SLOT_MIN_FREE_MB = {0: 3 * 1024, 1: 6 * 1024, 2: 6 * 1024 + 512}
MIN_DISK_GB = 30
BATCH_FOR_IMGSZ = {640: 16, 960: 8}


def _parse_version(ver: str) -> tuple[int, ...]:
    parts = []
    for tok in ver.split("."):
        digits = "".join(ch for ch in tok if ch.isdigit())
        if digits:
            parts.append(int(digits))
        else:
            break
    return tuple(parts)


def resolve_yolo_dir(dataset: str | Path = "yolo", yolo_dir: str | Path | None = None) -> Path:
    if yolo_dir is not None:
        return Path(yolo_dir)
    if str(dataset) == "yolo":
        return YOLO_DIR
    if str(dataset) == "yolo_v2":
        return YOLO_V2_DIR
    if str(dataset) == "yolo_v3":
        return YOLO_V3_DIR
    if str(dataset) == "yolo_v4":
        return YOLO_V4_DIR
    p = Path(dataset)
    if p.exists():
        return p
    raise ValueError(f"Unknown dataset '{dataset}' and path does not exist")


def _symlink_dir(dst: Path, target: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.is_symlink():
        if dst.resolve() == target.resolve():
            return
        dst.unlink()
    elif dst.exists():
        shutil.rmtree(dst)
    dst.symlink_to(target.resolve(), target_is_directory=True)


def build_oversampled_dataset(
    ydir: Path,
    stage_dir: Path,
    t: float = 0.02,
    cap: int = 20,
    extra_bg_manifest: Path | None = None,
) -> tuple[Path, dict]:
    """Create a symlink-isolated LVIS repeat-factor oversampled dataset config.

    - Only the ``train`` split is oversampled (via ``train.txt``).
    - ``val``, ``test``, and ``heldout`` remain unrepeated directory symlinks.
    - Directory symlinks under ``stage_dir/{images,labels}/{split}`` ensure Ultralytics writes
      ``.cache`` files inside ``stage_dir/labels/``, leaving ``ydir`` completely untouched.
    """
    import yaml

    if cap < 1:
        raise ValueError(f"oversample cap must be >= 1, got {cap}")
    ydir = Path(ydir)
    stage_dir = Path(stage_dir)
    ds = yaml.safe_load((ydir / "dataset.yaml").read_text(encoding="utf-8"))
    raw_names = ds["names"]
    if isinstance(raw_names, dict):
        names = {int(k): str(v) for k, v in raw_names.items()}
    else:
        names = {i: str(v) for i, v in enumerate(raw_names)}

    stage_dir.mkdir(parents=True, exist_ok=True)
    for split in ("train", "val", "test", "heldout"):
        img_src = ydir / "images" / split
        lbl_src = ydir / "labels" / split
        if img_src.exists():
            _symlink_dir(stage_dir / "images" / split, img_src)
        if lbl_src.exists():
            _symlink_dir(stage_dir / "labels" / split, lbl_src)

    train_imgs = sorted((ydir / "images" / "train").glob("*.jpg"))
    if not train_imgs:
        raise ValueError(f"No .jpg training images found in {ydir / 'images' / 'train'}")
    n_train = len(train_imgs)

    img_classes: list[set[int]] = []
    class_img_counts: dict[int, int] = {cid: 0 for cid in names}
    n_bg = 0
    for img_p in train_imgs:
        lbl_p = ydir / "labels" / "train" / f"{img_p.stem}.txt"
        cset: set[int] = set()
        if lbl_p.exists():
            for line in lbl_p.read_text(encoding="utf-8").splitlines():
                toks = line.strip().split()
                if toks:
                    cset.add(int(toks[0]))
        if not cset:
            n_bg += 1
        for cid in cset:
            class_img_counts[cid] = class_img_counts.get(cid, 0) + 1
        img_classes.append(cset)

    r_c: dict[int, float] = {}
    for cid, cnt in class_img_counts.items():
        if cnt > 0 and t > 0.0:
            f_c = cnt / n_train
            r_c[cid] = max(1.0, math.sqrt(t / f_c))
        else:
            r_c[cid] = 1.0

    train_lines: list[str] = []
    os_class_appearances: dict[int, int] = {cid: 0 for cid in names}
    repeat_hist: dict[int, int] = {}
    for img_p, cset in zip(train_imgs, img_classes):
        if not cset or t <= 0.0:
            r_i = 1
        else:
            max_rc = max(r_c[cid] for cid in cset)
            r_i = max(1, min(cap, round(max_rc)))
        repeat_hist[r_i] = repeat_hist.get(r_i, 0) + 1
        line_path = str(stage_dir / "images" / "train" / img_p.name)
        for _ in range(r_i):
            train_lines.append(line_path)
        for cid in cset:
            os_class_appearances[cid] = os_class_appearances.get(cid, 0) + r_i

    n_extra_bg = 0
    if extra_bg_manifest is not None:
        manifest_p = Path(extra_bg_manifest)
        if not manifest_p.is_file():
            raise FileNotFoundError(f"extra_bg_manifest not found: {manifest_p}")
        for raw_ln in manifest_p.read_text(encoding="utf-8").splitlines():
            p_str = raw_ln.strip()
            if p_str:
                train_lines.append(p_str)
                n_extra_bg += 1

    train_txt = stage_dir / "train.txt"
    train_txt.write_text("\n".join(train_lines) + "\n", encoding="utf-8")
    train_txt_sha256 = hashlib.sha256(train_txt.read_bytes()).hexdigest()

    for split in ("val", "test", "heldout"):
        split_img_dir = ydir / "images" / split
        if split_img_dir.exists():
            split_lines = [str(stage_dir / "images" / split / p.name) for p in sorted(split_img_dir.glob("*.jpg"))]
            (stage_dir / f"{split}.txt").write_text("\n".join(split_lines) + "\n", encoding="utf-8")

    out_ds = {
        "path": str(stage_dir.resolve()),
        "train": "train.txt",
        "val": "val.txt" if (stage_dir / "val.txt").exists() else "images/val",
        "test": "test.txt" if (stage_dir / "test.txt").exists() else "images/test",
        "names": names,
    }
    ds_yaml = stage_dir / "dataset.yaml"
    ds_yaml.write_text(yaml.safe_dump(out_ds, allow_unicode=True, sort_keys=False), encoding="utf-8")

    if (ydir / "images" / "heldout").exists():
        out_dsh = {
            "path": str(stage_dir.resolve()),
            "train": "train.txt",
            "val": "val.txt" if (stage_dir / "val.txt").exists() else "images/val",
            "test": "heldout.txt" if (stage_dir / "heldout.txt").exists() else "images/heldout",
            "names": names,
        }
        (stage_dir / "dataset_heldout.yaml").write_text(
            yaml.safe_dump(out_dsh, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )

    per_class_stats = {}
    for cid in sorted(names):
        cname = names[cid]
        cnt = class_img_counts.get(cid, 0)
        per_class_stats[cname] = {
            "class_id": cid,
            "train_images": cnt,
            "f_c": round(cnt / n_train, 8),
            "r_c": round(r_c.get(cid, 1.0), 4),
            "oversampled_images": os_class_appearances.get(cid, 0),
        }

    stats = {
        "source_dataset": str(ydir),
        "stage_dir": str(stage_dir),
        "t": float(t),
        "cap": int(cap),
        "n_train_unique": n_train,
        "n_train_oversampled": len(train_lines),
        "oversample_factor": round(len(train_lines) / n_train, 6),
        "n_background_images": n_bg,
        "n_extra_bg_images": n_extra_bg,
        "train_txt_sha256": train_txt_sha256,
        "repeat_histogram": {str(k): v for k, v in sorted(repeat_hist.items())},
        "per_class": per_class_stats,
    }
    (stage_dir / "oversample_stats.json").write_text(
        json.dumps(stats, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return ds_yaml, stats


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


def _watchdog(
    stop: threading.Event, log: Path, min_free_mb: int, min_ram_gb: float = 4.0, min_disk_gb: float = MIN_DISK_GB
) -> None:
    """Kill this process when GPU free memory < ``min_free_mb``, disk free < min_disk_gb or host
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
            if free < min_free_mb or disk < min_disk_gb or ram < min_ram_gb:
                f.write(f"limit hit (gpu free < {min_free_mb} MB, disk < {min_disk_gb} GB or "
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

    def __init__(self, name: str, *, mem_fraction: float = MEM_FRACTION, min_disk_gb: float = MIN_DISK_GB):
        self.name = name
        self.mem_fraction = mem_fraction
        self.min_disk_gb = min_disk_gb

    def __enter__(self):
        free, total = gpu_free_mb()
        print(f"[gpu] free {free} MB / {total} MB, disk {disk_free_gb():.1f} GB\n{gpu_apps()}", flush=True)
        if free < MIN_FREE_START_MB:
            _tempfail(f"[gpu] only {free} MB free (< 10 GB): not starting")
        if disk_free_gb() < self.min_disk_gb:
            _tempfail(f"[disk] < {self.min_disk_gb} GB free: not starting")
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

        if 0.0 < self.mem_fraction < 1.0:
            torch.cuda.set_per_process_memory_fraction(self.mem_fraction)
        self._stop = threading.Event()
        log = RUNS / f"{self.name}.gpu.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        min_free = SLOT_MIN_FREE_MB[self.slot]
        print(f"[gpu] slot {self.slot}, watchdog kill threshold {min_free} MB", flush=True)
        min_ram = 4.0 + 1.0 * self.slot  # newest job is killed first
        self._t = threading.Thread(
            target=_watchdog, args=(self._stop, log, min_free, min_ram, self.min_disk_gb), daemon=True
        )
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


def arm_data(arm: str, yolo_dir: Path = YOLO_DIR, heldout: bool = False) -> Path:
    """dataset.yaml for an arm. ``none`` and ``aug`` read the raw images (``aug`` changes training only)."""
    yaml_name = "dataset_heldout.yaml" if heldout else "dataset.yaml"
    if arm in ("none", "aug"):
        return yolo_dir / yaml_name
    return ABL_DIR / arm / yaml_name


def arm_images(arm: str, split: str, yolo_dir: Path = YOLO_DIR) -> Path:
    return arm_data(arm, yolo_dir=yolo_dir).parent / "images" / split


def prep_arm(arm: str, workers: int = 12, yolo_dir: Path = YOLO_DIR, splits: tuple[str, ...] | None = None) -> Path:
    """Copy of the YOLO dataset with ``arm`` applied to every whole image (train, val, test, and heldout if present)."""
    import yaml

    if arm in ("none", "aug"):
        return yolo_dir / "dataset.yaml"
    if splits is None:
        splits = ("train", "val", "test", "heldout") if (yolo_dir / "images" / "heldout").exists() else ("train", "val", "test")
    root = ABL_DIR / arm
    jobs = []
    for split in splits:
        if not (yolo_dir / "images" / split).exists():
            continue
        (root / "images" / split).mkdir(parents=True, exist_ok=True)
        lab = root / "labels" / split
        if not lab.exists():
            lab.parent.mkdir(parents=True, exist_ok=True)
            lab.symlink_to(yolo_dir / "labels" / split, target_is_directory=True)
        for p in sorted((yolo_dir / "images" / split).glob("*.jpg")):
            jobs.append((p, root / "images" / split / p.name, arm))
    with ProcessPoolExecutor(workers) as ex:
        list(ex.map(_prep_one, jobs, chunksize=32))
    ds = yaml.safe_load((yolo_dir / "dataset.yaml").read_text())
    ds["path"] = str(root)
    (root / "dataset.yaml").write_text(yaml.safe_dump(ds, allow_unicode=True, sort_keys=False))
    if (yolo_dir / "dataset_heldout.yaml").exists():
        dsh = yaml.safe_load((yolo_dir / "dataset_heldout.yaml").read_text())
        dsh["path"] = str(root)
        (root / "dataset_heldout.yaml").write_text(yaml.safe_dump(dsh, allow_unicode=True, sort_keys=False))
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


def _counts(split: str, names: dict[int, str], yolo_dir: Path = YOLO_DIR) -> dict:
    n_img, n_box = 0, {v: 0 for v in names.values()}
    for p in (yolo_dir / "labels" / split).glob("*.txt"):
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
          copies: bool = False, dataset: str = "yolo", yolo_dir: Path | None = None,
          out_dir: Path | None = None, eval_splits: tuple[str, ...] | None = None,
          mem_fraction: float = MEM_FRACTION, min_disk_gb: float = MIN_DISK_GB,
          oversample_t: float = 0.0, oversample_cap: int = 20,
          extra_bg_manifest: Path | None = None, optimizer: str | None = None,
          lr0: float | None = None, lrf: float | None = None, weight_decay: float | None = None,
          warmup_epochs: float | None = None, cos_lr: bool = False,
          mosaic: float | None = None, close_mosaic: int | None = None,
          device_arg: int | str = 0) -> dict:
    """``copies=True`` (all runs of the 5-arm ablation and the detector comparison): every arm, including
    ``none`` and ``aug``, reads a prepared q95 JPEG copy under ABL_DIR (``id`` = identity re-encode), so the
    arms differ only in the preprocessing, not in JPEG re-compression. The copy must exist (``prep-arm``):
    concurrent jobs never write it."""
    ydir = resolve_yolo_dir(dataset, yolo_dir)
    if out_dir is not None:
        dest_out = out_dir
    elif ydir == YOLO_V4_DIR:
        dest_out = OUT_V4
    elif ydir in (YOLO_V2_DIR, YOLO_V3_DIR):
        dest_out = OUT_V2
    else:
        dest_out = OUT
    batch = batch or BATCH_FOR_IMGSZ[imgsz]
    assert batch > 0, "fixed batch only"
    import ultralytics
    from ultralytics import YOLO

    from tastoria_ml.cv import predict_dump

    assert _parse_version(ultralytics.__version__) >= ULTRALYTICS_MIN_VERSION, (
        f"ultralytics >= {ULTRALYTICS_MIN_VERSION} required, got {ultralytics.__version__}"
    )
    dir_arm = ("id" if arm in ("none", "aug") else arm) if copies else arm
    oversample_stats: dict | None = None
    if oversample_t > 0.0 or extra_bg_manifest is not None:
        if copies or arm not in ("none", "aug"):
            raise ValueError("oversample_t > 0 / extra_bg_manifest only supports copies=False and arm in ('none', 'aug')")
        data, oversample_stats = build_oversampled_dataset(
            ydir, OVERSAMPLE_DIR / name, t=oversample_t, cap=oversample_cap, extra_bg_manifest=extra_bg_manifest
        )
    elif copies:
        data = ABL_DIR / dir_arm / "dataset.yaml"
        if not (ABL_DIR / dir_arm / "prep.done").exists():
            raise SystemExit(f"{data} not prepared: run prep-arm --arm {dir_arm} first")
    else:
        data = prep_arm(arm, yolo_dir=ydir) if arm not in ("none", "aug") else ydir / "dataset.yaml"
    if eval_splits is None:
        eval_splits = ("val", "test", "heldout") if (ydir / "images" / "heldout").exists() else ("val", "test")
    if arm == "aug":
        _patch_illuminant_aug()
    _disable_builtin_mlflow()
    run_dir = RUNS / name
    did_train = not (run_dir / "train.done").exists()
    continuation_mode: str | None = None
    with GpuGuard(name, mem_fraction=mem_fraction, min_disk_gb=min_disk_gb):
        t0 = time.time()
        last = run_dir / "weights" / "last.pt"
        if last.exists() and did_train:
            import torch

            ck = torch.load(last, map_location="cpu", weights_only=False)
            ck_epoch = int(ck.get("epoch", -1))
            if ck_epoch >= 0:
                ta = ck.setdefault("train_args", {})
                changed = False
                if int(ta.get("epochs", 0)) < epochs:
                    ta["epochs"] = int(epochs)
                    changed = True
                if int(ta.get("patience", 0)) != patience:
                    ta["patience"] = int(patience)
                    changed = True
                if isinstance(ck.get("stopper"), dict) and ck["stopper"].get("possible_stop"):
                    ck["stopper"]["possible_stop"] = False
                    changed = True
                if changed:
                    torch.save(ck, last)
                continuation_mode = "checkpoint_resume"
                print(f"[train] resuming unstripped checkpoint {last} (epoch={ck_epoch}, target_epochs={epochs}, patience={patience})", flush=True)
                YOLO(str(last)).train(resume=True, device=0, workers=workers, patience=patience)
            else:
                res_csv = run_dir / "results.csv"
                s1_csv = run_dir / "results_stage1.csv"
                if res_csv.exists() and not s1_csv.exists():
                    shutil.copy2(res_csv, s1_csv)
                continuation_mode = "warm_start_from_stripped_last_pt"
                print(f"[train] continuing from stripped {last} (target_epochs={epochs}, patience={patience})", flush=True)
                YOLO(str(last)).train(
                    data=str(data), epochs=epochs, imgsz=imgsz, batch=batch, patience=patience, seed=seed,
                    deterministic=True, workers=workers, project=str(RUNS), name=name, exist_ok=True, device=0,
                    plots=True, verbose=False, amp=True, warmup_epochs=1.0,
                )
        elif did_train:
            model_p = Path(model)
            weight_path = model_p if model_p.exists() else (REPO / "ml" / "runs" / "weights" / model)
            m = YOLO(str(weight_path if weight_path.exists() else model))
            train_kw: dict = dict(
                data=str(data), epochs=epochs, imgsz=imgsz, batch=batch, patience=patience, seed=seed,
                deterministic=True, workers=workers, project=str(RUNS), name=name, exist_ok=True,
                device=device_arg, plots=True, verbose=False, amp=True,
            )
            if optimizer is not None:
                train_kw["optimizer"] = optimizer
            if lr0 is not None:
                train_kw["lr0"] = lr0
            if lrf is not None:
                train_kw["lrf"] = lrf
            if weight_decay is not None:
                train_kw["weight_decay"] = weight_decay
            if warmup_epochs is not None:
                train_kw["warmup_epochs"] = warmup_epochs
            if cos_lr:
                train_kw["cos_lr"] = True
            if mosaic is not None:
                train_kw["mosaic"] = mosaic
            if close_mosaic is not None:
                train_kw["close_mosaic"] = close_mosaic
            m.train(**train_kw)
        (run_dir / "train.done").write_text("ok")
        train_s = time.time() - t0
        best = run_dir / "weights" / "best.pt"
        bm = YOLO(str(best))
        names = bm.names
        res = {}
        for split in eval_splits:
            if split == "heldout":
                eval_yaml = data.parent / "dataset_heldout.yaml"
                eval_split_arg = "test"
            else:
                eval_yaml = data
                eval_split_arg = split
            mt = bm.val(data=str(eval_yaml), split=eval_split_arg, imgsz=imgsz, batch=batch, device=0, plots=True,
                        verbose=False, project=str(RUNS), name=f"{name}_eval_{split}", exist_ok=True)
            res[split] = {
                "map50": float(mt.box.map50),
                "map50_95": float(mt.box.map),
                "precision": float(mt.box.mp),
                "recall": float(mt.box.mr),
                "per_class": _per_class(mt, names),
                "counts": _counts(split, names, yolo_dir=ydir),
            }
        modes = ["nms", "e2e"] if "26" in model else ["nms"]
        for split in eval_splits:
            todo = list(modes) if did_train else [m for m in modes if not predict_dump.pred_path(name, split, m).exists()]
            if not todo:
                continue
            img_dir = (ABL_DIR / dir_arm / "images" / split) if copies else arm_images(arm, split, yolo_dir=ydir)
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
    epochs_run = int(len(hist))
    if "time" in hist:  # ultralytics' cumulative wall time per epoch survives a resume
        train_s = float(hist["time"].iloc[-1])
    s1_csv = RUNS / name / "results_stage1.csv"
    stage1_epochs = 0
    if s1_csv.exists():
        hist_s1 = pd.read_csv(s1_csv)
        hist_s1.columns = [c.strip() for c in hist_s1.columns]
        stage1_epochs = int(len(hist_s1))
        epochs_run = stage1_epochs + int(len(hist))
        best_epoch = stage1_epochs + best_epoch
        if "time" in hist_s1 and "time" in hist:
            train_s = float(hist_s1["time"].iloc[-1]) + float(hist["time"].iloc[-1])
    if ydir == YOLO_V4_DIR:
        data_desc = "PUBLIC ONLY (Track C cleaned v4: Open Images V7 + Mendeley BD + LVIS v1 + DFV16 + V3Det + Roboflow curated + Omorros Kitchen heldout); not VN home fridge"
    elif ydir == YOLO_V3_DIR:
        data_desc = "PUBLIC ONLY (v2 + Mendeley expanded + Roboflow curated + V3Det + LVIS hard-neg); not VN home fridge"
    elif ydir == YOLO_V2_DIR:
        data_desc = "PUBLIC ONLY (Open Images V7 + Mendeley BD + LVIS v1 + RPC Checkout + Omorros Kitchen); not fridge photos"
    else:
        data_desc = "PUBLIC ONLY (Open Images V7 subset + Mendeley Bangladesh vegetables); not fridge photos"
    best_sha256 = hashlib.sha256(best.read_bytes()).hexdigest() if best.exists() else None
    summary = {
        "name": name,
        "dataset": ydir.name,
        "data": data_desc,
        "model": model,
        "ultralytics": ultralytics.__version__,
        "imgsz": imgsz,
        "batch": batch,
        "epochs_requested": epochs,
        "epochs_run": epochs_run,
        "stage1_epochs": stage1_epochs,
        "stage2_epochs": int(len(hist)) if stage1_epochs else epochs_run,
        "continuation_mode": continuation_mode,
        "best_epoch": best_epoch,
        "patience": patience,
        "seed": seed,
        "workers": workers,
        "preprocess_arm": arm,
        "copies": str(ABL_DIR / dir_arm) if copies else None,
        "oversample": (
            {
                "t": oversample_stats["t"],
                "cap": oversample_stats["cap"],
                "n_train_unique": oversample_stats["n_train_unique"],
                "n_train_oversampled": oversample_stats["n_train_oversampled"],
                "oversample_factor": oversample_stats["oversample_factor"],
                "train_txt_sha256": oversample_stats["train_txt_sha256"],
                "stage_dir": oversample_stats["stage_dir"],
            }
            if oversample_stats is not None
            else None
        ),
        "train_seconds": round(train_s, 1),
        "peak_cuda_reserved_gib": round(peak, 2),
        "memory_fraction": mem_fraction,
        "eval": res,
        "weights": str(best.relative_to(REPO)),
        "weights_sha256": best_sha256,
    }
    _log_mlflow(summary, hist, RUNS / name)
    dest_out.mkdir(parents=True, exist_ok=True)
    (dest_out / f"{name}.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
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


def export_onnx(
    weights: Path,
    out_onnx: Path,
    imgsz: int = 640,
    opset: int = 17,
    simplify: bool = True,
) -> Path:
    """Export raw [1, 4+C, 8400] opset-17 ONNX without NMS (``end2end='False'``) via a temp copy."""
    from ultralytics import YOLO

    out_onnx = Path(out_onnx)
    out_onnx.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_pt = Path(tmp) / "best.pt"
        shutil.copy2(weights, tmp_pt)
        exported = Path(
            YOLO(str(tmp_pt)).export(
                format="onnx", imgsz=imgsz, device="cpu", opset=opset, simplify=simplify, nms=None
            )
        )
        shutil.move(str(exported), str(out_onnx))
    return out_onnx


def latency(name: str, n: int = 100, threads: int = 2, imgsz: int = 640,
            dataset: str = "yolo", yolo_dir: Path | None = None, out_dir: Path | None = None) -> dict:
    import onnxruntime as ort
    from PIL import Image
    from ultralytics import YOLO

    ydir = resolve_yolo_dir(dataset, yolo_dir)
    if out_dir is not None:
        dest_out = out_dir
    elif ydir == YOLO_V4_DIR:
        dest_out = OUT_V4
    elif ydir in (YOLO_V2_DIR, YOLO_V3_DIR):
        dest_out = OUT_V2
    else:
        dest_out = OUT
    best = RUNS / name / "weights" / "best.pt"
    onnx_path = best.with_suffix(".onnx")
    if not onnx_path.exists():
        YOLO(str(best)).export(format="onnx", imgsz=imgsz, device="cpu", opset=17, simplify=True, nms=None)
    so = ort.SessionOptions()
    so.intra_op_num_threads = threads
    so.inter_op_num_threads = 1
    so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    sess = ort.InferenceSession(str(onnx_path), so, providers=["CPUExecutionProvider"])
    inp = sess.get_inputs()[0]
    files = sorted((ydir / "images" / "val").glob("*.jpg"))
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
        "dataset": ydir.name,
        "onnx": str(onnx_path.relative_to(REPO)),
        "onnx_bytes": onnx_path.stat().st_size,
        "onnxruntime": ort.__version__,
        "intra_op_num_threads": threads,
        "n_images": len(files),
        "imgsz": imgsz,
        "model_ms": {"p50": q(model_ms, 50), "p95": q(model_ms, 95), "p99": q(model_ms, 99),
                     "mean": float(np.mean(model_ms))},
        "letterbox_plus_model_ms": {"p50": q(e2e_ms, 50), "p95": q(e2e_ms, 95), "p99": q(e2e_ms, 99)},
        "cpu": cpu,
        "note": "measured on the shared training server (other jobs running), not on the target VPS; "
        "post-processing (score threshold) not included",
    }
    dest_out.mkdir(parents=True, exist_ok=True)
    (dest_out / f"{name}_latency.json").write_text(json.dumps(out, indent=2))
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
    ap.add_argument("--batch", type=int, default=None)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--dataset", default="yolo", choices=["yolo", "yolo_v2", "yolo_v3", "yolo_v4"])
    ap.add_argument("--yolo-dir", default=None)
    ap.add_argument("--mem-fraction", type=float, default=MEM_FRACTION)
    ap.add_argument("--min-disk-gb", type=float, default=MIN_DISK_GB)
    ap.add_argument("--oversample-t", type=float, default=0.0)
    ap.add_argument("--oversample-cap", type=int, default=20)
    ap.add_argument("--extra-bg-manifest", default=None)
    ap.add_argument("--optimizer", default=None)
    ap.add_argument("--lr0", type=float, default=None)
    ap.add_argument("--lrf", type=float, default=None)
    ap.add_argument("--weight-decay", type=float, default=None)
    ap.add_argument("--warmup-epochs", type=float, default=None)
    ap.add_argument("--cos-lr", action="store_true")
    ap.add_argument("--mosaic", type=float, default=None)
    ap.add_argument("--close-mosaic", type=int, default=None)
    ap.add_argument("--copies", action="store_true")
    a = ap.parse_args()
    ydir = resolve_yolo_dir(a.dataset, a.yolo_dir)
    if a.cmd == "gpu-check":
        print(gpu_free_mb(), gpu_apps())
    elif a.cmd == "prep-arm":
        print(prep_arm(a.arm, yolo_dir=ydir))
    elif a.cmd == "train":
        print(json.dumps(train(
            a.name, a.epochs, a.arm, a.model, imgsz=a.imgsz, batch=a.batch,
            patience=a.patience, seed=a.seed, workers=a.workers,
            copies=a.copies, dataset=a.dataset, yolo_dir=ydir,
            mem_fraction=a.mem_fraction, min_disk_gb=a.min_disk_gb,
            oversample_t=a.oversample_t, oversample_cap=a.oversample_cap,
            extra_bg_manifest=Path(a.extra_bg_manifest) if a.extra_bg_manifest else None,
            optimizer=a.optimizer, lr0=a.lr0, lrf=a.lrf, weight_decay=a.weight_decay,
            warmup_epochs=a.warmup_epochs, cos_lr=a.cos_lr,
            mosaic=a.mosaic, close_mosaic=a.close_mosaic,
        ), indent=2))
    elif a.cmd == "latency":
        print(json.dumps(latency(a.name, imgsz=a.imgsz, dataset=a.dataset, yolo_dir=ydir), indent=2))


if __name__ == "__main__":
    main()
