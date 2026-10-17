"""meal public types: /meal-plans bodies (openapi MealPlan*, SwapRequest, Substitute*, Substitution*) and the plan view
cooking and journal read through meal.service."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tastoria.modules.catalog.schemas import RecipeView

Meal = Literal["lunch", "dinner"]
PlanStatus = Literal["proposed", "accepted", "cooked", "abandoned", "expired"]
SwapReason = Literal["khong_hop_gu", "moi_an", "thieu_thoi_gian", "khac"]


class _Req(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MealPlanCreate(_Req):
    meal: Meal
    persons: int | None = Field(default=None, ge=1, le=6)
    max_minutes: int = Field(ge=10, le=180)
    coeater_allergen_codes: list[str] = Field(default_factory=list, max_length=32)
    pinned_lot_ids: list[uuid.UUID] = Field(default_factory=list, max_length=2)


class SubstitutionOut(BaseModel):
    original_ingredient_id: uuid.UUID
    substitute_ingredient_id: uuid.UUID
    grams: float
    origin: Literal["lookup", "embedding", "user"]
    created_at: datetime


class MealPlanItemOut(BaseModel):
    id: uuid.UUID
    slot: Literal["man", "rau", "canh"]
    recipe_id: uuid.UUID
    recipe_name_vi: str
    status: Literal["active", "swapped_out"]
    replaced_item_id: uuid.UUID | None
    swap_reason: SwapReason | None
    rank_score: float
    servings_scale: float
    kcal_per_person: float | None
    substitutions: list[SubstitutionOut]
    created_at: datetime


class MealPlanOut(BaseModel):
    id: uuid.UUID
    meal: Meal
    persons: int
    max_minutes: int
    status: PlanStatus
    e_target_kcal: float | None
    kcal_low: float | None
    kcal_high: float | None
    rice_bowls_per_person: float | None
    reason_vi: str
    ranker_version_id: uuid.UUID | None
    params_version: str
    coeater_allergen_codes: list[str]
    pinned_lot_ids: list[uuid.UUID]
    items: list[MealPlanItemOut]
    created_at: datetime
    updated_at: datetime


class MealPlanSummary(BaseModel):
    id: uuid.UUID
    meal: Meal
    persons: int
    status: PlanStatus
    recipe_names_vi: list[str]
    created_at: datetime


class MealPlanSummaryPage(BaseModel):
    items: list[MealPlanSummary]
    next_cursor: str | None


class SwapRequest(_Req):
    swap_reason: SwapReason


class SubstituteCandidateOut(BaseModel):
    substitute_ingredient_id: uuid.UUID
    name_vi: str
    ratio: float
    grams: float
    score: float
    origin: Literal["lookup", "embedding"]
    in_pantry: bool
    available_g_min: float  # FR-17-08 (extension): usable stock of the substitute, check-level lots excluded
    available_g_max: float


class MissingIngredientOut(BaseModel):
    original_ingredient_id: uuid.UUID
    name_vi: str
    need_g: float
    available_g_min: float
    candidates: list[SubstituteCandidateOut]


class SubstituteListOut(BaseModel):
    items: list[MissingIngredientOut]


class SubstitutionCreate(_Req):
    original_ingredient_id: uuid.UUID
    substitute_ingredient_id: uuid.UUID
    origin: Literal["lookup", "embedding", "user"]


# ---------------------------------------------------------------- for cooking / journal


@dataclass(frozen=True)
class PlanDish:
    item_id: uuid.UUID
    recipe: RecipeView  # the exact version the plan uses (BR-CATALOG-01)
    servings_scale: float


@dataclass(frozen=True)
class CookPlan:
    id: uuid.UUID
    user_id: uuid.UUID
    status: str
    persons: int
    max_minutes: int
    burners: int
    dishes: tuple[PlanDish, ...]
    pinned_lot_ids: tuple[uuid.UUID, ...]
