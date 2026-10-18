"""Tables owned by meal: meal_plans and their items, co-eater allergens, pinned lots, accepted substitutions.

The derived columns (kcal_low/high, rice bowls, kcal_per_person) change only while the plan is proposed/accepted, and
the identity columns are write-once — triggers trg_meal_* enforce both. ranker_version_id points at model_versions
(mlops has no code yet; the FK lives in the database only).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, ForeignKeyConstraint, Index, Numeric, SmallInteger, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ENUM, REAL, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from tastoria.core.db import Base

TZ = TIMESTAMP(timezone=True)
MEAL = ENUM("lunch", "dinner", name="meal_t", create_type=False)
PLAN_STATUS = ENUM(
    "proposed", "accepted", "cooked", "abandoned", "expired", name="meal_plan_status_t", create_type=False
)
SLOT = ENUM("man", "rau", "canh", name="slot_t", create_type=False)
ITEM_STATUS = ENUM("active", "swapped_out", name="plan_item_status_t", create_type=False)
SWAP_REASON = ENUM("khong_hop_gu", "moi_an", "thieu_thoi_gian", "khac", name="swap_reason_t", create_type=False)
SUB_ORIGIN = ENUM("lookup", "embedding", "user", name="substitution_origin_t", create_type=False)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))


class MealPlan(Base):
    __tablename__ = "meal_plans"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    meal: Mapped[str] = mapped_column(MEAL, nullable=False)
    persons: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    max_minutes: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[str] = mapped_column(PLAN_STATUS, nullable=False, server_default="proposed")
    e_target_kcal: Mapped[Decimal | None] = mapped_column(Numeric)
    kcal_low: Mapped[Decimal | None] = mapped_column(Numeric)
    kcal_high: Mapped[Decimal | None] = mapped_column(Numeric)
    rice_bowls_per_person: Mapped[Decimal | None] = mapped_column(Numeric)
    reason_vi: Mapped[str] = mapped_column(Text, nullable=False)
    ranker_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("model_versions.id"))
    params_version: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_meal_plans_id_user_id"),
        Index("ix_meal_plans_user_id_created_at", "user_id", text("created_at DESC")),
    )


class MealPlanCoeaterAllergen(Base):
    __tablename__ = "meal_plan_coeater_allergens"

    meal_plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meal_plans.id", ondelete="CASCADE"), primary_key=True
    )
    allergen_code: Mapped[str] = mapped_column(Text, ForeignKey("allergen_groups.code"), primary_key=True)


class MealPlanPin(Base):
    __tablename__ = "meal_plan_pins"

    meal_plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meal_plans.id", ondelete="CASCADE"), primary_key=True
    )
    lot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pantry_lots.id", ondelete="CASCADE"), primary_key=True
    )

    __table_args__ = (Index("ix_meal_plan_pins_lot_id", "lot_id"),)


class MealPlanItem(Base):
    __tablename__ = "meal_plan_items"

    id: Mapped[uuid.UUID] = _uuid_pk()
    meal_plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meal_plans.id", ondelete="CASCADE"), nullable=False
    )
    slot: Mapped[str] = mapped_column(SLOT, nullable=False)
    recipe_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(ITEM_STATUS, nullable=False, server_default="active")
    replaced_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meal_plan_items.id"), unique=True
    )
    swap_reason: Mapped[str | None] = mapped_column(SWAP_REASON)
    rank_score: Mapped[float] = mapped_column(REAL, nullable=False)
    servings_scale: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    kcal_per_person: Mapped[Decimal | None] = mapped_column(Numeric)
    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=text("now()"))

    __table_args__ = (
        ForeignKeyConstraint(["recipe_id", "slot"], ["recipes.id", "recipes.slot"]),
        UniqueConstraint("id", "meal_plan_id", "recipe_id", name="uq_meal_plan_items_id_meal_plan_id_recipe_id"),
        Index(
            "ux_meal_plan_items_active_slot",
            "meal_plan_id",
            "slot",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index("ix_meal_plan_items_meal_plan_id", "meal_plan_id"),
    )


class MealPlanItemSubstitution(Base):
    __tablename__ = "meal_plan_item_substitutions"

    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meal_plan_items.id", ondelete="CASCADE"), primary_key=True
    )
    original_ingredient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingredients.id"), primary_key=True
    )
    substitute_ingredient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingredients.id"), nullable=False
    )
    grams: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    origin: Mapped[str] = mapped_column(SUB_ORIGIN, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=text("now()"))
