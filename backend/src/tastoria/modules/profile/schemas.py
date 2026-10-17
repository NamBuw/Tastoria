"""Bodies of /me/profile, /me/energy-*, /me/allergens, /me/diet, /me/favorites, /me/settings (openapi-v1)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Sex = Literal["male", "female"]
Activity = Literal["light", "moderate", "heavy"]
Goal = Literal["maintain", "lose", "expert"]
KcalSource = Literal["suggested", "user", "expert"]


class _Req(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProfileOut(BaseModel):
    sex: Sex | None
    birth_year: int | None
    height_cm: float | None
    weight_kg: float | None
    activity_level: Activity | None
    goal: Goal | None
    kcal_target: int | None
    kcal_source: KcalSource | None
    diet_code: str | None
    allergen_codes: list[str]
    favorite_recipe_ids: list[uuid.UUID]
    health_profile_consented: bool
    updated_at: datetime | None
    # FR-10-04 (extension of openapi Profile): with kcal_source = suggested, the formula's current answer and
    # whether the stored target no longer matches it. The stored target is never changed silently.
    target_stale: bool = False
    suggested_kcal: int | None = None


class ProfileUpdate(_Req):
    sex: Sex | None
    birth_year: int | None = Field(ge=1900)
    height_cm: float | None = Field(ge=100, le=250)
    weight_kg: float | None = Field(ge=25, le=300)
    activity_level: Activity | None
    goal: Goal | None
    adult_confirmed: bool = False


class EnergySuggestionRequest(_Req):
    goal: Literal["maintain", "lose"] | None = None
    formula: Literal["fao_who_unu_1985", "mifflin_st_jeor"] = "fao_who_unu_1985"


class EnergySuggestion(BaseModel):
    formula: Literal["fao_who_unu_1985"]
    bmr_kcal: float
    pal: float
    tee_kcal: float
    suggested_kcal: int
    floor_applied: bool
    e_lunch_kcal: int
    e_dinner_kcal: int
    # extensions (FR-11-07, FR-11-16)
    goal: Literal["maintain", "lose"]
    age_years: int
    equation: str
    source: str
    bmr_mifflin_kcal: float | None = None


class EnergyTarget(_Req):
    kcal_target: int = Field(ge=800, le=5000)
    kcal_source: KcalSource
    goal: Goal | None = None
    confirm_below_floor: bool = False


class EnergyTargetOut(BaseModel):
    kcal_target: int
    kcal_source: KcalSource
    goal: Goal | None
    below_floor: bool  # FR-11-12
    e_lunch_kcal: int
    e_dinner_kcal: int


class AllergenSet(_Req):
    allergen_codes: list[str] = Field(max_length=32)


class DietSelection(_Req):
    diet_code: str | None


class FavoriteSet(_Req):
    recipe_ids: list[uuid.UUID] = Field(max_length=50)


class UserSettingsIn(_Req):
    burners: int = Field(default=2, ge=1, le=4)
    default_persons: int = Field(default=2, ge=1, le=6)
    timezone: str = Field(default="Asia/Ho_Chi_Minh", max_length=64)


class UserSettingsOut(BaseModel):
    burners: int
    default_persons: int
    timezone: str
    updated_at: datetime | None
