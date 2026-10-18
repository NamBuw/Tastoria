"""RFC 9457 problem details with the stable `code` catalogue of docs/api/openapi-v1.yaml (schema ProblemCode).

`ProblemCode` mirrors the OpenAPI enum exactly, in the same order (tests/unit/test_problem_codes.py compares them).
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from tastoria.core.context import get_request_id

log = logging.getLogger("tastoria.errors")

PROBLEM_BASE = "https://tastoria.ctslab.net/problems/"
PROBLEM_MEDIA_TYPE = "application/problem+json"


class ProblemCode(StrEnum):
    validation_error = "validation_error"
    not_found = "not_found"
    unauthenticated = "unauthenticated"
    token_revoked = "token_revoked"
    forbidden = "forbidden"
    app_too_old = "app_too_old"
    rate_limited = "rate_limited"
    conflict_state = "conflict_state"
    idempotency_key_required = "idempotency_key_required"
    idempotency_key_reused = "idempotency_key_reused"
    idempotency_in_progress = "idempotency_in_progress"
    service_unavailable = "service_unavailable"
    temporarily_unavailable = "temporarily_unavailable"
    email_taken = "email_taken"
    invalid_email = "invalid_email"
    weak_password = "weak_password"
    invalid_credentials = "invalid_credentials"
    login_locked = "login_locked"
    account_deletion_pending = "account_deletion_pending"
    refresh_invalid = "refresh_invalid"
    refresh_reused = "refresh_reused"
    reset_token_invalid = "reset_token_invalid"
    purpose_not_found = "purpose_not_found"
    purpose_not_allowed = "purpose_not_allowed"
    policy_outdated = "policy_outdated"
    consent_required = "consent_required"
    reauth_failed = "reauth_failed"
    invalid_request = "invalid_request"
    reason_required = "reason_required"
    request_not_manual = "request_not_manual"
    request_not_ready = "request_not_ready"
    request_not_downloadable = "request_not_downloadable"
    export_expired = "export_expired"
    age_below_minimum = "age_below_minimum"
    age_confirmation_required = "age_confirmation_required"
    profile_incomplete = "profile_incomplete"
    unknown_code = "unknown_code"
    favorites_limit = "favorites_limit"
    recipe_not_published = "recipe_not_published"
    below_floor_confirmation_required = "below_floor_confirmation_required"
    decryption_failed = "decryption_failed"
    image_too_large = "image_too_large"
    unsupported_media_type = "unsupported_media_type"
    image_too_many_pixels = "image_too_many_pixels"
    model_unavailable = "model_unavailable"
    queue_full = "queue_full"
    scan_not_editable = "scan_not_editable"
    invalid_scan_state = "invalid_scan_state"
    duplicate_item = "duplicate_item"
    unknown_ingredient = "unknown_ingredient"
    qty_kind_mismatch = "qty_kind_mismatch"
    qty_level_required = "qty_level_required"
    unit_conversion_missing = "unit_conversion_missing"
    freshness_check_required = "freshness_check_required"
    image_purged = "image_purged"
    acquired_at_in_future = "acquired_at_in_future"
    invalid_lot_transition = "invalid_lot_transition"
    lot_closed = "lot_closed"
    lot_not_check_level = "lot_not_check_level"
    no_feasible_tray = "no_feasible_tray"
    pin_unsatisfiable = "pin_unsatisfiable"
    no_alternative = "no_alternative"
    meal_plan_not_accepted = "meal_plan_not_accepted"
    meal_plan_not_cookable = "meal_plan_not_cookable"
    cook_session_in_progress = "cook_session_in_progress"
    cook_session_not_in_progress = "cook_session_not_in_progress"
    cook_session_not_completed = "cook_session_not_completed"
    undo_window_expired = "undo_window_expired"
    recipe_without_steps = "recipe_without_steps"
    invalid_iso_week = "invalid_iso_week"
    respondent_token_invalid = "respondent_token_invalid"
    survey_closed = "survey_closed"
    survey_already_completed = "survey_already_completed"
    survey_incomplete = "survey_incomplete"
    invalid_rating = "invalid_rating"
    invalid_favorites = "invalid_favorites"
    survey_form_misconfigured = "survey_form_misconfigured"
    internal_error = "internal_error"


# Codes the backend may send that the contract does not list (none since slice 2 added internal_error).
BACKEND_ONLY_CODES: frozenset[ProblemCode] = frozenset()

# Short Vietnamese titles; constant per code (clients branch on `code`, never on `title`).
TITLES: dict[ProblemCode, str] = {
    ProblemCode.validation_error: "Dữ liệu không hợp lệ",
    ProblemCode.not_found: "Không tìm thấy",
    ProblemCode.unauthenticated: "Chưa đăng nhập hoặc phiên đã hết hạn",
    ProblemCode.token_revoked: "Phiên đã bị thu hồi, cần làm mới",
    ProblemCode.forbidden: "Không đủ quyền",
    ProblemCode.app_too_old: "Phiên bản app quá cũ",
    ProblemCode.rate_limited: "Gửi quá nhiều yêu cầu",
    ProblemCode.conflict_state: "Trạng thái hiện tại không cho phép thao tác này",
    ProblemCode.idempotency_key_required: "Thiếu header Idempotency-Key",
    ProblemCode.idempotency_key_reused: "Idempotency-Key đã dùng cho yêu cầu khác",
    ProblemCode.idempotency_in_progress: "Yêu cầu cùng Idempotency-Key đang được xử lý",
    ProblemCode.service_unavailable: "Dịch vụ tạm thời chưa sẵn sàng",
    ProblemCode.temporarily_unavailable: "Lỗi tạm thời, chưa lưu gì; hãy gửi lại",
    ProblemCode.email_taken: "Email đã có tài khoản",
    ProblemCode.invalid_email: "Email không hợp lệ",
    ProblemCode.weak_password: "Mật khẩu quá ngắn",
    ProblemCode.invalid_credentials: "Email hoặc mật khẩu không đúng",
    ProblemCode.login_locked: "Tạm khoá đăng nhập do sai nhiều lần",
    ProblemCode.account_deletion_pending: "Tài khoản đang chờ xoá",
    ProblemCode.refresh_invalid: "Phiên không còn hiệu lực",
    ProblemCode.refresh_reused: "Phiên đã bị thu hồi do dùng lại token",
    ProblemCode.reset_token_invalid: "Liên kết đặt lại mật khẩu không còn hiệu lực",
    ProblemCode.purpose_not_found: "Mục đích không tồn tại",
    ProblemCode.purpose_not_allowed: "Mục đích không ghi được ở đây",
    ProblemCode.policy_outdated: "Điều khoản đã có phiên bản mới",
    ProblemCode.consent_required: "Cần đồng ý mục đích xử lý dữ liệu",
    ProblemCode.reauth_failed: "Mật khẩu xác nhận không đúng",
    ProblemCode.invalid_request: "Yêu cầu dữ liệu không hợp lệ",
    ProblemCode.request_not_ready: "Yêu cầu chưa hoàn tất",
    ProblemCode.request_not_downloadable: "Yêu cầu này không có tệp tải về",
    ProblemCode.export_expired: "Tệp xuất đã bị dọn",
    ProblemCode.age_below_minimum: "Tastoria chỉ tính mục tiêu năng lượng cho người từ 18 tuổi",
    ProblemCode.age_confirmation_required: "Cần xác nhận đã đủ 18 tuổi",
    ProblemCode.profile_incomplete: "Hồ sơ thiếu chỉ số để tính",
    ProblemCode.unknown_code: "Mã không có trong danh mục",
    ProblemCode.favorites_limit: "Tối đa 5 món hay ăn",
    ProblemCode.recipe_not_published: "Món không ở trạng thái đã công bố",
    ProblemCode.below_floor_confirmation_required: "Mục tiêu dưới mức sàn cần xác nhận",
    ProblemCode.decryption_failed: "Không đọc được hồ sơ sức khoẻ",
    ProblemCode.image_too_large: "Ảnh lớn hơn 3 MB",
    ProblemCode.unsupported_media_type: "Tệp không phải ảnh",
    ProblemCode.image_too_many_pixels: "Ảnh vượt 4096 × 4096 điểm ảnh",
    ProblemCode.model_unavailable: "Chưa có mô hình nhận diện đang chạy",
    ProblemCode.queue_full: "Hàng đợi nhận diện đang đầy",
    ProblemCode.scan_not_editable: "Lần quét không còn sửa được",
    ProblemCode.invalid_scan_state: "Trạng thái lần quét không cho phép thao tác này",
    ProblemCode.duplicate_item: "Nguyên liệu đã có chip trong lần quét",
    ProblemCode.qty_level_required: "Còn chip chưa chọn mức lượng",
    ProblemCode.freshness_check_required: "Còn chip cần kiểm tra trước khi dùng",
    ProblemCode.image_purged: "Ảnh gốc đã được xoá theo hạn 30 ngày",
    ProblemCode.unknown_ingredient: "Nguyên liệu không có hoặc đã ngừng dùng",
    ProblemCode.qty_kind_mismatch: "Cách nhập lượng không hợp với nguyên liệu",
    ProblemCode.unit_conversion_missing: "Chưa có quy đổi đơn vị cho nguyên liệu",
    ProblemCode.acquired_at_in_future: "Ngày mua ở tương lai",
    ProblemCode.invalid_lot_transition: "Không chuyển được trạng thái lô",
    ProblemCode.lot_closed: "Lô đã bỏ hoặc đã dùng hết",
    ProblemCode.lot_not_check_level: "Lô không ở mức kiểm tra trước khi dùng",
    ProblemCode.no_feasible_tray: "Không có mâm khả thi với đồ đang có",
    ProblemCode.pin_unsatisfiable: "Không mâm nào dùng đủ lô ghim",
    ProblemCode.no_alternative: "Không còn món thay phù hợp",
    ProblemCode.meal_plan_not_accepted: "Mâm chưa được nhận",
    ProblemCode.meal_plan_not_cookable: "Mâm không còn nấu được",
    ProblemCode.cook_session_in_progress: "Mâm đang có phiên nấu",
    ProblemCode.cook_session_not_in_progress: "Phiên nấu không còn đang nấu",
    ProblemCode.cook_session_not_completed: "Phiên nấu chưa hoàn tất",
    ProblemCode.undo_window_expired: "Đã quá 10 phút để hoàn tác",
    ProblemCode.recipe_without_steps: "Món chưa có bước nấu",
    ProblemCode.invalid_iso_week: "Tuần không hợp lệ (ISO 8601)",
    ProblemCode.internal_error: "Lỗi máy chủ",
}


class ApiError(Exception):
    """Raise from services/routers; rendered as application/problem+json.

    commit=True asks the Unit of Work to commit what the request already wrote before the error is returned
    (e.g. revoking a refresh-token family on reuse, counting a failed login).
    """

    def __init__(
        self,
        status: int,
        code: ProblemCode,
        detail: str | None = None,
        *,
        headers: dict[str, str] | None = None,
        extra: dict[str, Any] | None = None,
        errors: list[dict[str, str]] | None = None,
        commit: bool = False,
    ) -> None:
        super().__init__(f"{status} {code}: {detail or ''}")
        self.status = status
        self.code = ProblemCode(code)
        self.detail = detail
        self.headers = headers or {}
        self.extra = extra or {}
        self.errors = errors
        self.commit = commit


def problem_body(
    status: int,
    code: ProblemCode,
    *,
    detail: str | None = None,
    instance: str | None = None,
    extra: dict[str, Any] | None = None,
    errors: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "type": PROBLEM_BASE + code.value,
        "title": TITLES.get(code, code.value),
        "status": status,
        "code": code.value,
    }
    if detail:
        body["detail"] = detail
    if instance:
        body["instance"] = instance
    rid = get_request_id()
    if rid:
        body["request_id"] = rid
    if errors:
        body["errors"] = errors
    if extra:
        body.update(extra)
    return body


def problem_response(
    status: int,
    code: ProblemCode,
    *,
    detail: str | None = None,
    instance: str | None = None,
    headers: dict[str, str] | None = None,
    extra: dict[str, Any] | None = None,
    errors: list[dict[str, str]] | None = None,
) -> JSONResponse:
    body = problem_body(status, code, detail=detail, instance=instance, extra=extra, errors=errors)
    return JSONResponse(body, status_code=status, headers=headers, media_type=PROBLEM_MEDIA_TYPE)


# Pydantic error types that mean "wrong syntax or type" (400); everything else violates a domain constraint (422).
_SYNTAX_ERROR_TYPES = {"json_invalid", "model_type", "model_attributes_type", "extra_forbidden", "dict_type"}


def _is_syntax_error(err_type: str) -> bool:
    return err_type in _SYNTAX_ERROR_TYPES or err_type.endswith("_type") or err_type.endswith("_parsing")


def _pointer(loc: tuple[Any, ...]) -> str:
    if not loc:
        return "/"
    where, *rest = loc
    if where == "body":
        return "/" + "/".join(str(p) for p in rest) if rest else "/"
    return f"#/{where}/" + "/".join(str(p) for p in rest)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return problem_response(
            exc.status,
            exc.code,
            detail=exc.detail,
            instance=request.url.path,
            headers=exc.headers,
            extra=exc.extra,
            errors=exc.errors,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        errs = exc.errors()
        status = 400 if any(_is_syntax_error(e.get("type", "")) for e in errs) else 422
        items = [
            {
                "pointer": _pointer(tuple(e.get("loc", ()))),
                "code": e.get("type", "invalid"),
                "message": e.get("msg", ""),
            }
            for e in errs
        ]
        return problem_response(status, ProblemCode.validation_error, instance=request.url.path, errors=items)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {
            404: ProblemCode.not_found,
            401: ProblemCode.unauthenticated,
            403: ProblemCode.forbidden,
            405: ProblemCode.validation_error,
        }.get(exc.status_code, ProblemCode.internal_error)
        return problem_response(exc.status_code, code, instance=request.url.path, headers=getattr(exc, "headers", None))

    @app.exception_handler(OperationalError)
    async def _db_down(request: Request, exc: OperationalError) -> JSONResponse:
        log.error("database operational error", exc_info=exc)
        return problem_response(
            503, ProblemCode.temporarily_unavailable, instance=request.url.path, headers={"Retry-After": "1"}
        )

    # Anything else is caught by RequestContextMiddleware (500 internal_error, keeps X-Request-ID).
