"""catalog public types: API bodies of /reference, /recipes, /ingredients, /catalog/snapshot (openapi-v1), and the
read-only views other modules receive from catalog.service (meal, pantry, substitute, cooking)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

Slot = Literal["man", "rau", "canh"]


# ---------------------------------------------------------------- API bodies


class CodeName(BaseModel):
    code: str
    name_vi: str


class AllergenGroupOut(BaseModel):
    code: str
    name_vi: str
    name_en: str
    basis: Literal["codex_2024", "tastoria_extra"]


class DietOut(BaseModel):
    code: str
    name_vi: str
    excluded_food_group_codes: list[str]


class TagOut(BaseModel):
    code: str
    kind: Literal["flavor", "texture", "occasion"]
    name_vi: str


class NutrientOut(BaseModel):
    code: str
    name_vi: str
    unit: str


class QtyLevelOut(BaseModel):
    food_group_code: str
    level: Literal["it", "vua", "nhieu"]
    g_min: float
    g_max: float


class ConsentPurposeRef(BaseModel):
    code: str
    name_vi: str
    description_vi: str
    data_category: str
    is_sensitive: bool
    is_required: bool


class ReferenceData(BaseModel):
    data_version: str
    allergen_groups: list[AllergenGroupOut]
    diets: list[DietOut]
    food_groups: list[CodeName]
    cooking_methods: list[CodeName]
    tags: list[TagOut]
    nutrients: list[NutrientOut]
    qty_levels: list[QtyLevelOut]
    consent_purposes: list[ConsentPurposeRef]


class IngredientUnitOut(BaseModel):
    unit_code: str
    grams_per_unit: float
    source: str


class IngredientOut(BaseModel):
    id: uuid.UUID
    name_vi: str
    food_group_code: str
    is_staple: bool
    countable: bool
    shelf_life_days: float | None
    allergen_codes: list[str]
    units: list[IngredientUnitOut]
    synonyms: list[str]


class IngredientPage(BaseModel):
    items: list[IngredientOut]
    next_cursor: str | None


class RecipeSummary(BaseModel):
    id: uuid.UUID
    name_vi: str
    slot: Slot
    servings: int
    method_code: str
    total_minutes: int
    kcal_per_serving: float | None
    tag_codes: list[str]


class RecipeSummaryPage(BaseModel):
    items: list[RecipeSummary]
    next_cursor: str | None


class RecipeIngredientOut(BaseModel):
    ingredient_id: uuid.UUID
    name_vi: str
    grams: float
    role: Literal["main", "side", "seasoning"]
    is_optional: bool
    is_staple: bool
    allergen_codes: list[str]


class RecipeStepOut(BaseModel):
    step_no: int
    text_vi: str
    kind: Literal["active", "passive"]
    minutes: int
    uses_burner: bool


class RecipeSourceOut(BaseModel):
    url: str
    title: str
    accessed_on: date


class RecipeNutrientOut(BaseModel):
    nutrient_code: str
    per_serving: float


class MakeAheadOut(BaseModel):
    """Extension of openapi Recipe (slice 2): steps 1..through_step_no are done ahead (recipe_make_ahead)."""

    item_ingredient_id: uuid.UUID
    item_name_vi: str
    through_step_no: int
    whole_dish: bool


class RecipeOut(RecipeSummary):
    status: Literal["draft", "published", "retired"]
    notes: str | None
    ingredients: list[RecipeIngredientOut]
    steps: list[RecipeStepOut]
    sources: list[RecipeSourceOut]
    nutrition: list[RecipeNutrientOut]
    nutrition_data_version: str | None
    make_ahead: MakeAheadOut | None = None


class CatalogSnapshot(BaseModel):
    data_version: str
    generated_at: datetime
    recipes: list[RecipeOut]
    ingredients: list[IngredientOut]


# ---------------------------------------------------------------- views for other modules


@dataclass(frozen=True)
class IngredientView:
    id: uuid.UUID
    name_vi: str
    food_group_code: str
    is_staple: bool
    countable: bool
    shelf_life_days: float | None
    is_active: bool
    allergen_codes: frozenset[str]
    units: dict[str, float]  # unit_code -> grams per unit

    @property
    def rounding_unit_g(self) -> float | None:
        """Grams of the smallest counting unit: countable needs are rounded up to it (BR-TRAY-02)."""
        return min(self.units.values()) if self.countable and self.units else None


@dataclass(frozen=True)
class RecipeLine:
    ingredient: IngredientView
    grams: float  # as purchased, for `servings`
    role: str
    is_optional: bool


@dataclass(frozen=True)
class StepView:
    step_no: int
    text_vi: str
    kind: str
    minutes: int
    uses_burner: bool


@dataclass(frozen=True)
class MakeAheadView:
    item: IngredientView
    through_step_no: int
    whole_dish: bool  # every step done ahead: needs the item instead of the raw ingredients


@dataclass(frozen=True)
class RecipeView:
    id: uuid.UUID
    name_vi: str
    slot: str
    servings: int
    method_code: str
    status: str
    lines: tuple[RecipeLine, ...]
    steps: tuple[StepView, ...]
    tag_codes: frozenset[str]
    kcal_per_serving: float | None
    make_ahead: MakeAheadView | None = None
    created_at: datetime | None = None

    @property
    def allergen_codes(self) -> frozenset[str]:
        """Every allergen of every line, staples and optional lines included (BR-ALG-01)."""
        return frozenset(a for ln in self.lines for a in ln.ingredient.allergen_codes) | (
            self.make_ahead.item.allergen_codes if self.make_ahead else frozenset()
        )

    @property
    def food_group_codes(self) -> frozenset[str]:
        return frozenset(ln.ingredient.food_group_code for ln in self.lines) | (
            frozenset({self.make_ahead.item.food_group_code}) if self.make_ahead else frozenset()
        )

    @property
    def cook_steps(self) -> tuple[StepView, ...]:
        """Steps cooked at meal time: make-ahead steps (1..through_step_no) are done earlier."""
        cut = self.make_ahead.through_step_no if self.make_ahead else 0
        return tuple(s for s in self.steps if s.step_no > cut)

    @property
    def main_ingredient_ids(self) -> frozenset[uuid.UUID]:
        return frozenset(ln.ingredient.id for ln in self.lines if ln.role == "main")


@dataclass(frozen=True)
class FoodNutrition:
    """Nutrients per 100 g as purchased (EP applied) of one ingredient; empty when it has no composition row."""

    ingredient_id: uuid.UUID
    per_100g_purchased: dict[str, float] = field(default_factory=dict)
