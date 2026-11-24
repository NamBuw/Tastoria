"""HTTP layer of survey: /survey/respondents* (UC23). Public; every call after the first carries X-Respondent-Token."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from tastoria.core.config import Settings
from tastoria.core.db import Uow
from tastoria.core.ratelimit import client_ip, enforce_rate_limit
from tastoria.modules.survey import service
from tastoria.modules.survey.schemas import (
    FavoriteSet,
    SurveyRatingOut,
    SurveyRatingPut,
    SurveyRespondentCreate,
    SurveyRespondentCreated,
    SurveyRespondentOut,
)

router = APIRouter(tags=["survey"])
Token = Annotated[str | None, Header(alias="X-Respondent-Token")]


def _settings(request: Request) -> Settings:
    return request.app.state.settings


@router.post(
    "/survey/respondents",
    status_code=201,
    operation_id="survey_create_respondent",
    response_model=SurveyRespondentCreated,
)
def create_respondent(body: SurveyRespondentCreate, request: Request, uow: Uow) -> JSONResponse:
    s = _settings(request)
    enforce_rate_limit(request, bucket="survey_create", subject=client_ip(request, s), limit=50, window_s=300)
    out = service.create_respondent(uow.session, s, body)
    return JSONResponse(
        out.model_dump(mode="json"),
        status_code=201,
        headers={"Location": f"/api/v1/survey/respondents/{out.respondent.id}"},
    )


@router.get("/survey/respondents/{id}", operation_id="survey_get_respondent")
def get_respondent(id: uuid.UUID, request: Request, uow: Uow, token: Token = None) -> SurveyRespondentOut:
    s = _settings(request)
    enforce_rate_limit(
        request, bucket="survey_step", subject=f"{client_ip(request, s)}:{id}", limit=180, window_s=60
    )
    return service.get_respondent(uow.session, s, id, token)


@router.put("/survey/respondents/{id}/ratings/{recipeId}", operation_id="survey_put_rating")
def put_rating(
    id: uuid.UUID,
    recipeId: uuid.UUID,  # noqa: N803 (path parameter name of the contract)
    body: SurveyRatingPut,
    request: Request,
    uow: Uow,
    token: Token = None,
) -> SurveyRatingOut:
    s = _settings(request)
    enforce_rate_limit(
        request, bucket="survey_step", subject=f"{client_ip(request, s)}:{id}", limit=180, window_s=60
    )
    return service.put_rating(uow.session, s, id, token, recipeId, body)


@router.put("/survey/respondents/{id}/favorites", operation_id="survey_set_favorites")
def set_favorites(id: uuid.UUID, body: FavoriteSet, request: Request, uow: Uow, token: Token = None) -> FavoriteSet:
    s = _settings(request)
    enforce_rate_limit(
        request, bucket="survey_step", subject=f"{client_ip(request, s)}:{id}", limit=180, window_s=60
    )
    return service.set_favorites(uow.session, s, id, token, body)


@router.post("/survey/respondents/{id}/complete", operation_id="survey_complete_respondent")
def complete(id: uuid.UUID, request: Request, uow: Uow, token: Token = None) -> SurveyRespondentOut:
    s = _settings(request)
    enforce_rate_limit(
        request, bucket="survey_step", subject=f"{client_ip(request, s)}:{id}", limit=180, window_s=60
    )
    return service.complete(uow.session, s, id, token)
