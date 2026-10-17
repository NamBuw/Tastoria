"""BR-NUT-05 fallback engine (used when tastoria_ml is not installed) and the bundle loader on data/kb."""

from __future__ import annotations

import pytest
from conftest import KB_DIR, PROCESSED_DIR

from tastoria.modules.catalog.bundle import CompRow, load_bundle
from tastoria.modules.catalog.nutrition import compute, compute_fallback, per_serving


def _row(kcal: float, refuse: float | None = None, source: str = "fct2007", **more: float) -> CompRow:
    return CompRow(source, "1", "x", None, refuse, {"energy_kcal": kcal, **more})  # type: ignore[arg-type]


def test_edible_portion_from_refuse_fr_25_12() -> None:
    # 1 serving of 200 g with refuse 25 % and 40 kcal/100 g edible → 200 × 0.75 × 0.40 = 60 kcal
    got = per_serving([("a", 200)], lambda n: _row(40, 25), servings=1)
    assert got["energy_kcal"] == pytest.approx(60, abs=0.01)


def test_usda_rows_are_already_edible_and_values_split_by_servings() -> None:
    got = per_serving([("a", 100), ("b", 100)], lambda n: _row(50, 30, "usda_sr_legacy", protein_g=2), servings=4)
    assert got == {"energy_kcal": 25.0, "protein_g": 1.0}


def test_deep_fry_counts_only_absorbed_oil() -> None:
    comp = {"dầu ăn": _row(900, lipid_g=100), "thịt": _row(200, lipid_g=10)}
    pan = per_serving([("thịt", 400), ("dầu ăn", 100)], comp.get, servings=1)
    fried = per_serving([("thịt", 400), ("dầu ăn", 100)], comp.get, servings=1, deep_fried=True)
    assert pan["lipid_g"] == pytest.approx(140)
    assert fried["lipid_g"] == pytest.approx(40 + 20)  # 5 g per 100 g of food × 400 g = 20 g of the 100 g oil


def test_ingredient_without_composition_is_skipped() -> None:
    assert per_serving([("x", 100)], lambda n: None, servings=1) == {}


def test_fallback_matches_ml_engine_on_recipes_without_overrides() -> None:
    b = load_bundle(KB_DIR, PROCESSED_DIR)
    assert b.ok, b.errors
    fb = compute_fallback(b)
    assert fb.engine == "catalog" and fb.data_version.startswith("catalog-nut-r1+")
    assert 150 < fb.rice_bowl_kcal < 200
    ml = compute(b, PROCESSED_DIR)
    if ml.engine != "tastoria_ml":
        pytest.skip("tastoria_ml not installed")
    close = [s for s in b.recipes if abs(ml.per_serving[s]["energy_kcal"] - fb.per_serving[s]["energy_kcal"]) <= 0.2]
    assert len(close) >= 160  # the rest use the ML engine's documented refuse / moisture overrides
    assert ml.rice_bowl_kcal == pytest.approx(fb.rice_bowl_kcal, abs=0.1)
