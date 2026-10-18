"""Tables owned by mlops: model_versions, model_version_classes, model_deployments (db/schema.sql, ST07)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    LargeBinary,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from tastoria.core.db import Base

TZ = TIMESTAMP(timezone=True)
MODEL_NAME = ENUM("detector", "freshness", "ranker", "substitution", name="model_name_t", create_type=False)
MODEL_STATUS = ENUM("candidate", "validated", "rejected", "retired", name="model_status_t", create_type=False)


class ModelVersion(Base):
    __tablename__ = "model_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(MODEL_NAME, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_key: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    preprocess_version: Mapped[str | None] = mapped_column(Text)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False)
    gate_report_key: Mapped[str | None] = mapped_column(Text)
    mlflow_run_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(MODEL_STATUS, nullable=False, server_default="candidate")
    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=text("now()"))

    __table_args__ = (UniqueConstraint("name", "version"), UniqueConstraint("id", "name"))


class ModelVersionClass(Base):
    """Detector output index → vision_classes.id for one model version."""

    __tablename__ = "model_version_classes"

    model_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_versions.id"), primary_key=True
    )
    class_index: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    vision_class_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("vision_classes.id"), nullable=False)

    __table_args__ = (
        UniqueConstraint("model_version_id", "vision_class_id"),
        CheckConstraint("class_index >= 0", name="class_index"),
    )


class ModelDeployment(Base):
    """The one pointer to the version that runs, per model name (spec v2 §8, ST07)."""

    __tablename__ = "model_deployments"

    name: Mapped[str] = mapped_column(MODEL_NAME, primary_key=True)
    active_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True)
    previous_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    switched_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    switched_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    __table_args__ = (
        ForeignKeyConstraint(["active_version_id", "name"], ["model_versions.id", "model_versions.name"]),
        ForeignKeyConstraint(["previous_version_id", "name"], ["model_versions.id", "model_versions.name"]),
        CheckConstraint("previous_version_id <> active_version_id", name="previous"),
    )
