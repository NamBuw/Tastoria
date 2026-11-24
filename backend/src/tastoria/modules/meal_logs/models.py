"""Tables owned by meal_logs: meal_logs and meal_log_items."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Numeric, SmallInteger, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ENUM, JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from tastoria.core.db import Base

TZ = TIMESTAMP(timezone=True)
MEAL_LOG_SLOT = ENUM("sang", "trua", "toi", "phu", name="meal_log_slot_t", create_type=False)
MEAL_LOG_SOURCE = ENUM("scan_calorie", "barcode", "manual", "recipe", name="meal_log_source_t", create_type=False)
MEAL_LOG_ITEM_KIND = ENUM(
    "dish", "modifier", "barcode_item", "manual_item", name="meal_log_item_kind_t", create_type=False
)


class MealLog(Base):
    __tablename__ = "meal_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    logged_date: Mapped[date] = mapped_column(Date, nullable=False)
    logged_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=text("now()"))
    meal_slot: Mapped[str] = mapped_column(MEAL_LOG_SLOT, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(MEAL_LOG_SOURCE, nullable=False)
    source_ref_id: Mapped[str | None] = mapped_column(Text)
    portion_label: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'Vừa'"))
    portion_scale: Mapped[Decimal] = mapped_column(Numeric, nullable=False, server_default=text("1"))
    modifiers: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    kcal: Mapped[Decimal] = mapped_column(Numeric, nullable=False, server_default=text("0"))
    kcal_low: Mapped[Decimal] = mapped_column(Numeric, nullable=False, server_default=text("0"))
    kcal_high: Mapped[Decimal] = mapped_column(Numeric, nullable=False, server_default=text("0"))
    protein_g: Mapped[Decimal] = mapped_column(Numeric, nullable=False, server_default=text("0"))
    carbs_g: Mapped[Decimal] = mapped_column(Numeric, nullable=False, server_default=text("0"))
    fat_g: Mapped[Decimal] = mapped_column(Numeric, nullable=False, server_default=text("0"))
    fiber_g: Mapped[Decimal] = mapped_column(Numeric, nullable=False, server_default=text("0"))
    provenance_label_vi: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=text("now()"))

    __table_args__ = (
        Index("ix_meal_logs_user_id_logged_date", "user_id", text("logged_date DESC"), text("created_at DESC")),
    )


class MealLogItem(Base):
    __tablename__ = "meal_log_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    meal_log_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meal_logs.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("1"))
    item_kind: Mapped[str] = mapped_column(MEAL_LOG_ITEM_KIND, nullable=False, server_default=text("'dish'"))
    label_vi: Mapped[str] = mapped_column(Text, nullable=False)
    dish_slug: Mapped[str | None] = mapped_column(Text)
    recipe_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="SET NULL")
    )
    ingredient_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingredients.id", ondelete="SET NULL")
    )
    barcode: Mapped[str | None] = mapped_column(Text)
    grams: Mapped[Decimal | None] = mapped_column(Numeric)
    kcal: Mapped[Decimal] = mapped_column(Numeric, nullable=False, server_default=text("0"))
    protein_g: Mapped[Decimal] = mapped_column(Numeric, nullable=False, server_default=text("0"))
    carbs_g: Mapped[Decimal] = mapped_column(Numeric, nullable=False, server_default=text("0"))
    fat_g: Mapped[Decimal] = mapped_column(Numeric, nullable=False, server_default=text("0"))
    fiber_g: Mapped[Decimal] = mapped_column(Numeric, nullable=False, server_default=text("0"))
    modifiers: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("meal_log_id", "ordinal", name="uq_meal_log_items_meal_log_id_ordinal"),
        CheckConstraint("kcal >= 0", name="kcal"),
        Index("ix_meal_log_items_meal_log_id", "meal_log_id"),
        Index("ix_meal_log_items_recipe_id", "recipe_id"),
        Index("ix_meal_log_items_ingredient_id", "ingredient_id"),
    )
