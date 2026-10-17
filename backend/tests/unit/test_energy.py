"""BR-NUT-01..04 with hand-computed values (UC09, UC10, UC11 acceptance criteria)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from tastoria.modules.profile.energy import (
    AgeBelowMinimum,
    age_band,
    bmr_fao_who_unu_1985,
    bmr_mifflin_st_jeor,
    daily_target,
    meal_energy,
    pal_for,
    round_half_up,
    suggest,
)


@pytest.mark.parametrize(
    ("age", "band"),
    [(18, 0), (29, 0), (30, 1), (59, 1), (60, 2), (95, 2)],
)
def test_age_bands_are_half_open(age: int, band: int) -> None:
    assert age_band(age) == band


@pytest.mark.parametrize("age", [17, 0, -3])
def test_under_18_is_refused(age: int) -> None:
    with pytest.raises(AgeBelowMinimum):
        age_band(age)


@pytest.mark.parametrize(
    ("sex", "age", "weight", "expected"),
    [
        ("male", 30, 65, "1633"),  # 11.6 × 65 + 879 (FR-11-02)
        ("male", 29, 65, "1673.5"),  # 15.3 × 65 + 679
        ("male", 60, 80, "1567"),  # 13.5 × 80 + 487
        ("female", 25, 52, "1260.4"),  # 14.7 × 52 + 496
        ("female", 45, 70, "1438"),  # 8.7 × 70 + 829
        ("female", 60, 55, "1173.5"),  # 10.5 × 55 + 596
    ],
)
def test_bmr_fao_who_unu_1985(sex: str, age: int, weight: float, expected: str) -> None:
    assert bmr_fao_who_unu_1985(sex, age, weight) == Decimal(expected)


def test_bmr_mifflin_comparison_only() -> None:
    # 9.99 × 65 + 6.25 × 170 − 4.92 × 30 + 5 = 1569.25 (FR-11-16)
    assert bmr_mifflin_st_jeor("male", 30, 65, 170) == Decimal("1569.25")
    # female: 9.99 × 52 + 6.25 × 158 − 4.92 × 25 − 161 = 519.48 + 987.5 − 123 − 161 = 1222.98
    assert bmr_mifflin_st_jeor("female", 25, 52, 158) == Decimal("1222.98")


def test_pal_values() -> None:
    assert (pal_for("light"), pal_for("moderate"), pal_for("heavy")) == (
        Decimal("1.50"),
        Decimal("1.75"),
        Decimal("2.00"),
    )


def test_round_half_up_not_bankers() -> None:
    assert round_half_up(Decimal("1846.5")) == 1847
    assert round_half_up(Decimal("2857.75")) == 2858
    assert round_half_up(Decimal("661.85")) == 662
    assert round_half_up(Decimal("567.3")) == 567


@pytest.mark.parametrize(
    ("tee", "sex", "goal", "expected", "floored"),
    [
        ("2857.75", "male", "maintain", 2858, False),  # FR-11-04
        ("2857.75", "male", "lose", 2358, False),  # 2357.75 → 2358 (FR-11-05)
        ("1600", "female", "lose", 1200, True),  # 1100 < 1200 (FR-11-05)
        ("1999", "male", "lose", 1500, True),  # 1499 < 1500
        ("2000", "male", "lose", 1500, False),  # exactly the floor is not "applied"
        ("1700", "female", "lose", 1200, False),
    ],
)
def test_daily_target(tee: str, sex: str, goal: str, expected: int, floored: bool) -> None:
    assert daily_target(Decimal(tee), sex, goal) == (expected, floored)


def test_meal_energy_shares() -> None:
    assert (meal_energy(2000, "lunch"), meal_energy(2000, "dinner")) == (700, 600)  # FR-11-08
    assert (meal_energy(1891, "lunch"), meal_energy(1891, "dinner")) == (662, 567)  # 661.85, 567.3


def test_suggest_female_25_52kg_light_maintain() -> None:
    # FR-09-07: round((14.7 × 52 + 496) × 1.50) = round(1890.6) = 1891; lunch 662, dinner 567
    r = suggest(sex="female", age=25, weight_kg=52, height_cm=None, activity_level="light", goal="maintain")
    assert (r.bmr_kcal, r.pal, r.tee_kcal) == (Decimal("1260.4"), Decimal("1.50"), Decimal("1890.6"))
    assert (r.suggested_kcal, r.floor_applied, r.e_lunch_kcal, r.e_dinner_kcal) == (1891, False, 662, 567)


def test_suggest_60kg_gives_2067() -> None:
    # FR-10-04: (14.7 × 60 + 496) × 1.50 = 2067
    r = suggest(sex="female", age=25, weight_kg=60, height_cm=None, activity_level="light", goal="maintain")
    assert r.suggested_kcal == 2067


def test_suggest_lose_with_floor() -> None:
    # female 70 y, 45 kg, light: (10.5 × 45 + 596) × 1.5 = 1602.75; − 500 = 1102.75 < 1200 → 1200
    r = suggest(sex="female", age=70, weight_kg=45, height_cm=None, activity_level="light", goal="lose")
    assert (r.tee_kcal, r.suggested_kcal, r.floor_applied) == (Decimal("1602.75"), 1200, True)
    assert (r.e_lunch_kcal, r.e_dinner_kcal) == (420, 360)


def test_suggest_male_65_80kg_moderate_lose() -> None:
    # (13.5 × 80 + 487) × 1.75 = 2742.25; − 500 = 2242.25 → 2242
    r = suggest(sex="male", age=65, weight_kg=80, height_cm=None, activity_level="moderate", goal="lose")
    assert (r.suggested_kcal, r.floor_applied) == (2242, False)


def test_suggest_heavy_activity() -> None:
    # female 45 y, 70 kg, heavy: (8.7 × 70 + 829) × 2.00 = 2876
    r = suggest(sex="female", age=45, weight_kg=70, height_cm=None, activity_level="heavy", goal="maintain")
    assert r.suggested_kcal == 2876


def test_float_inputs_are_exact() -> None:
    # 14.7 × 52.3 in binary floating point is 768.8100000000001; Decimal keeps 768.81
    assert bmr_fao_who_unu_1985("female", 25, 52.3) == Decimal("1264.81")
