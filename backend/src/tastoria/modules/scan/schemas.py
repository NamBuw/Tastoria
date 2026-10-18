"""Request / response bodies of the scan endpoints (openapi-v1: Scan, ScanItem, Detection, ScanConfirmResult…)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ScanMode = Literal["fridge", "haul"]
ScanStatus = Literal["queued", "processing", "done", "failed", "expired", "confirmed", "discarded"]
QtyLevel = Literal["it", "vua", "nhieu"]
FreshnessLabel = Literal["tuoi", "dung_som", "dung_ngay", "kiem_tra"]


class _Req(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScanAccepted(BaseModel):
    id: uuid.UUID
    status: Literal["queued"] = "queued"
    created_at: datetime


class ScanImageOut(BaseModel):
    ordinal: int
    shelf_group: int
    width: int
    height: int
    contributed: bool
    purged: bool


class DetectionOut(BaseModel):
    id: int
    image_ordinal: int
    vision_class_code: str
    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float
    p_tuoi: float | None
    p_dung_som: float | None
    p_dung_ngay: float | None
    p_kiem_tra: float | None


class ScanItemOut(BaseModel):
    id: uuid.UUID
    ingredient_id: uuid.UUID
    ingredient_name_vi: str
    origin: Literal["model", "user_added"]
    model_count: int | None
    final_count: int | None
    qty_level: QtyLevel | None
    user_action: Literal["kept", "relabeled", "deleted", "edited"]
    original_ingredient_id: uuid.UUID | None
    predicted_freshness: FreshnessLabel | None
    user_freshness: FreshnessLabel | None
    needs_check: bool
    detections: list[DetectionOut]
    created_at: datetime
    updated_at: datetime


class UnseenLot(BaseModel):
    lot_id: uuid.UUID
    ingredient_id: uuid.UUID
    ingredient_name_vi: str


class ScanOut(BaseModel):
    id: uuid.UUID
    mode: ScanMode
    status: ScanStatus
    error_code: str | None
    attempts: int
    created_at: datetime
    enqueued_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    confirmed_at: datetime | None
    detector_version_id: uuid.UUID | None
    classifier_version_id: uuid.UUID | None
    preprocess_version: str | None
    images: list[ScanImageOut]
    items: list[ScanItemOut]
    unseen_lots: list[UnseenLot] | None = None  # fridge + done only (FR-12-18); left out otherwise


class ScanItemCreate(_Req):
    ingredient_id: uuid.UUID
    final_count: int | None = Field(default=None, ge=0, le=99)
    qty_level: QtyLevel | None = None
    user_freshness: FreshnessLabel | None = None


class ScanItemPatch(_Req):
    ingredient_id: uuid.UUID | None = None
    final_count: int | None = Field(default=None, ge=0, le=99)
    qty_level: QtyLevel | None = None
    user_freshness: FreshnessLabel | None = None


class ScanConfirmRequest(_Req):
    purchase_date: date | None = None


class ScanConfirmResult(BaseModel):
    scan_id: uuid.UUID
    status: Literal["confirmed"] = "confirmed"
    confirmed_at: datetime
    created_lot_ids: list[uuid.UUID]
    not_seen_lot_ids: list[uuid.UUID]
