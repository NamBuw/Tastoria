"""Baselines for Meal Calorie Estimation (F10):

1. ``ConstantBaseline``: Train-median / train-mean predictor on Nutrition5k 5 targets.
2. ``KBDishLookup``: Authoritative Tastoria Vietnamese KB dish lookup
   (``data/processed/kb/recipe_nutrition.csv`` + ``data/kb/dish_list.yaml`` +
   ``data/kb/validation/nin_dishes.yaml`` calibrated ``p80_abs_rel_error`` half-width)
   with ``nho``/``vua``/``lon`` portion scaling (``0.75 / 1.0 / 1.35``).
"""

from __future__ import annotations

import csv
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml

from tastoria_ml.calorie import PORTION_MULTIPLIERS, TARGET_COLS

DEFAULT_HALF_WIDTH = 0.25  # conservative uncalibrated fallback when NIN summary is unavailable/stale


def _fold_vi(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text.strip().casefold())
    stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
    return stripped.replace("đ", "d")


@dataclass(frozen=True)
class ConstantBaseline:
    median_vec: np.ndarray
    mean_vec: np.ndarray

    @classmethod
    def fit(cls, y_train: np.ndarray) -> ConstantBaseline:
        y = np.asarray(y_train, dtype=np.float64)
        return cls(
            median_vec=np.median(y, axis=0).astype(np.float32),
            mean_vec=np.mean(y, axis=0).astype(np.float32),
        )

    def predict_median(self, n: int) -> np.ndarray:
        return np.tile(self.median_vec, (n, 1))

    def predict_mean(self, n: int) -> np.ndarray:
        return np.tile(self.mean_vec, (n, 1))

    def to_dict(self) -> dict[str, dict[str, float]]:
        return {
            "train_median": {k: round(float(v), 3) for k, v in zip(TARGET_COLS, self.median_vec, strict=True)},
            "train_mean": {k: round(float(v), 3) for k, v in zip(TARGET_COLS, self.mean_vec, strict=True)},
        }


@dataclass(frozen=True)
class KBDishEntry:
    slug: str
    name_vi: str
    slot: str
    servings: int
    kcal_per_serving: float
    protein_g: float
    lipid_g: float
    glucid_g: float
    fiber_g: float
    sodium_mg: float | None
    data_version: str


@dataclass(frozen=True)
class KBDishEstimate:
    slug: str
    name_vi: str
    slot: str
    portion: str
    multiplier: float
    estimated_kcal: float
    kcal_low: float
    kcal_high: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float
    half_width_rel: float
    calibrated: bool
    data_version: str


class KBDishLookup:
    """Zero-latency Vietnamese dish calorie & macro lookup with NIN-calibrated uncertainty."""

    def __init__(
        self,
        entries: dict[str, KBDishEntry],
        *,
        half_width_rel: float,
        calibrated: bool,
        data_version: str,
    ) -> None:
        self.by_slug = entries
        self.half_width_rel = half_width_rel
        self.calibrated = calibrated
        self.data_version = data_version
        self._by_folded_name = {_fold_vi(e.name_vi): e for e in entries.values()}

    @classmethod
    def from_repo(cls, repo_root: Path) -> KBDishLookup:
        return cls.from_dirs(
            kb_dir=Path(repo_root) / "data" / "kb",
            processed_kb_dir=Path(repo_root) / "data" / "processed" / "kb",
        )

    @classmethod
    def from_dirs(cls, kb_dir: Path, processed_kb_dir: Path) -> KBDishLookup:
        kb_dir = Path(kb_dir)
        processed_kb_dir = Path(processed_kb_dir)

        dish_list = yaml.safe_load((kb_dir / "dish_list.yaml").read_text(encoding="utf-8"))["dishes"]
        name_by_slug = {d["slug"]: d["name_vi"] for d in dish_list}

        entries: dict[str, KBDishEntry] = {}
        versions: set[str] = set()
        csv_path = processed_kb_dir / "recipe_nutrition.csv"
        with csv_path.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                slug = row["slug"]
                versions.add(row["data_version"])
                entries[slug] = KBDishEntry(
                    slug=slug,
                    name_vi=name_by_slug.get(slug, slug),
                    slot=row["slot"],
                    servings=int(row["servings"]),
                    kcal_per_serving=float(row["kcal_per_serving"]),
                    protein_g=float(row["protein_g"]),
                    lipid_g=float(row["lipid_g"]),
                    glucid_g=float(row["glucid_g"]),
                    fiber_g=float(row["fiber_g"]),
                    sodium_mg=float(row["sodium_mg"]) if row.get("sodium_mg") else None,
                    data_version=row["data_version"],
                )

        data_version = next(iter(versions)) if len(versions) == 1 else "mixed"
        half_width = DEFAULT_HALF_WIDTH
        calibrated = False
        nin_path = kb_dir / "validation" / "nin_dishes.yaml"
        if nin_path.exists():
            nin_doc = yaml.safe_load(nin_path.read_text(encoding="utf-8"))
            summary = nin_doc.get("summary") or {}
            if (
                isinstance(summary.get("n"), int)
                and summary["n"] >= 30
                and summary.get("data_version") == data_version
                and isinstance(summary.get("p80_abs_rel_error"), int | float)
            ):
                half_width = float(summary["p80_abs_rel_error"])
                calibrated = True

        return cls(entries, half_width_rel=half_width, calibrated=calibrated, data_version=data_version)

    def lookup(self, *, slug: str | None = None, dish_name: str | None = None) -> KBDishEntry | None:
        if slug and slug.strip():
            norm_slug = slug.strip().lower()
            return self.by_slug.get(norm_slug)
        if dish_name:
            folded = _fold_vi(dish_name)
            if not folded:
                return None
            if folded in self._by_folded_name:
                return self._by_folded_name[folded]
            # Substring fallback requires >= 3 chars to avoid 1-2 char accidental matches (e.g. "a" -> "Gà luộc")
            if len(folded) >= 3:
                matches = [e for k, e in self._by_folded_name.items() if folded in k]
                if matches:
                    return min(matches, key=lambda e: len(e.name_vi))
        return None

    def estimate(
        self,
        *,
        slug: str | None = None,
        dish_name: str | None = None,
        portion: str = "vua",
    ) -> KBDishEstimate | None:
        if portion not in PORTION_MULTIPLIERS:
            raise ValueError(f"Unsupported portion {portion!r}; expected one of {tuple(PORTION_MULTIPLIERS)}")
        entry = self.lookup(slug=slug, dish_name=dish_name)
        if entry is None:
            return None
        mult = PORTION_MULTIPLIERS[portion]
        kcal = round(entry.kcal_per_serving * mult, 1)
        return KBDishEstimate(
            slug=entry.slug,
            name_vi=entry.name_vi,
            slot=entry.slot,
            portion=portion,
            multiplier=mult,
            estimated_kcal=kcal,
            kcal_low=round(max(0.0, kcal * (1.0 - self.half_width_rel)), 1),
            kcal_high=round(kcal * (1.0 + self.half_width_rel), 1),
            protein_g=round(entry.protein_g * mult, 1),
            carbs_g=round(entry.glucid_g * mult, 1),
            fat_g=round(entry.lipid_g * mult, 1),
            fiber_g=round(entry.fiber_g * mult, 1),
            half_width_rel=round(self.half_width_rel, 4),
            calibrated=self.calibrated,
            data_version=self.data_version,
        )
