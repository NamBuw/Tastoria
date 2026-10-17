"""Energy formulas (BR-NUT-01..04). Pure functions, exact decimal arithmetic, no I/O.

BMR: FAO/WHO/UNU 1985 equations from body weight W (kg), kcal/day, by sex and half-open age band
[18, 30), [30, 60), ≥ 60 (thiết kế v1 §2.1, verified in docs/research R2 §7):

    male    15.3 W + 679 | 11.6 W + 879 | 13.5 W + 487
    female  14.7 W + 496 |  8.7 W + 829 | 10.5 W + 596

TEE = BMR × PAL, PAL light 1.50 / moderate 1.75 / heavy 2.00 (BR-NUT-02).
Goal `lose`: E = TEE − 500, not below 1200 kcal (female) / 1500 kcal (male) (BR-NUT-03). No automatic gain.
E_meal = E × 0.35 (lunch) / 0.30 (dinner) (BR-NUT-04). Results round to whole kcal, half up (FR-11-04).
Mifflin–St Jeor is a comparison figure only (FR-11-16), never used to set E.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

Sex = Literal["male", "female"]
Activity = Literal["light", "moderate", "heavy"]
Goal = Literal["maintain", "lose"]
Meal = Literal["lunch", "dinner"]

MIN_AGE = 18
BMR_FAO: dict[Sex, tuple[tuple[Decimal, Decimal], ...]] = {
    "male": ((Decimal("15.3"), Decimal("679")), (Decimal("11.6"), Decimal("879")), (Decimal("13.5"), Decimal("487"))),
    "female": ((Decimal("14.7"), Decimal("496")), (Decimal("8.7"), Decimal("829")), (Decimal("10.5"), Decimal("596"))),
}
PAL: dict[Activity, Decimal] = {"light": Decimal("1.50"), "moderate": Decimal("1.75"), "heavy": Decimal("2.00")}
LOSS_DEFICIT = Decimal("500")
FLOOR: dict[Sex, int] = {"female": 1200, "male": 1500}
MEAL_SHARE: dict[Meal, Decimal] = {"lunch": Decimal("0.35"), "dinner": Decimal("0.30")}

FORMULA_FAO = "fao_who_unu_1985"
EQUATION_LABEL = "FAO/WHO/UNU 1985 (cân nặng)"
SOURCE = "FAO/WHO/UNU (1985). Energy and protein requirements. WHO Technical Report Series 724."


class AgeBelowMinimum(ValueError):
    pass


def _d(x: float | int | Decimal) -> Decimal:
    return x if isinstance(x, Decimal) else Decimal(str(x))


def round_half_up(x: Decimal) -> int:
    return int(x.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def age_band(age: int) -> int:
    """0 = [18, 30), 1 = [30, 60), 2 = ≥ 60."""
    if age < MIN_AGE:
        raise AgeBelowMinimum(age)
    if age < 30:
        return 0
    if age < 60:
        return 1
    return 2


def bmr_fao_who_unu_1985(sex: Sex, age: int, weight_kg: float | Decimal) -> Decimal:
    slope, intercept = BMR_FAO[sex][age_band(age)]
    return slope * _d(weight_kg) + intercept


def bmr_mifflin_st_jeor(sex: Sex, age: int, weight_kg: float | Decimal, height_cm: float | Decimal) -> Decimal:
    s = Decimal("5") if sex == "male" else Decimal("-161")
    return Decimal("9.99") * _d(weight_kg) + Decimal("6.25") * _d(height_cm) - Decimal("4.92") * age + s


def pal_for(activity: Activity) -> Decimal:
    return PAL[activity]


def daily_target(tee: Decimal, sex: Sex, goal: Goal) -> tuple[int, bool]:
    """(E in kcal/day, floor_applied)."""
    if goal == "maintain":
        return round_half_up(tee), False
    e = tee - LOSS_DEFICIT
    floor = Decimal(FLOOR[sex])
    if e < floor:
        return FLOOR[sex], True
    return round_half_up(e), False


def meal_energy(e_kcal: int, meal: Meal) -> int:
    return round_half_up(Decimal(e_kcal) * MEAL_SHARE[meal])


def below_floor(kcal: int, sex: Sex) -> bool:
    return kcal < FLOOR[sex]


@dataclass(frozen=True)
class EnergyResult:
    formula: str
    bmr_kcal: Decimal
    pal: Decimal
    tee_kcal: Decimal
    suggested_kcal: int
    floor_applied: bool
    e_lunch_kcal: int
    e_dinner_kcal: int
    bmr_mifflin_kcal: Decimal | None = None


def suggest(
    *,
    sex: Sex,
    age: int,
    weight_kg: float | Decimal,
    height_cm: float | Decimal | None,
    activity_level: Activity,
    goal: Goal,
    with_mifflin: bool = False,
) -> EnergyResult:
    bmr = bmr_fao_who_unu_1985(sex, age, weight_kg)
    pal = pal_for(activity_level)
    tee = bmr * pal
    e, floored = daily_target(tee, sex, goal)
    mifflin = bmr_mifflin_st_jeor(sex, age, weight_kg, height_cm) if with_mifflin and height_cm is not None else None
    return EnergyResult(
        formula=FORMULA_FAO,
        bmr_kcal=bmr,
        pal=pal,
        tee_kcal=tee,
        suggested_kcal=e,
        floor_applied=floored,
        e_lunch_kcal=meal_energy(e, "lunch"),
        e_dinner_kcal=meal_energy(e, "dinner"),
        bmr_mifflin_kcal=mifflin,
    )
