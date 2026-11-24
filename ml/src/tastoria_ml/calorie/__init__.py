"""Decoupled Meal / Dish Calorie & Macro Nutrition Package (F10).

Completely isolated from ``tastoria_ml.cv`` (the 37-class raw fridge detector).
Combines Tastoria's authoritative Vietnamese KB lookup (with ``nho``/``vua``/``lon``
portion scaling) and a lightweight Nutrition5k (CC BY 4.0) ONNX visual regressor.
"""

from __future__ import annotations

TARGET_COLS: tuple[str, ...] = ("kcal", "mass_g", "fat_g", "carb_g", "protein_g")
PHYSICAL_UPPER_BOUNDS: tuple[float, ...] = (3500.0, 3000.0, 250.0, 400.0, 250.0)
PORTION_MULTIPLIERS: dict[str, float] = {"nho": 0.75, "vua": 1.0, "lon": 1.35}
INPUT_SIZE = 224
PAD_VALUE = 128

__all__ = [
    "INPUT_SIZE",
    "PAD_VALUE",
    "PHYSICAL_UPPER_BOUNDS",
    "PORTION_MULTIPLIERS",
    "TARGET_COLS",
]
