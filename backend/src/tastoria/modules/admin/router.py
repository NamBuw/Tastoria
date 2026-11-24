"""HTTP layer of admin (UC27, UC29, UC30): /admin/data-requests, /admin/audit-log, /admin/models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from tastoria.core.auth import AuthUser, CurrentUser
from tastoria.core.config import Settings
from tastoria.core.db import Uow
from tastoria.core.errors import ApiError, ProblemCode
from tastoria.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from tastoria.core.ratelimit import client_ip, enforce_rate_limit
from tastoria.modules.admin import service
from tastoria.modules.admin.schemas import ModelName, ModelStatus, ModelVersionPage
from tastoria.modules.privacy import service as privacy
from tastoria.modules.privacy.schemas import (
    AdminDataRequestOut,
    AdminDataRequestPage,
    AuditLogEntryPage,
    DataRequestResolve,
    DsrStatus,
    DsrType,
)


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _rate_limit_admin_ip(request: Request) -> None:
    s = _settings(request)
    enforce_rate_limit(request, bucket="admin_ip", subject=client_ip(request, s), limit=120, window_s=60)


router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(_rate_limit_admin_ip)])


def _require_role(
    session: Session,
    user: AuthUser,
    required_role: str,
    *,
    settings: Settings,
    action: str,
    entity: str,
    entity_id: str | None = None,
) -> None:
    if user.role != required_role:
        privacy.write_audit(
            session,
            action=action,
            entity=entity,
            entity_id=entity_id,
            purpose="forbidden",
            actor_user_id=user.id,
            actor_role=user.role,
        )
        raise ApiError(403, ProblemCode.forbidden, commit=True)
    if user.role in service.PRIVILEGED_ROLES and (settings.env == "production" or user.mfa_enabled) and not user.mfa_verified:
        privacy.write_audit(
            session,
            action=action,
            entity=entity,
            entity_id=entity_id,
            purpose="mfa_required",
            actor_user_id=user.id,
            actor_role=user.role,
        )
        raise ApiError(403, ProblemCode.mfa_required, commit=True)


@router.get("/data-requests", operation_id="admin_list_data_requests")
def list_data_requests(
    request: Request,
    user: CurrentUser,
    uow: Uow,
    status: Annotated[list[DsrStatus] | None, Query()] = None,
    type: Annotated[list[DsrType] | None, Query()] = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> AdminDataRequestPage:
    enforce_rate_limit(request, bucket="admin_dsr_list", subject=str(user.id), limit=60, window_s=60)
    _require_role(uow.session, user, "admin", settings=_settings(request), action="dsr.list", entity="dsr_requests")
    return service.list_data_requests(
        uow.session,
        actor_user_id=user.id,
        statuses=list(status or []),
        types=list(type or []),
        cursor=cursor,
        limit=limit,
    )


@router.post("/data-requests/{id}/resolve", operation_id="admin_resolve_data_request")
def resolve_data_request(
    id: uuid.UUID,
    body: DataRequestResolve,
    request: Request,
    user: CurrentUser,
    uow: Uow,
) -> AdminDataRequestOut:
    enforce_rate_limit(request, bucket="admin_dsr_resolve", subject=str(user.id), limit=30, window_s=60)
    _require_role(
        uow.session,
        user,
        "admin",
        settings=_settings(request),
        action="dsr_resolve",
        entity="dsr_requests",
        entity_id=str(id),
    )
    return service.resolve_data_request(
        uow.session,
        actor_user_id=user.id,
        request_id=id,
        body=body,
    )


@router.get("/audit-log", operation_id="admin_list_audit_log")
def list_audit_log(
    request: Request,
    user: CurrentUser,
    uow: Uow,
    actor_user_id: uuid.UUID | None = None,
    entity: Annotated[str | None, Query(max_length=128)] = None,
    action: Annotated[str | None, Query(max_length=128)] = None,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> AuditLogEntryPage:
    enforce_rate_limit(request, bucket="admin_audit_log_list", subject=str(user.id), limit=60, window_s=60)
    _require_role(
        uow.session, user, "admin", settings=_settings(request), action="audit_log.list", entity="audit_log"
    )
    return service.list_audit_log(
        uow.session,
        actor_user_id=user.id,
        filter_actor_user_id=actor_user_id,
        entity=entity,
        action=action,
        from_dt=from_,
        to_dt=to,
        cursor=cursor,
        limit=limit,
    )


@router.get("/models", operation_id="admin_list_models")
def list_models(
    request: Request,
    user: CurrentUser,
    uow: Uow,
    name: ModelName | None = None,
    status: ModelStatus | None = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> ModelVersionPage:
    enforce_rate_limit(request, bucket="admin_models_list", subject=str(user.id), limit=60, window_s=60)
    _require_role(
        uow.session, user, "ml_operator", settings=_settings(request), action="model.list", entity="model_versions"
    )
    return service.list_models(
        uow.session,
        actor_user_id=user.id,
        name=name,
        status=status,
        cursor=cursor,
        limit=limit,
    )
