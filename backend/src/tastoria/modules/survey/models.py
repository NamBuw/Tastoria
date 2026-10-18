"""Tables owned by survey: survey_forms, survey_form_anchors, survey_respondents, survey_assignments, survey_ratings,
survey_favorites (db/schema.sql, module survey).

No column identifies a respondent beyond the random UUID (FR-23-13): no email, name, IP or user agent.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
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
SURVEY_CHANNEL = ENUM("link", "qr", name="survey_channel_t", create_type=False)


class SurveyForm(Base):
    __tablename__ = "survey_forms"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    version: Mapped[str] = mapped_column(Text, nullable=False)
    n_anchor: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    n_random: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    is_open: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=func.now())

    __table_args__ = (UniqueConstraint("version", name="uq_survey_forms_version"),)


class SurveyFormAnchor(Base):
    """Fixed once the form is open or has respondents (trigger trg_survey_form_anchors_guard)."""

    __tablename__ = "survey_form_anchors"

    form_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("survey_forms.id"), primary_key=True)
    recipe_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("recipes.id"), primary_key=True)


class SurveyRespondent(Base):
    __tablename__ = "survey_respondents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    form_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("survey_forms.id"), nullable=False)
    policy_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("policy_versions.id"), nullable=False
    )
    consented_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(TZ)
    channel: Mapped[str] = mapped_column(SURVEY_CHANNEL, nullable=False)


class SurveyAssignment(Base):
    """Write-once (trigger trg_survey_assignments_write_once)."""

    __tablename__ = "survey_assignments"

    respondent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("survey_respondents.id", ondelete="CASCADE"), primary_key=True
    )
    recipe_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("recipes.id"), primary_key=True)
    display_order: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    is_anchor: Mapped[bool] = mapped_column(Boolean, nullable=False)

    __table_args__ = (
        UniqueConstraint("respondent_id", "display_order", name="uq_survey_assignments_respondent_id_display_order"),
    )


class SurveyRating(Base):
    __tablename__ = "survey_ratings"

    respondent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    recipe_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    rating: Mapped[int | None] = mapped_column(SmallInteger)
    never_eaten: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    answered_at: Mapped[datetime] = mapped_column(TZ, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["respondent_id", "recipe_id"],
            ["survey_assignments.respondent_id", "survey_assignments.recipe_id"],
            ondelete="CASCADE",
        ),
        Index("ix_survey_ratings_recipe_id", "recipe_id"),
    )


class SurveyFavorite(Base):
    __tablename__ = "survey_favorites"

    respondent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("survey_respondents.id", ondelete="CASCADE"), primary_key=True
    )
    recipe_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("recipes.id"), primary_key=True)
