"""journal public types: GET /journal body (openapi JournalWeek, JournalDay)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel


class JournalDay(BaseModel):
    date: date
    cooked_trays: int
    kcal_per_person: float | None
    e_target_kcal: float | None
    urgent_lots_used: int


class JournalWeek(BaseModel):
    week: str
    timezone: str
    days: list[JournalDay]
    kcal_range_status: Literal["calibrated", "calibrating"]
