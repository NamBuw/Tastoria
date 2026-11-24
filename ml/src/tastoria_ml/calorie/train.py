"""GPU training & Parsimony Gate comparison for Meal Calorie visual regression (F10).

Runs in ``hac_env`` on GPU (<= 2 GB VRAM, batch=32, AMP fp16, NO 10 GB GpuGuard).
Stages checkpoints in ``/dev/shm/tastoria_stage_m3/runs`` so ``/dev/sda2`` stays clean.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader

from tastoria_ml.calorie import INPUT_SIZE, PAD_VALUE, PORTION_MULTIPLIERS, TARGET_COLS
from tastoria_ml.calorie.baselines import ConstantBaseline
from tastoria_ml.calorie.dataset import load_overhead_dataset, make_torch_dataset
from tastoria_ml.calorie.eval import compute_all_target_metrics, paired_bootstrap_mae
from tastoria_ml.calorie.model import MealCalorieNet, SUPPORTED_BACKBONES, WithNormCalorieWrapper

log = logging.getLogger("tastoria_ml.calorie.train")

PARSIMONY_MIN_VAL_GAIN_KCAL = 3.0


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def train_one_backbone(
    backbone_name: str,
    ds,
    *,
    out_dir: Path,
    epochs: int = 25,
    batch_size: int = 32,
    lr: float = 3e-4,
    weight_decay: float = 1e-4,
    patience: int = 7,
    seed: int = 20261017,
) -> dict:
    set_seed(seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    use_amp = device.type == "cuda"

    train_df = ds.split_df("train")
    val_df = ds.split_df("val")

    y_train = ds.targets_array(train_df)
    target_mean = y_train.mean(axis=0).astype(np.float32)
    target_std = np.maximum(y_train.std(axis=0), 1e-3).astype(np.float32)

    train_ds = make_torch_dataset(train_df, ds.images_by_id, augment=True, size=INPUT_SIZE, seed=seed)
    val_ds = make_torch_dataset(val_df, ds.images_by_id, augment=False, size=INPUT_SIZE, seed=seed)

    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True, num_workers=2, pin_memory=use_amp)
    val_loader = DataLoader(val_ds, batch_size=batch_size, shuffle=False, num_workers=2, pin_memory=use_amp)

    net = MealCalorieNet(backbone_name=backbone_name, pretrained=True, dropout=0.2).to(device)
    n_params = sum(p.numel() for p in net.parameters())

    in_mean = torch.tensor([0.485, 0.456, 0.406], device=device).view(1, 3, 1, 1) * 255.0
    in_std = torch.tensor([0.229, 0.224, 0.225], device=device).view(1, 3, 1, 1) * 255.0
    y_mean_t = torch.tensor(target_mean, device=device).view(1, -1)
    y_std_t = torch.tensor(target_std, device=device).view(1, -1)

    optimizer = torch.optim.AdamW(net.parameters(), lr=lr, weight_decay=weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs, eta_min=lr * 0.05)
    criterion = nn.SmoothL1Loss(beta=0.5)
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)

    if use_amp:
        torch.cuda.reset_peak_memory_stats(device)

    best_val_kcal_mae = float("inf")
    best_epoch = -1
    best_state = None
    no_improve = 0
    history = []
    t_start = time.perf_counter()

    for epoch in range(1, epochs + 1):
        net.train()
        train_loss_sum = 0.0
        n_train = 0
        for xb, yb in train_loader:
            xb = xb.to(device, non_blocking=True)
            yb = yb.to(device, non_blocking=True)
            x_norm = (xb - in_mean) / in_std
            y_norm = (yb - y_mean_t) / y_std_t

            optimizer.zero_grad(set_to_none=True)
            with torch.amp.autocast("cuda", enabled=use_amp):
                pred_norm = net(x_norm)
                loss = criterion(pred_norm, y_norm)
            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()
            train_loss_sum += float(loss.detach()) * len(xb)
            n_train += len(xb)
        scheduler.step()

        # Validation
        net.eval()
        val_preds = []
        val_trues = []
        with torch.no_grad():
            for xb, yb in val_loader:
                xb = xb.to(device, non_blocking=True)
                x_norm = (xb - in_mean) / in_std
                with torch.amp.autocast("cuda", enabled=use_amp):
                    pred_norm = net(x_norm)
                pred_raw = torch.clamp(pred_norm.float() * y_std_t + y_mean_t, min=0.0)
                val_preds.append(pred_raw.cpu().numpy())
                val_trues.append(yb.numpy())

        yp_val = np.concatenate(val_preds, axis=0)
        yt_val = np.concatenate(val_trues, axis=0)
        val_metrics = compute_all_target_metrics(yt_val, yp_val)
        val_kcal_mae = float(val_metrics["kcal"]["mae"])
        history.append({"epoch": epoch, "train_loss": round(train_loss_sum / max(n_train, 1), 5), "val_kcal_mae": val_kcal_mae})

        if val_kcal_mae < best_val_kcal_mae:
            best_val_kcal_mae = val_kcal_mae
            best_epoch = epoch
            best_state = {k: v.detach().cpu() for k, v in net.state_dict().items()}
            no_improve = 0
        else:
            no_improve += 1
            if no_improve >= patience:
                break

    elapsed_s = time.perf_counter() - t_start
    peak_vram_mb = float(torch.cuda.max_memory_allocated(device) / (1024 ** 2)) if use_amp else 0.0
    if use_amp and peak_vram_mb > 2048.0:
        raise RuntimeError(f"Peak VRAM {peak_vram_mb:.1f} MB exceeded 2048 MB safety cap")

    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt_path = out_dir / f"{backbone_name}_best.pt"
    torch.save(
        {
            "backbone_name": backbone_name,
            "state_dict": best_state,
            "target_mean": target_mean,
            "target_std": target_std,
            "best_epoch": best_epoch,
            "best_val_kcal_mae": best_val_kcal_mae,
            "n_params": n_params,
            "seed": seed,
        },
        ckpt_path,
    )

    # Recompute val metrics with best checkpoint
    net.load_state_dict(best_state)
    net.eval()
    wrapped = WithNormCalorieWrapper(net.cpu(), target_mean, target_std).eval()
    val_preds = []
    val_trues = []
    with torch.no_grad():
        for xb, yb in val_loader:
            val_preds.append(wrapped(xb).numpy())
            val_trues.append(yb.numpy())
    yp_val = np.concatenate(val_preds, axis=0)
    yt_val = np.concatenate(val_trues, axis=0)
    val_metrics_best = compute_all_target_metrics(yt_val, yp_val)

    return {
        "backbone": backbone_name,
        "ckpt_path": str(ckpt_path),
        "n_params": n_params,
        "best_epoch": best_epoch,
        "epochs_run": len(history),
        "elapsed_s": round(elapsed_s, 2),
        "peak_vram_mb": round(peak_vram_mb, 1),
        "val_metrics": val_metrics_best,
        "history": history,
    }


def evaluate_checkpoint_on_splits(ckpt_path: Path, ds, batch_size: int = 32) -> dict:
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=False)
    net = MealCalorieNet(backbone_name=ckpt["backbone_name"], pretrained=False, dropout=0.2)
    net.load_state_dict(ckpt["state_dict"])
    wrapped = WithNormCalorieWrapper(net, ckpt["target_mean"], ckpt["target_std"]).to(device).eval()

    train_df = ds.split_df("train")
    y_train = ds.targets_array(train_df)
    const_base = ConstantBaseline.fit(y_train)

    def _predict_df(df):
        loader = DataLoader(
            make_torch_dataset(df, ds.images_by_id, augment=False, size=INPUT_SIZE),
            batch_size=batch_size,
            shuffle=False,
            num_workers=0,
        )
        preds = []
        with torch.no_grad():
            for xb, _ in loader:
                preds.append(wrapped(xb.to(device)).cpu().numpy())
        return np.concatenate(preds, axis=0), ds.targets_array(df)

    results = {"constant_baseline": const_base.to_dict(), "splits": {}}
    for label, split_name, clean_only, excl_empty in [
        ("val", "val", False, False),
        ("test", "test", False, False),
        ("test_clean", "test", True, False),
        ("test_nonempty", "test", False, True),
        ("test_clean_nonempty", "test", True, True),
    ]:
        df = ds.split_df(split_name, clean_only=clean_only, exclude_empty=excl_empty)
        yp, yt = _predict_df(df)
        med_pred = const_base.predict_median(len(df))
        mean_pred = const_base.predict_mean(len(df))
        results["splits"][label] = {
            "n": len(df),
            "model": compute_all_target_metrics(yt, yp),
            "baseline_median": compute_all_target_metrics(yt, med_pred),
            "baseline_mean": compute_all_target_metrics(yt, mean_pred),
            "paired_bootstrap_kcal_vs_median": paired_bootstrap_mae(yt[:, 0], yp[:, 0], med_pred[:, 0]),
        }
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Train Meal Calorie MobileNetV3 models on Nutrition5k overhead")
    ap.add_argument("--stage-dir", type=Path, default=Path("/dev/shm/tastoria_stage_m3/calorie_lens"))
    ap.add_argument("--runs-dir", type=Path, default=Path("/dev/shm/tastoria_stage_m3/runs"))
    ap.add_argument("--epochs", type=int, default=25)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--seed", type=int, default=20261017)
    ap.add_argument("--eval-only", action="store_true", help="Evaluate existing checkpoints in --runs-dir without retraining")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ds = load_overhead_dataset(args.stage_dir)

    ablation = {}
    if args.eval_only:
        val_df = ds.split_df("val")
        for backbone in SUPPORTED_BACKBONES:
            ckpt_path = args.runs_dir / f"{backbone}_best.pt"
            ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=False)
            ev = evaluate_checkpoint_on_splits(ckpt_path, ds, batch_size=args.batch_size)
            ablation[backbone] = {
                "backbone": backbone,
                "ckpt_path": str(ckpt_path),
                "n_params": int(ckpt["n_params"]),
                "best_epoch": int(ckpt["best_epoch"]),
                "val_metrics": ev["splits"]["val"]["model"],
            }
    else:
        for backbone in SUPPORTED_BACKBONES:
            log.info("Training backbone=%s ...", backbone)
            res = train_one_backbone(
                backbone,
                ds,
                out_dir=args.runs_dir,
                epochs=args.epochs,
                batch_size=args.batch_size,
                seed=args.seed,
            )
            ablation[backbone] = res
            log.info(
                "Done %s: best_epoch=%d val_kcal_mae=%.2f peak_vram=%.1f MB elapsed=%.1fs",
                backbone,
                res["best_epoch"],
                res["val_metrics"]["kcal"]["mae"],
                res["peak_vram_mb"],
                res["elapsed_s"],
            )

    small_mae = float(ablation["mobilenetv3_small_100"]["val_metrics"]["kcal"]["mae"])
    large_mae = float(ablation["mobilenetv3_large_100"]["val_metrics"]["kcal"]["mae"])
    if (small_mae - large_mae) >= PARSIMONY_MIN_VAL_GAIN_KCAL:
        winner = "mobilenetv3_large_100"
        reason = (
            f"mobilenetv3_large_100 improved val kcal MAE by {small_mae - large_mae:.2f} kcal "
            f"(>= {PARSIMONY_MIN_VAL_GAIN_KCAL:.1f} kcal parsimony threshold)"
        )
    else:
        winner = "mobilenetv3_small_100"
        reason = (
            f"Parsimony Gate selected mobilenetv3_small_100: large gain {small_mae - large_mae:.2f} kcal "
            f"< {PARSIMONY_MIN_VAL_GAIN_KCAL:.1f} kcal threshold"
        )

    winner_ckpt = Path(ablation[winner]["ckpt_path"])
    eval_report = evaluate_checkpoint_on_splits(winner_ckpt, ds, batch_size=args.batch_size)
    summary = {
        "dataset_integrity": asdict(ds.integrity),
        "ablation": ablation,
        "selected_backbone": winner,
        "selection_reason": reason,
        "selected_ckpt": str(winner_ckpt),
        "evaluation": eval_report,
    }
    args.runs_dir.mkdir(parents=True, exist_ok=True)
    summary_path = args.runs_dir / "train_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({"selected_backbone": winner, "selection_reason": reason, "val_small_mae": small_mae, "val_large_mae": large_mae}, indent=2))
    print("Test kcal metrics:", json.dumps(eval_report["splits"]["test"]["model"]["kcal"], indent=2))
    print("Test_clean kcal metrics:", json.dumps(eval_report["splits"]["test_clean"]["model"]["kcal"], indent=2))
    print("Paired bootstrap vs median (test):", json.dumps(eval_report["splits"]["test"]["paired_bootstrap_kcal_vs_median"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
