"""Public data shapes of mlops (other modules import these and service.py only)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class ModelVersionView:
    id: uuid.UUID
    name: str
    version: str
    artifact_key: str
    sha256: str  # lower-case hex
    preprocess_version: str | None
    metrics: dict[str, Any]
    status: str
    created_at: datetime
    class_map: dict[int, int] = field(default_factory=dict)  # detector output index -> vision_classes.id
    is_active: bool = False
    gate_report_key: str | None = None
    mlflow_run_id: str | None = None


@dataclass(frozen=True)
class DeploymentView:
    name: str
    active_version_id: uuid.UUID
    previous_version_id: uuid.UUID | None
    switched_at: datetime
    switched_by: uuid.UUID | None = None


class MlopsError(Exception):
    """A refused operator command (exit code 1 in the CLI); nothing was written."""
