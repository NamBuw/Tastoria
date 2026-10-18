"""Table owned by events: interactions (append-only; id = client event_id). Written only with a current
`personalization` consent (BR-CONSENT-03). The composite FK (meal_plan_id, user_id) ties an event to a plan of the
same user; the item FK nulls only meal_plan_item_id when an item disappears."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, ForeignKeyConstraint, Index, SmallInteger, text
from sqlalchemy.dialects.postgresql import ENUM, REAL, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from tastoria.core.db import Base

TZ = TIMESTAMP(timezone=True)
ITYPE = ENUM(
    "served", "viewed", "swapped", "cooked", "liked", "disliked", "undone", name="interaction_type_t", create_type=False
)
SWAP_REASON = ENUM("khong_hop_gu", "moi_an", "thieu_thoi_gian", "khac", name="swap_reason_t", create_type=False)


class Interaction(Base):
    __tablename__ = "interactions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    recipe_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("recipes.id"), nullable=False)
    meal_plan_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    meal_plan_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    type: Mapped[str] = mapped_column(ITYPE, nullable=False)
    position: Mapped[int | None] = mapped_column(SmallInteger)
    swap_reason: Mapped[str | None] = mapped_column(SWAP_REASON)
    ranker_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("model_versions.id"))
    propensity: Mapped[float | None] = mapped_column(REAL)
    occurred_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    received_at: Mapped[datetime] = mapped_column(TZ, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["meal_plan_item_id", "meal_plan_id", "recipe_id"],
            ["meal_plan_items.id", "meal_plan_items.meal_plan_id", "meal_plan_items.recipe_id"],
            ondelete="SET NULL (meal_plan_item_id)",
        ),
        ForeignKeyConstraint(["meal_plan_id", "user_id"], ["meal_plans.id", "meal_plans.user_id"], ondelete="CASCADE"),
        Index("ix_interactions_user_id_occurred_at", "user_id", text("occurred_at DESC")),
        Index("ix_interactions_meal_plan_item_id", "meal_plan_item_id"),
        Index("ix_interactions_meal_plan_id_user_id", "meal_plan_id", "user_id"),
    )
