"""substitute public types: /shopping-items bodies (openapi ShoppingItem*) and the substitution candidates."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tastoria.modules.catalog.schemas import IngredientView

ShopStatus = Literal["open", "bought", "dropped"]


class _Req(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ShoppingItemOut(BaseModel):
    id: uuid.UUID
    ingredient_id: uuid.UUID
    ingredient_name_vi: str
    qty_g: float | None
    note: str | None
    status: ShopStatus
    source_meal_plan_item_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class ShoppingItemPage(BaseModel):
    items: list[ShoppingItemOut]
    next_cursor: str | None


class ShoppingItemCreate(_Req):
    ingredient_id: uuid.UUID
    qty_g: float | None = Field(default=None, gt=0, le=100_000)
    note: str | None = Field(default=None, max_length=500)
    source_meal_plan_item_id: uuid.UUID | None = None


class ShoppingItemPatch(_Req):
    qty_g: float | None = Field(default=None, gt=0, le=100_000)
    note: str | None = Field(default=None, max_length=500)
    status: ShopStatus | None = None


@dataclass(frozen=True)
class Candidate:
    substitute: IngredientView
    ratio: float
    score: float
    origin: str  # lookup (curated table) | embedding (substitution model, not deployed yet)
