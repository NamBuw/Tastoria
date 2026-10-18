"""survey public types: bodies of /survey/* and GET /admin/surveys (docs/api/openapi-v1.yaml), and the results the
admin CLI receives from survey.service."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

Channel = Literal["link", "qr"]
Slot = Literal["man", "rau", "canh"]


class _Req(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SurveyRespondentCreate(_Req):
    form_version: str | None = None
    policy_version_id: uuid.UUID
    consent: bool
    channel: Channel


class SurveyAssignmentOut(BaseModel):
    recipe_id: uuid.UUID
    name_vi: str
    slot: Slot
    display_order: int
    is_anchor: bool
    rating: int | None
    never_eaten: bool | None  # None = not answered yet


class SurveyRespondentOut(BaseModel):
    id: uuid.UUID
    form_version: str
    consented_at: datetime
    completed_at: datetime | None
    channel: Channel
    assignments: list[SurveyAssignmentOut]
    favorite_recipe_ids: list[uuid.UUID]


class SurveyRespondentCreated(BaseModel):
    respondent: SurveyRespondentOut
    respondent_token: str


class SurveyRatingPut(_Req):
    # Range and the rating/never_eaten pairing are checked in the service so they answer 422 invalid_rating.
    rating: int | None
    never_eaten: bool


class SurveyRatingOut(BaseModel):
    recipe_id: uuid.UUID
    rating: int | None
    never_eaten: bool
    answered_at: datetime


class FavoriteSet(_Req):
    recipe_ids: list[uuid.UUID]


class SurveyFormSummary(BaseModel):
    id: uuid.UUID
    version: str
    n_anchor: int
    n_random: int
    is_open: bool
    created_at: datetime
    respondents_total: int
    respondents_completed: int


class SurveyFormSummaryPage(BaseModel):
    items: list[SurveyFormSummary]
    next_cursor: str | None


# ---------------------------------------------------------------- CLI results (admin)


@dataclass
class CreatedForm:
    form_id: uuid.UUID
    version: str
    seed: int
    anchors: dict[str, list[str]]  # slot -> recipe names
    closed_version: str | None


@dataclass
class ExportResult:
    form_version: str
    directory: str
    is_open: bool
    respondents: int
    ratings: int
    files: dict[str, dict[str, Any]] = field(default_factory=dict)
