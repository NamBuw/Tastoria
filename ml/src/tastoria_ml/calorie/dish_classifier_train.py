"""Train lightweight 131-class Vietnamese, Asian & Global dish classifier and export calibrated ONNX.

Exports:
  - ``model.onnx`` (opset 17, baked ImageNet normalization + temperature-scaled logits)
  - ``serving.json`` (SHA-256, input spec, calibrated temperature, confidence threshold, class metadata)
  - ``metrics.json`` (top-1, top-5, VN-33 top-1, macro-F1, ECE, selective accuracy)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np
import timm
import torch
import torch.nn as nn
import torch.nn.functional as F
from PIL import Image
from sklearn.metrics import f1_score
from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler
from torchvision import transforms

from tastoria_ml.calorie.dish_taxonomy import CANONICAL_DISHES

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


class FolderDishDataset(Dataset):
    def __init__(self, root: Path, class_to_idx: dict[str, int], tfm) -> None:
        self.samples: list[tuple[Path, int]] = []
        self.tfm = tfm
        for cid, idx in class_to_idx.items():
            d = root / cid
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
            im = im.convert("RGB")
            return self.tfm(im), y


class WithNormDishClassifierWrapper(nn.Module):
    """Wraps backbone with model-specific uint8-range [0,255] normalization + temperature scaling T."""

    def __init__(
        self,
        backbone: nn.Module,
        temperature: float = 1.0,
        mean: tuple[float, float, float] = IMAGENET_MEAN,
        std: tuple[float, float, float] = IMAGENET_STD,
    ) -> None:
        super().__init__()
        self.backbone = backbone
        self.register_buffer("in_mean", torch.tensor(mean, dtype=torch.float32).view(1, 3, 1, 1) * 255.0)
        self.register_buffer("in_std", torch.tensor(std, dtype=torch.float32).view(1, 3, 1, 1) * 255.0)
        self.register_buffer("inv_temp", torch.tensor(1.0 / max(1e-3, float(temperature)), dtype=torch.float32))

    def forward(self, image: torch.Tensor) -> torch.Tensor:
        x_norm = (image - self.in_mean) / self.in_std
        return self.backbone(x_norm) * self.inv_temp


def _ece(probs: np.ndarray, targets: np.ndarray, n_bins: int = 15) -> float:
    confs = probs.max(axis=1)
    preds = probs.argmax(axis=1)
    correct = (preds == targets).astype(np.float64)
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    for i in range(n_bins):
        mask = (confs > bins[i]) & (confs <= bins[i + 1]) if i > 0 else (confs >= bins[0]) & (confs <= bins[1])
        if mask.any():
            ece += abs(correct[mask].mean() - confs[mask].mean()) * mask.mean()
    return float(ece)


def _fit_temperature(logits: np.ndarray, targets: np.ndarray) -> float:
    """1D L-BFGS / grid search over T in [0.4, 3.0] to minimize NLL on val."""
    t_tensor = torch.from_numpy(targets).long()
    l_tensor = torch.from_numpy(logits).float()
    best_t, best_nll = 1.0, float("inf")
    for t in np.linspace(0.4, 2.5, 85):
        nll = float(F.cross_entropy(l_tensor / float(t), t_tensor).item())
        if nll < best_nll:
            best_nll = nll
            best_t = float(t)
    # Fine grid
    for t in np.linspace(max(0.3, best_t - 0.1), best_t + 0.1, 41):
        nll = float(F.cross_entropy(l_tensor / float(t), t_tensor).item())
        if nll < best_nll:
            best_nll = nll
            best_t = float(t)
    return round(best_t, 4)


def _choose_conf_threshold(probs: np.ndarray, targets: np.ndarray, min_prec: float = 0.95) -> tuple[float, float, float]:
    """Choose lowest threshold (>= 0.35) where selective accuracy >= min_prec (fallback 0.45)."""
    confs = probs.max(axis=1)
    correct = probs.argmax(axis=1) == targets
    best_th = 0.45
    best_cov = float((confs >= best_th).mean()) if (confs >= best_th).any() else 0.0
    best_prec = float(correct[confs >= best_th].mean()) if (confs >= best_th).any() else 0.0
    for th in np.round(np.linspace(0.35, 0.85, 21), 2):
        m = confs >= th
        if m.sum() < 20:
            continue
        prec = float(correct[m].mean())
        cov = float(m.mean())
        if prec >= min_prec:
            best_th, best_prec, best_cov = float(th), prec, cov
            break
        if th == 0.45:
            best_th, best_prec, best_cov = float(th), prec, cov
    return best_th, best_prec, best_cov


def train_and_export(
    data_dir: Path,
    out_dir: Path,
    backbone: str = "efficientnet_b0",
    epochs: int = 16,
    batch_size: int = 128,
    lr: float = 1.2e-3,
    backbone_lr_mult: float = 0.25,
    ema_decay: float = 0.0,
    mixup_prob: float = 0.0,
    export_int8: bool = False,
    img_size: int = 224,
    workers: int = 8,
    mem_fraction: float = 0.20,
    seed: int = 0,
) -> dict:
    torch.manual_seed(seed)
    np.random.seed(seed)
    if torch.cuda.is_available():
        try:
            torch.cuda.set_per_process_memory_fraction(mem_fraction)
        except Exception:
            pass
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    classes = list(CANONICAL_DISHES)
    class_to_idx = {d.dish_id: i for i, d in enumerate(classes)}
    home_focus_ids = {"dau_phu_non", "trung_xao_ca_chua", "thit_kho_tau", "ca_kho_to", "rau_muong_xao", "mi_tom", "rau_cu_xao_thap_cam", "ca_hap_xi_dau", "rau_cai_xao", "omelette"}
    vn_indices = {i for i, d in enumerate(classes) if d.category == "vn" or d.dish_id in home_focus_ids}

    model = timm.create_model(backbone, pretrained=True, num_classes=len(classes), drop_rate=0.2).to(device)
    data_cfg = timm.data.resolve_model_data_config(model)
    in_mean = tuple(float(x) for x in data_cfg.get("mean", IMAGENET_MEAN))
    in_std = tuple(float(x) for x in data_cfg.get("std", IMAGENET_STD))

    train_tfm = transforms.Compose([
        transforms.RandomResizedCrop(img_size, scale=(0.68, 1.0), ratio=(0.85, 1.15)),
        transforms.RandomHorizontalFlip(),
        transforms.RandAugment(num_ops=2, magnitude=7),
        transforms.ColorJitter(brightness=0.22, contrast=0.22, saturation=0.22, hue=0.05),
        transforms.ToTensor(),
        transforms.Normalize(in_mean, in_std),
        transforms.RandomErasing(p=0.15),
    ])
    val_tfm = transforms.Compose([
        transforms.Resize(int(img_size * 256 / 224)),
        transforms.CenterCrop(img_size),
        transforms.ToTensor(),
        transforms.Normalize(in_mean, in_std),
    ])

    train_ds = FolderDishDataset(data_dir / "images" / "train", class_to_idx, train_tfm)
    val_ds = FolderDishDataset(data_dir / "images" / "val", class_to_idx, val_tfm)
    print(f"[train] backbone={backbone} mean={in_mean} std={in_std} ema={ema_decay} mixup={mixup_prob} device={device} train={len(train_ds)} val={len(val_ds)} classes={len(classes)}", flush=True)

    # Balanced sampler with 1.6x priority weight on Vietnamese + core everyday dishes
    cls_counts = np.bincount([y for _, y in train_ds.samples], minlength=len(classes))
    cls_weights = np.zeros(len(classes), dtype=np.float64)
    for c, cnt in enumerate(cls_counts):
        if cnt > 0:
            w = 1.0 / math.sqrt(cnt)
            if c in vn_indices:
                w *= 1.6
            cls_weights[c] = w
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
    param_groups = [{"params": body_params, "lr": lr * backbone_lr_mult}, {"params": head_params, "lr": lr}]
    optimizer = torch.optim.AdamW(param_groups, weight_decay=1e-2)
    scheduler = torch.optim.lr_scheduler.OneCycleLR(
        optimizer, max_lr=[lr * backbone_lr_mult, lr], epochs=epochs, steps_per_epoch=len(train_loader), pct_start=0.12
    )
    criterion = nn.CrossEntropyLoss(label_smoothing=0.1)
    scaler = torch.amp.GradScaler("cuda", enabled=device.type == "cuda")
    ema_state: dict[str, torch.Tensor] | None = (
        {k: v.detach().clone() for k, v in model.state_dict().items()} if ema_decay > 0.0 else None
    )

    best_score = -1.0
    best_state = None
    best_logits = None
    best_targets = None
    t_start = time.time()
    rng = np.random.default_rng(seed)

    def _eval_model(m: nn.Module) -> tuple[np.ndarray, np.ndarray, float, float, float]:
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
        vm = np.isin(vy, list(vn_indices))
        vt1 = float((pr[vm] == vy[vm]).mean()) if vm.any() else 0.0
        mf1 = float(f1_score(vy, pr, average="macro", zero_division=0))
        return vl, vy, t1, vt1, mf1

    for ep in range(1, epochs + 1):
        model.train()
        tr_loss = 0.0
        use_mix = mixup_prob > 0.0 and ep <= max(1, epochs - 3)
        for xb, yb in train_loader:
            xb = xb.to(device, non_blocking=True)
            yb = yb.to(device, non_blocking=True)
            optimizer.zero_grad(set_to_none=True)
            if use_mix and rng.random() < mixup_prob and len(xb) > 1:
                lam = float(rng.beta(0.2, 0.2))
                perm = torch.randperm(len(xb), device=device)
                if rng.random() < 0.5:
                    # CutMix
                    H, W = xb.shape[2], xb.shape[3]
                    rw, rh = int(W * math.sqrt(1.0 - lam)), int(H * math.sqrt(1.0 - lam))
                    cx, cy = int(rng.integers(0, W)), int(rng.integers(0, H))
                    x1, x2 = max(0, cx - rw // 2), min(W, cx + rw // 2)
                    y1, y2 = max(0, cy - rh // 2), min(H, cy + rh // 2)
                    xb_m = xb.clone()
                    xb_m[:, :, y1:y2, x1:x2] = xb[perm, :, y1:y2, x1:x2]
                    lam = 1.0 - ((x2 - x1) * (y2 - y1) / float(W * H))
                else:
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

        v_logits, v_y, top1, vn_top1, macro_f1 = _eval_model(model)
        score = 0.5 * top1 + 0.5 * vn_top1
        ep_tag = "raw"
        cand_state = {k: v.cpu() for k, v in model.state_dict().items()}
        if ema_state is not None and ep >= max(3, epochs // 3):
            raw_backup = {k: v.detach().clone() for k, v in model.state_dict().items()}
            model.load_state_dict(ema_state)
            el, ey, et1, evt1, emf1 = _eval_model(model)
            escore = 0.5 * et1 + 0.5 * evt1
            model.load_state_dict(raw_backup)
            if escore > score:
                v_logits, v_y, top1, vn_top1, macro_f1, score = el, ey, et1, evt1, emf1, escore
                cand_state = {k: v.cpu() for k, v in ema_state.items()}
                ep_tag = "ema"
        print(
            f"Epoch {ep:02d}/{epochs} [{ep_tag}] | loss={tr_loss/len(train_ds):.4f} | val_top1={top1:.4f} | vn33_top1={vn_top1:.4f} | macro_f1={macro_f1:.4f}",
            flush=True,
        )
        if score > best_score:
            best_score = score
            best_logits = v_logits
            best_targets = v_y
            best_state = cand_state

    assert best_state is not None and best_logits is not None and best_targets is not None
    model.load_state_dict(best_state)
    model.cpu().eval()

    # Post-hoc temperature scaling & top-k/calibration stats
    temp = _fit_temperature(best_logits, best_targets)
    scaled_probs = torch.softmax(torch.from_numpy(best_logits) / temp, dim=1).numpy()
    raw_probs = torch.softmax(torch.from_numpy(best_logits), dim=1).numpy()
    preds = scaled_probs.argmax(axis=1)
    top5_hits = np.any(np.argsort(-scaled_probs, axis=1)[:, :5] == best_targets[:, None], axis=1)
    vn_mask = np.isin(best_targets, list(vn_indices))
    conf_th, sel_prec, sel_cov = _choose_conf_threshold(scaled_probs, best_targets, min_prec=0.95)
    # Calibrate ID Energy Score & MaxLogit OOD bounds on temperature-scaled val logits
    scaled_val_logits = best_logits / float(temp)
    val_max_logits = scaled_val_logits.max(axis=1)
    val_energies = -(val_max_logits + np.log(np.exp(scaled_val_logits - val_max_logits[:, None]).sum(axis=1)))
    ood_energy_max = round(float(np.percentile(val_energies, 99.0)) + 0.5, 3)
    ood_max_logit_min = round(max(3.5, float(np.percentile(val_max_logits, 1.0)) - 0.5), 3)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    wrapper = WithNormDishClassifierWrapper(model, temperature=temp, mean=in_mean, std=in_std).eval()
    dummy = torch.zeros((1, 3, img_size, img_size), dtype=torch.float32)
    onnx_path = out_dir / "model.onnx"
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
    if export_int8:
        from onnxruntime.quantization import QuantType, quantize_dynamic

        int8_path = out_dir / "model_int8.onnx"
        quantize_dynamic(str(onnx_path), str(int8_path), weight_type=QuantType.QUInt8)
    sha256 = hashlib.sha256(onnx_path.read_bytes()).hexdigest()

    serving = {
        "schema_version": "dish_classifier.serving.v1",
        "artifact_file": "model.onnx",
        "artifact_sha256": sha256,
        "backbone": backbone,
        "input": {"name": "image", "shape": [1, 3, img_size, img_size], "pad_value": 128, "crop": "center"},
        "temperature": temp,
        "conf_threshold": conf_th,
        "margin_threshold": 0.15,
        "ood_energy_max": ood_energy_max,
        "ood_max_logit_min": ood_max_logit_min,
        "raps_tau": 0.95,
        "raps_k_reg": 3,
        "raps_lambda": 0.01,
        "n_classes": len(classes),
        "classes": [
            {
                "id": d.dish_id,
                "name_vi": d.name_vi,
                "name_en": d.name_en,
                "category": d.category,
                "kb_slug": d.kb_slug,
                "slot": d.slot,
            }
            for d in classes
        ],
    }
    (out_dir / "serving.json").write_text(json.dumps(serving, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    metrics = {
        "backbone": backbone,
        "epochs": epochs,
        "train_seconds": round(time.time() - t_start, 1),
        "n_classes": len(classes),
        "train_images": len(train_ds),
        "val_images": len(val_ds),
        "val_top1": round(float((preds == best_targets).mean()), 4),
        "val_top5": round(float(top5_hits.mean()), 4),
        "val_vn33_top1": round(float((preds[vn_mask] == best_targets[vn_mask]).mean()), 4),
        "val_vn33_top5": round(float(top5_hits[vn_mask].mean()), 4),
        "val_macro_f1": round(float(f1_score(best_targets, preds, average="macro", zero_division=0)), 4),
        "ece_before_temp": round(_ece(raw_probs, best_targets), 4),
        "ece_after_temp": round(_ece(scaled_probs, best_targets), 4),
        "temperature": temp,
        "conf_threshold": conf_th,
        "selective_precision": round(sel_prec, 4),
        "selective_coverage": round(sel_cov, 4),
        "onnx_bytes": onnx_path.stat().st_size,
        "artifact_sha256": sha256,
    }
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return metrics


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--backbone", default="efficientnet_b0")
    ap.add_argument("--epochs", type=int, default=16)
    ap.add_argument("--batch-size", type=int, default=128)
    ap.add_argument("--lr", type=float, default=1.2e-3)
    ap.add_argument("--backbone-lr-mult", type=float, default=0.25)
    ap.add_argument("--ema-decay", type=float, default=0.0)
    ap.add_argument("--mixup-prob", type=float, default=0.0)
    ap.add_argument("--export-int8", action="store_true")
    ap.add_argument("--img-size", type=int, default=224)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--mem-fraction", type=float, default=0.20)
    a = ap.parse_args()
    print(
        json.dumps(
            train_and_export(
                a.data_dir,
                a.out_dir,
                backbone=a.backbone,
                epochs=a.epochs,
                batch_size=a.batch_size,
                lr=a.lr,
                backbone_lr_mult=a.backbone_lr_mult,
                ema_decay=a.ema_decay,
                mixup_prob=a.mixup_prob,
                export_int8=a.export_int8,
                img_size=a.img_size,
                workers=a.workers,
                mem_fraction=a.mem_fraction,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
