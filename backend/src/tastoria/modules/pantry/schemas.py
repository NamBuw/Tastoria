"""pantry public types: bodies of /pantry/lots* (openapi-v1 PantryLot, QuantityInput, ...) and the lot view, needs and
deductions other modules (meal, cooking) exchange with pantry.service."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag, model_validator

LotStatus = Literal["in_stock", "used_up", "discarded", "not_seen"]
Label = Literal["tuoi", "dung_som", "dung_ngay", "kiem_tra", "chua_ro"]


class _Req(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GramsQty(_Req):
    g_min: float = Field(ge=0, le=100_000)
    g_max: float = Field(ge=0, le=100_000)

    @model_validator(mode="after")
    def _ordered(self) -> GramsQty:
        if self.g_min > self.g_max:
            raise ValueError("g_min > g_max")
        return self


class CountQty(_Req):
    count: int = Field(ge=1, le=999)
    unit_code: str = Field(max_length=16)


class LevelQty(_Req):
    qty_level: Literal["it", "vua", "nhieu"]


def _qty_kind(v: Any) -> str:
    keys = set(v) if isinstance(v, dict) else set(type(v).model_fields) if isinstance(v, BaseModel) else set()
    if "count" in keys or "unit_code" in keys:
        return "count"
    if "qty_level" in keys:
        return "level"
    return "grams"


# One of three ways to give an amount (BR-QTY-01/02); the keys pick the shape, so a bad value inside the chosen shape
# is a 422 (FR-14-17), not a union mismatch.
QuantityInput = Annotated[
    Annotated[GramsQty, Tag("grams")] | Annotated[CountQty, Tag("count")] | Annotated[LevelQty, Tag("level")],
    Discriminator(_qty_kind),
]


class PantryLotCreate(_Req):
    ingredient_id: uuid.UUID
    quantity: QuantityInput
    acquired_at: datetime | None = None


class PantryLotPatch(_Req):
    """JSON Merge Patch: fields left out stay as they are."""

    balance: QuantityInput | None = None
    acquired_at: datetime | None = None
    acquired_basis: Literal["purchase_date_entered"] | None = None
    status: Literal["in_stock", "used_up"] | None = None
    user_checked: Literal[True] | None = None


class PantryLotOut(BaseModel):
    id: uuid.UUID
    ingredient_id: uuid.UUID
    ingredient_name_vi: str
    initial_g_min: float
    initial_g_max: float
    balance_g_min: float
    balance_g_max: float
    acquired_at: datetime
    acquired_basis: Literal["purchase_date_entered", "first_seen"]
    status: LotStatus
    p_tuoi: float | None
    p_dung_som: float | None
    p_dung_ngay: float | None
    p_kiem_tra: float | None
    freshness_observed_at: datetime | None
    user_checked_at: datetime | None
    urgency: float | None  # null = "chưa rõ hạn" (FR-14-05)
    freshness_label: Label
    available: bool
    created_at: datetime
    updated_at: datetime


class PantryLotPage(BaseModel):
    items: list[PantryLotOut]
    next_cursor: str | None


# ---------------------------------------------------------------- for other modules


@dataclass(frozen=True)
class LotView:
    """A lot as meal planning sees it now: balance from v_pantry_lot_balance, u and label computed at read."""

    id: uuid.UUID
    ingredient_id: uuid.UUID
    status: str
    g_min: float
    g_max: float
    urgency: float | None
    label: str
    available: bool
    rewarded: bool  # counts in U(m): u ∈ [0.5, 1.0], not at check level
    acquired_at: datetime


@dataclass(frozen=True)
class Need:
    ingredient_id: uuid.UUID
    grams: float
    report_short: bool = True  # False for staples and optional lines: deducted when there are lots, never "missing"


@dataclass(frozen=True)
class Deduction:
    transaction_id: int
    lot_id: uuid.UUID
    ingredient_id: uuid.UUID
    delta_g_min: float
    delta_g_max: float
    urgency_at_event: float | None


@dataclass(frozen=True)
class Shortfall:
    ingredient_id: uuid.UUID
    need_g: float
    available_g_min: float
    short_g: float


@dataclass(frozen=True)
class ScanLotInput:
    """One confirmed scan chip as the pantry receives it (UC13 step 13)."""

    scan_item_id: uuid.UUID
    ingredient_id: uuid.UUID
    g_min: float
    g_max: float
    probs: tuple[float, float, float, float] | None  # p_tuoi, p_dung_som, p_dung_ngay, p_kiem_tra of the chip
    user_checked: bool  # a "kiểm tra" chip the user confirmed as still usable (FR-13-20)


@dataclass(frozen=True)
class ScanApplyResult:
    created_lot_ids: list[uuid.UUID]
    updated_lot_ids: list[uuid.UUID]
    not_seen_lot_ids: list[uuid.UUID]
