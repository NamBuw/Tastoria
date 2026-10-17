"""cooking public types: bodies of /cook-sessions* (openapi CookSession*, CookComplete*, ScheduleEntry)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CookStatus = Literal["in_progress", "completed", "reverted", "abandoned"]


class _Req(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CookSessionCreate(_Req):
    meal_plan_id: uuid.UUID
    serve_at: datetime
    # FR-19-10 (extension of openapi CookSessionCreate): cook even when the schedule is longer than max_minutes
    confirm_over_time: bool = False


class ScheduleEntryOut(BaseModel):
    recipe_id: uuid.UUID
    step_no: int
    start_offset_s: int
    end_offset_s: int
    text_vi: str
    kind: Literal["active", "passive"]
    uses_burner: bool


class CookSessionOut(BaseModel):
    id: uuid.UUID
    meal_plan_id: uuid.UUID
    status: CookStatus
    serve_at: datetime
    burners: int
    started_at: datetime
    completed_at: datetime | None
    reverted_at: datetime | None
    created_at: datetime
    makespan_s: int
    undo_deadline: datetime | None
    schedule: list[ScheduleEntryOut]


class DishFeedback(_Req):
    meal_plan_item_id: uuid.UUID
    liked: bool | None


class CookCompleteRequest(_Req):
    completed_at: datetime | None = None
    feedback: list[DishFeedback] = Field(default_factory=list, max_length=3)


class PantryDeductionOut(BaseModel):
    transaction_id: int
    lot_id: uuid.UUID
    ingredient_id: uuid.UUID
    delta_g_min: float
    delta_g_max: float
    urgency_at_event: float | None


class ShortfallOut(BaseModel):
    """FR-20-10 (extension of openapi CookCompletion): needed more than the pantry held; lots went to 0."""

    ingredient_id: uuid.UUID
    need_g: float
    available_g_min: float
    short_g: float


class CookCompletion(BaseModel):
    cook_session: CookSessionOut
    deductions: list[PantryDeductionOut]
    interactions_recorded: bool
    shortfalls: list[ShortfallOut] = []
