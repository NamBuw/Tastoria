"""Nutrition5k (``shalev396/calorie-lens-data``, CC BY 4.0) dataset loader & split auditor.

Enforces strict plate-``group`` split isolation, maps ``overhead/*.parquet`` images
to ``dishes.parquet`` targets ``[kcal, mass_g, fat_g, carb_g, protein_g]``, and
explicitly tracks the ``kcal == 0`` / ``n_items == 0`` empty-plate anomalies.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from PIL import Image

from tastoria_ml.calorie import INPUT_SIZE, PAD_VALUE, TARGET_COLS

log = logging.getLogger("tastoria_ml.calorie.dataset")

PARQUET_TO_DATASET_COL: dict[str, str] = {
    "kcal": "kcal",
    "mass": "mass_g",
    "fat": "fat_g",
    "carb": "carb_g",
    "protein": "protein_g",
}


@dataclass(frozen=True)
class AnomalyReport:
    empty_plate_dish_ids: tuple[str, ...]
    counts_by_split: dict[str, int]


@dataclass(frozen=True)
class SplitIntegrityReport:
    counts: dict[str, int]
    test_clean_count: int
    test_clean_group_overlap_train: int
    test_clean_group_overlap_val: int
    train_val_group_overlap: int
    anomalies: AnomalyReport


@dataclass
class OverheadDataset:
    meta: pd.DataFrame
    images_by_id: dict[str, bytes]
    integrity: SplitIntegrityReport

    def split_df(self, split: str, *, clean_only: bool = False, exclude_empty: bool = False) -> pd.DataFrame:
        df = self.meta[self.meta["split"] == split]
        if clean_only and split == "test":
            df = df[df["test_clean"] == True]  # noqa: E712
        if exclude_empty:
            df = df[(df["kcal"] > 0.0) & (df["n_items"] > 0)]
        return df.reset_index(drop=True)

    def targets_array(self, df: pd.DataFrame) -> np.ndarray:
        return df[list(TARGET_COLS)].to_numpy(dtype=np.float32)


def letterbox_rgb(img: Image.Image, size: int = INPUT_SIZE, pad_value: int = PAD_VALUE) -> np.ndarray:
    """Resize preserving aspect ratio and pad to ``(size, size, 3)`` uint8 RGB."""
    rgb = img.convert("RGB")
    rgb.thumbnail((size, size), Image.Resampling.BILINEAR)
    canvas = np.full((size, size, 3), pad_value, dtype=np.uint8)
    w, h = rgb.size
    px, py = (size - w) // 2, (size - h) // 2
    canvas[py : py + h, px : px + w] = np.asarray(rgb, dtype=np.uint8)
    return canvas


def decode_jpeg_letterbox(raw_bytes: bytes, size: int = INPUT_SIZE, pad_value: int = PAD_VALUE) -> np.ndarray:
    with Image.open(io.BytesIO(raw_bytes)) as im:
        return letterbox_rgb(im, size=size, pad_value=pad_value)


def check_split_integrity(df: pd.DataFrame) -> SplitIntegrityReport:
    """Verify zero plate-group leakage for ``test_clean`` against train/val and log empty-plate anomalies."""
    train_groups = set(df.loc[df["split"] == "train", "group"].dropna().astype(str))
    val_groups = set(df.loc[df["split"] == "val", "group"].dropna().astype(str))
    clean_groups = set(df.loc[(df["split"] == "test") & (df["test_clean"] == True), "group"].dropna().astype(str))  # noqa: E712

    overlap_train = len(clean_groups & train_groups)
    overlap_val = len(clean_groups & val_groups)
    if overlap_train > 0 or overlap_val > 0:
        raise ValueError(
            f"Split leakage detected in test_clean: overlap_train={overlap_train}, overlap_val={overlap_val}"
        )

    empty = df[(df["kcal"] == 0) | (df["n_items"] == 0)]
    empty_ids = tuple(sorted(empty["dish_id"].astype(str).tolist()))
    empty_by_split = {str(k): int(v) for k, v in empty["split"].value_counts().items()}

    counts = {str(k): int(v) for k, v in df["split"].value_counts().items()}
    clean_n = int(((df["split"] == "test") & (df["test_clean"] == True)).sum())  # noqa: E712
    return SplitIntegrityReport(
        counts=counts,
        test_clean_count=clean_n,
        test_clean_group_overlap_train=overlap_train,
        test_clean_group_overlap_val=overlap_val,
        train_val_group_overlap=len(train_groups & val_groups),
        anomalies=AnomalyReport(empty_plate_dish_ids=empty_ids, counts_by_split=empty_by_split),
    )


def load_overhead_dataset(stage_dir: Path) -> OverheadDataset:
    """Load staged ``shalev396/calorie-lens-data`` overhead split from ``stage_dir``."""
    stage_dir = Path(stage_dir)
    dishes_path = stage_dir / "dishes.parquet"
    overhead_dir = stage_dir / "overhead"
    if not dishes_path.exists():
        raise FileNotFoundError(f"Missing dishes.parquet in {stage_dir}")
    parquet_files = sorted(overhead_dir.glob("*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(f"Missing overhead/*.parquet in {stage_dir}")

    dishes = pd.read_parquet(dishes_path)
    dishes = dishes[dishes["has_overhead"] == True].copy()  # noqa: E712
    dishes = dishes.rename(columns={"mass": "mass_g", "fat": "fat_g", "carb": "carb_g", "protein": "protein_g"})

    images_by_id: dict[str, bytes] = {}
    for pf in parquet_files:
        part = pd.read_parquet(pf, columns=["dish_id", "image"])
        for dish_id, img_obj in zip(part["dish_id"], part["image"], strict=True):
            raw = img_obj["bytes"] if isinstance(img_obj, dict) else bytes(img_obj)
            images_by_id[str(dish_id)] = raw

    missing_imgs = set(dishes["dish_id"].astype(str)) - set(images_by_id)
    if missing_imgs:
        raise ValueError(f"Missing overhead images for {len(missing_imgs)} dishes (e.g. {sorted(missing_imgs)[:3]})")

    dishes = dishes.sort_values(["split", "dish_id"]).reset_index(drop=True)
    integrity = check_split_integrity(dishes)
    log.info(
        "Loaded Nutrition5k overhead: counts=%s test_clean=%d empty_plates=%s",
        integrity.counts,
        integrity.test_clean_count,
        integrity.anomalies.empty_plate_dish_ids,
    )
    return OverheadDataset(meta=dishes, images_by_id=images_by_id, integrity=integrity)


def make_torch_dataset(
    df: pd.DataFrame,
    images_by_id: dict[str, bytes],
    *,
    augment: bool = False,
    size: int = INPUT_SIZE,
    seed: int = 20261017,
) -> Any:
    """Build a PyTorch Dataset returning ``(uint8_float32_CHW, targets_5)``. Lazy-imports torch."""
    import torch
    from torch.utils.data import Dataset

    class _OverheadTorchDS(Dataset):
        def __init__(self) -> None:
            self.dish_ids = df["dish_id"].astype(str).tolist()
            self.targets = df[list(TARGET_COLS)].to_numpy(dtype=np.float32)
            self.augment = augment
            self.rng = np.random.default_rng(seed)

        def __len__(self) -> int:
            return len(self.dish_ids)

        def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
            raw = images_by_id[self.dish_ids[idx]]
            with Image.open(io.BytesIO(raw)) as im:
                if self.augment:
                    if self.rng.random() < 0.5:
                        im = im.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                    if self.rng.random() < 0.5:
                        im = im.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
                    if self.rng.random() < 0.5:
                        angle = float(self.rng.uniform(-15.0, 15.0))
                        im = im.rotate(angle, resample=Image.Resampling.BILINEAR, fillcolor=(PAD_VALUE, PAD_VALUE, PAD_VALUE))
                arr = letterbox_rgb(im, size=size, pad_value=PAD_VALUE)
            if self.augment:
                # Mild brightness/contrast jitter preserving plate scale
                alpha = float(self.rng.uniform(0.90, 1.10))
                beta = float(self.rng.uniform(-10.0, 10.0))
                arr_f = np.clip(arr.astype(np.float32) * alpha + beta, 0.0, 255.0)
            else:
                arr_f = arr.astype(np.float32)
            chw = torch.from_numpy(arr_f.transpose(2, 0, 1))
            y = torch.from_numpy(self.targets[idx].copy())
            return chw, y

    return _OverheadTorchDS()
