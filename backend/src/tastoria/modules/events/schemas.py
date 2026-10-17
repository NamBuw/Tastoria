"""events public types: POST /events bodies (openapi EventBatch, EventBatchResult) and events other modules record."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

InteractionType = Literal["served", "viewed", "swapped", "cooked", "liked", "disliked", "undone"]
SwapReason = Literal["khong_hop_gu", "moi_an", "thieu_thoi_gian", "khac"]


class InteractionEventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: uuid.UUID
    type: InteractionType
    recipe_id: uuid.UUID
    meal_plan_id: uuid.UUID | None = None
    meal_plan_item_id: uuid.UUID | None = None
    position: int | None = Field(default=None, ge=0, le=32767)
    swap_reason: SwapReason | None = None
    occurred_at: datetime

    @model_validator(mode="after")
    def _consistent(self) -> InteractionEventIn:
        if self.swap_reason is not None and self.type != "swapped":
            raise ValueError("swap_reason only goes with type = swapped")
        if self.meal_plan_item_id is not None and self.meal_plan_id is None:
            raise ValueError("meal_plan_item_id needs meal_plan_id")
        return self


class EventBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[InteractionEventIn] = Field(min_length=1, max_length=100)


class EventBatchResult(BaseModel):
    accepted: int
    duplicates: int
    skipped_no_consent: int


@dataclass(frozen=True)
class Event:
    """An interaction another module records inside its own Unit of Work (served, swapped, cooked, liked, ...)."""

    type: str
    recipe_id: uuid.UUID
    occurred_at: datetime
    meal_plan_id: uuid.UUID | None = None
    meal_plan_item_id: uuid.UUID | None = None
    position: int | None = None
    swap_reason: str | None = None
    ranker_version_id: uuid.UUID | None = None
    propensity: float | None = None
    event_id: uuid.UUID | None = None  # None → a new uuid4


@dataclass(frozen=True)
class RecipeSignal:
    """Counts used by the baseline ranker: positive = liked + cooked, negative = disliked + swapped as khong_hop_gu."""

    positive: int = 0
    negative: int = 0
