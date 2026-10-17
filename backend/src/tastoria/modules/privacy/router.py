"""HTTP layer of privacy: /policies/{purpose}/current, /me/consents*, /me/data-requests* (UC05–UC08)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse, Response

from tastoria.core.db import Uow
from tastoria.modules.identity.service import CurrentUser
from tastoria.modules.privacy import service
from tastoria.modules.privacy.schemas import (
    ConsentDecisionBatch,
    ConsentList,
    ConsentWithdrawRequest,
    ConsentWithdrawResult,
    DataRequestCreate,
    DataRequestOut,
    PolicyVersionOut,
)
from tastoria.modules.privacy.service import PrivacyDeps, privacy_deps

router = APIRouter(tags=["privacy"])
Deps = Annotated[PrivacyDeps, Depends(privacy_deps)]


def _app_version(request: Request) -> str | None:
    return request.headers.get("x-app-version")


@router.get("/policies/{purpose}/current", operation_id="privacy_get_current_policy")
def get_current_policy(purpose: str, uow: Uow) -> PolicyVersionOut:
    return service.get_current_policy(uow.session, purpose)


@router.get("/me/consents", operation_id="privacy_list_consents")
def list_consents(user: CurrentUser, uow: Uow) -> ConsentList:
    return service.list_consents(uow.session, user.id)


@router.post("/me/consents", operation_id="privacy_record_consents")
def record_consents(
    body: ConsentDecisionBatch, request: Request, user: CurrentUser, uow: Uow, deps: Deps
) -> ConsentList:
    return service.record_consents(
        uow, deps, user_id=user.id, channel=body.channel, decisions=body.decisions, app_version=_app_version(request)
    )


@router.post("/me/consents/{purpose}/withdraw", operation_id="privacy_withdraw_consent")
def withdraw_consent(
    purpose: str,
    request: Request,
    user: CurrentUser,
    uow: Uow,
    deps: Deps,
    body: Annotated[ConsentWithdrawRequest | None, Body()] = None,
) -> ConsentWithdrawResult:
    channel = body.channel if body else "settings"
    return service.withdraw_consent(
        uow, deps, user_id=user.id, purpose=purpose, channel=channel, app_version=_app_version(request)
    )


@router.post("/me/data-requests", status_code=202, operation_id="privacy_create_data_request")
def create_data_request(body: DataRequestCreate, user: CurrentUser, uow: Uow, deps: Deps) -> JSONResponse:
    res = service.create_data_request(
        uow, deps, user_id=user.id, type_=body.type, note=body.note, password=body.password
    )
    headers = {"Location": f"/api/v1/me/data-requests/{res.request.id}"}
    if res.created:
        headers["Retry-After"] = "60"
    return JSONResponse(res.request.model_dump(mode="json"), status_code=202 if res.created else 200, headers=headers)


@router.get("/me/data-requests/{id}", operation_id="privacy_get_data_request")
def get_data_request(id: uuid.UUID, user: CurrentUser, uow: Uow, deps: Deps) -> DataRequestOut:
    return service.get_data_request(uow.session, deps, user_id=user.id, request_id=id)


@router.get("/me/data-requests/{id}/download", operation_id="privacy_download_data_export")
def download(id: uuid.UUID, user: CurrentUser, uow: Uow, deps: Deps) -> Response:
    return service.download_export(uow.session, deps, user_id=user.id, request_id=id)
