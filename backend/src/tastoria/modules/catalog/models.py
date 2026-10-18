"""Tables owned by catalog (model.yaml `tables[].module = catalog`), mapped exactly as db/schema.sql + migration 0003.

Reference data (food groups, allergen groups, diets, cooking methods, tags, quantity levels, nutrients), the food
composition rows actually used by ingredients, ingredients with synonyms/allergens/units, and recipes with their
ingredients, steps, tags, sources, computed nutrition and make-ahead item. Published recipes are immutable
(BR-CATALOG-01): triggers trg_recipes_guard / trg_recipe_children_guard enforce it in the database.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from tastoria.core.db import Base

TZ = TIMESTAMP(timezone=True)
ALLERGEN_BASIS = ENUM("codex_2024", "tastoria_extra", name="allergen_basis_t", create_type=False)
SLOT = ENUM("man", "rau", "canh", name="slot_t", create_type=False)
RECIPE_STATUS = ENUM("draft", "published", "retired", name="recipe_status_t", create_type=False)
LANG = ENUM("vi", "en", name="lang_t", create_type=False)
QTY_LEVEL = ENUM("it", "vua", "nhieu", name="qty_level_t", create_type=False)
TAG_KIND = ENUM("flavor", "texture", "occasion", name="tag_kind_t", create_type=False)
ROLE = ENUM("main", "side", "seasoning", name="ingredient_role_t", create_type=False)
STEP_KIND = ENUM("active", "passive", name="step_kind_t", create_type=False)
INSTANCE_DEF = ENUM("item", "group_of", "package", name="instance_def_t", create_type=False)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))


# ---------------------------------------------------------------- reference


class FoodGroup(Base):
    __tablename__ = "food_groups"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name_vi: Mapped[str] = mapped_column(Text, nullable=False)


class NutrientSource(Base):
    __tablename__ = "nutrient_sources"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    license: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (UniqueConstraint("code", name="uq_nutrient_sources_code"),)


class FoodItem(Base):
    __tablename__ = "food_items"

    source_id: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("nutrient_sources.id"), primary_key=True, autoincrement=False
    )
    source_code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str | None] = mapped_column(Text)
    refuse_pct: Mapped[Decimal | None] = mapped_column(Numeric)


class Nutrient(Base):
    __tablename__ = "nutrients"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name_vi: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str] = mapped_column(Text, nullable=False)


class FoodNutrient(Base):
    __tablename__ = "food_nutrients"

    source_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    source_code: Mapped[str] = mapped_column(Text, primary_key=True)
    nutrient_code: Mapped[str] = mapped_column(Text, ForeignKey("nutrients.code"), primary_key=True)
    per_100g: Mapped[Decimal] = mapped_column(Numeric, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(["source_id", "source_code"], ["food_items.source_id", "food_items.source_code"]),
    )


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


class DietExclusion(Base):
    __tablename__ = "diet_exclusions"

    diet_code: Mapped[str] = mapped_column(Text, ForeignKey("diets.code"), primary_key=True)
    food_group_code: Mapped[str] = mapped_column(Text, ForeignKey("food_groups.code"), primary_key=True)


class QtyLevel(Base):
    __tablename__ = "qty_levels"

    food_group_code: Mapped[str] = mapped_column(Text, ForeignKey("food_groups.code"), primary_key=True)
    level: Mapped[str] = mapped_column(QTY_LEVEL, primary_key=True)
    g_min: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    g_max: Mapped[Decimal] = mapped_column(Numeric, nullable=False)


class CookingMethod(Base):
    __tablename__ = "cooking_methods"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name_vi: Mapped[str] = mapped_column(Text, nullable=False)


class Tag(Base):
    __tablename__ = "tags"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(TAG_KIND, nullable=False)
    name_vi: Mapped[str] = mapped_column(Text, nullable=False)


# ---------------------------------------------------------------- ingredients


class Ingredient(Base):
    __tablename__ = "ingredients"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name_vi: Mapped[str] = mapped_column(Text, nullable=False)
    food_group_code: Mapped[str] = mapped_column(Text, ForeignKey("food_groups.code"), nullable=False)
    comp_source_id: Mapped[int | None] = mapped_column(SmallInteger)
    comp_source_code: Mapped[str | None] = mapped_column(Text)
    is_staple: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    countable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    shelf_life_days: Mapped[Decimal | None] = mapped_column(Numeric)
    shelf_life_basis: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=func.now())

    __table_args__ = (
        ForeignKeyConstraint(
            ["comp_source_id", "comp_source_code"], ["food_items.source_id", "food_items.source_code"]
        ),
        Index("ux_ingredients_name_vi_active", "name_vi", unique=True, postgresql_where=text("is_active")),
    )


class IngredientSynonym(Base):
    __tablename__ = "ingredient_synonyms"

    ingredient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ingredients.id"), primary_key=True)
    synonym: Mapped[str] = mapped_column(Text, primary_key=True)
    lang: Mapped[str] = mapped_column(LANG, primary_key=True)
    source: Mapped[str | None] = mapped_column(Text)


class IngredientAllergen(Base):
    __tablename__ = "ingredient_allergens"

    ingredient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ingredients.id"), primary_key=True)
    allergen_code: Mapped[str] = mapped_column(Text, ForeignKey("allergen_groups.code"), primary_key=True)

    __table_args__ = (Index("ix_ingredient_allergens_allergen_code", "allergen_code"),)


class IngredientUnit(Base):
    __tablename__ = "ingredient_units"

    ingredient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ingredients.id"), primary_key=True)
    unit_code: Mapped[str] = mapped_column(Text, primary_key=True)
    grams_per_unit: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)


# ---------------------------------------------------------------- vision classes (design v2 §7)


class VisionClass(Base):
    """Classes of the ingredient detector (data/kb/vision_classes.yaml). `id` is assigned once per `code` and never
    reused: model_version_classes and detections point at it."""

    __tablename__ = "vision_classes"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name_vi: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    countable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    instance_def: Mapped[str] = mapped_column(INSTANCE_DEF, nullable=False)
    has_freshness_model: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


class VisionClassIngredient(Base):
    __tablename__ = "vision_class_ingredients"

    vision_class_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("vision_classes.id"), primary_key=True)
    ingredient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ingredients.id"), primary_key=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    __table_args__ = (
        Index(
            "ux_vision_class_ingredients_default", "vision_class_id", unique=True, postgresql_where=text("is_default")
        ),
    )


# ---------------------------------------------------------------- recipes


class Recipe(Base):
    """Published recipes are immutable (BR-CATALOG-01, trigger trg_recipes_guard)."""

    __tablename__ = "recipes"

    id: Mapped[uuid.UUID] = _uuid_pk()
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


class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredients"

    recipe_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("recipes.id"), primary_key=True)
    ingredient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ingredients.id"), primary_key=True)
    grams: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    role: Mapped[str] = mapped_column(ROLE, nullable=False)
    is_optional: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    __table_args__ = (Index("ix_recipe_ingredients_ingredient_id", "ingredient_id"),)


class RecipeStep(Base):
    __tablename__ = "recipe_steps"

    recipe_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("recipes.id"), primary_key=True)
    step_no: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    text_vi: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(STEP_KIND, nullable=False)
    minutes: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    uses_burner: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


class RecipeTag(Base):
    __tablename__ = "recipe_tags"

    recipe_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("recipes.id"), primary_key=True)
    tag_code: Mapped[str] = mapped_column(Text, ForeignKey("tags.code"), primary_key=True)


class RecipeSource(Base):
    __tablename__ = "recipe_sources"

    recipe_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("recipes.id"), primary_key=True)
    url: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    accessed_on: Mapped[date] = mapped_column(Date, nullable=False)


class RecipeNutrition(Base):
    __tablename__ = "recipe_nutrition"

    recipe_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("recipes.id"), primary_key=True)
    nutrient_code: Mapped[str] = mapped_column(Text, ForeignKey("nutrients.code"), primary_key=True)
    per_serving: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    data_version: Mapped[str] = mapped_column(Text, nullable=False)


class RecipeMakeAhead(Base):
    """Migration 0003: recipe whose steps 1..through_step_no are done ahead (passive > 2 h); the made-ahead
    product the user must hold in the pantry is `item_ingredient_id`."""

    __tablename__ = "recipe_make_ahead"

    recipe_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("recipes.id"), primary_key=True)
    item_ingredient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingredients.id"), nullable=False
    )
    through_step_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(["recipe_id", "through_step_no"], ["recipe_steps.recipe_id", "recipe_steps.step_no"]),
        Index("ix_recipe_make_ahead_item_ingredient_id", "item_ingredient_id"),
    )
