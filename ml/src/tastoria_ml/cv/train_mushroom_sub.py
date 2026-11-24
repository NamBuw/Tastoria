"""Train 8-class FungiCLEF safety-gated mushroom sub-classifier & export calibrated ONNX (`G-11`).

Classes (8):
  0..5: 6 VN culinary species (nam-rom, nam-huong-tuoi, nam-kim-cham, nam-dui-ga, nam-so, nam-mo)
  6:    other_mushroom (wild / OOD + deadly lookalikes)
  7:    not_mushroom (hard negatives to suppress false-positive `nam` detections)

Exports opset-17 FP32 ``model.onnx`` with baked ``[0, 255]`` RGB ImageNet normalization
outputting unscaled ``logits`` (so runtime computes both calibrated ``softmax(logits / T)``
and Energy OOD score ``E(x) = -T * log(sum(exp(logits / T)))``) along with ``serving.json``
(temperature ``T``, 95% ID ``energy_threshold``, FungiCLEF ``c_psc=100`` safety gates) and
``metrics.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort
import timm
import torch
import torch.nn as nn
import torch.nn.functional as F
from PIL import Image, ImageOps
from sklearn.metrics import classification_report, confusion_matrix, f1_score
from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler
from torchvision import transforms

from tastoria_ml.cv.ingest_mushroom_sub import CLASSES, CULINARY_CLASSES, DEFAULT_STAGE_DIR

REPO = Path(__file__).resolve().parents[4]
DEFAULT_OUT_DIR = REPO / "deploy" / "models" / "mushroom_classifier"
DEFAULT_YOLO_V4_DIR = REPO / "data" / "processed" / "cv" / "yolo_v4"

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)
PAD_VALUE = 128
IMG_SIZE = 224
NAM_YOLO_CLASS_IDX = 21

CULINARY_PROB_MIN = 0.85
OTHER_MUSHROOM_PROB_MAX = 0.03
C_PSC = 100

CLASS_META: dict[str, dict[str, str | int | None]] = {
    "nam-rom": {"name_vi": "nấm rơm", "name_en": "straw mushroom", "shelf_life_days": 2},
    "nam-huong-tuoi": {"name_vi": "nấm hương tươi", "name_en": "fresh shiitake", "shelf_life_days": 7},
    "nam-kim-cham": {"name_vi": "nấm kim châm", "name_en": "enoki mushroom", "shelf_life_days": 7},
    "nam-dui-ga": {"name_vi": "nấm đùi gà", "name_en": "king oyster mushroom", "shelf_life_days": 7},
    "nam-so": {"name_vi": "nấm sò", "name_en": "oyster mushroom", "shelf_life_days": 7},
    "nam-mo": {"name_vi": "nấm mỡ", "name_en": "button mushroom", "shelf_life_days": 7},
    "other_mushroom": {"name_vi": "nấm khác", "name_en": "other/wild mushroom", "shelf_life_days": None},
    "not_mushroom": {"name_vi": "không phải nấm", "name_en": "not mushroom", "shelf_life_days": None},
}


def check_gpu_free_mb(min_free_mb: int = 10 * 1024) -> int:
    """Query ``nvidia-smi`` and fail loudly if free VRAM < ``min_free_mb``."""
    out = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
        text=True,
    )
    free_mb = int(out.strip().splitlines()[0].strip())
    if free_mb < min_free_mb:
        raise RuntimeError(f"Insufficient GPU free memory: {free_mb} MiB < {min_free_mb} MiB required")
    return free_mb


def letterbox_pil(im: Image.Image, size: int = IMG_SIZE, pad_value: int = PAD_VALUE) -> Image.Image:
    """Letterbox RGB PIL image to ``(size, size)`` with pad=``pad_value`` (matches ``scan/freshness.py``)."""
    rgb = ImageOps.exif_transpose(im).convert("RGB")
    rgb.thumbnail((size, size), Image.Resampling.BILINEAR)
    canvas = Image.new("RGB", (size, size), (pad_value, pad_value, pad_value))
    w, h = rgb.size
    canvas.paste(rgb, ((size - w) // 2, (size - h) // 2))
    return canvas


def letterbox_array(im: Image.Image, size: int = IMG_SIZE, pad_value: int = PAD_VALUE) -> np.ndarray:
    """Return ``(3, size, size)`` float32 array in ``[0.0, 255.0]`` matching ``scan/freshness.py``."""
    lb = letterbox_pil(im, size=size, pad_value=pad_value)
    return np.asarray(lb, dtype=np.uint8).transpose(2, 0, 1).astype(np.float32)


class MushroomFolderDataset(Dataset):
    def __init__(self, split_dir: Path, class_to_idx: dict[str, int], tfm) -> None:
        self.samples: list[tuple[Path, int]] = []
        self.tfm = tfm
        for slug, idx in class_to_idx.items():
            d = split_dir / slug
            if not d.is_dir():
                continue
            for p in sorted(d.iterdir()):
                if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                    self.samples.append((p, idx))

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, index: int):
        p, y = self.samples[index]
        with Image.open(p) as im:
            rgb = ImageOps.exif_transpose(im).convert("RGB")
            return self.tfm(rgb), y


class WithNormMushroomWrapper(nn.Module):
    """Bakes ``[0, 255]`` RGB normalization into exported ONNX and outputs raw ``logits``."""

    def __init__(
        self,
        backbone: nn.Module,
        mean: tuple[float, float, float] = IMAGENET_MEAN,
        std: tuple[float, float, float] = IMAGENET_STD,
    ) -> None:
        super().__init__()
        self.backbone = backbone
        self.register_buffer("in_mean", torch.tensor(mean, dtype=torch.float32).view(1, 3, 1, 1) * 255.0)
        self.register_buffer("in_std", torch.tensor(std, dtype=torch.float32).view(1, 3, 1, 1) * 255.0)

    def forward(self, image: torch.Tensor) -> torch.Tensor:
        x_norm = (image - self.in_mean) / self.in_std
        return self.backbone(x_norm)


def compute_probs_and_energy(logits: np.ndarray, temperature: float) -> tuple[np.ndarray, np.ndarray]:
    """Compute calibrated softmax probs and Energy OOD scores ``E(x) = -T * log sum exp(logits / T)``."""
    t = max(1e-3, float(temperature))
    scaled = logits.astype(np.float64) / t
    m = scaled.max(axis=1, keepdims=True)
    exp_s = np.exp(scaled - m)
    sum_exp = exp_s.sum(axis=1, keepdims=True)
    probs = exp_s / np.maximum(sum_exp, 1e-12)
    energy = (-t * (m[:, 0] + np.log(np.maximum(sum_exp[:, 0], 1e-12)))).astype(np.float64)
    return probs, energy


def _ece(probs: np.ndarray, targets: np.ndarray, n_bins: int = 12) -> float:
    confs = probs.max(axis=1)
    preds = probs.argmax(axis=1)
    correct = (preds == targets).astype(np.float64)
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    for i in range(n_bins):
        mask = (confs > bins[i]) & (confs <= bins[i + 1]) if i > 0 else (confs >= bins[0]) & (confs <= bins[1])
        if mask.any():
            ece += abs(float(correct[mask].mean()) - float(confs[mask].mean())) * float(mask.mean())
    return float(ece)


def _fit_temperature(logits: np.ndarray, targets: np.ndarray) -> float:
    t_tensor = torch.from_numpy(targets).long()
    l_tensor = torch.from_numpy(logits).float()
    best_t, best_nll = 1.0, float("inf")
    for t in np.linspace(0.4, 3.0, 105):
        nll = float(F.cross_entropy(l_tensor / float(t), t_tensor).item())
        if nll < best_nll:
            best_nll = nll
            best_t = float(t)
    for t in np.linspace(max(0.3, best_t - 0.1), best_t + 0.1, 41):
        nll = float(F.cross_entropy(l_tensor / float(t), t_tensor).item())
        if nll < best_nll:
            best_nll = nll
            best_t = float(t)
    return round(best_t, 4)


def evaluate_fungiclef_safety(
    logits: np.ndarray,
    targets: np.ndarray,
    *,
    temperature: float,
    energy_threshold: float,
    culinary_prob_min: float = CULINARY_PROB_MIN,
    other_prob_max: float = OTHER_MUSHROOM_PROB_MAX,
) -> dict[str, Any]:
    """Evaluate 3-condition FungiCLEF safety gate + ``not_mushroom`` suppression."""
    probs, energy = compute_probs_and_energy(logits, temperature)
    preds = probs.argmax(axis=1)
    p_top = probs.max(axis=1)
    p_other = probs[:, 6]

    is_not_mush = preds == 7
    is_cul_top = preds < 6
    safe_accept = is_cul_top & (p_top >= culinary_prob_min) & (p_other < other_prob_max) & (energy <= energy_threshold)
    abstained = (~is_not_mush) & (~safe_accept)

    cul_mask = targets < 6
    other_mask = targets == 6
    not_mush_mask = targets == 7

    psc_errors = int((safe_accept & other_mask).sum())
    not_mush_misclassified_as_cul = int((safe_accept & not_mush_mask).sum())
    cul_wrong_species = int((safe_accept & cul_mask & (preds != targets)).sum())

    return {
        "n_total": int(len(targets)),
        "culinary_safe_acceptance_rate": round(float(safe_accept[cul_mask].mean()), 4) if cul_mask.any() else 0.0,
        "culinary_selective_precision": round(float((preds[safe_accept] == targets[safe_accept]).mean()), 4)
        if safe_accept.any()
        else 1.0,
        "other_mushroom_psc_count": psc_errors,
        "other_mushroom_psc_rate": round(float(safe_accept[other_mask].mean()), 4) if other_mask.any() else 0.0,
        "other_mushroom_safe_rejection_rate": round(float((~safe_accept[other_mask]).mean()), 4)
        if other_mask.any()
        else 1.0,
        "not_mushroom_suppression_recall": round(float(is_not_mush[not_mush_mask].mean()), 4)
        if not_mush_mask.any()
        else 0.0,
        "not_mushroom_false_culinary_accept": not_mush_misclassified_as_cul,
        "culinary_false_suppression_rate": round(float(is_not_mush[cul_mask].mean()), 4) if cul_mask.any() else 0.0,
        "culinary_abstained_rate": round(float(abstained[cul_mask].mean()), 4) if cul_mask.any() else 0.0,
        "fungiclef_weighted_cost": int(cul_wrong_species + C_PSC * psc_errors + not_mush_misclassified_as_cul),
    }


def make_cpu_ort_session(onnx_path: Path, intra_op_threads: int = 2) -> ort.InferenceSession:
    so = ort.SessionOptions()
    so.intra_op_num_threads = intra_op_threads
    so.inter_op_num_threads = 1
    so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    so.add_session_config_entry("session.intra_op.allow_spinning", "0")
    so.add_session_config_entry("session.inter_op.allow_spinning", "0")
    return ort.InferenceSession(str(onnx_path), so, providers=["CPUExecutionProvider"])


def benchmark_ort_latency(sess: ort.InferenceSession, img_size: int = IMG_SIZE, n_runs: int = 100) -> dict[str, float]:
    inp_name = sess.get_inputs()[0].name
    rng = np.random.default_rng(0)
    x = rng.uniform(0.0, 255.0, size=(1, 3, img_size, img_size)).astype(np.float32)
    for _ in range(10):
        sess.run(None, {inp_name: x})
    times_ms: list[float] = []
    for _ in range(n_runs):
        t0 = time.perf_counter()
        sess.run(None, {inp_name: x})
        times_ms.append((time.perf_counter() - t0) * 1000.0)
    return {
        "p50_ms": round(float(np.percentile(times_ms, 50)), 3),
        "p95_ms": round(float(np.percentile(times_ms, 95)), 3),
        "mean_ms": round(float(np.mean(times_ms)), 3),
        "n_runs": n_runs,
    }


def _train_single_backbone(
    stage_dir: Path,
    backbone: str,
    *,
    epochs: int = 18,
    batch_size: int = 64,
    lr: float = 1e-3,
    backbone_lr_mult: float = 0.25,
    ema_decay: float = 0.999,
    mixup_prob: float = 0.15,
    img_size: int = IMG_SIZE,
    workers: int = 4,
    mem_fraction: float = 0.15,
    seed: int = 42,
) -> dict[str, Any]:
    torch.manual_seed(seed)
    np.random.seed(seed)
    if torch.cuda.is_available():
        check_gpu_free_mb(min_free_mb=10 * 1024)
        torch.cuda.set_per_process_memory_fraction(min(0.15, float(mem_fraction)))
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    class_to_idx = {slug: i for i, slug in enumerate(CLASSES)}
    model = timm.create_model(backbone, pretrained=True, num_classes=len(CLASSES), drop_rate=0.2).to(device)
    data_cfg = timm.data.resolve_model_data_config(model)
    in_mean = tuple(float(x) for x in data_cfg.get("mean", IMAGENET_MEAN))
    in_std = tuple(float(x) for x in data_cfg.get("std", IMAGENET_STD))

    def _train_geom(im: Image.Image) -> Image.Image:
        if np.random.random() < 0.5:
            im = letterbox_pil(im, size=img_size, pad_value=PAD_VALUE)
        return im

    train_tfm = transforms.Compose([
        transforms.Lambda(_train_geom),
        transforms.RandomResizedCrop(img_size, scale=(0.72, 1.0), ratio=(0.82, 1.22)),
        transforms.RandomHorizontalFlip(p=0.5),
        transforms.RandomVerticalFlip(p=0.15),
        transforms.RandomRotation(degrees=20, fill=(PAD_VALUE, PAD_VALUE, PAD_VALUE)),
        transforms.ColorJitter(brightness=0.22, contrast=0.22, saturation=0.22, hue=0.04),
        transforms.ToTensor(),
        transforms.Normalize(in_mean, in_std),
        transforms.RandomErasing(p=0.15),
    ])
    eval_tfm = transforms.Compose([
        transforms.Lambda(lambda im: letterbox_pil(im, size=img_size, pad_value=PAD_VALUE)),
        transforms.ToTensor(),
        transforms.Normalize(in_mean, in_std),
    ])

    train_ds = MushroomFolderDataset(stage_dir / "images" / "train", class_to_idx, train_tfm)
    val_ds = MushroomFolderDataset(stage_dir / "images" / "val", class_to_idx, eval_tfm)

    cls_counts = np.bincount([y for _, y in train_ds.samples], minlength=len(CLASSES))
    cls_weights = np.array([1.0 / math.sqrt(c) if c > 0 else 0.0 for c in cls_counts], dtype=np.float64)
    # Give extra sampling emphasis to deadly lookalike OOD class (other_mushroom)
    cls_weights[6] *= 1.25
    sample_weights = torch.DoubleTensor([cls_weights[y] for _, y in train_ds.samples])
    sampler = WeightedRandomSampler(sample_weights, num_samples=len(train_ds), replacement=True)

    train_loader = DataLoader(train_ds, batch_size=batch_size, sampler=sampler, num_workers=workers, pin_memory=True)
    val_loader = DataLoader(val_ds, batch_size=batch_size, shuffle=False, num_workers=workers, pin_memory=True)

    head_params, body_params = [], []
    for n, p in model.named_parameters():
        if not p.requires_grad:
            continue
        if any(k in n for k in ("head.", "fc.", "classifier.")):
            head_params.append(p)
        else:
            body_params.append(p)
    optimizer = torch.optim.AdamW(
        [{"params": body_params, "lr": lr * backbone_lr_mult}, {"params": head_params, "lr": lr}],
        weight_decay=1e-2,
    )
    scheduler = torch.optim.lr_scheduler.OneCycleLR(
        optimizer,
        max_lr=[lr * backbone_lr_mult, lr],
        epochs=epochs,
        steps_per_epoch=max(1, len(train_loader)),
        pct_start=0.12,
    )
    # Mild label smoothing (0.04) preserves crisp high-confidence probabilities & Energy separation
    criterion = nn.CrossEntropyLoss(label_smoothing=0.04)
    scaler = torch.amp.GradScaler("cuda", enabled=device.type == "cuda")
    ema_state = {k: v.detach().clone() for k, v in model.state_dict().items()} if ema_decay > 0.0 else None

    best_score = -1.0
    best_state: dict[str, torch.Tensor] | None = None
    best_logits: np.ndarray | None = None
    best_targets: np.ndarray | None = None
    best_metrics: dict[str, float] = {}
    rng = np.random.default_rng(seed)
    t0 = time.time()

    def _eval(m: nn.Module) -> tuple[np.ndarray, np.ndarray, float, float]:
        m.eval()
        ls, ys = [], []
        with torch.no_grad():
            for xb, yb in val_loader:
                xb = xb.to(device, non_blocking=True)
                with torch.amp.autocast("cuda", enabled=device.type == "cuda"):
                    logits = m(xb)
                ls.append(logits.float().cpu().numpy())
                ys.append(yb.numpy())
        vl = np.concatenate(ls, axis=0)
        vy = np.concatenate(ys, axis=0)
        pr = vl.argmax(axis=1)
        t1 = float((pr == vy).mean())
        mf1 = float(f1_score(vy, pr, average="macro", zero_division=0))
        return vl, vy, t1, mf1

    for ep in range(1, epochs + 1):
        model.train()
        tr_loss = 0.0
        use_mix = mixup_prob > 0.0 and ep <= max(1, epochs - 4)
        for xb, yb in train_loader:
            xb = xb.to(device, non_blocking=True)
            yb = yb.to(device, non_blocking=True)
            optimizer.zero_grad(set_to_none=True)
            if use_mix and rng.random() < mixup_prob and len(xb) > 1:
                lam = float(rng.beta(0.2, 0.2))
                perm = torch.randperm(len(xb), device=device)
                xb_m = lam * xb + (1.0 - lam) * xb[perm]
                with torch.amp.autocast("cuda", enabled=device.type == "cuda"):
                    logits = model(xb_m)
                    loss = lam * criterion(logits, yb) + (1.0 - lam) * criterion(logits, yb[perm])
            else:
                with torch.amp.autocast("cuda", enabled=device.type == "cuda"):
                    logits = model(xb)
                    loss = criterion(logits, yb)
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            scaler.step(optimizer)
            scaler.update()
            scheduler.step()
            if ema_state is not None:
                with torch.no_grad():
                    cur = model.state_dict()
                    for k, ev in ema_state.items():
                        if ev.is_floating_point():
                            ev.mul_(ema_decay).add_(cur[k], alpha=1.0 - ema_decay)
                        else:
                            ev.copy_(cur[k])
            tr_loss += float(loss.item()) * len(yb)

        vl, vy, t1, mf1 = _eval(model)
        score = 0.65 * mf1 + 0.35 * t1
        cand_state = {k: v.cpu() for k, v in model.state_dict().items()}
        tag = "raw"
        if ema_state is not None and ep >= max(3, epochs // 3):
            backup = {k: v.detach().clone() for k, v in model.state_dict().items()}
            model.load_state_dict(ema_state)
            el, ey, et1, emf1 = _eval(model)
            escore = 0.65 * emf1 + 0.35 * et1
            model.load_state_dict(backup)
            if escore > score:
                vl, vy, t1, mf1, score = el, ey, et1, emf1, escore
                cand_state = {k: v.cpu() for k, v in ema_state.items()}
                tag = "ema"
        print(
            f"[{backbone}] Ep {ep:02d}/{epochs} [{tag}] loss={tr_loss/len(train_ds):.4f} "
            f"val_top1={t1:.4f} val_macro_f1={mf1:.4f}",
            flush=True,
        )
        if score > best_score:
            best_score = score
            best_state = cand_state
            best_logits = vl
            best_targets = vy
            best_metrics = {"val_top1": round(t1, 4), "val_macro_f1": round(mf1, 4), "best_epoch": ep}

    assert best_state is not None and best_logits is not None and best_targets is not None
    model.load_state_dict(best_state)
    model.cpu().eval()
    max_vram_gb = (torch.cuda.max_memory_allocated() / (1024**3)) if torch.cuda.is_available() else 0.0
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    return {
        "backbone": backbone,
        "model": model,
        "in_mean": in_mean,
        "in_std": in_std,
        "val_logits": best_logits,
        "val_targets": best_targets,
        "val_metrics": best_metrics,
        "train_seconds": round(time.time() - t0, 1),
        "max_vram_gb": round(max_vram_gb, 3),
        "train_images": len(train_ds),
        "val_images": len(val_ds),
    }


def run_yolo_v4_nam_stress_check(
    sess: ort.InferenceSession,
    *,
    temperature: float,
    energy_threshold: float,
    yolo_v4_dir: Path = DEFAULT_YOLO_V4_DIR,
    max_crops: int = 200,
) -> dict[str, Any]:
    """Run ONNX MushroomClassifier with 3-condition FungiCLEF safety gate on ``yolo_v4`` ``nam`` boxes."""
    if not yolo_v4_dir.is_dir():
        return {"available": False, "reason": f"missing {yolo_v4_dir}"}

    inp_name = sess.get_inputs()[0].name
    crops_meta: list[tuple[Path, tuple[float, float, float, float]]] = []
    for split in ("val", "test"):
        lbl_dir = yolo_v4_dir / "labels" / split
        img_dir = yolo_v4_dir / "images" / split
        if not lbl_dir.is_dir():
            continue
        for lp in sorted(lbl_dir.glob("*.txt")):
            nam_boxes = []
            for ln in lp.read_text(encoding="utf-8").splitlines():
                parts = ln.strip().split()
                if len(parts) >= 5 and int(parts[0]) == NAM_YOLO_CLASS_IDX:
                    cx, cy, bw, bh = map(float, parts[1:5])
                    nam_boxes.append((
                        max(0.0, cx - bw / 2),
                        max(0.0, cy - bh / 2),
                        min(1.0, cx + bw / 2),
                        min(1.0, cy + bh / 2),
                    ))
            if not nam_boxes:
                continue
            for ext in (".jpg", ".jpeg", ".png", ".webp"):
                cand = img_dir / (lp.stem + ext)
                if cand.is_file():
                    for box in nam_boxes:
                        crops_meta.append((cand, box))
                    break
            if len(crops_meta) >= max_crops:
                break
        if len(crops_meta) >= max_crops:
            break

    crops_meta = crops_meta[:max_crops]
    pred_counts: Counter[str] = Counter()
    accepted_confs: list[float] = []
    times_ms: list[float] = []
    for img_path, (x1, y1, x2, y2) in crops_meta:
        with Image.open(img_path) as im:
            rgb = ImageOps.exif_transpose(im).convert("RGB")
            w, h = rgb.size
            px1 = max(0, min(w - 1, math.floor(x1 * w)))
            py1 = max(0, min(h - 1, math.floor(y1 * h)))
            px2 = max(px1 + 1, min(w, math.ceil(x2 * w)))
            py2 = max(py1 + 1, min(h, math.ceil(y2 * h)))
            crop = rgb.crop((px1, py1, px2, py2))
        arr = letterbox_array(crop, size=IMG_SIZE, pad_value=PAD_VALUE)[None, ...]
        t0 = time.perf_counter()
        logits = sess.run(None, {inp_name: arr})[0]
        times_ms.append((time.perf_counter() - t0) * 1000.0)
        probs, energy = compute_probs_and_energy(logits, temperature)
        p_row = probs[0]
        e_val = float(energy[0])
        top_idx = int(np.argmax(p_row))
        conf = float(p_row[top_idx])
        slug = CLASSES[top_idx]
        if slug == "not_mushroom":
            pred_counts["suppressed_not_mushroom"] += 1
        elif (
            slug in CULINARY_CLASSES
            and conf >= CULINARY_PROB_MIN
            and float(p_row[6]) < OTHER_MUSHROOM_PROB_MAX
            and e_val <= energy_threshold
        ):
            pred_counts[slug] += 1
            accepted_confs.append(conf)
        else:
            pred_counts["safety_abstained"] += 1

    return {
        "available": True,
        "n_crops": len(crops_meta),
        "accepted_rate": round(len(accepted_confs) / max(1, len(crops_meta)), 4),
        "mean_accepted_conf": round(float(np.mean(accepted_confs)), 4) if accepted_confs else None,
        "pred_distribution": dict(pred_counts),
        "crop_p50_ms": round(float(np.percentile(times_ms, 50)), 3) if times_ms else None,
        "crop_p95_ms": round(float(np.percentile(times_ms, 95)), 3) if times_ms else None,
    }


def train_compare_and_export(
    stage_dir: Path = DEFAULT_STAGE_DIR,
    out_dir: Path = DEFAULT_OUT_DIR,
    *,
    backbones: list[str] | None = None,
    epochs: int = 18,
    batch_size: int = 64,
    mem_fraction: float = 0.15,
    workers: int = 4,
    seed: int = 42,
) -> dict[str, Any]:
    backbones = backbones or ["convnext_atto", "efficientnet_b0", "mobilenetv3_large_100"]
    stage_dir = Path(stage_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_onnx_dir = stage_dir / "_tmp_onnx"
    tmp_onnx_dir.mkdir(parents=True, exist_ok=True)

    candidates: list[dict[str, Any]] = []
    comparison_table: list[dict[str, Any]] = []

    for bb in backbones:
        res = _train_single_backbone(
            stage_dir,
            bb,
            epochs=epochs,
            batch_size=batch_size,
            mem_fraction=mem_fraction,
            workers=workers,
            seed=seed,
        )
        temp_t = _fit_temperature(res["val_logits"], res["val_targets"])
        wrapper = WithNormMushroomWrapper(res["model"], mean=res["in_mean"], std=res["in_std"]).eval()
        tmp_onnx = tmp_onnx_dir / f"{bb}.onnx"
        dummy = torch.zeros((1, 3, IMG_SIZE, IMG_SIZE), dtype=torch.float32)
        torch.onnx.export(
            wrapper,
            dummy,
            str(tmp_onnx),
            input_names=["image"],
            output_names=["logits"],
            opset_version=17,
            dynamic_axes={"image": {0: "batch"}, "logits": {0: "batch"}},
            dynamo=False,
        )
        sess = make_cpu_ort_session(tmp_onnx, intra_op_threads=2)
        lat = benchmark_ort_latency(sess, img_size=IMG_SIZE, n_runs=80)
        entry = {
            "backbone": bb,
            **res["val_metrics"],
            "temperature": temp_t,
            "cpu_p50_ms": lat["p50_ms"],
            "cpu_p95_ms": lat["p95_ms"],
            "onnx_bytes": tmp_onnx.stat().st_size,
            "max_vram_gb": res["max_vram_gb"],
            "train_seconds": res["train_seconds"],
        }
        print(f"[compare] {json.dumps(entry)}", flush=True)
        comparison_table.append(entry)
        res["temp_t"] = temp_t
        res["cpu_lat"] = lat
        candidates.append(res)

    eligible = [c for c in candidates if c["cpu_lat"]["p95_ms"] < 25.0]
    pool = eligible if eligible else candidates
    winner = max(pool, key=lambda c: (c["val_metrics"]["val_macro_f1"], c["val_metrics"]["val_top1"]))
    print(f"[winner] Selected {winner['backbone']} (val_macro_f1={winner['val_metrics']['val_macro_f1']})", flush=True)

    # Fit temperature T and 95% ID energy_threshold strictly on val
    temp_t = _fit_temperature(winner["val_logits"], winner["val_targets"])
    val_raw_probs, _ = compute_probs_and_energy(winner["val_logits"], 1.0)
    val_probs, val_energies = compute_probs_and_energy(winner["val_logits"], temp_t)
    val_id_energies = val_energies[winner["val_targets"] < 6]
    energy_threshold = round(float(np.percentile(val_id_energies, 95)), 4)
    val_safety = evaluate_fungiclef_safety(
        winner["val_logits"], winner["val_targets"], temperature=temp_t, energy_threshold=energy_threshold
    )

    # Export final ONNX outputting raw unscaled logits
    wrapper = WithNormMushroomWrapper(winner["model"], mean=winner["in_mean"], std=winner["in_std"]).eval()
    onnx_path = out_dir / "model.onnx"
    dummy = torch.zeros((1, 3, IMG_SIZE, IMG_SIZE), dtype=torch.float32)
    torch.onnx.export(
        wrapper,
        dummy,
        str(onnx_path),
        input_names=["image"],
        output_names=["logits"],
        opset_version=17,
        dynamic_axes={"image": {0: "batch"}, "logits": {0: "batch"}},
        dynamo=False,
    )
    sha256 = hashlib.sha256(onnx_path.read_bytes()).hexdigest()

    # Held-out test evaluation + PyTorch vs ORT parity (batched for fast CPU execution)
    torch.set_num_threads(min(4, os.cpu_count() or 4))
    class_to_idx = {slug: i for i, slug in enumerate(CLASSES)}
    test_ds = MushroomFolderDataset(stage_dir / "images" / "test", class_to_idx, lambda im: im)
    sess = make_cpu_ort_session(onnx_path, intra_op_threads=2)
    inp_name = sess.get_inputs()[0].name

    all_arrs: list[np.ndarray] = []
    test_targets: list[int] = []
    for p, y in test_ds.samples:
        with Image.open(p) as im:
            all_arrs.append(letterbox_array(im, size=IMG_SIZE, pad_value=PAD_VALUE))
        test_targets.append(y)
    test_x = np.stack(all_arrs, axis=0)

    pt_logits_list, ort_logits_list = [], []
    with torch.no_grad():
        for start in range(0, len(test_x), 64):
            xb = test_x[start : start + 64]
            pt_logits_list.append(wrapper(torch.from_numpy(xb)).numpy())
            ort_logits_list.append(sess.run(None, {inp_name: xb})[0])

    pt_logits = np.concatenate(pt_logits_list, axis=0)
    ort_logits = np.concatenate(ort_logits_list, axis=0)
    test_y = np.asarray(test_targets, dtype=np.int64)

    pt_probs, _ = compute_probs_and_energy(pt_logits, temp_t)
    ort_probs, _ = compute_probs_and_energy(ort_logits, temp_t)
    parity = {
        "n_images": int(len(test_y)),
        "max_abs_logit_diff": float(np.abs(pt_logits - ort_logits).max()),
        "max_abs_prob_diff": float(np.abs(pt_probs - ort_probs).max()),
        "argmax_agreement": float((pt_logits.argmax(1) == ort_logits.argmax(1)).mean()),
    }
    if parity["max_abs_logit_diff"] >= 1e-4:
        raise RuntimeError(f"PyTorch-vs-ORT parity failed: max_abs_logit_diff={parity['max_abs_logit_diff']}")

    test_preds = ort_probs.argmax(axis=1)
    cul_mask = test_y < 6
    test_top1 = float((test_preds == test_y).mean())
    test_macro_f1 = float(f1_score(test_y, test_preds, average="macro", zero_division=0))
    test_cul_top1 = float((test_preds[cul_mask] == test_y[cul_mask]).mean()) if cul_mask.any() else 0.0
    test_cul_macro_f1 = (
        float(f1_score(test_y[cul_mask], test_preds[cul_mask], labels=list(range(6)), average="macro", zero_division=0))
        if cul_mask.any()
        else 0.0
    )
    test_safety = evaluate_fungiclef_safety(
        ort_logits, test_y, temperature=temp_t, energy_threshold=energy_threshold
    )

    cpu_lat = benchmark_ort_latency(sess, img_size=IMG_SIZE, n_runs=120)
    if cpu_lat["p95_ms"] >= 25.0:
        raise RuntimeError(f"CPU p95 latency {cpu_lat['p95_ms']} ms exceeds 25 ms budget")

    yolo_stress = run_yolo_v4_nam_stress_check(sess, temperature=temp_t, energy_threshold=energy_threshold)

    ingest_summary = {}
    sp = stage_dir / "summary.json"
    if sp.is_file():
        ingest_summary = json.loads(sp.read_text(encoding="utf-8"))

    serving = {
        "schema_version": "mushroom_classifier.serving.v1",
        "artifact_file": "model.onnx",
        "artifact_sha256": sha256,
        "backbone": winner["backbone"],
        "input": {
            "name": "image",
            "shape": [1, 3, IMG_SIZE, IMG_SIZE],
            "pad_value": PAD_VALUE,
            "crop": "letterbox",
            "color_space": "RGB",
            "range": [0.0, 255.0],
        },
        "calibration": {"temperature": temp_t},
        "output": {"name": "logits", "calibration_applied_in_onnx": False},
        "safety": {
            "culinary_prob_min": CULINARY_PROB_MIN,
            "other_mushroom_prob_max": OTHER_MUSHROOM_PROB_MAX,
            "energy_threshold": energy_threshold,
            "c_psc": C_PSC,
        },
        "abstention": {
            "tau": CULINARY_PROB_MIN,
            "other_mushroom_max": OTHER_MUSHROOM_PROB_MAX,
            "energy_threshold": energy_threshold,
            "ood_class": "other_mushroom",
            "not_mushroom_class": "not_mushroom",
        },
        "n_classes": len(CLASSES),
        "classes": [
            {
                "id": slug,
                "name_vi": CLASS_META[slug]["name_vi"],
                "name_en": CLASS_META[slug]["name_en"],
                "shelf_life_days": CLASS_META[slug]["shelf_life_days"],
            }
            for slug in CLASSES
        ],
    }
    (out_dir / "serving.json").write_text(json.dumps(serving, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    cls_rep = classification_report(
        test_y,
        test_preds,
        labels=list(range(len(CLASSES))),
        target_names=list(CLASSES),
        output_dict=True,
        zero_division=0,
    )
    metrics = {
        "backbone": winner["backbone"],
        "backbone_comparison": comparison_table,
        "epochs": epochs,
        "train_seconds": winner["train_seconds"],
        "max_vram_gb": winner["max_vram_gb"],
        "n_classes": len(CLASSES),
        "train_images": winner["train_images"],
        "val_images": winner["val_images"],
        "test_images": int(len(test_y)),
        "val_top1": winner["val_metrics"]["val_top1"],
        "val_macro_f1": winner["val_metrics"]["val_macro_f1"],
        "val_ece_before_temp": round(_ece(val_raw_probs, winner["val_targets"]), 4),
        "val_ece_after_temp": round(_ece(val_probs, winner["val_targets"]), 4),
        "val_safety": val_safety,
        "test_top1": round(test_top1, 4),
        "test_macro_f1": round(test_macro_f1, 4),
        "test_culinary_top1": round(test_cul_top1, 4),
        "test_culinary_macro_f1": round(test_cul_macro_f1, 4),
        "test_ece": round(_ece(ort_probs, test_y), 4),
        "test_safety": test_safety,
        "test_confusion_matrix": confusion_matrix(test_y, test_preds, labels=list(range(len(CLASSES)))).tolist(),
        "test_per_class": {k: cls_rep[k] for k in CLASSES if k in cls_rep},
        "temperature": temp_t,
        "energy_threshold": energy_threshold,
        "safety_gates": serving["safety"],
        "onnx_parity": parity,
        "cpu_latency_2threads": cpu_lat,
        "yolo_v4_nam_stress": yolo_stress,
        "dataset_summary": ingest_summary,
        "onnx_bytes": onnx_path.stat().st_size,
        "artifact_sha256": sha256,
    }
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return metrics


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage-dir", type=Path, default=DEFAULT_STAGE_DIR)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument("--backbones", nargs="+", default=["convnext_atto", "efficientnet_b0", "mobilenetv3_large_100"])
    ap.add_argument("--epochs", type=int, default=18)
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--mem-fraction", type=float, default=0.15)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    os.environ.setdefault("TORCH_HOME", str(a.stage_dir / "_torch_cache"))
    res = train_compare_and_export(
        a.stage_dir,
        a.out_dir,
        backbones=a.backbones,
        epochs=a.epochs,
        batch_size=a.batch_size,
        mem_fraction=a.mem_fraction,
        workers=a.workers,
        seed=a.seed,
    )
    print(json.dumps({k: v for k, v in res.items() if k != "dataset_summary"}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
