"""Catalog tables needed by this slice (allergen_groups, diets, recipes). The catalog-import slice maps the rest."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, SmallInteger, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import ENUM, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from tastoria.core.db import Base

TZ = TIMESTAMP(timezone=True)
ALLERGEN_BASIS = ENUM("codex_2024", "tastoria_extra", name="allergen_basis_t", create_type=False)
SLOT = ENUM("man", "rau", "canh", name="slot_t", create_type=False)
RECIPE_STATUS = ENUM("draft", "published", "retired", name="recipe_status_t", create_type=False)


class AllergenGroup(Base):
    __tablename__ = "allergen_groups"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name_vi: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    basis: Mapped[str] = mapped_column(ALLERGEN_BASIS, nullable=False)


class Diet(Base):
    __tablename__ = "diets"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name_vi: Mapped[str] = mapped_column(Text, nullable=False)


class CookingMethod(Base):
    __tablename__ = "cooking_methods"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name_vi: Mapped[str] = mapped_column(Text, nullable=False)


class Recipe(Base):
    """Published recipes are immutable (BR-CATALOG-01, trigger trg_recipes_guard)."""

    __tablename__ = "recipes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    name_vi: Mapped[str] = mapped_column(Text, nullable=False)
    slot: Mapped[str] = mapped_column(SLOT, nullable=False)
    servings: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    method_code: Mapped[str] = mapped_column(Text, ForeignKey("cooking_methods.code"), nullable=False)
    status: Mapped[str] = mapped_column(RECIPE_STATUS, nullable=False, server_default="draft")
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("id", "slot", name="uq_recipes_id_slot"),
        Index("ux_recipes_name_vi_live", "name_vi", unique=True, postgresql_where=text("status <> 'retired'")),
    )
