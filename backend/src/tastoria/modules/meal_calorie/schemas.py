"""Public API schemas for the decoupled meal_calorie module (M17)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

PortionSize = Literal["nho", "vua", "lon"]
EstimateSource = Literal["kb_calibrated", "onnx_nutrition5k", "hybrid"]
FusionMode = Literal["kb_exact", "variance_weighted", "top3_blend", "visual_fallback"]
DishSlot = Literal["man", "rau", "canh"]
NutritionGrade = Literal["A", "B", "C", "D"]


class ModifierSuggestionOut(BaseModel):
    id: str
    label_vi: str
    kcal_delta: float
    fat_delta_g: float = 0.0
    carbs_delta_g: float = 0.0
    protein_delta_g: float = 0.0


class MacroKcalSplitOut(BaseModel):
    protein_pct: int
    carbs_pct: int
    fat_pct: int


class DishCandidateOut(BaseModel):
    dish_id: str
    name_vi: str
    name_en: str
    confidence: float
    kb_slug: str | None = None
    kcal_vua: float | None = None


class MealCalorieDishOut(BaseModel):
    slug: str
    name_vi: str
    slot: DishSlot
    kcal_per_serving: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float


class MealCalorieDishListOut(BaseModel):
    data_version: str
    calibrated: bool
    half_width_rel: float
    dishes: list[MealCalorieDishOut]


class BarcodeNutritionOut(BaseModel):
    barcode: str
    product_name: str
    brand: str | None = None
    serving_size: str | None = None
    serving_g: float | None = None
    kcal_per_serving: float | None = None
    protein_g_per_serving: float | None = None
    carbs_g_per_serving: float | None = None
    fat_g_per_serving: float | None = None
    fiber_g_per_serving: float | None = None
    kcal_per_100g: float | None = None
    protein_g_per_100g: float | None = None
    carbs_g_per_100g: float | None = None
    fat_g_per_100g: float | None = None
    fiber_g_per_100g: float | None = None
    source: str
    image_url: str | None = None
    nutrition_score: int | None = None
    nutrition_grade: NutritionGrade | None = None
    macro_kcal_split: MacroKcalSplitOut | None = None


class MealCalorieEstimateOut(BaseModel):
    dish_name_vi: str | None = None
    kb_slug: str | None = None
    slot: DishSlot | None = None
    portion: PortionSize = "vua"
    portion_multiplier: float
    estimated_kcal: float
    kcal_low: float
    kcal_high: float
    estimated_mass_g: float | None = None
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float | None = None
    source: EstimateSource
    calibrated: bool
    half_width_rel: float
    latency_ms: float
    visual_kcal: float | None = None
    domain_shift_note: str | None = None
    ood_clamped: bool = False
    recognized_dish_id: str | None = None
    recognized_confidence: float | None = None
    top_candidates: list[DishCandidateOut] = Field(default_factory=list)
    nutrition_score: int | None = None
    nutrition_grade: NutritionGrade | None = None
    macro_kcal_split: MacroKcalSplitOut | None = None
    serving_desc_vi: str | None = None
    source_ref: str | None = None
    disambiguation_required: bool = False
    top_margin: float | None = None
    provenance_label_vi: str = "Ước lượng trực quan theo khẩu phần"
    fusion_mode: FusionMode = "visual_fallback"
    suggested_modifiers: list[ModifierSuggestionOut] = Field(default_factory=list)
