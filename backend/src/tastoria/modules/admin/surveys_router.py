"""HTTP layer of admin for the taste survey: GET /admin/surveys (UC24 flow B). Role `ml_operator` only."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from tastoria.core.auth import CurrentUser
from tastoria.core.db import Uow
from tastoria.core.errors import ApiError, ProblemCode
from tastoria.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from tastoria.modules.admin import service
from tastoria.modules.survey.schemas import SurveyFormSummaryPage

router = APIRouter(tags=["admin"])


@router.get("/admin/surveys", operation_id="admin_list_surveys")
def list_surveys(
    user: CurrentUser,
    uow: Uow,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> SurveyFormSummaryPage:
    if user.role != service.SURVEY_ROLE:  # FR-24-05; nothing is written
        raise ApiError(403, ProblemCode.forbidden)
    return service.list_surveys(uow.session, actor_user_id=user.id, cursor=cursor, limit=limit)
