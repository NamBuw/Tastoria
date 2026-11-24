"""HTTP layer of admin for the taste survey: GET /admin/surveys (UC24 flow B). Role `ml_operator` only."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from tastoria.core.auth import CurrentUser
from tastoria.core.config import Settings
from tastoria.core.db import Uow
from tastoria.core.errors import ApiError, ProblemCode
from tastoria.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from tastoria.core.ratelimit import client_ip, enforce_rate_limit
from tastoria.modules.admin import service
from tastoria.modules.survey.schemas import SurveyFormSummaryPage


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _rate_limit_admin_ip(request: Request) -> None:
    s = _settings(request)
    enforce_rate_limit(request, bucket="admin_ip", subject=client_ip(request, s), limit=120, window_s=60)


router = APIRouter(tags=["admin"], dependencies=[Depends(_rate_limit_admin_ip)])


@router.get("/admin/surveys", operation_id="admin_list_surveys")
def list_surveys(
    request: Request,
    user: CurrentUser,
    uow: Uow,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> SurveyFormSummaryPage:
    enforce_rate_limit(request, bucket="admin_surveys_list", subject=str(user.id), limit=60, window_s=60)
    if user.role != service.SURVEY_ROLE:  # FR-24-05; nothing is written
        raise ApiError(403, ProblemCode.forbidden)
    if (_settings(request).env == "production" or user.mfa_enabled) and not user.mfa_verified:
        raise ApiError(403, ProblemCode.mfa_required)
    return service.list_surveys(uow.session, actor_user_id=user.id, cursor=cursor, limit=limit)
