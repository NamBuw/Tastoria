"""Tables owned by cooking: cook_sessions (no user_id: the owner is the plan's, 3NF) and cook_schedule_entries."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, ForeignKeyConstraint, Index, Integer, SmallInteger, text
from sqlalchemy.dialects.postgresql import ENUM, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from tastoria.core.db import Base

TZ = TIMESTAMP(timezone=True)
COOK_STATUS = ENUM("in_progress", "completed", "reverted", "abandoned", name="cook_status_t", create_type=False)


class CookSession(Base):
    __tablename__ = "cook_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    meal_plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meal_plans.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(COOK_STATUS, nullable=False, server_default="in_progress")
    serve_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    burners: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    started_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(TZ)
    reverted_at: Mapped[datetime | None] = mapped_column(TZ)
    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=text("now()"))

    __table_args__ = (
        Index(
            "ux_cook_sessions_one_live",
            "meal_plan_id",
            unique=True,
            postgresql_where=text("status IN ('in_progress', 'completed')"),
        ),
        Index("ix_cook_sessions_meal_plan_id", "meal_plan_id"),
    )


class CookScheduleEntry(Base):
    __tablename__ = "cook_schedule_entries"

    cook_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cook_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    recipe_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    step_no: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    start_offset_s: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset_s: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(["recipe_id", "step_no"], ["recipe_steps.recipe_id", "recipe_steps.step_no"]),
    )
