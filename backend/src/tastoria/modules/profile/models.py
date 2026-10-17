"""Tables owned by profile: profiles (health columns AES-GCM encrypted), user_allergens, user_favorite_recipes,
user_settings."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, LargeBinary, SmallInteger, Text, func, text
from sqlalchemy.dialects.postgresql import ENUM, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from tastoria.core.db import Base

TZ = TIMESTAMP(timezone=True)
ACTIVITY = ENUM("light", "moderate", "heavy", name="activity_level_t", create_type=False)
GOAL = ENUM("maintain", "lose", "expert", name="goal_t", create_type=False)
KCAL_SOURCE = ENUM("suggested", "user", "expert", name="kcal_source_t", create_type=False)


class Profile(Base):
    __tablename__ = "profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    sex_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    birth_year_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    height_cm_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    weight_kg_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    enc_key_id: Mapped[str | None] = mapped_column(Text)
    activity_level: Mapped[str | None] = mapped_column(ACTIVITY)
    goal: Mapped[str | None] = mapped_column(GOAL)
    kcal_target: Mapped[int | None] = mapped_column(Integer)
    kcal_source: Mapped[str | None] = mapped_column(KCAL_SOURCE)
    diet_code: Mapped[str | None] = mapped_column(Text, ForeignKey("diets.code"))
    updated_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=func.now())


class UserAllergen(Base):
    __tablename__ = "user_allergens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    allergen_code: Mapped[str] = mapped_column(Text, ForeignKey("allergen_groups.code"), primary_key=True)


class UserFavoriteRecipe(Base):
    __tablename__ = "user_favorite_recipes"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    recipe_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("recipes.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=func.now())


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    burners: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="2")
    default_persons: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="2")
    timezone: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'Asia/Ho_Chi_Minh'"))
    updated_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=func.now())
