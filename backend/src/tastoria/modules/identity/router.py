"""HTTP layer of identity: /api/v1/auth/* (UC01–UC04)."""

from __future__ import annotations

import uuid
from typing import Annotated
from urllib.parse import urlparse, urlsplit

from fastapi import APIRouter, Depends, Request, Response, status

from tastoria.core.auth import CurrentUser
from tastoria.core.config import Settings
from tastoria.core.db import Uow
from tastoria.core.errors import ApiError, ProblemCode
from tastoria.core.ratelimit import client_ip, email_subject, enforce_rate_limit
from tastoria.modules.identity import service
from tastoria.modules.identity.schemas import (
    AuthSession,
    ChangePasswordRequest,
    LoginRequest,
    LogoutRequest,
    MfaDisableRequest,
    MfaSetupOut,
    MfaVerifyRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    RefreshRequest,
    RegisterRequest,
    SessionListOut,
    VerifyEmailConfirm,
)
from tastoria.modules.identity.service import IdentityDeps, identity_deps

router = APIRouter(prefix="/auth", tags=["identity"])

Deps = Annotated[IdentityDeps, Depends(identity_deps)]

# TODO(security): Contract #1 specifies `tastoria_refresh` scoped to Path=/api/v1/auth (which precludes `__Host-`
# and allows local HTTP dev without `__Secure-` rejection). Production forces `Secure=True`.
REFRESH_COOKIE_NAME = "tastoria_refresh"
REFRESH_COOKIE_PATH = "/api/v1/auth"


def _is_web_client(request: Request) -> bool:
    return request.headers.get("x-client-platform", "").strip().lower() == "web"


def _is_https(request: Request) -> bool:
    proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    return proto == "https" or request.url.scheme == "https"


def _cookie_secure(request: Request, settings: Settings) -> bool:
    return settings.env == "production" or _is_https(request)


def _normalize_origin(raw: str) -> str | None:
    s = raw.strip()
    if not s or s.lower() == "null":
        return None
    parts = urlsplit(s)
    if not parts.scheme or not parts.netloc or parts.username or parts.password:
        return None
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        return None
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if not host:
        return None
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    try:
        port = parts.port
    except ValueError:
        return None
    if port is not None and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        return f"{scheme}://{host}:{port}"
    return f"{scheme}://{host}"


def _is_same_origin_loopback(request: Request, norm_origin: str) -> bool:
    parsed = urlparse(norm_origin)
    expected_scheme = "https" if _is_https(request) else "http"
    req_host = (request.headers.get("host") or "").strip().lower()
    return (
        parsed.hostname in {"127.0.0.1", "localhost"}
        and parsed.scheme == expected_scheme
        and bool(req_host)
        and parsed.netloc == req_host
    )


# TODO(security): Contract #1 enforces non-simple header `X-Client-Platform: web` (which triggers CORS preflight
# on cross-origin browser requests) + `Origin`/`Sec-Fetch-Site` validation + `SameSite=Lax` + strict CORS
# `allow_origins` rather than a separate double-submit CSRF cookie (`tastoria_csrf`/`X-CSRF-Token`) so the
# M1<->M4 web auth contract stays intact without client storage/cookie changes. Revisit if permissive CORS is added.
def _verify_refresh_csrf(request: Request, deps: IdentityDeps) -> None:
    if not _is_web_client(request):
        raise ApiError(403, ProblemCode.forbidden, "Thiếu header X-Client-Platform: web")
    sec_fetch_site = request.headers.get("sec-fetch-site")
    if sec_fetch_site is not None and sec_fetch_site.strip().lower() == "cross-site":
        raise ApiError(403, ProblemCode.forbidden, "Từ chối yêu cầu cross-site")
    raw_origin = request.headers.get("origin")
    if raw_origin is not None:
        norm_origin = _normalize_origin(raw_origin)
        allowed = {o for item in deps.settings.effective_cors_origins if (o := _normalize_origin(item)) is not None}
        if norm_origin is None or (norm_origin not in allowed and not _is_same_origin_loopback(request, norm_origin)):
            raise ApiError(403, ProblemCode.forbidden, "Origin không được phép")


def _set_refresh_cookie(
    response: Response, request: Request, settings: Settings, token: str, max_age_s: int
) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        max_age=max_age_s,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(request, settings),
    )


def _clear_refresh_cookie(response: Response, request: Request, settings: Settings) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(request, settings),
    )


def _maybe_cookie_session(request: Request, response: Response, deps: IdentityDeps, auth: AuthSession) -> AuthSession:
    if _is_web_client(request) and auth.refresh_token:
        _set_refresh_cookie(
            response, request, deps.settings, auth.refresh_token, deps.settings.refresh_token_ttl_days * 86400
        )
        return auth.model_copy(update={"refresh_token": None})
    return auth


@router.post("/register", status_code=status.HTTP_201_CREATED, operation_id="identity_register_user")
def register(body: RegisterRequest, request: Request, response: Response, uow: Uow, deps: Deps) -> AuthSession:
    ip = client_ip(request, deps.settings)
    enforce_rate_limit(
        request,
        bucket="auth_register",
        subject=ip,
        limit=10,
        window_s=300,
    )
    auth = service.register(
        uow,
        deps,
        email=body.email,
        password=body.password,
        user_agent=request.headers.get("user-agent"),
        ip_address=ip,
    )
    return _maybe_cookie_session(request, response, deps, auth)


@router.post("/login", operation_id="identity_login_user")
def login(body: LoginRequest, request: Request, response: Response, uow: Uow, deps: Deps) -> AuthSession:
    ip = client_ip(request, deps.settings)
    enforce_rate_limit(
        request,
        bucket="auth_login_ip",
        subject=ip,
        limit=60,
        window_s=300,
    )
    auth = service.login(
        uow.session,
        deps,
        email=body.email,
        password=body.password,
        ip=ip,
        user_agent=request.headers.get("user-agent"),
        totp_code=body.totp_code,
    )
    return _maybe_cookie_session(request, response, deps, auth)


@router.post("/refresh", operation_id="identity_refresh_token")
def refresh(
    request: Request,
    response: Response,
    uow: Uow,
    deps: Deps,
    body: RefreshRequest | None = None,
) -> AuthSession:
    ip = client_ip(request, deps.settings)
    enforce_rate_limit(
        request,
        bucket="auth_refresh_ip",
        subject=ip,
        limit=60,
        window_s=60,
    )
    body_token = body.refresh_token if body and body.refresh_token else None
    cookie_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if body_token is None and cookie_token is not None:
        _verify_refresh_csrf(request, deps)
    token = body_token or cookie_token
    if not token:
        raise ApiError(401, ProblemCode.refresh_invalid)
    auth = service.refresh(
        uow.session,
        deps,
        refresh_token=token,
        user_agent=request.headers.get("user-agent"),
        ip_address=ip,
    )
    use_cookie = _is_web_client(request) or (body_token is None and cookie_token is not None)
    if use_cookie and auth.refresh_token:
        _set_refresh_cookie(
            response, request, deps.settings, auth.refresh_token, deps.settings.refresh_token_ttl_days * 86400
        )
        return auth.model_copy(update={"refresh_token": None})
    return auth


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, operation_id="identity_logout_session")
def logout(
    request: Request,
    user: CurrentUser,
    uow: Uow,
    deps: Deps,
    body: LogoutRequest | None = None,
) -> Response:
    body_token = body.refresh_token if body and body.refresh_token else None
    cookie_token = request.cookies.get(REFRESH_COOKIE_NAME)
    token = body_token or cookie_token
    if token:
        service.logout(uow.session, user_id=user.id, refresh_token=token)
    resp = Response(status_code=status.HTTP_204_NO_CONTENT)
    if _is_web_client(request) or cookie_token is not None:
        _clear_refresh_cookie(resp, request, deps.settings)
    return resp


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT, operation_id="identity_logout_all_sessions")
def logout_all(request: Request, user: CurrentUser, uow: Uow, deps: Deps) -> Response:
    service.logout_all(uow.session, user_id=user.id)
    resp = Response(status_code=status.HTTP_204_NO_CONTENT)
    if _is_web_client(request) or REFRESH_COOKIE_NAME in request.cookies:
        _clear_refresh_cookie(resp, request, deps.settings)
    return resp


@router.post(
    "/password-reset/request", status_code=status.HTTP_204_NO_CONTENT, operation_id="identity_request_password_reset"
)
def password_reset_request(body: PasswordResetRequest, request: Request, uow: Uow, deps: Deps) -> Response:
    enforce_rate_limit(
        request,
        bucket="auth_reset_ip",
        subject=client_ip(request, deps.settings),
        limit=10,
        window_s=300,
    )
    enforce_rate_limit(
        request,
        bucket="auth_reset_email",
        subject=email_subject(body.email),
        limit=5,
        window_s=900,
    )
    service.request_password_reset(uow, deps, email=body.email)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT, operation_id="identity_confirm_password_reset"
)
def password_reset_confirm(body: PasswordResetConfirm, request: Request, uow: Uow, deps: Deps) -> Response:
    enforce_rate_limit(
        request,
        bucket="auth_reset_confirm_ip",
        subject=client_ip(request, deps.settings),
        limit=10,
        window_s=300,
    )
    service.confirm_password_reset(uow, deps, token=body.token, new_password=body.new_password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/verify-email/request",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="identity_request_email_verification",
)
def verify_email_request(request: Request, user: CurrentUser, uow: Uow, deps: Deps) -> Response:
    enforce_rate_limit(
        request,
        bucket="auth_verify_email_ip",
        subject=client_ip(request, deps.settings),
        limit=10,
        window_s=300,
    )
    enforce_rate_limit(
        request,
        bucket="auth_verify_email_user",
        subject=str(user.id),
        limit=5,
        window_s=900,
    )
    service.request_email_verification(uow, deps, user_id=user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/verify-email/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="identity_confirm_email_verification",
)
def verify_email_confirm(body: VerifyEmailConfirm, request: Request, uow: Uow, deps: Deps) -> Response:
    enforce_rate_limit(
        request,
        bucket="auth_verify_confirm_ip",
        subject=client_ip(request, deps.settings),
        limit=10,
        window_s=300,
    )
    service.confirm_email_verification(uow.session, token=body.token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/change-password", operation_id="identity_change_password")
def change_password(
    body: ChangePasswordRequest,
    request: Request,
    response: Response,
    user: CurrentUser,
    uow: Uow,
    deps: Deps,
) -> AuthSession:
    enforce_rate_limit(
        request,
        bucket="auth_change_pw_user",
        subject=str(user.id),
        limit=10,
        window_s=300,
    )
    ip = client_ip(request, deps.settings)
    auth = service.change_password(
        uow.session,
        deps,
        user_id=user.id,
        current_password=body.current_password,
        new_password=body.new_password,
        ip_address=ip,
        user_agent=request.headers.get("user-agent"),
        mfa_verified=user.mfa_verified,
    )
    return _maybe_cookie_session(request, response, deps, auth)


@router.get("/sessions", operation_id="identity_list_sessions")
def list_sessions(request: Request, user: CurrentUser, uow: Uow, deps: Deps) -> SessionListOut:
    enforce_rate_limit(
        request,
        bucket="auth_sessions_list",
        subject=str(user.id),
        limit=60,
        window_s=60,
    )
    return service.list_sessions(
        uow.session,
        user_id=user.id,
        current_refresh_token=request.cookies.get(REFRESH_COOKIE_NAME),
    )


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="identity_revoke_session",
)
def revoke_session(session_id: uuid.UUID, request: Request, user: CurrentUser, uow: Uow, deps: Deps) -> Response:
    enforce_rate_limit(
        request,
        bucket="auth_sessions_delete",
        subject=str(user.id),
        limit=30,
        window_s=60,
    )
    service.revoke_session(uow.session, user_id=user.id, session_id=session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/mfa/setup", operation_id="identity_mfa_setup")
def mfa_setup(request: Request, user: CurrentUser, uow: Uow, deps: Deps) -> MfaSetupOut:
    enforce_rate_limit(
        request,
        bucket="auth_mfa_setup",
        subject=str(user.id),
        limit=10,
        window_s=300,
    )
    return service.mfa_setup(uow.session, deps, user_id=user.id)


@router.post("/mfa/verify", operation_id="identity_mfa_verify")
def mfa_verify(
    body: MfaVerifyRequest,
    request: Request,
    response: Response,
    user: CurrentUser,
    uow: Uow,
    deps: Deps,
) -> AuthSession:
    enforce_rate_limit(
        request,
        bucket="auth_mfa_verify",
        subject=str(user.id),
        limit=10,
        window_s=300,
    )
    ip = client_ip(request, deps.settings)
    auth = service.mfa_verify(
        uow.session,
        deps,
        user_id=user.id,
        code=body.code,
        user_agent=request.headers.get("user-agent"),
        ip_address=ip,
    )
    return _maybe_cookie_session(request, response, deps, auth)


@router.post("/mfa/disable", status_code=status.HTTP_204_NO_CONTENT, operation_id="identity_mfa_disable")
def mfa_disable(body: MfaDisableRequest, request: Request, user: CurrentUser, uow: Uow, deps: Deps) -> Response:
    enforce_rate_limit(
        request,
        bucket="auth_mfa_disable",
        subject=str(user.id),
        limit=10,
        window_s=300,
    )
    ip = client_ip(request, deps.settings)
    service.mfa_disable(
        uow.session,
        deps,
        user_id=user.id,
        password=body.password,
        code=body.code,
        ip_address=ip,
    )
    resp = Response(status_code=status.HTTP_204_NO_CONTENT)
    if _is_web_client(request) or REFRESH_COOKIE_NAME in request.cookies:
        _clear_refresh_cookie(resp, request, deps.settings)
    return resp
