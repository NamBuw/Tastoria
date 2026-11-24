"""meal_logs public types: /meal-logs bodies (openapi MealLogCreate, MealLogOut, MealLogPage, ...)."""

from __future__ import annotations

import math
import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MealSlot = Literal["sang", "trua", "toi", "phu"]
MealLogSource = Literal["scan_calorie", "barcode", "manual", "recipe"]
MealLogSourceIn = Literal["scan_calorie", "calorie_scan", "barcode", "manual", "recipe"]
MealLogItemKind = Literal["dish", "modifier", "barcode_item", "manual_item"]

_SOURCE_ALIASES: dict[str, MealLogSource] = {
    "calorie_scan": "scan_calorie",
    "scan_calorie": "scan_calorie",
    "barcode": "barcode",
    "manual": "manual",
    "recipe": "recipe",
}


def normalize_source_type(raw: str) -> MealLogSource:
    return _SOURCE_ALIASES[raw]


def _check_finite(val: float | None, name: str) -> None:
    if val is not None and not math.isfinite(val):
        raise ValueError(f"{name} phải là số hữu hạn")


class _Req(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MealLogItemIn(_Req):
    item_kind: MealLogItemKind = "dish"
    label_vi: str | None = Field(default=None, max_length=200)
    dish_slug: str | None = Field(default=None, max_length=128)
    recipe_id: uuid.UUID | None = None
    ingredient_id: uuid.UUID | None = None
    barcode: str | None = Field(default=None, max_length=64)
    grams: float | None = Field(default=None, gt=0, le=20_000)
    kcal: float | None = Field(default=None, ge=0, le=10_000)
    protein_g: float | None = Field(default=None, ge=0, le=1_000)
    carbs_g: float | None = Field(default=None, ge=0, le=1_000)
    fat_g: float | None = Field(default=None, ge=0, le=1_000)
    fiber_g: float | None = Field(default=None, ge=0, le=500)
    modifiers: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _validate_item(self) -> MealLogItemIn:
        for fname in ("grams", "kcal", "protein_g", "carbs_g", "fat_g", "fiber_g"):
            _check_finite(getattr(self, fname), fname)
        if self.label_vi is not None:
            stripped = self.label_vi.strip()
            if not stripped:
                raise ValueError("label_vi không được để trống")
            self.label_vi = stripped
        elif self.recipe_id is None and self.ingredient_id is None:
            raise ValueError("cần label_vi hoặc recipe_id hoặc ingredient_id")
        return self


class MealLogCreate(_Req):
    logged_date: date | None = None
    logged_at: datetime | None = None
    meal_slot: MealSlot
    title: str = Field(min_length=1, max_length=200)
    source_type: MealLogSourceIn
    source_ref_id: str | None = Field(default=None, max_length=200)
    portion_label: str = Field(default="Vừa", min_length=1, max_length=64)
    portion_scale: float = Field(default=1.0, gt=0, le=20.0)
    modifiers: list[str] = Field(default_factory=list, max_length=20)
    kcal: float = Field(default=0.0, ge=0, le=20_000)
    kcal_low: float | None = Field(default=None, ge=0, le=20_000)
    kcal_high: float | None = Field(default=None, ge=0, le=20_000)
    protein_g: float = Field(default=0.0, ge=0, le=2_000)
    carbs_g: float = Field(default=0.0, ge=0, le=2_000)
    fat_g: float = Field(default=0.0, ge=0, le=2_000)
    fiber_g: float = Field(default=0.0, ge=0, le=1_000)
    provenance_label_vi: str = Field(default="", max_length=200)
    notes: str | None = Field(default=None, max_length=1000)
    items: list[MealLogItemIn] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def _validate_create(self) -> MealLogCreate:
        for fname in ("portion_scale", "kcal", "kcal_low", "kcal_high", "protein_g", "carbs_g", "fat_g", "fiber_g"):
            _check_finite(getattr(self, fname), fname)
        self.title = self.title.strip()
        if not self.title:
            raise ValueError("title không được để trống")
        self.portion_label = self.portion_label.strip()
        if not self.portion_label:
            raise ValueError("portion_label không được để trống")
        if self.kcal_low is not None and self.kcal_high is not None and self.kcal_low > self.kcal_high:
            raise ValueError("kcal_low phải nhỏ hơn hoặc bằng kcal_high")
        if not self.items:
            lo = self.kcal if self.kcal_low is None else self.kcal_low
            hi = self.kcal if self.kcal_high is None else self.kcal_high
            if lo > self.kcal or self.kcal > hi:
                raise ValueError("kcal phải nằm trong khoảng [kcal_low, kcal_high]")
        return self


class MealLogItemOut(BaseModel):
    id: uuid.UUID
    ordinal: int
    item_kind: MealLogItemKind
    label_vi: str
    dish_slug: str | None
    recipe_id: uuid.UUID | None
    ingredient_id: uuid.UUID | None
    barcode: str | None
    grams: float | None
    kcal: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float
    modifiers: list[Any]
    created_at: datetime


class MealLogOut(BaseModel):
    id: uuid.UUID
    logged_date: date
    logged_at: datetime
    meal_slot: MealSlot
    title: str
    source_type: MealLogSource
    source_ref_id: str | None
    portion_label: str
    portion_scale: float
    modifiers: list[Any]
    kcal: float
    kcal_low: float
    kcal_high: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float
    provenance_label_vi: str
    notes: str | None
    items: list[MealLogItemOut]
    created_at: datetime
    updated_at: datetime


class MealLogPage(BaseModel):
    items: list[MealLogOut]
    next_cursor: str | None
