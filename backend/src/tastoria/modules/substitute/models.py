"""Tables owned by substitute: substitution_pairs, ingredient_embeddings, and shopping_items."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Index, Numeric, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ENUM, REAL, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import UserDefinedType

from tastoria.core.db import Base

TZ = TIMESTAMP(timezone=True)
SLOT = ENUM("man", "rau", "canh", name="slot_t", create_type=False)
SHOP_STATUS = ENUM("open", "bought", "dropped", name="shopping_status_t", create_type=False)


class PgVector(UserDefinedType):
    cache_ok = True

    def __init__(self, dim: int) -> None:
        self.dim = dim

    def get_col_spec(self, **kw: object) -> str:
        return f"vector({self.dim})"


class IngredientEmbedding(Base):
    __tablename__ = "ingredient_embeddings"

    ingredient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingredients.id"), primary_key=True
    )
    model_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_versions.id"), primary_key=True
    )
    vector: Mapped[object] = mapped_column(PgVector(100), nullable=False)


class SubstitutionPair(Base):
    __tablename__ = "substitution_pairs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    ingredient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ingredients.id"), nullable=False)
    substitute_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ingredients.id"), nullable=False)
    context_slot: Mapped[str | None] = mapped_column(SLOT)
    context_method_code: Mapped[str | None] = mapped_column(Text, ForeignKey("cooking_methods.code"))
    ratio: Mapped[Decimal] = mapped_column(Numeric, nullable=False, server_default=text("1"))
    score: Mapped[float] = mapped_column(REAL, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    curated: Mapped[bool] = mapped_column(Boolean, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "ingredient_id",
            "substitute_id",
            "context_slot",
            "context_method_code",
            name="uq_substitution_pairs_ctx",
            postgresql_nulls_not_distinct=True,
        ),
    )


class ShoppingItem(Base):
    __tablename__ = "shopping_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    ingredient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ingredients.id"), nullable=False)
    qty_g: Mapped[Decimal | None] = mapped_column(Numeric)
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(SHOP_STATUS, nullable=False, server_default="open")
    source_meal_plan_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meal_plan_items.id", ondelete="SET NULL")
    )
    pantry_lot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pantry_lots.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=text("now()"))

    __table_args__ = (
        Index("ix_shopping_items_user_id_status", "user_id", "status"),
        Index("ix_shopping_items_source_meal_plan_item_id", "source_meal_plan_item_id"),
        Index("ix_shopping_items_pantry_lot_id", "pantry_lot_id"),
        Index(
            "ux_shopping_items_open_null_src",
            "user_id",
            "ingredient_id",
            unique=True,
            postgresql_where=text("status = 'open' AND source_meal_plan_item_id IS NULL"),
        ),
        Index(
            "ux_shopping_items_open_with_src",
            "user_id",
            "ingredient_id",
            "source_meal_plan_item_id",
            unique=True,
            postgresql_where=text("status = 'open' AND source_meal_plan_item_id IS NOT NULL"),
        ),
    )
