"""Tables owned by scan: scans, scan_images, scan_items, detections (db/schema.sql, ST01)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM, REAL, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from tastoria.core.db import Base

TZ = TIMESTAMP(timezone=True)
SCAN_MODE = ENUM("fridge", "haul", name="scan_mode_t", create_type=False)
SCAN_STATUS = ENUM(
    "queued",
    "processing",
    "done",
    "failed",
    "expired",
    "confirmed",
    "discarded",
    name="scan_status_t",
    create_type=False,
)
ITEM_ORIGIN = ENUM("model", "user_added", name="scan_item_origin_t", create_type=False)
USER_ACTION = ENUM("kept", "relabeled", "deleted", "edited", name="scan_user_action_t", create_type=False)
FRESHNESS = ENUM("tuoi", "dung_som", "dung_ngay", "kiem_tra", name="freshness_t", create_type=False)
QTY_LEVEL = ENUM("it", "vua", "nhieu", name="qty_level_t", create_type=False)


class Scan(Base):
    __tablename__ = "scans"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    mode: Mapped[str] = mapped_column(SCAN_MODE, nullable=False)
    status: Mapped[str] = mapped_column(SCAN_STATUS, nullable=False)
    error_code: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    detector_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("model_versions.id"))
    classifier_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("model_versions.id"))
    preprocess_version: Mapped[str | None] = mapped_column(Text)
    enqueued_at: Mapped[datetime | None] = mapped_column(TZ)
    started_at: Mapped[datetime | None] = mapped_column(TZ)
    finished_at: Mapped[datetime | None] = mapped_column(TZ)
    confirmed_at: Mapped[datetime | None] = mapped_column(TZ)
    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=text("now()"))

    __table_args__ = (
        CheckConstraint("attempts >= 0", name="attempts"),
        CheckConstraint("(status = 'confirmed') = (confirmed_at IS NOT NULL)", name="confirmed"),
        Index("ix_scans_user_id_created_at", "user_id", text("created_at DESC")),
        Index("ix_scans_stuck", "started_at", postgresql_where=text("status IN ('queued', 'processing')")),
    )


class ScanImage(Base):
    __tablename__ = "scan_images"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    scan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scans.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    shelf_group: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("1"))
    storage_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    contributed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    purged_at: Mapped[datetime | None] = mapped_column(TZ)

    __table_args__ = (
        UniqueConstraint("scan_id", "ordinal"),
        CheckConstraint("ordinal BETWEEN 1 AND 2", name="ordinal"),
        CheckConstraint("width > 0 AND height > 0", name="size"),
        CheckConstraint("shelf_group >= 1", name="shelf_group"),
        Index("ix_scan_images_purge", "scan_id", postgresql_where=text("purged_at IS NULL AND NOT contributed")),
    )


class ScanItem(Base):
    """A chip. scan_id, origin and model_count are write-once (trigger trg_scan_items_write_once)."""

    __tablename__ = "scan_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    scan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scans.id", ondelete="CASCADE"), nullable=False
    )
    ingredient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ingredients.id"), nullable=False)
    origin: Mapped[str] = mapped_column(ITEM_ORIGIN, nullable=False)
    model_count: Mapped[int | None] = mapped_column(SmallInteger)
    final_count: Mapped[int | None] = mapped_column(SmallInteger)
    qty_level: Mapped[str | None] = mapped_column(QTY_LEVEL)
    user_action: Mapped[str] = mapped_column(USER_ACTION, nullable=False, server_default="kept")
    original_ingredient_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("ingredients.id"))
    user_freshness: Mapped[str | None] = mapped_column(FRESHNESS)
    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=text("now()"))

    __table_args__ = (
        CheckConstraint("model_count >= 0", name="model_count"),
        CheckConstraint("final_count BETWEEN 0 AND 99", name="final_count"),
        CheckConstraint("user_action <> 'relabeled' OR original_ingredient_id IS NOT NULL", name="relabeled"),
        CheckConstraint(
            "original_ingredient_id IS NULL OR (origin = 'model' AND original_ingredient_id <> ingredient_id)",
            name="original",
        ),
        CheckConstraint("origin = 'model' OR (model_count IS NULL AND user_action <> 'deleted')", name="user_added"),
        Index("ix_scan_items_scan_id", "scan_id"),
    )


class Detection(Base):
    __tablename__ = "detections"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    scan_image_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scan_images.id", ondelete="CASCADE"), nullable=False
    )
    scan_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scan_items.id", ondelete="SET NULL")
    )
    vision_class_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("vision_classes.id"), nullable=False)
    x1: Mapped[float] = mapped_column(REAL, nullable=False)
    y1: Mapped[float] = mapped_column(REAL, nullable=False)
    x2: Mapped[float] = mapped_column(REAL, nullable=False)
    y2: Mapped[float] = mapped_column(REAL, nullable=False)
    confidence: Mapped[float] = mapped_column(REAL, nullable=False)
    p_tuoi: Mapped[float | None] = mapped_column(REAL)
    p_dung_som: Mapped[float | None] = mapped_column(REAL)
    p_dung_ngay: Mapped[float | None] = mapped_column(REAL)
    p_kiem_tra: Mapped[float | None] = mapped_column(REAL)

    __table_args__ = (
        Index("ix_detections_scan_image_id", "scan_image_id"),
        Index("ix_detections_scan_item_id", "scan_item_id"),
    )
