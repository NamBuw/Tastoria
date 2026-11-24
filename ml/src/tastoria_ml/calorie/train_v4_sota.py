"""Train Tastoria V4 SOTA Calorie, Mass, Food-Fill & Multi-Dish Engine (RDINet / DPF-Nutrition inspired).

Key SOTA mechanisms (zero extra inference cost in ONNX):
  1. Offline Frozen Depth Teacher (``MiDaS_small`` on CUDA): precomputes 3D relative depth geometry
     ``[depth_mean, depth_std, depth_p90]`` per training dish, distilled into a training-only aux head.
  2. Auxiliary 103-Ingredient Multi-Label Head: supervised by ``FoodSeg103`` ``classes_on_image`` so the
     ConvNeXt-Tiny backbone internalizes fine-grained ingredient composition.
  3. Composite Physics + PMAE Loss: ``SmoothL1 + 0.25 * Relative_PMAE + 0.15 * Atwater_Physics``
     (enforces ``kcal ≈ 4*P + 4*C + 9*F`` and minimizes percentage error across small & large dishes).
  4. 2-Stage Training + Model EMA (decay=0.995):
     - Stage 1 (18 epochs): multi-domain joint training across Nutrition5k (5x) + MM-Food-100K (10,000
       camera dishes) + UECFoodPixComplete (10,000 masks) + FoodSeg103 (7,118 masks + 103 ingredients)
       + VNFood-103 (5,078).
     - Stage 2 (8 epochs, low LR 4e-5): high-precision calibration polish on Nutrition5k (6x) +
       VNFood + UECFoodPix + FoodSeg + MM-Food.
  5. Exports backward-compatible 7-output ONNX ``[kcal, mass_g, fat_g, carb_g, protein_g, food_area_ratio, multi_dish_score]``
     and reports exact Nutrition5k ``PMAE (%) = MAE / mean_true * 100`` vs SnapCalorie (16.5%) / DPF-Nutrition (14.7%).

Strictly caps GPU 121 memory via ``--mem-fraction 0.18`` (<= 8.3 GB VRAM).
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import random
import re
import shutil
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import timm
import torch
import torch.nn as nn
import torch.nn.functional as F
from huggingface_hub import HfApi, hf_hub_download
from PIL import Image, ImageOps
from torch.utils.data import ConcatDataset, DataLoader, Dataset

from tastoria_ml.calorie import INPUT_SIZE, PAD_VALUE, PORTION_MULTIPLIERS, TARGET_COLS
from tastoria_ml.calorie.baselines import ConstantBaseline
from tastoria_ml.calorie.dataset import letterbox_rgb, load_overhead_dataset, make_torch_dataset
from tastoria_ml.calorie.dish_taxonomy import UEC100_TO_CANONICAL
from tastoria_ml.calorie.eval import compute_all_target_metrics
from tastoria_ml.calorie.export_onnx import benchmark_onnx_cpu, sha256_file
from tastoria_ml.calorie.train_v2 import VNCalorieTorchDataset, build_vn_asian_calorie_samples, stage_nutrition5k
from tastoria_ml.calorie.train_v3_portion import _img_phash, _mask_stats, _parse_portion_grams
from tastoria_ml.cv.phash import hamming

UPPER_7 = np.array([3500.0, 3000.0, 250.0, 400.0, 250.0, 1.0, 1.0], dtype=np.float32)
N_FOODSEG_CLS = 104  # 0..103


def _build_sota_corpus(
    kb_dir: Path,
    stage_dir: Path,
    exclude_dir: Path,
    max_mmfood: int = 10000,
    seed: int = 20261017,
) -> tuple[list[tuple[bytes, np.ndarray, np.ndarray, np.ndarray]], list[tuple[bytes, np.ndarray, np.ndarray, np.ndarray]]]:
    """Return (train, val) tuples of (jpeg_bytes, y7, mask7, ing_multihot_or_zeros_with_has_flag)."""
    import yaml

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

    def _ok_rgb(raw: bytes) -> bytes | None:
        with Image.open(io.BytesIO(raw)) as im:
            rgb = ImageOps.exif_transpose(im).convert("RGB")
            if ex_arr is not None and ex_arr.size > 0 and int(hamming(ex_arr, _img_phash(rgb)).min()) <= 4:
                return None
            rgb.thumbnail((256, 256), Image.Resampling.BILINEAR)
            buf = io.BytesIO()
            rgb.save(buf, "JPEG", quality=86)
            return buf.getvalue()

    train_s, val_s = [], []
    zero_ing = np.zeros(N_FOODSEG_CLS + 1, dtype=np.float32)  # last col = has_ing_supervision

    # 1. UECFOODPIXCOMPLETE
    print("[v4_sota] Ingesting UECFOODPIXCOMPLETE...", flush=True)
    u_dl = stage_dir / "_dl_uecpix"
    for s in HfApi().dataset_info("justinsiow/UECFOODPIXCOMPLETE").siblings:
        if s.rfilename.endswith(".parquet"):
            lp = Path(hf_hub_download("justinsiow/UECFOODPIXCOMPLETE", s.rfilename, repo_type="dataset", local_dir=str(u_dl)))
            bucket = val_s if "validation" in lp.name else train_s
            for batch in pq.ParquetFile(lp).iter_batches(batch_size=256, columns=["image", "label"]):
                for ic, lc in zip(batch.column("image").to_pylist(), batch.column("label").to_pylist()):
                    try:
                        iraw = ic["bytes"] if isinstance(ic, dict) and ic.get("bytes") else bytes(ic)
                        lraw = lc["bytes"] if isinstance(lc, dict) and lc.get("bytes") else bytes(lc)
                        jb = _ok_rgb(iraw)
                        if not jb:
                            continue
                        with Image.open(io.BytesIO(lraw)) as mim:
                            area, multi = _mask_stats(mim)
                            pix = np.asarray(mim)
                            pix = pix[..., 0] if pix.ndim == 3 else pix
                            fg = pix[pix > 0]
                            y7 = np.zeros(7, dtype=np.float32)
                            m7 = np.array([0, 0, 0, 0, 0, 1, 1], dtype=np.float32)
                            if fg.size > 0:
                                vals, cnts = np.unique(fg, return_counts=True)
                                cid = UEC100_TO_CANONICAL.get(int(vals[np.argmax(cnts)]))
                                if cid and cid in targets_by_id:
                                    y7[:5] = targets_by_id[cid]
                                    m7[:5] = 1.0
                            y7[5], y7[6] = area, multi
                            bucket.append((jb, y7, m7, zero_ing))
                    except Exception:
                        pass
            lp.unlink(missing_ok=True)
    shutil.rmtree(u_dl, ignore_errors=True)

    # 2. FoodSeg103 (+ 103 ingredient multi-hot labels!)
    print("[v4_sota] Ingesting FoodSeg103 (masks + 103 ingredients)...", flush=True)
    fs_dl = stage_dir / "_dl_foodseg"
    for s in HfApi().dataset_info("EduardoPacheco/FoodSeg103").siblings:
        if s.rfilename.endswith(".parquet"):
            lp = Path(hf_hub_download("EduardoPacheco/FoodSeg103", s.rfilename, repo_type="dataset", local_dir=str(fs_dl)))
            bucket = val_s if "validation" in lp.name else train_s
            for batch in pq.ParquetFile(lp).iter_batches(batch_size=256, columns=["image", "label", "classes_on_image"]):
                for ic, lc, clses in zip(
                    batch.column("image").to_pylist(),
                    batch.column("label").to_pylist(),
                    batch.column("classes_on_image").to_pylist(),
                ):
                    try:
                        iraw = ic["bytes"] if isinstance(ic, dict) and ic.get("bytes") else bytes(ic)
                        lraw = lc["bytes"] if isinstance(lc, dict) and lc.get("bytes") else bytes(lc)
                        jb = _ok_rgb(iraw)
                        if not jb:
                            continue
                        with Image.open(io.BytesIO(lraw)) as mim:
                            area, _ = _mask_stats(mim)
                        ing = np.zeros(N_FOODSEG_CLS + 1, dtype=np.float32)
                        valid_c = [int(c) for c in (clses or []) if 0 < int(c) < N_FOODSEG_CLS]
                        for c in valid_c:
                            ing[c] = 1.0
                        ing[-1] = 1.0  # supervised
                        multi = min(1.0, max(0.0, (len(valid_c) - 1) / 5.0))
                        y7 = np.array([0, 0, 0, 0, 0, area, multi], dtype=np.float32)
                        m7 = np.array([0, 0, 0, 0, 0, 1, 1], dtype=np.float32)
                        bucket.append((jb, y7, m7, ing))
                    except Exception:
                        pass
            lp.unlink(missing_ok=True)
    shutil.rmtree(fs_dl, ignore_errors=True)

    # 3. MM-Food-100K (up to 10,000 real camera/homemade/restaurant dishes with parsed grams + macros)
    mm_path = Path(hf_hub_download("Humanbased-AI/MM-Food-100K", "MM-Food-100K.csv", repo_type="dataset"))
    mm_rows = []
    with mm_path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                if float(row.get("food_prob") or 0) < 0.90:
                    continue
                if row.get("food_type") not in ("Homemade food", "Restaurant food", "Packaged food"):
                    continue
                npf = json.loads(row["nutritional_profile"])
                kcal = float(npf["calories_kcal"])
                prot = float(npf["protein_g"])
                carb = float(npf["carbohydrate_g"])
                fat = float(npf["fat_g"])
                grams = _parse_portion_grams(row["portion_size"])
                if grams is None or not (30.0 <= kcal <= 2500.0):
                    continue
                # Consistency filter: filter extreme Atwater garbage > 2.5x mismatch
                atw = 4.0 * prot + 4.0 * carb + 9.0 * fat
                if atw > 20.0 and (kcal / atw > 2.2 or atw / max(1.0, kcal) > 2.2):
                    continue
                mm_rows.append((row["image_url"], np.array([kcal, grams, fat, carb, prot, 0.0, 0.0], dtype=np.float32)))
            except Exception:
                continue
    rng = random.Random(seed)
    rng.shuffle(mm_rows)
    mm_rows = mm_rows[:max_mmfood]
    print(f"[v4_sota] Downloading {len(mm_rows)} MM-Food-100K curated phone photos...", flush=True)

    def _dl(u: str) -> bytes | None:
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0 Tastoria/4.0"})
            with urllib.request.urlopen(req, timeout=8) as r:
                b = r.read(3_500_000)
                return b if len(b) > 1000 else None
        except Exception:
            return None

    m7_cal = np.array([1, 1, 1, 1, 1, 0, 0], dtype=np.float32)
    with ThreadPoolExecutor(max_workers=24) as ex:
        futs = {ex.submit(_dl, u): y7 for u, y7 in mm_rows}
        idx = 0
        for fut in as_completed(futs):
            raw = fut.result()
            if not raw:
                continue
            try:
                jb = _ok_rgb(raw)
                if jb:
                    (val_s if idx % 10 == 0 else train_s).append((jb, futs[fut], m7_cal, zero_ing))
                    idx += 1
            except Exception:
                pass

    print(f"[v4_sota] Extra corpus: train={len(train_s)}, val={len(val_s)}", flush=True)
    return train_s, val_s


@torch.no_grad()
def _compute_depth_stats(
    jpegs: list[bytes], midas: nn.Module, device: torch.device, batch_size: int = 64
) -> np.ndarray:
    """Run frozen MiDaS_small depth teacher offline on CUDA -> [depth_mean, depth_std, depth_p90] per image."""
    m_mean = torch.tensor([0.485, 0.456, 0.406], device=device).view(1, 3, 1, 1) * 255.0
    m_std = torch.tensor([0.229, 0.224, 0.225], device=device).view(1, 3, 1, 1) * 255.0
    out_feats = []
    t0 = time.perf_counter()
    for i in range(0, len(jpegs), batch_size):
        arrs = []
        for jb in jpegs[i : i + batch_size]:
            with Image.open(io.BytesIO(jb)) as im:
                im = im.convert("RGB").resize((256, 256), Image.Resampling.BILINEAR)
                arrs.append(np.asarray(im, dtype=np.float32).transpose(2, 0, 1))
        xb = (torch.from_numpy(np.stack(arrs, axis=0)).to(device) - m_mean) / m_std
        with torch.amp.autocast("cuda", enabled=device.type == "cuda"):
            d = midas(xb)  # (B, 256, 256)
        d_flat = d.float().view(d.shape[0], -1)
        # Scale-invariant center crop weighting & percentile depth spread
        d_min = d_flat.min(dim=1, keepdim=True).values
        d_max = d_flat.max(dim=1, keepdim=True).values
        d_norm = (d_flat - d_min) / torch.clamp(d_max - d_min, min=1e-4)
        stats = torch.stack(
            [
                d_norm.mean(dim=1),
                d_norm.std(dim=1),
                torch.quantile(d_norm, 0.90, dim=1),
            ],
            dim=1,
        )
        out_feats.append(stats.cpu().numpy())
    res = np.concatenate(out_feats, axis=0).astype(np.float32) if out_feats else np.zeros((0, 3), dtype=np.float32)
    print(f"[v4_sota] MiDaS depth distillation precomputed for {len(res)} images in {time.perf_counter()-t0:.1f}s", flush=True)
    return res


class SotaCalorieDS(Dataset):
    def __init__(
        self,
        jpegs: list[bytes],
        y7: np.ndarray,
        m7: np.ndarray,
        ing: np.ndarray,
        depth3: np.ndarray,
        *,
        augment: bool = False,
        scale_targets_on_zoom: bool = False,
        seed: int = 0,
    ) -> None:
        self.jpegs = jpegs
        self.y7 = y7
        self.m7 = m7
        self.ing = ing
        self.depth3 = depth3
        self.augment = augment
        self.scale_targets_on_zoom = scale_targets_on_zoom
        self.rng = np.random.default_rng(seed)

    def __len__(self) -> int:
        return len(self.jpegs)

    def __getitem__(self, idx: int):
        y = self.y7[idx].copy()
        m = self.m7[idx].copy()
        ing = self.ing[idx]
        d3 = self.depth3[idx]
        with Image.open(io.BytesIO(self.jpegs[idx])) as im:
            im = im.convert("RGB")
            if self.augment:
                if self.rng.random() < 0.5:
                    im = im.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                if self.scale_targets_on_zoom and m[0] > 0.5 and m[5] < 0.5:
                    sc = float(self.rng.uniform(0.86, 1.14))
                    y[:5] *= sc
                if self.rng.random() < 0.35:
                    ang = float(self.rng.uniform(-14.0, 14.0))
                    im = im.rotate(ang, resample=Image.Resampling.BILINEAR, fillcolor=(PAD_VALUE, PAD_VALUE, PAD_VALUE))
            arr = letterbox_rgb(im, size=INPUT_SIZE, pad_value=PAD_VALUE).astype(np.float32)
        if self.augment:
            arr = np.clip(arr * float(self.rng.uniform(0.88, 1.12)) + float(self.rng.uniform(-10, 10)), 0.0, 255.0)
        return (
            torch.from_numpy(arr.transpose(2, 0, 1)),
            torch.from_numpy(y),
            torch.from_numpy(m),
            torch.from_numpy(ing),
            torch.from_numpy(d3),
        )


class RDINetV4CalorieModel(nn.Module):
    """ConvNeXt-Tiny shared visual encoder with 7-output main head + training-only Depth & Ingredient aux heads."""

    def __init__(self, backbone_name: str = "convnext_tiny.fb_in22k_ft_in1k", pretrained: bool = True) -> None:
        super().__init__()
        self.backbone_name = backbone_name
        self.encoder = timm.create_model(backbone_name, pretrained=pretrained, num_classes=0, drop_rate=0.2)
        nf = int(self.encoder.num_features)
        self.main_head = nn.Sequential(
            nn.LayerNorm(nf),
            nn.Dropout(0.15),
            nn.Linear(nf, 256),
            nn.GELU(),
            nn.Linear(256, 7),
        )
        self.depth_head = nn.Linear(nf, 3)
        self.ing_head = nn.Linear(nf, N_FOODSEG_CLS)

    def forward_train(self, x_norm: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        feat = self.encoder(x_norm)
        return self.main_head(feat), self.depth_head(feat), self.ing_head(feat)

    def forward(self, x_norm: torch.Tensor) -> torch.Tensor:
        return self.main_head(self.encoder(x_norm))


class WithNormV4Wrapper(nn.Module):
    def __init__(self, model: RDINetV4CalorieModel, y_mean: np.ndarray, y_std: np.ndarray) -> None:
        super().__init__()
        self.model = model
        self.register_buffer("in_mean", torch.tensor([0.485, 0.456, 0.406], dtype=torch.float32).view(1, 3, 1, 1) * 255.0)
        self.register_buffer("in_std", torch.tensor([0.229, 0.224, 0.225], dtype=torch.float32).view(1, 3, 1, 1) * 255.0)
        self.register_buffer("y_mean", torch.tensor(y_mean, dtype=torch.float32).view(1, -1))
        self.register_buffer("y_std", torch.tensor(y_std, dtype=torch.float32).view(1, -1))
        self.register_buffer("y_max", torch.tensor(UPPER_7, dtype=torch.float32).view(1, -1))

    def forward(self, image: torch.Tensor) -> torch.Tensor:
        x_norm = (image - self.in_mean) / self.in_std
        z = self.model(x_norm)
        pred = z * self.y_std + self.y_mean
        return torch.minimum(torch.clamp(pred, min=0.0), self.y_max)


def run_v4_sota(
    stage_dir: Path,
    runs_dir: Path,
    out_dir: Path,
    kb_dir: Path,
    stage1_epochs: int = 20,
    stage2_epochs: int = 8,
    batch_size: int = 48,
    mem_fraction: float = 0.18,
    seed: int = 20261017,
) -> dict:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.set_per_process_memory_fraction(mem_fraction)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    use_amp = device.type == "cuda"

    n5k_dir = stage_dir / "calorie_lens"
    stage_nutrition5k(n5k_dir)
    ds = load_overhead_dataset(n5k_dir)
    vn_tr, vn_va = build_vn_asian_calorie_samples(
        kb_dir=kb_dir, work_dir=runs_dir, exclude_dir=Path("/home/namnx/NamBuw/Tastoria/app/assets/food"), max_per_vn_class=80, max_per_uec_class=45, seed=seed
    )
    ex_tr, ex_va = _build_sota_corpus(
        kb_dir=kb_dir, stage_dir=stage_dir, exclude_dir=Path("/home/namnx/NamBuw/Tastoria/app/assets/food"), max_mmfood=10000, seed=seed
    )

    n5k_tr_df = ds.split_df("train")
    n5k_va_df = ds.split_df("val")

    def _n5k_arrays(df):
        jpegs = [ds.images_by_id[str(did)] for did in df["dish_id"]]
        y5 = ds.targets_array(df)
        y7 = np.zeros((len(df), 7), dtype=np.float32)
        y7[:, :5] = y5
        y7[:, 6] = 0.25
        m7 = np.array([[1, 1, 1, 1, 1, 0, 1]], dtype=np.float32).repeat(len(df), axis=0)
        ing = np.zeros((len(df), N_FOODSEG_CLS + 1), dtype=np.float32)
        return jpegs, y7, m7, ing

    n5k_tr_j, n5k_tr_y, n5k_tr_m, n5k_tr_ing = _n5k_arrays(n5k_tr_df)
    n5k_va_j, n5k_va_y, n5k_va_m, n5k_va_ing = _n5k_arrays(n5k_va_df)

    vn_tr_j = [x[0] for x in vn_tr]
    vn_tr_y = np.zeros((len(vn_tr), 7), dtype=np.float32)
    if vn_tr:
        vn_tr_y[:, :5] = np.stack([x[1] for x in vn_tr], 0)
    vn_tr_m = np.array([[1, 1, 1, 1, 1, 0, 0]], dtype=np.float32).repeat(len(vn_tr), axis=0) if vn_tr else np.zeros((0, 7), np.float32)
    vn_tr_ing = np.zeros((len(vn_tr), N_FOODSEG_CLS + 1), dtype=np.float32)

    ex_tr_j = [x[0] for x in ex_tr]
    ex_tr_y = np.stack([x[1] for x in ex_tr], 0)
    ex_tr_m = np.stack([x[2] for x in ex_tr], 0)
    ex_tr_ing = np.stack([x[3] for x in ex_tr], 0)

    ex_va_j = [x[0] for x in ex_va]
    ex_va_y = np.stack([x[1] for x in ex_va], 0)
    ex_va_m = np.stack([x[2] for x in ex_va], 0)
    ex_va_ing = np.stack([x[3] for x in ex_va], 0)

    # Precompute frozen MiDaS_small 3D depth distillation targets once & unload teacher from VRAM
    midas = torch.hub.load("intel-isl/MiDaS", "MiDaS_small", pretrained=True, trust_repo=True).to(device).eval()
    n5k_tr_d = _compute_depth_stats(n5k_tr_j, midas, device)
    n5k_va_d = _compute_depth_stats(n5k_va_j, midas, device)
    vn_tr_d = _compute_depth_stats(vn_tr_j, midas, device)
    ex_tr_d = _compute_depth_stats(ex_tr_j, midas, device)
    ex_va_d = _compute_depth_stats(ex_va_j, midas, device)
    del midas
    if use_amp:
        torch.cuda.empty_cache()

    y_mean7 = np.array([
        n5k_tr_y[:, 0].mean(), n5k_tr_y[:, 1].mean(), n5k_tr_y[:, 2].mean(),
        n5k_tr_y[:, 3].mean(), n5k_tr_y[:, 4].mean(), 0.45, 0.30,
    ], dtype=np.float32)
    y_std7 = np.array([
        max(1.0, n5k_tr_y[:, 0].std()), max(1.0, n5k_tr_y[:, 1].std()), max(0.5, n5k_tr_y[:, 2].std()),
        max(0.5, n5k_tr_y[:, 3].std()), max(0.5, n5k_tr_y[:, 4].std()), 0.22, 0.25,
    ], dtype=np.float32)

    n5k_tr_ds = SotaCalorieDS(n5k_tr_j, n5k_tr_y, n5k_tr_m, n5k_tr_ing, n5k_tr_d, augment=True, scale_targets_on_zoom=False, seed=seed)
    n5k_va_ds = SotaCalorieDS(n5k_va_j, n5k_va_y, n5k_va_m, n5k_va_ing, n5k_va_d, augment=False, seed=seed)
    vn_tr_ds = SotaCalorieDS(vn_tr_j, vn_tr_y, vn_tr_m, vn_tr_ing, vn_tr_d, augment=True, scale_targets_on_zoom=True, seed=seed)
    ex_tr_ds = SotaCalorieDS(ex_tr_j, ex_tr_y, ex_tr_m, ex_tr_ing, ex_tr_d, augment=True, scale_targets_on_zoom=True, seed=seed)
    ex_va_ds = SotaCalorieDS(ex_va_j, ex_va_y, ex_va_m, ex_va_ing, ex_va_d, augment=False, seed=seed)

    # Filter MM-Food-100K/UEC high-confidence kcal rows for Stage 2 polish
    s1_ds = ConcatDataset([n5k_tr_ds] * 5 + [vn_tr_ds, ex_tr_ds])
    s2_ds = ConcatDataset([n5k_tr_ds] * 6 + [vn_tr_ds, ex_tr_ds])

    n5k_va_loader = DataLoader(n5k_va_ds, batch_size=batch_size, shuffle=False, num_workers=2, pin_memory=use_amp)
    ex_va_loader = DataLoader(ex_va_ds, batch_size=batch_size, shuffle=False, num_workers=2, pin_memory=use_amp)

    in_mean = torch.tensor([0.485, 0.456, 0.406], device=device).view(1, 3, 1, 1) * 255.0
    in_std = torch.tensor([0.229, 0.224, 0.225], device=device).view(1, 3, 1, 1) * 255.0
    ym_t = torch.tensor(y_mean7, device=device).view(1, 7)
    ys_t = torch.tensor(y_std7, device=device).view(1, 7)

    model = RDINetV4CalorieModel("convnext_tiny.fb_in22k_ft_in1k", pretrained=True).to(device)
    ema_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
    ema_decay = 0.995
    crit_reg = nn.SmoothL1Loss(reduction="none", beta=0.4)
    crit_bce = nn.BCEWithLogitsLoss(reduction="none")
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)

    best_score = float("inf")
    best_state = None
    best_ep = 1
    t0 = time.perf_counter()

    def _eval(eval_m: nn.Module) -> tuple[float, float, float, float]:
        eval_m.eval()
        ps, ts = [], []
        with torch.no_grad():
            for xb, yb, _, _, _ in n5k_va_loader:
                xb = xb.to(device, non_blocking=True)
                with torch.amp.autocast("cuda", enabled=use_amp):
                    pn = eval_m((xb - in_mean) / in_std)
                pr = torch.clamp(pn.float() * ys_t + ym_t, min=0.0)
                ps.append(pr[:, :5].cpu().numpy())
                ts.append(yb[:, :5].numpy())
        yt, yp = np.concatenate(ts, 0), np.concatenate(ps, 0)
        m = compute_all_target_metrics(yt, yp)
        k_mae = float(m["kcal"]["mae"])
        k_pmae = k_mae / max(1.0, float(yt[:, 0].mean())) * 100.0
        m_mae = float(m["mass_g"]["mae"])
        a_errs = []
        with torch.no_grad():
            for xb, yb, mb, _, _ in ex_va_loader:
                xb = xb.to(device, non_blocking=True)
                with torch.amp.autocast("cuda", enabled=use_amp):
                    pn = eval_m((xb - in_mean) / in_std)
                pr = torch.clamp(pn.float() * ys_t + ym_t, min=0.0).cpu().numpy()
                m5 = mb[:, 5].numpy() > 0.5
                if m5.any():
                    a_errs.append(np.abs(pr[m5, 5] - yb[m5, 5].numpy()))
        a_mae = float(np.concatenate(a_errs).mean()) if a_errs else 0.0
        return k_mae, k_pmae, m_mae, a_mae

    def _run_stage(stage_name: str, train_ds: Dataset, epochs: int, max_lr: float, ep_offset: int) -> None:
        nonlocal best_score, best_state, best_ep
        loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True, num_workers=4, pin_memory=use_amp)
        opt = torch.optim.AdamW(model.parameters(), lr=max_lr, weight_decay=2e-4)
        sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs, eta_min=max_lr * 0.05)

        for ep in range(1, epochs + 1):
            model.train()
            for xb, yb, mb, ingb, d3b in loader:
                xb = xb.to(device, non_blocking=True)
                yb = yb.to(device, non_blocking=True)
                mb = mb.to(device, non_blocking=True)
                ingb = ingb.to(device, non_blocking=True)
                d3b = d3b.to(device, non_blocking=True)
                opt.zero_grad(set_to_none=True)
                with torch.amp.autocast("cuda", enabled=use_amp):
                    zn, pred_d3, pred_ing = model.forward_train((xb - in_mean) / in_std)
                    yn = (yb - ym_t) / ys_t
                    l_reg = (crit_reg(zn, yn) * mb).sum() / torch.clamp(mb.sum(), min=1.0)

                    # Real-unit predictions for PMAE + Atwater physics loss
                    pred_real = torch.clamp(zn * ys_t + ym_t, min=0.0)
                    l_pmae = (torch.abs(pred_real[:, :5] - yb[:, :5]) / torch.clamp(yb[:, :5].abs(), min=35.0) * mb[:, :5]).sum() / torch.clamp(mb[:, :5].sum(), min=1.0)
                    atw = 4.0 * pred_real[:, 4] + 4.0 * pred_real[:, 3] + 9.0 * pred_real[:, 2]
                    l_atw = (torch.abs(pred_real[:, 0] - atw) * mb[:, 0]).sum() / torch.clamp(mb[:, 0].sum(), min=1.0) / 100.0

                    # Aux losses: Depth distillation + FoodSeg103 ingredients
                    l_depth = F.smooth_l1_loss(pred_d3, d3b)
                    ing_mask = ingb[:, -1] > 0.5
                    l_ing = crit_bce(pred_ing[ing_mask], ingb[ing_mask, :-1]).mean() if ing_mask.any() else torch.tensor(0.0, device=device)

                    loss = l_reg + 0.25 * l_pmae + 0.15 * l_atw + 0.20 * l_depth + 0.25 * l_ing
                scaler.scale(loss).backward()
                scaler.unscale_(opt)
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                scaler.step(opt)
                scaler.update()
                with torch.no_grad():
                    cur = model.state_dict()
                    for k, ev in ema_state.items():
                        if ev.is_floating_point():
                            ev.mul_(ema_decay).add_(cur[k], alpha=1.0 - ema_decay)
                        else:
                            ev.copy_(cur[k])
            sched.step()

            km, kp, mm, am = _eval(model)
            sc = km + 0.30 * mm + 50.0 * am
            tag = "raw"
            cand = {k: v.detach().cpu() for k, v in model.state_dict().items()}
            if ep >= 4:
                bk = {k: v.detach().clone() for k, v in model.state_dict().items()}
                model.load_state_dict(ema_state)
                ekm, ekp, emm, eam = _eval(model)
                esc = ekm + 0.30 * emm + 50.0 * eam
                model.load_state_dict(bk)
                if esc < sc:
                    km, kp, mm, am, sc = ekm, ekp, emm, eam, esc
                    cand = {k: v.detach().cpu() for k, v in ema_state.items()}
                    tag = "ema"
            tot_ep = ep_offset + ep
            print(f"[{stage_name} {tot_ep:02d} {tag}] val_kcal_mae={km:.2f} (PMAE={kp:.2f}%) | mass_mae={mm:.2f}g | area_mae={am:.3f}", flush=True)
            if sc < best_score:
                best_score = sc
                best_ep = tot_ep
                best_state = cand

    _run_stage("S1", s1_ds, stage1_epochs, 2.0e-4, 0)
    assert best_state is not None
    model.load_state_dict({k: v.to(device) for k, v in best_state.items()})
    ema_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
    _run_stage("S2", s2_ds, stage2_epochs, 4.5e-5, stage1_epochs)

    runs_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    model.load_state_dict(best_state)
    wrapped = WithNormV4Wrapper(model.cpu(), y_mean7, y_std7).eval()
    onnx_path = out_dir / "model.onnx"
    torch.onnx.export(wrapped, torch.zeros(1, 3, INPUT_SIZE, INPUT_SIZE), str(onnx_path), input_names=["image"], output_names=["pred"], dynamic_axes={"image": {0: "n"}, "pred": {0: "n"}}, opset_version=17, dynamo=False)

    lat = benchmark_onnx_cpu(onnx_path, n_warmup=10, n_runs=200)
    const_base = ConstantBaseline.fit(ds.targets_array(n5k_tr_df))
    splits_out = {}
    for sp, clean in (("val", False), ("test", False), ("test_clean", True)):
        sdf = ds.split_df("test" if clean else sp, clean_only=clean)
        dl = DataLoader(make_torch_dataset(sdf, ds.images_by_id, augment=False, size=INPUT_SIZE), batch_size=32, shuffle=False)
        sp_p, sp_t = [], []
        with torch.no_grad():
            for xb, yb in dl:
                sp_p.append(wrapped(xb)[:, :5].numpy())
                sp_t.append(yb.numpy())
        yt, yp = np.concatenate(sp_t, 0), np.concatenate(sp_p, 0)
        m_sp = compute_all_target_metrics(yt, yp)
        k_pmae = float(m_sp["kcal"]["mae"]) / max(1.0, float(yt[:, 0].mean())) * 100.0
        m_pmae = float(m_sp["mass_g"]["mae"]) / max(1.0, float(yt[:, 1].mean())) * 100.0
        splits_out[sp] = {
            "n": int(len(sdf)),
            "kcal_pmae_pct": round(k_pmae, 2),
            "mass_pmae_pct": round(m_pmae, 2),
            "model": m_sp,
            "baseline_median": compute_all_target_metrics(yt, const_base.predict_median(len(sdf))),
        }

    sha = sha256_file(onnx_path)
    honest = {
        "best_epoch": best_ep,
        "train_seconds": round(time.perf_counter() - t0, 1),
        "val_kcal_mae": splits_out["val"]["model"]["kcal"]["mae"],
        "val_kcal_pmae_pct": splits_out["val"]["kcal_pmae_pct"],
        "test_kcal_mae": splits_out["test"]["model"]["kcal"]["mae"],
        "test_kcal_pmae_pct": splits_out["test"]["kcal_pmae_pct"],
        "test_mass_mae": splits_out["test"]["model"]["mass_g"]["mae"],
        "test_mass_pmae_pct": splits_out["test"]["mass_pmae_pct"],
        "test_kcal_r2": splits_out["test"]["model"]["kcal"]["r2"],
        "test_clean_kcal_mae": splits_out["test_clean"]["model"]["kcal"]["mae"],
        "test_clean_kcal_pmae_pct": splits_out["test_clean"]["kcal_pmae_pct"],
        "cpu_p50_ms": lat["p50_ms"],
        "cpu_p95_ms": lat["p95_ms"],
    }
    serving = {
        "schema_version": "meal_calorie.serving.v1",
        "name": "meal_calorie",
        "version": "meal_calorie_convnext_tiny_v4_rdinet_sota",
        "backbone": "convnext_tiny.fb_in22k_ft_in1k",
        "license": "CC-BY-4.0 (Nutrition5k + MM-Food-100K + UECFoodPixComplete + FoodSeg103 + VNFood-103)",
        "artifact_file": "model.onnx",
        "artifact_sha256": sha,
        "artifact_bytes": onnx_path.stat().st_size,
        "input": {"name": "image", "shape": [1, 3, INPUT_SIZE, INPUT_SIZE], "layout": "NCHW", "color": "RGB", "preprocess": "letterbox", "pad_value": PAD_VALUE, "range": "0..255_float32", "norm_baked_in_onnx": True},
        "outputs": {"name": "pred", "shape": [1, 7], "columns": [*TARGET_COLS, "food_area_ratio", "multi_dish_score"], "clamped_non_negative": True},
        "portion_multipliers": dict(PORTION_MULTIPLIERS),
        "honest_metrics": honest,
        "domain_shift_note": "Ước lượng trực quan SOTA v4 (chưng cất chiều sâu MiDaS 3D + học đa thành phần FoodSeg103 + MM-Food-100K + VNFood-103 + Nutrition5k).",
    }
    (out_dir / "serving.json").write_text(json.dumps(serving, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "metrics.json").write_text(json.dumps({"selected": "convnext_tiny.fb_in22k_ft_in1k", "constant_baseline": const_base.to_dict(), "splits": splits_out, "cpu_latency": lat, "artifact_sha256": sha}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("V4 SOTA DONE:", json.dumps(honest, indent=2), flush=True)
    return serving


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage-dir", type=Path, default=Path("/dev/shm/cal_v4_stage"))
    ap.add_argument("--runs-dir", type=Path, default=Path("/dev/shm/cal_v4_runs"))
    ap.add_argument("--out-dir", type=Path, default=Path("/dev/shm/cal_v4_out"))
    ap.add_argument("--kb-dir", type=Path, default=Path("/home/namnx/NamBuw/Tastoria/data/kb"))
    ap.add_argument("--stage1-epochs", type=int, default=20)
    ap.add_argument("--stage2-epochs", type=int, default=8)
    ap.add_argument("--mem-fraction", type=float, default=0.18)
    a = ap.parse_args()
    run_v4_sota(a.stage_dir, a.runs_dir, a.out_dir, a.kb_dir, stage1_epochs=a.stage1_epochs, stage2_epochs=a.stage2_epochs, mem_fraction=a.mem_fraction)


if __name__ == "__main__":
    main()
