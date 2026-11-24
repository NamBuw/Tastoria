"""journal public types: GET /journal body (openapi JournalWeek, JournalDay, JournalMacros, CookedMeal)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from tastoria.modules.meal_logs.schemas import MealLogOut


class JournalMacros(BaseModel):
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float


class CookedDishOut(BaseModel):
    recipe_id: uuid.UUID
    name_vi: str
    slot: Literal["man", "rau", "canh"]
    kcal_per_person: float | None


class CookedMealOut(BaseModel):
    cook_session_id: uuid.UUID
    meal_plan_id: uuid.UUID
    date: date
    completed_at: datetime
    meal: Literal["lunch", "dinner"]
    persons: int
    kcal_per_person: float | None
    rice_bowls_per_person: float | None
    macros: JournalMacros
    dishes: list[CookedDishOut]


class JournalDay(BaseModel):
    date: date
    cooked_trays: int
    meal_logs_count: int = 0
    meal_logs_kcal: float = 0.0
    kcal_per_person: float | None
    e_target_kcal: float | None
    urgent_lots_used: int
    protein_g: float | None = None
    carbs_g: float | None = None
    fat_g: float | None = None
    fiber_g: float | None = None


class JournalWeek(BaseModel):
    week: str
    timezone: str
    days: list[JournalDay]
    kcal_range_status: Literal["calibrated", "calibrating"]
    macros: JournalMacros
    cooked_history: list[CookedMealOut]
    meal_logs: list[MealLogOut] = []
