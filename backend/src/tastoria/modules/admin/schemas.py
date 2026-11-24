"""HTTP schemas for admin endpoints (openapi-v1 ModelVersion, ModelDeployment, ModelVersionPage)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

ModelName = Literal[
    "detector",
    "freshness",
    "ranker",
    "substitution",
    "meal_calorie",
    "dish_classifier",
    "mushroom_classifier",
]
ModelStatus = Literal["candidate", "validated", "rejected", "retired"]


class ModelVersionOut(BaseModel):
    id: uuid.UUID
    name: ModelName
    version: str
    artifact_key: str
    sha256: str
    preprocess_version: str | None
    metrics: dict[str, Any]
    gate_report_key: str | None
    mlflow_run_id: str | None
    status: ModelStatus
    is_active: bool
    created_at: datetime


class ModelDeploymentOut(BaseModel):
    name: ModelName
    active_version_id: uuid.UUID
    previous_version_id: uuid.UUID | None
    switched_at: datetime
    switched_by: uuid.UUID | None


class ModelVersionPage(BaseModel):
    items: list[ModelVersionOut]
    next_cursor: str | None
    deployments: list[ModelDeploymentOut]
