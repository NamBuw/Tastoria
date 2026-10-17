"""HTTP layer of identity: /api/v1/auth/* (UC01–UC04)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from tastoria.core.db import UnitOfWork, get_uow
from tastoria.modules.identity import service
from tastoria.modules.identity.schemas import (
    AuthSession,
    LoginRequest,
    LogoutRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    RefreshRequest,
    RegisterRequest,
)
from tastoria.modules.identity.service import CurrentUser, IdentityDeps, identity_deps

router = APIRouter(prefix="/auth", tags=["identity"])

Uow = Annotated[UnitOfWork, Depends(get_uow)]
Deps = Annotated[IdentityDeps, Depends(identity_deps)]


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/register", status_code=status.HTTP_201_CREATED, operation_id="identity_register_user")
def register(body: RegisterRequest, request: Request, uow: Uow, deps: Deps) -> AuthSession:
    return service.register(
        uow.session, deps, email=body.email, password=body.password, user_agent=request.headers.get("user-agent")
    )


@router.post("/login", operation_id="identity_login_user")
def login(body: LoginRequest, request: Request, uow: Uow, deps: Deps) -> AuthSession:
    return service.login(
        uow.session,
        deps,
        email=body.email,
        password=body.password,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )


@router.post("/refresh", operation_id="identity_refresh_token")
def refresh(body: RefreshRequest, request: Request, uow: Uow, deps: Deps) -> AuthSession:
    return service.refresh(uow.session, deps, refresh_token=body.refresh_token, user_agent=request.headers.get("user-agent"))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, operation_id="identity_logout_session")
def logout(body: LogoutRequest, user: CurrentUser, uow: Uow) -> Response:
    service.logout(uow.session, user_id=user.id, refresh_token=body.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT, operation_id="identity_logout_all_sessions")
def logout_all(user: CurrentUser, uow: Uow) -> Response:
    service.logout_all(uow.session, user_id=user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/password-reset/request", status_code=status.HTTP_204_NO_CONTENT, operation_id="identity_request_password_reset"
)
def password_reset_request(body: PasswordResetRequest, uow: Uow, deps: Deps) -> Response:
    service.request_password_reset(uow, deps, email=body.email)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT, operation_id="identity_confirm_password_reset"
)
def password_reset_confirm(body: PasswordResetConfirm, uow: Uow, deps: Deps) -> Response:
    service.confirm_password_reset(uow, deps, token=body.token, new_password=body.new_password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
