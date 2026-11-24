"""Train V3 Multi-Task Factorized Calorie, Mass, Food-Fill & Multi-Dish Regressor on GPU 121.

Outputs 7 targets (preserving 0..4 contract of ``WithNormCalorieWrapper`` + adding 5..6):
  0: ``kcal``
  1: ``mass_g``
  2: ``fat_g``
  3: ``carb_g``
  4: ``protein_g``
  5: ``food_area_ratio`` (in ``[0.0, 1.0]``, pixel foreground fraction from segmentation masks)
  6: ``multi_dish_score`` (in ``[0.0, 1.0]``, spatial spread / multi-dish complexity proxy)

Combines:
  - ``shalev396/calorie-lens-data`` (Nutrition5k weighed overhead meals, exact splits preserved)
  - ``justinsiow/UECFOODPIXCOMPLETE`` (10,000 Asian dishes with pixel masks -> fill + spread + KB macros)
  - ``EduardoPacheco/FoodSeg103`` (7,118 multi-ingredient pixel masks -> fill + multi-dish complexity)
  - ``Humanbased-AI/MM-Food-100K`` (sampled diverse phone/homemade dishes with nutrition + portion weights)
  - ``jeandeanny/vn-food-combined-2026`` + ``mi_tom`` (3,500+ Vietnamese meals)

Strictly enforces ``--mem-fraction`` (default ``0.18``, <= 8.3 GB VRAM on GPU 121).
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import random
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import timm
import torch
import torch.nn as nn
import yaml
from huggingface_hub import HfApi, hf_hub_download
from PIL import Image, ImageOps
from torch.utils.data import ConcatDataset, DataLoader, Dataset

from tastoria_ml.calorie import INPUT_SIZE, PAD_VALUE, PORTION_MULTIPLIERS, TARGET_COLS
from tastoria_ml.calorie.dataset import letterbox_rgb, load_overhead_dataset, make_torch_dataset
from tastoria_ml.calorie.dish_taxonomy import UEC100_TO_CANONICAL
from tastoria_ml.calorie.eval import compute_all_target_metrics
from tastoria_ml.calorie.export_onnx import benchmark_onnx_cpu, sha256_file
from tastoria_ml.calorie.train import evaluate_checkpoint_on_splits
from tastoria_ml.calorie.train_v2 import build_vn_asian_calorie_samples, stage_nutrition5k
from tastoria_ml.cv.phash import hamming, phash

UPPER_7 = np.array([3500.0, 3000.0, 250.0, 400.0, 250.0, 1.0, 1.0], dtype=np.float32)


def _img_phash(im: Image.Image) -> int:
    g = im.convert("L")
    g.thumbnail((256, 256))
    return int(phash(np.asarray(g)))


def _parse_portion_grams(portion_json_str: str) -> float | None:
    try:
        items = json.loads(portion_json_str)
    except Exception:
        return None
    if not isinstance(items, list):
        return None
    total = 0.0
    found = False
    for it in items:
        s = str(it).lower()
        for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(kg|g|ml)\b", s):
            v = float(m.group(1))
            unit = m.group(2)
            total += v * 1000.0 if unit == "kg" else v
            found = True
    return total if (found and 30.0 <= total <= 2500.0) else None


def _mask_stats(mask_im: Image.Image) -> tuple[float, float]:
    """Return (food_area_ratio, multi_dish_score proxy) from segmentation mask."""
    arr = np.asarray(mask_im)
    fg = (arr[..., 0] > 0) if arr.ndim == 3 else (arr > 0)
    area_ratio = float(fg.mean())
    if arr.ndim == 3:
        uniq = np.unique(arr[..., 0])
    else:
        uniq = np.unique(arr)
    n_labels = int((uniq > 0).sum())
    if n_labels >= 2:
        multi = min(1.0, (n_labels - 1) / 5.0)
    else:
        # Spatial spread heuristic if single foreground class
        ys, xs = np.where(fg)
        if ys.size < 20:
            multi = 0.0
        else:
            h, w = fg.shape
            span = max((ys.max() - ys.min()) / max(1, h), (xs.max() - xs.min()) / max(1, w))
            multi = 0.35 if span > 0.78 and area_ratio < 0.45 else 0.15
    return float(np.clip(area_ratio, 0.0, 1.0)), float(np.clip(multi, 0.0, 1.0))


def build_extra_cal_samples(
    kb_dir: Path,
    stage_dir: Path,
    exclude_dir: Path,
    max_mmfood: int = 4500,
    seed: int = 20261017,
) -> tuple[list[tuple[bytes, np.ndarray, np.ndarray]], list[tuple[bytes, np.ndarray, np.ndarray]]]:
    """Return (train, val) tuples of (jpeg_bytes, target_7, mask_7[0/1]) for UECFoodPix, FoodSeg103, MM-Food."""
    rec_doc = yaml.safe_load((kb_dir / "recognized_dishes_nutrition.yaml").read_text(encoding="utf-8"))
    targets_by_id: dict[str, np.ndarray] = {}
    for d in rec_doc["dishes"]:
        p, f, c = float(d["protein_g"]), float(d["lipid_g"]), float(d["glucid_g"])
        m = re.search(r"~(\d+)\s*g", str(d.get("serving_desc_vi") or ""))
        mass = float(m.group(1)) if m else max(120.0, round((p + f + c) * 3.8, 1))
        targets_by_id[d["dish_id"]] = np.array([float(d["kcal_per_serving"]), mass, f, c, p], dtype=np.float32)

    ex_hashes = []
    if exclude_dir.is_dir():
        for p in sorted(exclude_dir.iterdir()):
            if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                with Image.open(p) as im:
                    ex_hashes.append(_img_phash(im.convert("RGB")))
    ex_arr = np.asarray(ex_hashes, dtype=np.uint64) if ex_hashes else None

    def _ok_rgb(raw: bytes) -> tuple[Image.Image, bytes] | None:
        with Image.open(io.BytesIO(raw)) as im:
            rgb = ImageOps.exif_transpose(im).convert("RGB")
            if ex_arr is not None and ex_arr.size > 0 and int(hamming(ex_arr, _img_phash(rgb)).min()) <= 4:
                return None
            rgb.thumbnail((256, 256), Image.Resampling.BILINEAR)
            buf = io.BytesIO()
            rgb.save(buf, "JPEG", quality=86)
            return rgb, buf.getvalue()

    train_s, val_s = [], []

    # 1. UECFOODPIXCOMPLETE (food_area_ratio + multi_dish_score from exact masks)
    print("[cal_v3] Downloading UECFOODPIXCOMPLETE masks...", flush=True)
    u_dl = stage_dir / "_dl_uecpix"
    u_info = HfApi().dataset_info("justinsiow/UECFOODPIXCOMPLETE")
    for s in u_info.siblings:
        if s.rfilename.endswith(".parquet"):
            lp = Path(hf_hub_download("justinsiow/UECFOODPIXCOMPLETE", s.rfilename, repo_type="dataset", local_dir=str(u_dl)))
            sp_bucket = val_s if "validation" in lp.name else train_s
            pf = pq.ParquetFile(lp)
            for batch in pf.iter_batches(batch_size=256, columns=["image", "label"]):
                for icell, lcell in zip(batch.column("image").to_pylist(), batch.column("label").to_pylist()):
                    try:
                        iraw = icell["bytes"] if isinstance(icell, dict) and icell.get("bytes") else bytes(icell)
                        lraw = lcell["bytes"] if isinstance(lcell, dict) and lcell.get("bytes") else bytes(lcell)
                        ok = _ok_rgb(iraw)
                        if not ok:
                            continue
                        with Image.open(io.BytesIO(lraw)) as mim:
                            area, multi = _mask_stats(mim)
                            m_arr = np.asarray(mim)
                            pix = m_arr[..., 0] if m_arr.ndim == 3 else m_arr
                            fg_vals = pix[pix > 0]
                            y7 = np.zeros(7, dtype=np.float32)
                            m7 = np.array([0, 0, 0, 0, 0, 1, 1], dtype=np.float32)
                            if fg_vals.size > 0:
                                vals, cnts = np.unique(fg_vals, return_counts=True)
                                dom = int(vals[np.argmax(cnts)])
                                cid = UEC100_TO_CANONICAL.get(dom)
                                if cid and cid in targets_by_id:
                                    y7[:5] = targets_by_id[cid]
                                    m7[:5] = 1.0
                            y7[5], y7[6] = area, multi
                            sp_bucket.append((ok[1], y7, m7))
                    except Exception:
                        pass
            lp.unlink(missing_ok=True)

    # 2. FoodSeg103 (multi-ingredient food_area_ratio + multi_dish_score)
    print("[cal_v3] Downloading FoodSeg103 masks...", flush=True)
    fs_dl = stage_dir / "_dl_foodseg"
    fs_info = HfApi().dataset_info("EduardoPacheco/FoodSeg103")
    for s in fs_info.siblings:
        if s.rfilename.endswith(".parquet"):
            lp = Path(hf_hub_download("EduardoPacheco/FoodSeg103", s.rfilename, repo_type="dataset", local_dir=str(fs_dl)))
            sp_bucket = val_s if "validation" in lp.name else train_s
            pf = pq.ParquetFile(lp)
            for batch in pf.iter_batches(batch_size=256, columns=["image", "label", "classes_on_image"]):
                for icell, lcell, clses in zip(
                    batch.column("image").to_pylist(),
                    batch.column("label").to_pylist(),
                    batch.column("classes_on_image").to_pylist(),
                ):
                    try:
                        iraw = icell["bytes"] if isinstance(icell, dict) and icell.get("bytes") else bytes(icell)
                        lraw = lcell["bytes"] if isinstance(lcell, dict) and lcell.get("bytes") else bytes(lcell)
                        ok = _ok_rgb(iraw)
                        if not ok:
                            continue
                        with Image.open(io.BytesIO(lraw)) as mim:
                            area, _ = _mask_stats(mim)
                        n_ing = len([c for c in (clses or []) if int(c) > 0])
                        multi = min(1.0, max(0.0, (n_ing - 1) / 5.0))
                        y7 = np.array([0, 0, 0, 0, 0, area, multi], dtype=np.float32)
                        m7 = np.array([0, 0, 0, 0, 0, 1, 1], dtype=np.float32)
                        sp_bucket.append((ok[1], y7, m7))
                    except Exception:
                        pass
            lp.unlink(missing_ok=True)

    # 3. MM-Food-100K (diverse camera/homemade/restaurant dishes with real kcal + grams)
    mm_path = Path(hf_hub_download("Humanbased-AI/MM-Food-100K", "MM-Food-100K.csv", repo_type="dataset"))
    mm_rows = []
    with mm_path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                if float(row.get("food_prob") or 0) < 0.90:
                    continue
                if row.get("food_type") not in ("Homemade food", "Restaurant food"):
                    continue
                npf = json.loads(row["nutritional_profile"])
                kcal = float(npf["calories_kcal"])
                prot = float(npf["protein_g"])
                carb = float(npf["carbohydrate_g"])
                fat = float(npf["fat_g"])
                grams = _parse_portion_grams(row["portion_size"])
                if grams is None or not (30.0 <= kcal <= 2500.0):
                    continue
                mm_rows.append((row["image_url"], np.array([kcal, grams, fat, carb, prot, 0.0, 0.0], dtype=np.float32)))
            except Exception:
                continue
    rng = random.Random(seed)
    rng.shuffle(mm_rows)
    mm_rows = mm_rows[:max_mmfood]
    print(f"[cal_v3] Downloading {len(mm_rows)} MM-Food-100K phone-photo nutrition targets...", flush=True)

    def _dl(u: str) -> bytes | None:
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0 Tastoria/3.0"})
            with urllib.request.urlopen(req, timeout=8) as r:
                b = r.read(3_500_000)
                return b if len(b) > 1000 else None
        except Exception:
            return None

    m7_cal = np.array([1, 1, 1, 1, 1, 0, 0], dtype=np.float32)
    with ThreadPoolExecutor(max_workers=20) as ex:
        futs = {ex.submit(_dl, u): y7 for u, y7 in mm_rows}
        idx = 0
        for fut in as_completed(futs):
            raw = fut.result()
            if not raw:
                continue
            try:
                ok = _ok_rgb(raw)
                if ok:
                    (val_s if idx % 10 == 0 else train_s).append((ok[1], futs[fut], m7_cal))
                    idx += 1
            except Exception:
                pass

    print(f"[cal_v3] Extra samples collected: train={len(train_s)}, val={len(val_s)}", flush=True)
    return train_s, val_s


class MaskedTupleCalorieDS(Dataset):
    def __init__(self, samples: list[tuple[bytes, np.ndarray, np.ndarray]], *, augment: bool = False, seed: int = 0) -> None:
        self.samples = samples
        self.augment = augment
        self.rng = np.random.default_rng(seed)

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        raw, base_y, mask = self.samples[idx]
        y = base_y.copy()
        with Image.open(io.BytesIO(raw)) as im:
            im = im.convert("RGB")
            if self.augment:
                if self.rng.random() < 0.5:
                    im = im.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                # Geometric zoom augmentation scales visible portion & food fill consistently
                if mask[0] > 0.5 and mask[5] < 0.5:
                    sc = float(self.rng.uniform(0.84, 1.16))
                    y[:5] = y[:5] * sc
            arr = letterbox_rgb(im, size=INPUT_SIZE, pad_value=PAD_VALUE).astype(np.float32)
        if self.augment:
            arr = np.clip(arr * float(self.rng.uniform(0.88, 1.12)) + float(self.rng.uniform(-10, 10)), 0.0, 255.0)
        return torch.from_numpy(arr.transpose(2, 0, 1)), torch.from_numpy(y), torch.from_numpy(mask)


class WrappedBaseDS(Dataset):
    """Wraps 5-target Nutrition5k/VN datasets into 7-target masked tuples (computes fill proxy for Nutrition5k)."""

    def __init__(self, base_ds: Dataset, is_n5k: bool = False) -> None:
        self.base_ds = base_ds
        self.is_n5k = is_n5k

    def __len__(self) -> int:
        return len(self.base_ds)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        x, y5 = self.base_ds[idx]
        y7 = torch.zeros(7, dtype=torch.float32)
        y7[:5] = y5
        m7 = torch.tensor([1.0, 1.0, 1.0, 1.0, 1.0, 0.0, 0.0], dtype=torch.float32)
        if self.is_n5k:
            y7[6] = 0.25
            m7[6] = 1.0
        return x, y7, m7


class MealCalorieNetV3(nn.Module):
    def __init__(self, backbone_name: str, pretrained: bool = True, dropout: float = 0.2) -> None:
        super().__init__()
        self.backbone_name = backbone_name
        self.backbone = timm.create_model(backbone_name, pretrained=pretrained, num_classes=7, drop_rate=dropout)

    def forward(self, x_norm: torch.Tensor) -> torch.Tensor:
        return self.backbone(x_norm)


class WithNormCalorieWrapperV3(nn.Module):
    def __init__(self, net: MealCalorieNetV3, y_mean: np.ndarray, y_std: np.ndarray) -> None:
        super().__init__()
        self.net = net
        self.register_buffer("in_mean", torch.tensor([0.485, 0.456, 0.406], dtype=torch.float32).view(1, 3, 1, 1) * 255.0)
        self.register_buffer("in_std", torch.tensor([0.229, 0.224, 0.225], dtype=torch.float32).view(1, 3, 1, 1) * 255.0)
        self.register_buffer("y_mean", torch.tensor(y_mean, dtype=torch.float32).view(1, -1))
        self.register_buffer("y_std", torch.tensor(y_std, dtype=torch.float32).view(1, -1))
        self.register_buffer("y_max", torch.tensor(UPPER_7, dtype=torch.float32).view(1, -1))

    def forward(self, image: torch.Tensor) -> torch.Tensor:
        x_norm = (image - self.in_mean) / self.in_std
        z = self.net(x_norm)
        pred = z * self.y_std + self.y_mean
        return torch.minimum(torch.clamp(pred, min=0.0), self.y_max)


def run_v3_training(
    stage_dir: Path,
    runs_dir: Path,
    out_dir: Path,
    kb_dir: Path,
    epochs: int = 20,
    batch_size: int = 48,
    mem_fraction: float = 0.18,
    seed: int = 20261017,
) -> dict:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.set_per_process_memory_fraction(mem_fraction)

    n5k_dir = stage_dir / "calorie_lens"
    stage_nutrition5k(n5k_dir)
    ds = load_overhead_dataset(n5k_dir)

    vn_train, vn_val = build_vn_asian_calorie_samples(
        kb_dir=kb_dir, work_dir=runs_dir, exclude_dir=Path("/home/namnx/NamBuw/Tastoria/app/assets/food"), seed=seed
    )
    ex_train, ex_val = build_extra_cal_samples(
        kb_dir=kb_dir, stage_dir=stage_dir, exclude_dir=Path("/home/namnx/NamBuw/Tastoria/app/assets/food"), seed=seed
    )

    from tastoria_ml.calorie.train_v2 import VNCalorieTorchDataset
    n5k_tr_df, n5k_va_df = ds.split_df("train"), ds.split_df("val")
    n5k_tr_ds = WrappedBaseDS(make_torch_dataset(n5k_tr_df, ds.images_by_id, augment=True, size=INPUT_SIZE, seed=seed), is_n5k=True)
    n5k_va_ds = WrappedBaseDS(make_torch_dataset(n5k_va_df, ds.images_by_id, augment=False, size=INPUT_SIZE, seed=seed), is_n5k=True)
    vn_tr_ds = WrappedBaseDS(VNCalorieTorchDataset(vn_train, augment=True, seed=seed))
    vn_va_ds = WrappedBaseDS(VNCalorieTorchDataset(vn_val, augment=False, seed=seed))
    ex_tr_ds = MaskedTupleCalorieDS(ex_train, augment=True, seed=seed)
    ex_va_ds = MaskedTupleCalorieDS(ex_val, augment=False, seed=seed)

    # Target stats over valid targets
    y_n5k = ds.targets_array(n5k_tr_df)
    y_mean7 = np.array([y_n5k[:, 0].mean(), y_n5k[:, 1].mean(), y_n5k[:, 2].mean(), y_n5k[:, 3].mean(), y_n5k[:, 4].mean(), 0.45, 0.30], dtype=np.float32)
    y_std7 = np.array([max(1.0, y_n5k[:, 0].std()), max(1.0, y_n5k[:, 1].std()), max(0.5, y_n5k[:, 2].std()), max(0.5, y_n5k[:, 3].std()), max(0.5, y_n5k[:, 4].std()), 0.22, 0.25], dtype=np.float32)

    comb_tr = ConcatDataset([n5k_tr_ds, n5k_tr_ds, n5k_tr_ds, n5k_tr_ds, vn_tr_ds, ex_tr_ds])
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    use_amp = device.type == "cuda"
    tr_loader = DataLoader(comb_tr, batch_size=batch_size, shuffle=True, num_workers=4, pin_memory=use_amp)
    n5k_va_loader = DataLoader(n5k_va_ds, batch_size=batch_size, shuffle=False, num_workers=2, pin_memory=use_amp)
    ex_va_loader = DataLoader(ex_va_ds, batch_size=batch_size, shuffle=False, num_workers=2, pin_memory=use_amp)

    in_mean = torch.tensor([0.485, 0.456, 0.406], device=device).view(1, 3, 1, 1) * 255.0
    in_std = torch.tensor([0.229, 0.224, 0.225], device=device).view(1, 3, 1, 1) * 255.0
    ym_t = torch.tensor(y_mean7, device=device).view(1, 7)
    ys_t = torch.tensor(y_std7, device=device).view(1, 7)

    runs_dir.mkdir(parents=True, exist_ok=True)
    ablation = {}

    for bname, lr in (("convnext_atto", 3.5e-4), ("efficientnet_b2", 3.5e-4)):
        net = MealCalorieNetV3(bname, pretrained=True, dropout=0.2).to(device)
        opt = torch.optim.AdamW(net.parameters(), lr=lr, weight_decay=1e-4)
        sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs, eta_min=lr * 0.05)
        crit = nn.SmoothL1Loss(reduction="none", beta=0.45)
        scaler = torch.amp.GradScaler("cuda", enabled=use_amp)
        best_val = float("inf")
        best_state = None
        best_ep = 1
        t0 = time.perf_counter()

        for ep in range(1, epochs + 1):
            net.train()
            for xb, yb, mb in tr_loader:
                xb, yb, mb = xb.to(device, non_blocking=True), yb.to(device, non_blocking=True), mb.to(device, non_blocking=True)
                opt.zero_grad(set_to_none=True)
                with torch.amp.autocast("cuda", enabled=use_amp):
                    pn = net((xb - in_mean) / in_std)
                    yn = (yb - ym_t) / ys_t
                    loss_mat = crit(pn, yn) * mb
                    loss = loss_mat.sum() / torch.clamp(mb.sum(), min=1.0)
                scaler.scale(loss).backward()
                scaler.unscale_(opt)
                torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
                scaler.step(opt)
                scaler.update()
            sched.step()

            net.eval()
            ps, ts = [], []
            with torch.no_grad():
                for xb, yb, _ in n5k_va_loader:
                    xb = xb.to(device, non_blocking=True)
                    with torch.amp.autocast("cuda", enabled=use_amp):
                        pn = net((xb - in_mean) / in_std)
                    pr = torch.clamp(pn.float() * ys_t + ym_t, min=0.0)
                    ps.append(pr[:, :5].cpu().numpy())
                    ts.append(yb[:, :5].numpy())
            n5k_m = compute_all_target_metrics(np.concatenate(ts, 0), np.concatenate(ps, 0))
            n5k_kcal_mae = float(n5k_m["kcal"]["mae"])
            n5k_mass_mae = float(n5k_m["mass_g"]["mae"])

            # Check extra mask validation (area_ratio MAE)
            area_errs = []
            with torch.no_grad():
                for xb, yb, mb in ex_va_loader:
                    xb = xb.to(device, non_blocking=True)
                    with torch.amp.autocast("cuda", enabled=use_amp):
                        pn = net((xb - in_mean) / in_std)
                    pr = torch.clamp(pn.float() * ys_t + ym_t, min=0.0).cpu().numpy()
                    m5 = mb[:, 5].numpy() > 0.5
                    if m5.any():
                        area_errs.append(np.abs(pr[m5, 5] - yb[m5, 5].numpy()))
            area_mae = float(np.concatenate(area_errs).mean()) if area_errs else 0.0
            score = n5k_kcal_mae + 0.35 * n5k_mass_mae + 50.0 * area_mae
            print(f"[{bname}] Ep {ep:02d}/{epochs} | n5k_kcal_mae={n5k_kcal_mae:.2f} | mass_mae={n5k_mass_mae:.2f} | area_mae={area_mae:.3f}", flush=True)
            if score < best_val:
                best_val = score
                best_ep = ep
                best_state = {k: v.detach().cpu() for k, v in net.state_dict().items()}

        ckpt_p = runs_dir / f"{bname}_v3_best.pt"
        torch.save({"backbone_name": bname, "state_dict": best_state, "y_mean": y_mean7, "y_std": y_std7, "best_epoch": best_ep, "best_score": best_val}, ckpt_p)

        net.load_state_dict(best_state)
        wrapped = WithNormCalorieWrapperV3(net.cpu(), y_mean7, y_std7).eval()
        cand_dir = runs_dir / f"onnx_{bname}"
        cand_dir.mkdir(parents=True, exist_ok=True)
        cand_onnx = cand_dir / "model.onnx"
        torch.onnx.export(wrapped, torch.zeros(1, 3, INPUT_SIZE, INPUT_SIZE), str(cand_onnx), input_names=["image"], output_names=["pred"], dynamic_axes={"image": {0: "n"}, "pred": {0: "n"}}, opset_version=17, dynamo=False)
        lat = benchmark_onnx_cpu(cand_onnx, n_warmup=5, n_runs=80)

        # Evaluate on Nutrition5k test & test_clean
        from tastoria_ml.calorie.baselines import ConstantBaseline
        const_base = ConstantBaseline.fit(ds.targets_array(n5k_tr_df))
        splits_out = {}
        for sp, clean in (("val", False), ("test", False), ("test_clean", True)):
            sdf = ds.split_df("test" if clean else sp, clean_only=clean)
            sl = DataLoader(make_torch_dataset(sdf, ds.images_by_id, augment=False, size=INPUT_SIZE), batch_size=32, shuffle=False)
            sp_p, sp_t = [], []
            with torch.no_grad():
                for xb, yb in sl:
                    sp_p.append(wrapped(xb)[:, :5].numpy())
                    sp_t.append(yb.numpy())
            y_true_s, y_pred_s = np.concatenate(sp_t, 0), np.concatenate(sp_p, 0)
            splits_out[sp] = {
                "n": int(len(sdf)),
                "model": compute_all_target_metrics(y_true_s, y_pred_s),
                "baseline_median": compute_all_target_metrics(y_true_s, const_base.predict_median(len(sdf))),
            }

        ablation[bname] = {
            "ckpt": str(ckpt_p),
            "onnx": str(cand_onnx),
            "best_epoch": best_ep,
            "elapsed_s": round(time.perf_counter() - t0, 1),
            "cpu_latency": lat,
            "val_area_mae": round(area_mae, 4),
            "val_kcal_mae": splits_out["val"]["model"]["kcal"]["mae"],
            "test_kcal_mae": splits_out["test"]["model"]["kcal"]["mae"],
            "test_mass_mae": splits_out["test"]["model"]["mass_g"]["mae"],
            "test_kcal_r2": splits_out["test"]["model"]["kcal"]["r2"],
            "test_clean_kcal_mae": splits_out["test_clean"]["model"]["kcal"]["mae"],
            "splits": splits_out,
            "constant_baseline": const_base.to_dict(),
        }

    # Parsimonious selection under <= 50 ms CPU latency budget
    eligible = [b for b, info in ablation.items() if info["cpu_latency"]["p95_ms"] <= 50.0]
    if not eligible:
        eligible = list(ablation.keys())
    winner = min(eligible, key=lambda b: ablation[b]["val_kcal_mae"])
    out_dir.mkdir(parents=True, exist_ok=True)
    import shutil
    final_onnx = out_dir / "model.onnx"
    shutil.copy2(ablation[winner]["onnx"], final_onnx)
    sha = sha256_file(final_onnx)
    lat_w = benchmark_onnx_cpu(final_onnx)

    serving = {
        "schema_version": "meal_calorie.serving.v1",
        "name": "meal_calorie",
        "version": f"meal_calorie_{winner}_v3_multitask",
        "backbone": winner,
        "license": "CC-BY-4.0 (Nutrition5k + UECFoodPixComplete + FoodSeg103 + MM-Food-100K + VNFood-103)",
        "artifact_file": "model.onnx",
        "artifact_sha256": sha,
        "artifact_bytes": final_onnx.stat().st_size,
        "input": {"name": "image", "shape": [1, 3, INPUT_SIZE, INPUT_SIZE], "layout": "NCHW", "color": "RGB", "preprocess": "letterbox", "pad_value": PAD_VALUE, "range": "0..255_float32", "norm_baked_in_onnx": True},
        "outputs": {"name": "pred", "shape": [1, 7], "columns": [*TARGET_COLS, "food_area_ratio", "multi_dish_score"], "clamped_non_negative": True},
        "portion_multipliers": dict(PORTION_MULTIPLIERS),
        "honest_metrics": {
            "val_kcal_mae": ablation[winner]["val_kcal_mae"],
            "test_kcal_mae": ablation[winner]["test_kcal_mae"],
            "test_mass_mae": ablation[winner]["test_mass_mae"],
            "test_kcal_r2": ablation[winner]["test_kcal_r2"],
            "test_clean_kcal_mae": ablation[winner]["test_clean_kcal_mae"],
            "cpu_p50_ms": lat_w["p50_ms"],
            "cpu_p95_ms": lat_w["p95_ms"],
        },
        "domain_shift_note": "Ước lượng trực quan đa nhiệm v3 (Nutrition5k + MM-Food + UECFoodPix + VNFood); kết hợp phân rã khối lượng & độ phủ khay ăn với chuẩn NIN.",
    }
    (out_dir / "serving.json").write_text(json.dumps(serving, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "metrics.json").write_text(
        json.dumps(
            {
                "selected": winner,
                "constant_baseline": ablation[winner]["constant_baseline"],
                "splits": ablation[winner]["splits"],
                "ablation": {k: {ak: av for ak, av in v.items() if ak not in ("splits", "constant_baseline")} for k, v in ablation.items()},
                "cpu_latency": lat_w,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"selected": winner, "honest_metrics": serving["honest_metrics"]}, indent=2), flush=True)
    return serving


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage-dir", type=Path, default=Path("/dev/shm/cal_v3_stage"))
    ap.add_argument("--runs-dir", type=Path, default=Path("/dev/shm/cal_v3_runs"))
    ap.add_argument("--out-dir", type=Path, default=Path("/dev/shm/cal_v3_out"))
    ap.add_argument("--kb-dir", type=Path, default=Path("/home/namnx/NamBuw/Tastoria/data/kb"))
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--mem-fraction", type=float, default=0.18)
    a = ap.parse_args()
    run_v3_training(a.stage_dir, a.runs_dir, a.out_dir, a.kb_dir, epochs=a.epochs, mem_fraction=a.mem_fraction)


if __name__ == "__main__":
    main()
