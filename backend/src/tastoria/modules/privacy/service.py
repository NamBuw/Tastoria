"""privacy public interface (M03): consents by purpose, policy versions, data-subject requests, audit log.

Cross-module data (export, erase by purpose, account deletion) goes through `SubjectDataHandler`s that the
assembly root registers (ADR 0001, dependency inversion): privacy never imports business modules.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import logging
import os
import uuid
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, Protocol

from fastapi import Request
from fastapi.responses import Response
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from tastoria.core.clock import utcnow
from tastoria.core.config import Settings
from tastoria.core.context import get_request_id
from tastoria.core.db import UnitOfWork, run_in_uow
from tastoria.core.errors import ApiError, ProblemCode
from tastoria.modules.identity import service as identity
from tastoria.modules.privacy.models import AuditLog, ConsentEvent, ConsentPurpose, DsrRequest, PolicyVersion
from tastoria.modules.privacy.schemas import (
    ConsentDecision,
    ConsentList,
    ConsentPurposeOut,
    ConsentState,
    ConsentWithdrawResult,
    DataRequestOut,
    PolicyVersionOut,
)

log = logging.getLogger("tastoria.privacy")

POLICY_DIR = Path(__file__).resolve().parent / "policies"
PURPOSES = ("health_profile", "personalization", "photo_contribution", "survey")
USER_PURPOSES = ("health_profile", "personalization", "photo_contribution")  # survey is for respondents (A03)
AUTO_TYPES = ("export", "delete", "withdraw")  # completed by the system ≤ 24 h (BR-DSR-01)
MANUAL_TYPES = ("correct", "restrict", "object")  # closed by an admin (UC08, UC27)
DUE = {
    "export": timedelta(hours=24),
    "delete": timedelta(hours=24),
    "withdraw": timedelta(hours=24),
    "access": timedelta(hours=24),
    "correct": timedelta(days=10),
    "restrict": timedelta(days=15),
    "object": timedelta(days=15),
}


# ---------------------------------------------------------------- cross-module handlers


class SubjectDataHandler(Protocol):
    """Registered per module by tastoria.app. Every method must be idempotent (jobs may run twice)."""

    name: str

    def export(self, session: Session, user_id: uuid.UUID) -> dict[str, list[dict[str, Any]]]: ...

    def erase_purpose(self, session: Session, user_id: uuid.UUID, purpose: str) -> None: ...

    def erase_files(self, user_id: uuid.UUID) -> None: ...


@dataclass
class PrivacyDeps:
    settings: Settings
    sessionmaker: sessionmaker[Session]
    handlers: list[SubjectDataHandler] = field(default_factory=list)

    @property
    def storage(self) -> Path:
        return Path(self.settings.storage_dir)

    def schedule(self, uow: UnitOfWork, request_id: uuid.UUID) -> None:
        """Run the DSR job after the request commits. Only `sync` exists in this slice (RQ comes with scans);
        `tastoria jobs process-dsr` re-runs anything left open if the process died in between."""

        def run() -> None:
            process_request(self, request_id)

        uow.after_commit(run)


def privacy_deps(request: Request) -> PrivacyDeps:
    return request.app.state.privacy


# ---------------------------------------------------------------- audit log


def write_audit(
    session: Session,
    *,
    action: str,
    entity: str,
    entity_id: str | None = None,
    purpose: str | None = None,
    actor_user_id: uuid.UUID | None = None,
    actor_role: str = "user",
) -> None:
    session.add(
        AuditLog(
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            action=action,
            entity=entity,
            entity_id=entity_id,
            purpose=purpose,
            request_id=get_request_id(),
            created_at=utcnow(),
        )
    )


def subject_ref(settings: Settings, user_id: uuid.UUID) -> bytes:
    return hmac.new(settings.dsr_hmac_key.encode(), user_id.bytes, hashlib.sha256).digest()


# ---------------------------------------------------------------- policies


def _purpose(session: Session, code: str) -> ConsentPurpose:
    p = session.get(ConsentPurpose, code) if code in PURPOSES else None
    if p is None:
        raise ApiError(404, ProblemCode.purpose_not_found)
    return p


def current_policy(session: Session, purpose: str) -> PolicyVersion | None:
    return session.scalars(
        select(PolicyVersion)
        .where(PolicyVersion.purpose_code == purpose, PolicyVersion.effective_from <= text("now()"))
        .order_by(PolicyVersion.effective_from.desc())
        .limit(1)
    ).first()


def policy_version_labels(session: Session, ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, str]:
    """policy_versions.id -> version label (survey export, UC24)."""
    wanted = list(set(ids))
    if not wanted:
        return {}
    rows = session.execute(select(PolicyVersion.id, PolicyVersion.version).where(PolicyVersion.id.in_(wanted)))
    return {pid: version for pid, version in rows}


def _policy_text(pv: PolicyVersion) -> str:
    path = POLICY_DIR / f"{pv.purpose_code}-{pv.version}.md"
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        log.error("policy text missing", extra={"path": str(path)})
        raise ApiError(500, ProblemCode.internal_error, "Thiếu văn bản điều khoản.") from None
    if hashlib.sha256(raw).digest() != bytes(pv.text_sha256):
        log.error("policy text does not match text_sha256", extra={"path": str(path)})
        raise ApiError(500, ProblemCode.internal_error, "Văn bản điều khoản không khớp bản đã công bố.")
    return raw.decode("utf-8")


def _purpose_out(p: ConsentPurpose) -> ConsentPurposeOut:
    return ConsentPurposeOut(
        code=p.code,
        name_vi=p.name_vi,
        description_vi=p.description_vi,
        data_category=p.data_category,
        is_sensitive=p.is_sensitive,
        is_required=p.is_required,
    )


def list_purposes(session: Session) -> list[ConsentPurposeOut]:
    """The consent purposes (BR-CONSENT-01) for GET /reference."""
    return [_purpose_out(p) for p in session.scalars(select(ConsentPurpose).order_by(ConsentPurpose.code))]


def get_current_policy(session: Session, purpose: str) -> PolicyVersionOut:
    p = _purpose(session, purpose)
    pv = current_policy(session, purpose)
    if pv is None:
        raise ApiError(404, ProblemCode.purpose_not_found, "Mục đích chưa có điều khoản hiệu lực.")
    return PolicyVersionOut(
        id=pv.id,
        purpose_code=pv.purpose_code,
        version=pv.version,
        text_sha256=bytes(pv.text_sha256).hex(),
        effective_from=pv.effective_from,
        purpose=_purpose_out(p),
        text_vi=_policy_text(pv),
    )


# ---------------------------------------------------------------- consent state (view v_current_consents)

_CURRENT = text(
    "SELECT purpose_code, action, is_granted, policy_version_id, policy_version, on_current_policy, decided_at "
    "FROM v_current_consents WHERE user_id = :u"
)


def _states(session: Session, user_id: uuid.UUID) -> dict[str, ConsentState]:
    rows = {r.purpose_code: r for r in session.execute(_CURRENT, {"u": user_id})}
    out: dict[str, ConsentState] = {}
    for code in PURPOSES:
        cur = current_policy(session, code)
        r = rows.get(code)
        if r is None:
            state = "none"
        elif r.action == "withdraw":
            state = "withdrawn"
        else:
            state = "granted" if r.on_current_policy else "superseded"
        out[code] = ConsentState(
            purpose_code=code,
            state=state,
            policy_version_id=r.policy_version_id if r else None,
            version=r.policy_version if r else None,
            current_policy_version_id=cur.id if cur else None,
            decided_at=r.decided_at if r else None,
        )
    return out


def list_consents(session: Session, user_id: uuid.UUID) -> ConsentList:
    return ConsentList(items=list(_states(session, user_id).values()))


def has_consent(session: Session, user_id: uuid.UUID, purpose: str) -> bool:
    """True only for a grant of the policy version currently in force (FR-05-07: none/withdrawn/superseded → False)."""
    row = session.execute(
        text(
            "SELECT is_granted AND on_current_policy FROM v_current_consents WHERE user_id = :u AND purpose_code = :p"
        ),
        {"u": user_id, "p": purpose},
    ).first()
    return bool(row and row[0])


def _lock_consents(session: Session, user_id: uuid.UUID) -> None:
    """Serialise consent decisions of one user (two devices, or a retry racing the first request)."""
    session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"consent:{user_id}"})


def record_consents(
    uow: UnitOfWork,
    deps: PrivacyDeps,
    *,
    user_id: uuid.UUID,
    channel: str,
    decisions: list[ConsentDecision],
    app_version: str | None,
) -> ConsentList:
    session = uow.session
    _lock_consents(session, user_id)
    resolved: list[tuple[ConsentDecision, PolicyVersion]] = []
    seen: set[str] = set()
    for d in decisions:  # validate everything before writing anything (UC05 6a, 6c)
        pv = session.get(PolicyVersion, d.policy_version_id)
        if pv is None or pv.purpose_code not in USER_PURPOSES:
            raise ApiError(422, ProblemCode.purpose_not_allowed, extra={"policy_version_id": str(d.policy_version_id)})
        if pv.purpose_code in seen:
            raise ApiError(
                422,
                ProblemCode.validation_error,
                errors=[{"pointer": "/decisions", "code": "duplicate_purpose", "message": pv.purpose_code}],
            )
        seen.add(pv.purpose_code)
        cur = current_policy(session, pv.purpose_code)
        if cur is None or cur.id != pv.id:
            raise ApiError(409, ProblemCode.policy_outdated, extra={"purpose_code": pv.purpose_code})
        resolved.append((d, pv))

    states = _states(session, user_id)
    for d, pv in resolved:
        st = states[pv.purpose_code]
        if d.action == "grant":
            if st.state == "granted":
                continue  # FR-05-05: same version already granted
            session.add(
                ConsentEvent(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    policy_version_id=pv.id,
                    action="grant",
                    channel=channel,
                    app_version=app_version,
                )
            )
            session.flush()
        else:
            _withdraw(uow, deps, user_id=user_id, purpose=pv.purpose_code, channel=channel, app_version=app_version)
    return list_consents(session, user_id)


def _withdraw(
    uow: UnitOfWork, deps: PrivacyDeps, *, user_id: uuid.UUID, purpose: str, channel: str, app_version: str | None
) -> uuid.UUID | None:
    session = uow.session
    st = _states(session, user_id)[purpose]
    if st.state in ("none", "withdrawn"):
        return None  # FR-05-14: nothing to withdraw, nothing written
    session.add(
        ConsentEvent(
            id=uuid.uuid4(),
            user_id=user_id,
            policy_version_id=st.policy_version_id,  # the version that was granted
            action="withdraw",
            channel=channel,
            app_version=app_version,
        )
    )
    identity.bump_token_version(session, user_id)  # effective immediately (BR-CONSENT-04)
    now = utcnow()
    req = DsrRequest(
        id=uuid.uuid4(),
        user_id=user_id,
        subject_ref=subject_ref(deps.settings, user_id),
        type="withdraw",
        status="received",
        received_at=now,
        acknowledged_at=now,
        note=purpose,
    )
    session.add(req)
    session.flush()
    deps.schedule(uow, req.id)
    return req.id


def withdraw_consent(
    uow: UnitOfWork, deps: PrivacyDeps, *, user_id: uuid.UUID, purpose: str, channel: str, app_version: str | None
) -> ConsentWithdrawResult:
    session = uow.session
    _purpose(session, purpose)
    if purpose not in USER_PURPOSES:
        raise ApiError(422, ProblemCode.purpose_not_allowed)
    _lock_consents(session, user_id)
    req_id = _withdraw(uow, deps, user_id=user_id, purpose=purpose, channel=channel, app_version=app_version)
    st = _states(session, user_id)[purpose]
    return ConsentWithdrawResult(**st.model_dump(), data_request_id=req_id)


# ---------------------------------------------------------------- data-subject requests (UC06, UC07, UC08)


def _export_path(deps: PrivacyDeps, result_key: str) -> Path:
    return deps.storage / result_key


def _out(deps: PrivacyDeps, r: DsrRequest) -> DataRequestOut:
    downloadable = (
        r.type == "export"
        and r.status == "completed"
        and r.result_key is not None
        and _export_path(deps, r.result_key).is_file()
    )
    return DataRequestOut(
        id=r.id,
        type=r.type,
        status=r.status,
        received_at=r.received_at,
        acknowledged_at=r.acknowledged_at,
        completed_at=r.completed_at,
        due_at=r.received_at + DUE[r.type],
        download_available=downloadable,
        note=r.note,
    )


@dataclass(frozen=True)
class CreatedRequest:
    request: DataRequestOut
    created: bool


def create_data_request(
    uow: UnitOfWork,
    deps: PrivacyDeps,
    *,
    user_id: uuid.UUID,
    type_: str,
    note: str | None,
    password: str | None,
) -> CreatedRequest:
    session = uow.session
    if type_ == "access":
        raise ApiError(
            422,
            ProblemCode.invalid_request,
            "Xem dữ liệu ngay trong app (Hồ sơ, Kho, Nhật ký); tải bản sao đầy đủ bằng yêu cầu type = export.",
        )
    if type_ == "withdraw":
        raise ApiError(422, ProblemCode.invalid_request, "Rút đồng ý bằng POST /me/consents/{purpose}/withdraw (UC05).")
    note = (note or "").strip() or None
    if type_ in MANUAL_TYPES and note is None:
        raise ApiError(422, ProblemCode.invalid_request, "Cần mô tả nội dung yêu cầu.")
    if type_ == "delete" and (not password or not identity.check_password(session, user_id, password)):
        raise ApiError(403, ProblemCode.reauth_failed)

    session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"dsr:{user_id}:{type_}"})
    open_req = session.scalars(
        select(DsrRequest).where(
            DsrRequest.user_id == user_id,
            DsrRequest.type == type_,
            DsrRequest.status.in_(("received", "in_progress")),
        )
    ).first()
    if open_req is not None:
        return CreatedRequest(_out(deps, open_req), created=False)

    now = utcnow()
    req = DsrRequest(
        id=uuid.uuid4(),
        user_id=user_id,
        subject_ref=subject_ref(deps.settings, user_id),
        type=type_,
        status="received",
        received_at=now,
        acknowledged_at=now,
        note=note,
    )
    session.add(req)
    session.flush()
    if type_ == "delete":
        identity.begin_account_deletion(session, user_id)  # UC07 step 5, same transaction
    if type_ in AUTO_TYPES:
        deps.schedule(uow, req.id)
    return CreatedRequest(_out(deps, req), created=True)


def _owned_request(session: Session, user_id: uuid.UUID, request_id: uuid.UUID) -> DsrRequest:
    r = session.get(DsrRequest, request_id)
    if r is None or r.user_id != user_id:
        raise ApiError(404, ProblemCode.not_found)  # BOLA: same answer for "missing" and "someone else's"
    return r


def get_data_request(
    session: Session, deps: PrivacyDeps, *, user_id: uuid.UUID, request_id: uuid.UUID
) -> DataRequestOut:
    return _out(deps, _owned_request(session, user_id, request_id))


def download_export(session: Session, deps: PrivacyDeps, *, user_id: uuid.UUID, request_id: uuid.UUID) -> Response:
    r = _owned_request(session, user_id, request_id)
    if r.type != "export":
        raise ApiError(409, ProblemCode.request_not_downloadable)
    if r.status != "completed" or r.result_key is None:
        raise ApiError(409, ProblemCode.request_not_ready)
    if not _export_path(deps, r.result_key).is_file():
        raise ApiError(410, ProblemCode.export_expired)
    write_audit(session, action="dsr_download", entity="dsr_requests", entity_id=str(r.id), actor_user_id=user_id)
    return Response(
        status_code=200,
        media_type="application/zip",
        headers={
            "X-Accel-Redirect": deps.settings.accel_redirect_prefix + r.result_key,
            "Content-Disposition": f'attachment; filename="tastoria-du-lieu-{r.id}.zip"',
        },
    )


# ---------------------------------------------------------------- DSR job (sync in this slice)


def _privacy_export(session: Session, user_id: uuid.UUID) -> dict[str, list[dict[str, Any]]]:
    events = session.scalars(select(ConsentEvent).where(ConsentEvent.user_id == user_id)).all()
    pvs = {pv.id: pv for pv in session.scalars(select(PolicyVersion)).all()}
    reqs = session.scalars(select(DsrRequest).where(DsrRequest.user_id == user_id)).all()
    return {
        "consent_events": [
            {
                "purpose_code": pvs[e.policy_version_id].purpose_code,
                "policy_version": pvs[e.policy_version_id].version,
                "action": e.action,
                "channel": e.channel,
                "app_version": e.app_version,
                "created_at": e.created_at.isoformat(),
            }
            for e in events
        ],
        "v_current_consents": [s.model_dump(mode="json") for s in _states(session, user_id).values()],
        "dsr_requests": [
            {
                "id": str(r.id),
                "type": r.type,
                "status": r.status,
                "received_at": r.received_at.isoformat(),
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "note": r.note,
            }
            for r in reqs
        ],
    }


_DESCRIPTIONS = {
    "users": "Tài khoản: email, vai trò, trạng thái, thời điểm tạo.",
    "refresh_tokens": "Các phiên đăng nhập: thời điểm cấp, hết hạn, thu hồi, thiết bị (User-Agent).",
    "consent_events": "Mọi lần đồng ý / rút đồng ý: mục đích, phiên bản điều khoản, kênh, thời điểm.",
    "v_current_consents": "Trạng thái đồng ý hiện hành theo từng mục đích.",
    "dsr_requests": "Các yêu cầu về dữ liệu cá nhân bạn đã gửi.",
    "profiles": "Hồ sơ: chỉ số cơ thể (đã giải mã), mức vận động, mục tiêu năng lượng, chế độ ăn.",
    "user_allergens": "Nhóm dị ứng đã khai.",
    "user_favorite_recipes": "Món hay ăn đã chọn.",
    "user_settings": "Cài đặt bếp: số họng bếp, số người mặc định, múi giờ.",
    "pantry_lots": "Các lô trong kho: nguyên liệu, lượng ban đầu, ngày mua, trạng thái.",
    "pantry_transactions": "Sổ thay đổi lượng của từng lô (thêm, sửa, bỏ, trừ khi nấu, hoàn tác).",
    "meal_plans": "Các mâm cơm đã được gợi ý: bữa, số người, trạng thái, mục tiêu năng lượng, dòng lý do.",
    "meal_plan_items": "Món trong từng mâm, kể cả món đã đổi ra và lý do đổi.",
    "cook_sessions": "Các phiên nấu: giờ dọn mâm, lúc bắt đầu, nấu xong, hoàn tác.",
    "interactions": "Tương tác với món (được gợi ý, xem, đổi, nấu, thích, không thích) khi bạn đồng ý cá nhân hoá.",
    "shopping_items": "Danh sách đi chợ.",
}


def _write_export(deps: PrivacyDeps, request_id: uuid.UUID, tables: dict[str, list[dict[str, Any]]]) -> str:
    key = f"exports/{request_id}.zip"
    path = _export_path(deps, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "exported_at": utcnow().isoformat(),
        "request_id": str(request_id),
        "files": [
            {"file": f"{name}.json", "rows": len(rows), "description_vi": _DESCRIPTIONS.get(name, name)}
            for name, rows in tables.items()
        ],
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for name, rows in tables.items():
            zf.writestr(f"{name}.json", json.dumps(rows, ensure_ascii=False, indent=2, default=str))
    tmp = path.with_suffix(".zip.tmp")
    tmp.write_bytes(buf.getvalue())
    os.replace(tmp, path)  # never leave a half-written archive under the final name
    return key


def _claim(session: Session, request_id: uuid.UUID) -> DsrRequest | None:
    r = session.get(DsrRequest, request_id, with_for_update=True)
    if r is None or r.status in ("completed", "rejected") or r.type not in AUTO_TYPES:
        return None
    return r


def process_request(deps: PrivacyDeps, request_id: uuid.UUID) -> None:
    """Complete one export / withdraw / delete request. Safe to run again (FR-07-09)."""

    def mark_in_progress(uow: UnitOfWork) -> tuple[str, uuid.UUID | None, str | None] | None:
        r = _claim(uow.session, request_id)
        if r is None:
            return None
        r.status = "in_progress"
        return r.type, r.user_id, r.note

    claimed = run_in_uow(deps.sessionmaker, mark_in_progress)
    if claimed is None:
        return
    type_, user_id, note = claimed  # type: ignore[misc]

    if type_ == "export":
        _run_export(deps, request_id, user_id)
    elif type_ == "withdraw":
        _run_withdraw(deps, request_id, user_id, note)
    elif type_ == "delete":
        _run_delete(deps, request_id, user_id)


def _complete(r: DsrRequest, *, result_key: str | None = None) -> None:
    r.status = "completed"
    r.completed_at = utcnow()
    if result_key:
        r.result_key = result_key


def _run_export(deps: PrivacyDeps, request_id: uuid.UUID, user_id: uuid.UUID | None) -> None:
    def work(uow: UnitOfWork) -> None:
        r = _claim(uow.session, request_id)
        if r is None:
            return
        tables: dict[str, list[dict[str, Any]]] = {}
        if user_id is not None:
            for h in deps.handlers:
                tables.update(h.export(uow.session, user_id))
            tables.update(_privacy_export(uow.session, user_id))
        _complete(r, result_key=_write_export(deps, request_id, tables))

    run_in_uow(deps.sessionmaker, work)


def _run_withdraw(deps: PrivacyDeps, request_id: uuid.UUID, user_id: uuid.UUID | None, purpose: str | None) -> None:
    def work(uow: UnitOfWork) -> None:
        r = _claim(uow.session, request_id)
        if r is None:
            return
        if user_id is not None and purpose:
            uow.session.execute(text("SET LOCAL tastoria.erasure = 'on'"))  # e.g. deleting interactions
            for h in deps.handlers:
                h.erase_purpose(uow.session, user_id, purpose)
        _complete(r)

    run_in_uow(deps.sessionmaker, work)


def _run_delete(deps: PrivacyDeps, request_id: uuid.UUID, user_id: uuid.UUID | None) -> None:
    # 1. files first, while user_id still finds them (UC07 step 8); missing files are not errors.
    if user_id is not None:
        for h in deps.handlers:
            h.erase_files(user_id)

        def export_keys(uow: UnitOfWork) -> list[str]:
            rows = uow.session.scalars(
                select(DsrRequest.result_key).where(DsrRequest.user_id == user_id, DsrRequest.result_key.is_not(None))
            ).all()
            return [k for k in rows if k]

        for key in run_in_uow(deps.sessionmaker, export_keys):  # type: ignore[union-attr]
            _export_path(deps, key).unlink(missing_ok=True)

    # 2. the users row, with every personal table cascading (UC07 step 9), and the evidence row (step 10).
    def work(uow: UnitOfWork) -> None:
        session = uow.session
        r = _claim(session, request_id)
        if r is None:
            return
        session.execute(text("SET LOCAL tastoria.erasure = 'on'"))
        if user_id is not None:
            identity.delete_user(session, user_id)
        session.refresh(r)
        _complete(r)
        write_audit(
            session,
            action="dsr_delete_completed",
            entity="dsr_requests",
            entity_id=str(request_id),
            actor_role="system",
        )

    run_in_uow(deps.sessionmaker, work)


def pending_request_ids(sm: sessionmaker[Session]) -> list[uuid.UUID]:
    def q(uow: UnitOfWork) -> list[uuid.UUID]:
        return list(
            uow.session.scalars(
                select(DsrRequest.id)
                .where(DsrRequest.type.in_(AUTO_TYPES), DsrRequest.status.in_(("received", "in_progress")))
                .order_by(DsrRequest.received_at)
            ).all()
        )

    return run_in_uow(sm, q)  # type: ignore[return-value]


def process_pending(deps: PrivacyDeps, *, on_error: Callable[[uuid.UUID, Exception], None] | None = None) -> int:
    """Re-run every open automatic request (crash recovery for the sync backend; cron-able)."""
    done = 0
    for rid in pending_request_ids(deps.sessionmaker):
        try:
            process_request(deps, rid)
            done += 1
        except Exception as exc:
            log.exception("dsr job failed", extra={"dsr_request_id": str(rid)})
            if on_error:
                on_error(rid, exc)
    return done
