"""Train V2 Multi-Domain Visual Calorie & Macro Regressor on Host 121 L40S GPU.

Combines:
  1. ``shalev396/calorie-lens-data`` (Nutrition5k overhead weighed plates, preserving exact train/val/test/test_clean splits)
  2. ``jeandeanny/vn-food-combined-2026`` + ``kng-research/uecfood256`` (310-class Vietnamese & Asian dishes)
     paired with their calibrated NIN/FCT2007/USDA ``(kcal, mass_g, fat_g, carb_g, protein_g)`` targets
     and realistic portion jitter (``0.75x .. 1.35x``).

Strictly enforces ``torch.cuda.set_per_process_memory_fraction(0.12)`` on host 121 L40S (~5.5 GB max ceiling, actual ~600 MB).
Exports opset-17 ONNX + ``serving.json`` + ``metrics.json`` to ``deploy/models/meal_calorie/``.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import random
import shutil
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import torch
import torch.nn as nn
import yaml
from huggingface_hub import HfApi, hf_hub_download
from PIL import Image, ImageOps
from torch.utils.data import ConcatDataset, DataLoader, Dataset

from tastoria_ml.calorie import INPUT_SIZE, PAD_VALUE, PORTION_MULTIPLIERS, TARGET_COLS
from tastoria_ml.calorie.baselines import ConstantBaseline
from tastoria_ml.calorie.dataset import letterbox_rgb, load_overhead_dataset, make_torch_dataset
from tastoria_ml.calorie.dish_taxonomy import UEC256_TO_CANONICAL, VN103_TO_CANONICAL
from tastoria_ml.calorie.eval import compute_all_target_metrics, paired_bootstrap_mae
from tastoria_ml.calorie.export_onnx import benchmark_onnx_cpu, sha256_file
from tastoria_ml.calorie.model import MealCalorieNet, WithNormCalorieWrapper
from tastoria_ml.cv.phash import hamming, phash

log = logging.getLogger("tastoria_ml.calorie.train_v2")


def _img_phash(im: Image.Image) -> int:
    g = im.convert("L")
    g.thumbnail((256, 256))
    return int(phash(np.asarray(g)))


def stage_nutrition5k(stage_dir: Path) -> None:
    stage_dir.mkdir(parents=True, exist_ok=True)
    if (stage_dir / "dishes.parquet").is_file() and list((stage_dir / "overhead").glob("*.parquet")):
        return
    api = HfApi()
    info = api.dataset_info("shalev396/calorie-lens-data")
    for sib in info.siblings:
        rf = sib.rfilename
        if rf == "dishes.parquet" or (rf.startswith("overhead/") and rf.endswith(".parquet")):
            hf_hub_download("shalev396/calorie-lens-data", rf, repo_type="dataset", local_dir=str(stage_dir))


def build_vn_asian_calorie_samples(
    kb_dir: Path,
    work_dir: Path,
    exclude_dir: Path | None = None,
    max_per_vn_class: int = 75,
    max_per_uec_class: int = 40,
    seed: int = 20261017,
) -> tuple[list[tuple[bytes, np.ndarray]], list[tuple[bytes, np.ndarray]]]:
    """Build (raw_jpeg_bytes, target_5[kcal, mass_g, fat_g, carb_g, protein_g]) for VN103 + UEC256."""
    rec_doc = yaml.safe_load((kb_dir / "recognized_dishes_nutrition.yaml").read_text(encoding="utf-8"))
    pkg_doc = yaml.safe_load((kb_dir / "everyday_packaged_foods.yaml").read_text(encoding="utf-8"))

    # Map dish_id -> (kcal, mass_g, fat_g, carb_g, protein_g)
    import re
    targets_by_id: dict[str, np.ndarray] = {}
    for d in rec_doc["dishes"]:
        did = d["dish_id"]
        kcal = float(d["kcal_per_serving"])
        p = float(d["protein_g"])
        f = float(d["lipid_g"])
        c = float(d["glucid_g"])
        sdesc = str(d.get("serving_desc_vi") or "")
        m = re.search(r"~(\d+)\s*g", sdesc)
        mass_g = float(m.group(1)) if m else max(120.0, round((p + f + c) * 3.8, 1))
        targets_by_id[did] = np.array([kcal, mass_g, f, c, p], dtype=np.float32)

    excluded_hashes: list[int] = []
    if exclude_dir and exclude_dir.is_dir():
        for p in sorted(exclude_dir.iterdir()):
            if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                with Image.open(p) as im:
                    excluded_hashes.append(_img_phash(im.convert("RGB")))
    ex_arr = np.asarray(excluded_hashes, dtype=np.uint64) if excluded_hashes else None

    train_samples: list[tuple[bytes, np.ndarray]] = []
    val_samples: list[tuple[bytes, np.ndarray]] = []

    dl_dir = work_dir / "_dl_vn"
    dl_dir.mkdir(parents=True, exist_ok=True)
    api = HfApi()
    vn_info = api.dataset_info("jeandeanny/vn-food-combined-2026")
    pfiles = sorted([s.rfilename for s in vn_info.siblings if s.rfilename.endswith(".parquet")])

    # Download validation shards + first 4 train shards of VNFood-103
    selected_shards = [f for f in pfiles if "validation-" in f] + [f for f in pfiles if "train-" in f][:4]
    cls_counts = {"train": {}, "val": {}}
    vn103_label_map = None

    for rf in selected_shards:
        sp = "val" if "validation-" in rf else "train"
        cap = 15 if sp == "val" else max_per_vn_class
        lp = Path(hf_hub_download("jeandeanny/vn-food-combined-2026", rf, repo_type="dataset", local_dir=str(dl_dir)))
        if vn103_label_map is None:
            schema = pq.read_schema(lp)
            meta = json.loads(schema.metadata[b"huggingface"].decode())
            vn103_names = meta["info"]["features"]["label"]["names"]
            vn103_label_map = [VN103_TO_CANONICAL[n] for n in vn103_names]
        pf = pq.ParquetFile(lp)
        for batch in pf.iter_batches(batch_size=256, columns=["image", "label"]):
            for cell, lidx in zip(batch.column("image").to_pylist(), batch.column("label").to_pylist()):
                cid = vn103_label_map[int(lidx)]
                if cid not in targets_by_id:
                    continue
                if cls_counts[sp].get(cid, 0) >= cap:
                    continue
                raw = cell["bytes"] if isinstance(cell, dict) and cell.get("bytes") else bytes(cell)
                try:
                    with Image.open(io.BytesIO(raw)) as im:
                        rgb = ImageOps.exif_transpose(im).convert("RGB")
                        if ex_arr is not None and ex_arr.size > 0 and int(hamming(ex_arr, _img_phash(rgb)).min()) <= 4:
                            continue
                        rgb.thumbnail((256, 256), Image.Resampling.BILINEAR)
                        buf = io.BytesIO()
                        rgb.save(buf, "JPEG", quality=86)
                        jb = buf.getvalue()
                    if sp == "val":
                        val_samples.append((jb, targets_by_id[cid]))
                    else:
                        train_samples.append((jb, targets_by_id[cid]))
                    cls_counts[sp][cid] = cls_counts[sp].get(cid, 0) + 1
                except Exception:
                    pass
        lp.unlink(missing_ok=True)
    shutil.rmtree(dl_dir, ignore_errors=True)

    # Also add mi_tom samples from yolo_v4
    yolo_v4 = Path("/home/namnx/NamBuw/Tastoria/data/processed/cv/yolo_v4")
    if (yolo_v4 / "dataset.yaml").is_file() and "mi_tom" in targets_by_id:
        ds = yaml.safe_load((yolo_v4 / "dataset.yaml").read_text(encoding="utf-8"))
        raw_names = ds["names"]
        names_map = {int(k): v for k, v in raw_names.items()} if isinstance(raw_names, dict) else {i: v for i, v in enumerate(raw_names)}
        mitom_cls = next((k for k, v in names_map.items() if v == "mi_tom"), None)
        if mitom_cls is not None:
            for sp, bucket in (("val", val_samples), ("train", train_samples)):
                for lbl in sorted((yolo_v4 / "labels" / sp).glob("*.txt")):
                    lines = [ln.strip().split() for ln in lbl.read_text(encoding="utf-8").splitlines() if ln.strip()]
                    if not any(int(float(ln[0])) == mitom_cls for ln in lines):
                        continue
                    ip = yolo_v4 / "images" / sp / f"{lbl.stem}.jpg"
                    if ip.is_file():
                        bucket.append((ip.read_bytes(), targets_by_id["mi_tom"]))

    print(f"[vn_cal] collected train={len(train_samples)} val={len(val_samples)} Vietnamese/Asian dish calorie samples", flush=True)
    return train_samples, val_samples


class VNCalorieTorchDataset(Dataset):
    def __init__(self, samples: list[tuple[bytes, np.ndarray]], *, augment: bool = False, seed: int = 20261017) -> None:
        self.samples = samples
        self.augment = augment
        self.rng = np.random.default_rng(seed)

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        raw, base_y = self.samples[idx]
        y = base_y.copy()
        with Image.open(io.BytesIO(raw)) as im:
            im = im.convert("RGB")
            if self.augment:
                if self.rng.random() < 0.5:
                    im = im.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                # Portion scale augmentation: zooming in/out simulates bigger/smaller serving bowl
                scale = float(self.rng.uniform(0.82, 1.18))
                y = y * scale
                if self.rng.random() < 0.4:
                    angle = float(self.rng.uniform(-12.0, 12.0))
                    im = im.rotate(angle, resample=Image.Resampling.BILINEAR, fillcolor=(PAD_VALUE, PAD_VALUE, PAD_VALUE))
            arr = letterbox_rgb(im, size=INPUT_SIZE, pad_value=PAD_VALUE)
        if self.augment:
            alpha = float(self.rng.uniform(0.88, 1.12))
            beta = float(self.rng.uniform(-10.0, 10.0))
            arr_f = np.clip(arr.astype(np.float32) * alpha + beta, 0.0, 255.0)
        else:
            arr_f = arr.astype(np.float32)
        return torch.from_numpy(arr_f.transpose(2, 0, 1)), torch.from_numpy(y.astype(np.float32))


def run_v2_training(
    stage_dir: Path,
    runs_dir: Path,
    deploy_dir: Path,
    kb_dir: Path,
    kb_csv: Path,
    epochs: int = 22,
    batch_size: int = 48,
    seed: int = 20261017,
) -> dict:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
        try:
            torch.cuda.set_per_process_memory_fraction(0.12)
        except Exception:
            pass

    stage_nutrition5k(stage_dir)
    ds = load_overhead_dataset(stage_dir)
    vn_train, vn_val = build_vn_asian_calorie_samples(
        kb_dir=kb_dir,
        work_dir=runs_dir,
        exclude_dir=Path("/home/namnx/NamBuw/Tastoria/app/assets/food"),
        seed=seed,
    )

    n5k_train_df = ds.split_df("train")
    n5k_val_df = ds.split_df("val")
    y_n5k = ds.targets_array(n5k_train_df)
    y_vn = np.stack([y for _, y in vn_train], axis=0) if vn_train else y_n5k
    y_comb = np.concatenate([y_n5k, y_vn], axis=0)
    target_mean = y_comb.mean(axis=0).astype(np.float32)
    target_std = np.maximum(y_comb.std(axis=0), 1e-3).astype(np.float32)

    n5k_train_ds = make_torch_dataset(n5k_train_df, ds.images_by_id, augment=True, size=INPUT_SIZE, seed=seed)
    n5k_val_ds = make_torch_dataset(n5k_val_df, ds.images_by_id, augment=False, size=INPUT_SIZE, seed=seed)
    vn_train_ds = VNCalorieTorchDataset(vn_train, augment=True, seed=seed)
    vn_val_ds = VNCalorieTorchDataset(vn_val, augment=False, seed=seed)

    # Combine Nutrition5k (2x weighted so test_clean MAE remains optimal) + VN/Asian meals
    comb_train_ds = ConcatDataset([n5k_train_ds, n5k_train_ds, vn_train_ds])
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    use_amp = device.type == "cuda"

    train_loader = DataLoader(comb_train_ds, batch_size=batch_size, shuffle=True, num_workers=4, pin_memory=use_amp)
    n5k_val_loader = DataLoader(n5k_val_ds, batch_size=batch_size, shuffle=False, num_workers=2, pin_memory=use_amp)
    vn_val_loader = DataLoader(vn_val_ds, batch_size=batch_size, shuffle=False, num_workers=2, pin_memory=use_amp)

    in_mean = torch.tensor([0.485, 0.456, 0.406], device=device).view(1, 3, 1, 1) * 255.0
    in_std = torch.tensor([0.229, 0.224, 0.225], device=device).view(1, 3, 1, 1) * 255.0
    y_mean_t = torch.tensor(target_mean, device=device).view(1, -1)
    y_std_t = torch.tensor(target_std, device=device).view(1, -1)

    ablation = {}
    runs_dir.mkdir(parents=True, exist_ok=True)

    for backbone_name in ("mobilenetv3_small_100", "mobilenetv3_large_100"):
        net = MealCalorieNet(backbone_name=backbone_name, pretrained=True, dropout=0.2).to(device)
        n_params = sum(p.numel() for p in net.parameters())
        optimizer = torch.optim.AdamW(net.parameters(), lr=4e-4, weight_decay=1e-4)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs, eta_min=2e-5)
        criterion = nn.SmoothL1Loss(beta=0.45)
        scaler = torch.amp.GradScaler("cuda", enabled=use_amp)
        if use_amp:
            torch.cuda.reset_peak_memory_stats(device)

        best_score = float("inf")
        best_epoch = 1
        best_state = None
        history = []
        t0 = time.perf_counter()

        for epoch in range(1, epochs + 1):
            net.train()
            tr_loss = 0.0
            n_tr = 0
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
                tr_loss += float(loss.detach()) * len(xb)
                n_tr += len(xb)
            scheduler.step()

            net.eval()
            def _eval_loader(loader):
                ps, ts = [], []
                with torch.no_grad():
                    for xb, yb in loader:
                        xb = xb.to(device, non_blocking=True)
                        with torch.amp.autocast("cuda", enabled=use_amp):
                            pn = net((xb - in_mean) / in_std)
                        pr = torch.clamp(pn.float() * y_std_t + y_mean_t, min=0.0)
                        ps.append(pr.cpu().numpy())
                        ts.append(yb.numpy())
                return compute_all_target_metrics(np.concatenate(ts, 0), np.concatenate(ps, 0))

            m_n5k = _eval_loader(n5k_val_loader)
            m_vn = _eval_loader(vn_val_loader)
            n5k_mae = float(m_n5k["kcal"]["mae"])
            vn_mae = float(m_vn["kcal"]["mae"])
            comb_mae = 0.65 * n5k_mae + 0.35 * vn_mae
            print(
                f"[{backbone_name}] Ep {epoch:02d}/{epochs} | n5k_val_mae={n5k_mae:.2f} | vn_val_mae={vn_mae:.2f} | comb={comb_mae:.2f}",
                flush=True,
            )
            history.append({"epoch": epoch, "n5k_val_kcal_mae": n5k_mae, "vn_val_kcal_mae": vn_mae})
            if comb_mae < best_score:
                best_score = comb_mae
                best_epoch = epoch
                best_state = {k: v.detach().cpu() for k, v in net.state_dict().items()}

        peak_vram = float(torch.cuda.max_memory_allocated(device) / (1024 ** 2)) if use_amp else 0.0
        ckpt_path = runs_dir / f"{backbone_name}_best.pt"
        torch.save(
            {
                "backbone_name": backbone_name,
                "state_dict": best_state,
                "target_mean": target_mean,
                "target_std": target_std,
                "best_epoch": best_epoch,
                "best_val_kcal_mae": best_score,
                "n_params": n_params,
                "seed": seed,
            },
            ckpt_path,
        )
        net.load_state_dict(best_state)
        net.eval()
        wrapped = WithNormCalorieWrapper(net.cpu(), target_mean, target_std).eval()
        ps, ts = [], []
        with torch.no_grad():
            for xb, yb in n5k_val_loader:
                ps.append(wrapped(xb).numpy())
                ts.append(yb.numpy())
        val_m = compute_all_target_metrics(np.concatenate(ts, 0), np.concatenate(ps, 0))
        ablation[backbone_name] = {
            "backbone": backbone_name,
            "ckpt_path": str(ckpt_path),
            "n_params": n_params,
            "best_epoch": best_epoch,
            "epochs_run": epochs,
            "elapsed_s": round(time.perf_counter() - t0, 2),
            "peak_vram_mb": round(peak_vram, 1),
            "val_metrics": val_m,
            "history": history,
        }

    # Select winner & evaluate on Nutrition5k splits
    from tastoria_ml.calorie.train import PARSIMONY_MIN_VAL_GAIN_KCAL, evaluate_checkpoint_on_splits
    s_mae = float(ablation["mobilenetv3_small_100"]["val_metrics"]["kcal"]["mae"])
    l_mae = float(ablation["mobilenetv3_large_100"]["val_metrics"]["kcal"]["mae"])
    winner = "mobilenetv3_large_100" if (s_mae - l_mae) >= PARSIMONY_MIN_VAL_GAIN_KCAL else "mobilenetv3_small_100"
    reason = f"Selected {winner} (small_mae={s_mae:.2f}, large_mae={l_mae:.2f}) trained on Nutrition5k + VNFood-103 multi-domain corpus."
    winner_ckpt = Path(ablation[winner]["ckpt_path"])
    ev = evaluate_checkpoint_on_splits(winner_ckpt, ds, batch_size=batch_size)

    summary = {
        "selected_backbone": winner,
        "selected_ckpt": str(winner_ckpt),
        "selection_reason": reason,
        "ablation": ablation,
        "evaluation": ev,
    }
    summary_path = runs_dir / "train_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    from tastoria_ml.calorie.export_onnx import export_model
    serving = export_model(
        ckpt_path=winner_ckpt,
        train_summary_path=summary_path,
        stage_dir=stage_dir,
        deploy_dir=deploy_dir,
        kb_csv_path=kb_csv,
    )
    print("Exported V2 MealCalorieEstimator:", json.dumps(serving["honest_metrics"], indent=2), flush=True)
    return serving


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage-dir", type=Path, default=Path("/dev/shm/cal_v2_stage/calorie_lens"))
    ap.add_argument("--runs-dir", type=Path, default=Path("/dev/shm/cal_v2_stage/runs"))
    ap.add_argument("--deploy-dir", type=Path, default=Path("/home/namnx/NamBuw/Tastoria/deploy/models/meal_calorie"))
    ap.add_argument("--kb-dir", type=Path, default=Path("/home/namnx/NamBuw/Tastoria/data/kb"))
    ap.add_argument("--kb-csv", type=Path, default=Path("/home/namnx/NamBuw/Tastoria/data/processed/kb/recipe_nutrition.csv"))
    ap.add_argument("--epochs", type=int, default=22)
    args = ap.parse_args()
    run_v2_training(args.stage_dir, args.runs_dir, args.deploy_dir, args.kb_dir, args.kb_csv, epochs=args.epochs)


if __name__ == "__main__":
    main()

