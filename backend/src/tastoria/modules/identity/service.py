"""identity public interface (M02): accounts, passwords, sessions, password reset, current-user dependency.

Other modules import only this file (and schemas). Functions take the request's `Session`/`UnitOfWork` and never
commit (ADR 0007).
"""

from __future__ import annotations

import logging
import math
import random
import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from email_validator import EmailNotValidError, validate_email
from fastapi import Request
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from tastoria.core.auth import AuthUser
from tastoria.core.clock import utcnow
from tastoria.core.config import Settings
from tastoria.core.db import UnitOfWork
from tastoria.core.errors import ApiError, ProblemCode
from tastoria.modules.identity import passwords, tokens
from tastoria.modules.identity.mailer import Mailer
from tastoria.modules.identity.models import EmailOutbox, EmailVerificationToken, PasswordReset, RefreshToken, User
from tastoria.modules.identity.schemas import AuthSession, MfaSetupOut, SessionListOut, SessionOut, UserSummary
from tastoria.modules.identity.throttle import LoginThrottle, ThrottleUnavailable

log = logging.getLogger("tastoria.identity")

# One message for unknown email and wrong password (FR-02-02).
_BAD_CREDENTIALS = "Email hoặc mật khẩu không đúng."
_REFRESH_GRACE = timedelta(seconds=10)
_EMAIL_VERIFICATION_TTL = timedelta(hours=24)
_rng = random.SystemRandom()


@dataclass(frozen=True)
class IdentityDeps:
    settings: Settings
    throttle: LoginThrottle
    mailer: Mailer
    sessionmaker: sessionmaker[Session] | None = None


def identity_deps(request: Request) -> IdentityDeps:
    st = request.app.state
    return IdentityDeps(st.settings, st.login_throttle, st.mailer, getattr(st, "sessionmaker", None))


# ---------------------------------------------------------------- current user (bearer access token)


class BearerAuthenticator:
    """Installed by tastoria.app as `app.state.authenticator` (used by tastoria.core.auth.current_user)."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def authenticate(self, request: Request, session: Session) -> AuthUser:
        unauthenticated = ApiError(401, ProblemCode.unauthenticated, headers={"WWW-Authenticate": "Bearer"})
        scheme, _, raw = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not raw.strip():
            raise unauthenticated
        try:
            claims = tokens.decode_access_token(self.settings, raw.strip())
        except tokens.InvalidAccessToken:
            raise unauthenticated from None
        user = session.get(User, claims.user_id)
        if user is None:
            raise unauthenticated
        if claims.token_version != user.token_version or user.status != "active":
            raise ApiError(401, ProblemCode.token_revoked, headers={"WWW-Authenticate": "Bearer"})
        return AuthUser(
            id=user.id,
            role=user.role,
            email=user.email,
            mfa_verified=claims.mfa,
            mfa_enabled=user.mfa_enabled_at is not None,
        )


# ---------------------------------------------------------------- helpers


def _check_password_policy(settings: Settings, password: str) -> None:
    if len(password) < settings.password_min_length:
        raise ApiError(
            422,
            ProblemCode.weak_password,
            f"Mật khẩu cần ít nhất {settings.password_min_length} ký tự.",
            extra={"password_min_length": settings.password_min_length},
        )
    if len(password) > settings.password_max_length:
        raise ApiError(
            422,
            ProblemCode.validation_error,
            errors=[{"pointer": "/password", "code": "too_long", "message": "Mật khẩu quá dài."}],
        )


def _normalize_email(raw: str) -> str:
    try:
        info = validate_email(raw.strip(), check_deliverability=False)
    except EmailNotValidError:
        raise ApiError(422, ProblemCode.invalid_email) from None
    if len(info.normalized) > 254:
        raise ApiError(422, ProblemCode.invalid_email)
    return info.normalized


def user_summary(user: User) -> UserSummary:
    return UserSummary(
        id=user.id,
        email=user.email,
        role=user.role,
        status=user.status,
        created_at=user.created_at,
        email_verified=user.email_verified_at is not None,
        mfa_enabled=user.mfa_enabled_at is not None,
    )


def _open_session(
    session: Session,
    settings: Settings,
    user: User,
    *,
    user_agent: str | None,
    ip_address: str | None = None,
    family_id: uuid.UUID | None = None,
    mfa: bool = False,
) -> tuple[AuthSession, RefreshToken]:
    now = utcnow()
    raw = tokens.new_opaque_token()
    rt = RefreshToken(
        id=uuid.uuid4(),
        user_id=user.id,
        family_id=family_id or uuid.uuid4(),
        token_sha256=tokens.sha256(raw),
        issued_at=now,
        expires_at=now + timedelta(days=settings.refresh_token_ttl_days),
        user_agent=(user_agent or None) and user_agent[:512],
        ip_address=ip_address,
        last_used_at=now,
    )
    session.add(rt)
    session.flush()
    access = tokens.issue_access_token(
        settings, user_id=user.id, role=user.role, token_version=user.token_version, now=now, mfa=mfa
    )
    return (
        AuthSession(
            access_token=access,
            expires_in=settings.access_token_ttl_s,
            refresh_token=raw,
            refresh_expires_at=rt.expires_at,
            user=user_summary(user),
        ),
        rt,
    )


def _find_user_by_email(session: Session, email: str, *, for_update: bool = False) -> User | None:
    stmt = select(User).where(User.email == email.strip())
    if for_update:
        stmt = stmt.with_for_update()
    return session.scalars(stmt).one_or_none()


def _revoke_all(session: Session, user_id: uuid.UUID, now: datetime) -> None:
    session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )


def _verify_email_link(settings: Settings, raw_token: str) -> str:
    base = settings.reset_url_base.replace("/dat-lai-mat-khau", "/xac-minh-email")
    return f"{base}?token={raw_token}"


def _queue_email(
    uow: UnitOfWork,
    deps: IdentityDeps,
    *,
    user_id: uuid.UUID | None,
    to: str,
    template: str,
    subject: str,
    body: str,
) -> None:
    now = utcnow()
    outbox_id = uuid.uuid4()
    uow.session.add(
        EmailOutbox(
            id=outbox_id,
            user_id=user_id,
            to_email=to,
            template=template,
            subject=subject,
            body_text=body,
            status="pending",
            attempts=0,
            next_attempt_at=now,
            created_at=now,
        )
    )
    uow.session.flush()

    def _deliver() -> None:
        err: str | None = None
        try:
            deps.mailer.send(to, subject, body)
        except Exception as exc:
            err = f"{exc.__class__.__name__}: {exc}"[:500]
            log.warning("email delivery failed", extra={"outbox_id": str(outbox_id), "template": template})
        if deps.sessionmaker is None:
            return
        try:
            with deps.sessionmaker() as s:
                done_at = utcnow()
                if err is None:
                    s.execute(
                        update(EmailOutbox)
                        .where(EmailOutbox.id == outbox_id)
                        .values(
                            status="sent",
                            attempts=EmailOutbox.attempts + 1,
                            sent_at=done_at,
                            last_error=None,
                        )
                    )
                else:
                    s.execute(
                        update(EmailOutbox)
                        .where(EmailOutbox.id == outbox_id)
                        .values(
                            status="failed",
                            attempts=EmailOutbox.attempts + 1,
                            last_error=err,
                            next_attempt_at=done_at + timedelta(minutes=5),
                        )
                    )
                s.commit()
        except Exception:
            log.exception("failed updating email_outbox", extra={"outbox_id": str(outbox_id)})

    uow.after_commit(_deliver)


def _create_verification_email(uow: UnitOfWork, deps: IdentityDeps, user: User, now: datetime) -> None:
    uow.session.execute(
        delete(EmailVerificationToken).where(
            EmailVerificationToken.user_id == user.id,
            EmailVerificationToken.verified_at.is_(None),
        )
    )
    raw = tokens.new_opaque_token()
    uow.session.add(
        EmailVerificationToken(
            id=uuid.uuid4(),
            user_id=user.id,
            token_sha256=tokens.sha256(raw),
            created_at=now,
            expires_at=now + _EMAIL_VERIFICATION_TTL,
        )
    )
    uow.session.flush()
    link = _verify_email_link(deps.settings, raw)
    body = (
        "Chào mừng bạn đến với Mỹ Vị.\n\n"
        f"Mở liên kết sau trong 24 giờ để xác minh địa chỉ email của bạn:\n{link}\n\n"
        "Nếu bạn không đăng ký tài khoản này, hãy bỏ qua thư này.\n"
    )
    _queue_email(
        uow,
        deps,
        user_id=user.id,
        to=user.email,
        template="verify_email",
        subject="Xác minh email Mỹ Vị",
        body=body,
    )


# ---------------------------------------------------------------- UC01 register


def register(
    uow: UnitOfWork,
    deps: IdentityDeps,
    *,
    email: str,
    password: str,
    user_agent: str | None,
    ip_address: str | None = None,
) -> AuthSession:
    session = uow.session
    email = _normalize_email(email)
    _check_password_policy(deps.settings, password)
    if _find_user_by_email(session, email) is not None:
        raise ApiError(409, ProblemCode.email_taken)
    now = utcnow()
    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=passwords.hash_password(password),
        role="user",
        status="active",
        token_version=0,
        failed_logins=0,
        created_at=now,
        updated_at=now,
    )
    session.add(user)
    try:
        session.flush()
    except IntegrityError:  # concurrent registration of the same email
        raise ApiError(409, ProblemCode.email_taken) from None
    _create_verification_email(uow, deps, user, now)
    auth, _ = _open_session(session, deps.settings, user, user_agent=user_agent, ip_address=ip_address)
    return auth


# ---------------------------------------------------------------- UC02 login / refresh


def _record_login_failure(
    session: Session,
    deps: IdentityDeps,
    *,
    user: User | None,
    email: str,
    ip: str,
) -> int:
    try:
        lock_s = deps.throttle.register_failure(email, ip)
    except ThrottleUnavailable:
        raise ApiError(503, ProblemCode.service_unavailable, headers={"Retry-After": "5"}) from None
    if user is not None:
        now = utcnow()
        vals: dict[str, Any] = {
            "failed_logins": func.least(User.failed_logins + 1, 32767),
            "updated_at": now,
        }
        if lock_s:
            vals["locked_until"] = now + timedelta(seconds=lock_s)
        session.execute(update(User).where(User.id == user.id).values(**vals))
    return lock_s


def login(
    session: Session,
    deps: IdentityDeps,
    *,
    email: str,
    password: str,
    ip: str,
    user_agent: str | None,
    totp_code: str | None = None,
) -> AuthSession:
    s = deps.settings
    try:
        locked = deps.throttle.locked_for(email, ip)
    except ThrottleUnavailable:
        log.error("login throttle unavailable; refusing login (fail closed)")
        raise ApiError(503, ProblemCode.service_unavailable, headers={"Retry-After": "5"}) from None
    if locked:
        raise ApiError(429, ProblemCode.login_locked, headers={"Retry-After": str(locked)})

    user = _find_user_by_email(session, email, for_update=False)
    now = utcnow()
    if user is not None and user.locked_until is not None and user.locked_until > now:
        retry = max(1, math.ceil((user.locked_until - now).total_seconds()))
        raise ApiError(429, ProblemCode.login_locked, headers={"Retry-After": str(retry)})

    ok, new_hash = passwords.verify_password(password, user.password_hash if user else None)
    if not ok:
        lock_s = _record_login_failure(session, deps, user=user, email=email, ip=ip)
        if lock_s:
            raise ApiError(429, ProblemCode.login_locked, headers={"Retry-After": str(lock_s)}, commit=True)
        raise ApiError(401, ProblemCode.invalid_credentials, _BAD_CREDENTIALS, commit=True)

    assert user is not None
    if user.status == "deletion_requested":
        raise ApiError(403, ProblemCode.account_deletion_pending)

    mfa_verified = False
    if user.mfa_enabled_at is not None:
        if not totp_code:
            raise ApiError(403, ProblemCode.mfa_required)
        if user.totp_secret_enc is None or user.totp_key_id is None:
            raise ApiError(500, ProblemCode.internal_error)
        try:
            secret = tokens.decrypt_totp_secret(s, user.totp_key_id, user.id, user.totp_secret_enc)
        except tokens.TotpDecryptionFailed:
            raise ApiError(500, ProblemCode.internal_error) from None
        if not tokens.verify_totp(secret, totp_code, now=utcnow()):
            lock_s = _record_login_failure(session, deps, user=user, email=email, ip=ip)
            if lock_s:
                raise ApiError(429, ProblemCode.login_locked, headers={"Retry-After": str(lock_s)}, commit=True)
            raise ApiError(401, ProblemCode.mfa_invalid, commit=True)
        mfa_verified = True

    try:
        deps.throttle.reset(email, ip)
    except ThrottleUnavailable:
        raise ApiError(503, ProblemCode.service_unavailable, headers={"Retry-After": "5"}) from None

    succ_vals: dict[str, Any] = {"failed_logins": 0, "locked_until": None}
    if new_hash:
        succ_vals["password_hash"] = new_hash
        succ_vals["updated_at"] = utcnow()
    session.execute(update(User).where(User.id == user.id).values(**succ_vals))
    session.expire(user)
    refreshed_user = session.get(User, user.id)
    assert refreshed_user is not None
    auth, _ = _open_session(session, s, refreshed_user, user_agent=user_agent, ip_address=ip, mfa=mfa_verified)
    return auth


def refresh(
    session: Session,
    deps: IdentityDeps,
    *,
    refresh_token: str,
    user_agent: str | None,
    ip_address: str | None = None,
) -> AuthSession:
    now = utcnow()
    old = session.scalars(
        select(RefreshToken).where(RefreshToken.token_sha256 == tokens.sha256(refresh_token)).with_for_update()
    ).one_or_none()
    if old is None:
        raise ApiError(401, ProblemCode.refresh_invalid)
    user = session.get(User, old.user_id)
    if user is not None and user.status == "deletion_requested":
        raise ApiError(403, ProblemCode.account_deletion_pending)
    if old.revoked_at is not None:
        if old.replaced_by_id is not None and (now - old.revoked_at) <= _REFRESH_GRACE:
            raise ApiError(409, ProblemCode.refresh_retry_conflict, headers={"Retry-After": "1"})
        # Outside 10s grace or explicitly revoked (replaced_by_id is None): treat family as stolen (FR-02-07).
        session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == old.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        log.warning("refresh token reuse; family revoked", extra={"family_id": str(old.family_id)})
        raise ApiError(401, ProblemCode.refresh_reused, commit=True)
    if old.expires_at <= now:
        raise ApiError(401, ProblemCode.refresh_invalid)
    assert user is not None
    mfa = user.mfa_enabled_at is not None and old.issued_at >= user.mfa_enabled_at
    auth, new = _open_session(
        session, deps.settings, user, user_agent=user_agent, ip_address=ip_address, family_id=old.family_id, mfa=mfa
    )
    old.revoked_at = now
    old.replaced_by_id = new.id
    old.last_used_at = now
    return auth


# ---------------------------------------------------------------- UC03 logout & sessions


def logout(session: Session, *, user_id: uuid.UUID, refresh_token: str) -> None:
    """Revoke the family of `refresh_token` if it belongs to the caller; otherwise do nothing (FR-03-02, 03-05)."""
    rt = session.scalars(
        select(RefreshToken).where(RefreshToken.token_sha256 == tokens.sha256(refresh_token))
    ).one_or_none()
    if rt is None or rt.user_id != user_id:
        return
    session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == rt.family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )


def logout_all(session: Session, *, user_id: uuid.UUID) -> None:
    bump_token_version(session, user_id)
    _revoke_all(session, user_id, utcnow())


def list_sessions(
    session: Session, *, user_id: uuid.UUID, current_refresh_token: str | None = None
) -> SessionListOut:
    now = utcnow()
    current_hash = tokens.sha256(current_refresh_token) if current_refresh_token else None
    rows = session.scalars(
        select(RefreshToken)
        .where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > now,
        )
        .order_by(RefreshToken.issued_at.desc(), RefreshToken.id.desc())
    ).all()
    return SessionListOut(
        items=[
            SessionOut(
                id=r.id,
                family_id=r.family_id,
                user_agent=r.user_agent,
                ip_address=r.ip_address,
                issued_at=r.issued_at,
                last_used_at=r.last_used_at,
                expires_at=r.expires_at,
                is_current=(current_hash is not None and bytes(r.token_sha256) == current_hash),
            )
            for r in rows
        ]
    )


def revoke_session(session: Session, *, user_id: uuid.UUID, session_id: uuid.UUID) -> None:
    rt = session.scalars(
        select(RefreshToken).where(RefreshToken.id == session_id, RefreshToken.user_id == user_id)
    ).one_or_none()
    if rt is None or rt.revoked_at is not None:
        raise ApiError(404, ProblemCode.session_not_found)
    session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == rt.family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )


# ---------------------------------------------------------------- UC01/UC02 email verification, change-password, MFA


def request_email_verification(uow: UnitOfWork, deps: IdentityDeps, *, user_id: uuid.UUID) -> None:
    session = uow.session
    user = session.get(User, user_id, with_for_update=True)
    if user is None or user.status != "active" or user.email_verified_at is not None:
        return
    now = utcnow()
    recent = session.scalars(
        select(EmailVerificationToken).where(
            EmailVerificationToken.user_id == user.id,
            EmailVerificationToken.verified_at.is_(None),
            EmailVerificationToken.expires_at > now,
            EmailVerificationToken.created_at > now - timedelta(seconds=deps.settings.reset_resend_cooldown_s),
        )
    ).first()
    if recent is not None:
        return
    _create_verification_email(uow, deps, user, now)


def confirm_email_verification(session: Session, *, token: str) -> None:
    now = utcnow()
    vt = session.scalars(
        select(EmailVerificationToken)
        .where(EmailVerificationToken.token_sha256 == tokens.sha256(token))
        .with_for_update()
    ).one_or_none()
    if vt is None or vt.verified_at is not None or vt.expires_at <= now:
        raise ApiError(400, ProblemCode.verification_token_invalid)
    user = session.get(User, vt.user_id, with_for_update=True)
    if user is None or user.status != "active":
        raise ApiError(400, ProblemCode.verification_token_invalid)
    vt.verified_at = now
    if user.email_verified_at is None:
        user.email_verified_at = now
        user.updated_at = now


def change_password(
    session: Session,
    deps: IdentityDeps,
    *,
    user_id: uuid.UUID,
    current_password: str,
    new_password: str,
    ip_address: str,
    user_agent: str | None,
    mfa_verified: bool = False,
) -> AuthSession:
    if not check_password_throttled(session, deps.throttle, user_id, current_password, ip_address):
        raise ApiError(401, ProblemCode.invalid_credentials, _BAD_CREDENTIALS)
    _check_password_policy(deps.settings, new_password)
    user = session.get(User, user_id, with_for_update=True)
    assert user is not None
    now = utcnow()
    user.password_hash = passwords.hash_password(new_password)
    user.failed_logins = 0
    user.locked_until = None
    user.updated_at = now
    bump_token_version(session, user.id)
    _revoke_all(session, user.id, now)
    session.flush()
    session.expire(user)
    refreshed = session.get(User, user.id)
    assert refreshed is not None
    auth, _ = _open_session(
        session,
        deps.settings,
        refreshed,
        user_agent=user_agent,
        ip_address=ip_address,
        mfa=(mfa_verified and refreshed.mfa_enabled_at is not None),
    )
    return auth


def mfa_setup(session: Session, deps: IdentityDeps, *, user_id: uuid.UUID) -> MfaSetupOut:
    user = session.get(User, user_id, with_for_update=True)
    assert user is not None
    if user.mfa_enabled_at is not None:
        raise ApiError(409, ProblemCode.conflict_state, "Xác thực hai bước đã được bật.")
    secret = tokens.generate_totp_secret()
    enc, key_id = tokens.encrypt_totp_secret(deps.settings, user.id, secret)
    user.totp_secret_enc = enc
    user.totp_key_id = key_id
    user.updated_at = utcnow()
    session.flush()
    b32 = tokens.totp_secret_b32(secret)
    return MfaSetupOut(secret=b32, otpauth_uri=tokens.provisioning_uri(b32, user.email, issuer="Mỹ Vị"))


def mfa_verify(
    session: Session,
    deps: IdentityDeps,
    *,
    user_id: uuid.UUID,
    code: str,
    user_agent: str | None,
    ip_address: str | None,
) -> AuthSession:
    user = session.get(User, user_id, with_for_update=True)
    assert user is not None
    if user.totp_secret_enc is None or user.totp_key_id is None:
        raise ApiError(409, ProblemCode.mfa_not_enabled)
    try:
        secret = tokens.decrypt_totp_secret(deps.settings, user.totp_key_id, user.id, user.totp_secret_enc)
    except tokens.TotpDecryptionFailed:
        raise ApiError(500, ProblemCode.internal_error) from None
    now = utcnow()
    if not tokens.verify_totp(secret, code, now=now):
        raise ApiError(401, ProblemCode.mfa_invalid)
    if user.mfa_enabled_at is None:
        user.mfa_enabled_at = now
    user.updated_at = now
    bump_token_version(session, user.id)
    _revoke_all(session, user.id, now)
    session.flush()
    session.expire(user)
    refreshed = session.get(User, user.id)
    assert refreshed is not None
    auth, _ = _open_session(
        session, deps.settings, refreshed, user_agent=user_agent, ip_address=ip_address, mfa=True
    )
    return auth


def mfa_disable(
    session: Session,
    deps: IdentityDeps,
    *,
    user_id: uuid.UUID,
    password: str,
    code: str,
    ip_address: str,
) -> None:
    user = session.get(User, user_id)
    assert user is not None
    if user.mfa_enabled_at is None or user.totp_secret_enc is None or user.totp_key_id is None:
        raise ApiError(409, ProblemCode.mfa_not_enabled)
    if not check_password_throttled(session, deps.throttle, user_id, password, ip_address):
        raise ApiError(401, ProblemCode.invalid_credentials, _BAD_CREDENTIALS)
    try:
        secret = tokens.decrypt_totp_secret(deps.settings, user.totp_key_id, user.id, user.totp_secret_enc)
    except tokens.TotpDecryptionFailed:
        raise ApiError(500, ProblemCode.internal_error) from None
    now = utcnow()
    if not tokens.verify_totp(secret, code, now=now):
        raise ApiError(401, ProblemCode.mfa_invalid)
    user = session.get(User, user_id, with_for_update=True, populate_existing=True)
    assert user is not None
    if user.mfa_enabled_at is None or user.totp_secret_enc is None or user.totp_key_id is None:
        raise ApiError(409, ProblemCode.mfa_not_enabled)
    user.mfa_enabled_at = None
    user.totp_secret_enc = None
    user.totp_key_id = None
    user.updated_at = now
    bump_token_version(session, user.id)
    _revoke_all(session, user.id, now)
    session.flush()


# ---------------------------------------------------------------- UC04 password reset


def request_password_reset(uow: UnitOfWork, deps: IdentityDeps, *, email: str) -> None:
    """Always succeeds silently (no account enumeration). Mail goes out after commit with equalized timing."""
    t0 = time.perf_counter()
    target = 0.04 + _rng.uniform(0.0, 0.02)
    s = deps.settings
    session = uow.session
    user = _find_user_by_email(session, email, for_update=True)
    if user is None or user.status != "active":
        tokens.sha256(tokens.new_opaque_token())
    else:
        now = utcnow()
        recent = session.scalars(
            select(PasswordReset).where(
                PasswordReset.user_id == user.id,
                PasswordReset.used_at.is_(None),
                PasswordReset.expires_at > now,
                PasswordReset.created_at > now - timedelta(seconds=s.reset_resend_cooldown_s),
            )
        ).first()
        if recent is not None:
            tokens.sha256(tokens.new_opaque_token())
        else:
            session.execute(  # FR-04-05: only the newest link stays valid
                update(PasswordReset)
                .where(PasswordReset.user_id == user.id, PasswordReset.used_at.is_(None))
                .values(used_at=now)
            )
            raw = tokens.new_opaque_token()
            session.add(
                PasswordReset(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    token_sha256=tokens.sha256(raw),
                    created_at=now,
                    expires_at=now + timedelta(seconds=s.reset_token_ttl_s),
                )
            )
            session.flush()
            to = user.email
            link = f"{s.reset_url_base}?token={raw}"
            minutes = s.reset_token_ttl_s // 60
            body = (
                "Bạn (hoặc ai đó) vừa yêu cầu đặt lại mật khẩu Mỹ Vị cho địa chỉ này.\n\n"
                f"Mở liên kết sau trong {minutes} phút để đặt mật khẩu mới:\n{link}\n\n"
                "Nếu bạn không yêu cầu, hãy bỏ qua thư này; mật khẩu hiện tại vẫn giữ nguyên.\n"
            )
            _queue_email(
                uow,
                deps,
                user_id=user.id,
                to=to,
                template="password_reset",
                subject="Đặt lại mật khẩu Mỹ Vị",
                body=body,
            )

    rem = target - (time.perf_counter() - t0)
    if rem > 0:
        time.sleep(rem)


def confirm_password_reset(uow: UnitOfWork, deps: IdentityDeps, *, token: str, new_password: str) -> None:
    session = uow.session
    now = utcnow()
    pr = session.scalars(
        select(PasswordReset).where(PasswordReset.token_sha256 == tokens.sha256(token)).with_for_update()
    ).one_or_none()
    if pr is None or pr.used_at is not None or pr.expires_at <= now:
        raise ApiError(400, ProblemCode.reset_token_invalid)
    _check_password_policy(deps.settings, new_password)  # weak password does not consume the token (FR-04-09)
    user = session.get(User, pr.user_id, with_for_update=True)
    assert user is not None
    user.password_hash = passwords.hash_password(new_password)
    user.failed_logins = 0
    user.locked_until = None
    user.updated_at = now
    pr.used_at = now
    bump_token_version(session, user.id)
    _revoke_all(session, user.id, now)
    email = user.email
    uow.after_commit(lambda: deps.throttle.clear_email(email))  # FR-04-08


# ---------------------------------------------------------------- used by other modules


def bump_token_version(session: Session, user_id: uuid.UUID) -> int:
    """Invalidate every access token issued so far (logout-all, withdraw consent, password reset, deletion)."""
    new = session.execute(
        update(User)
        .where(User.id == user_id)
        .values(token_version=User.token_version + 1, updated_at=utcnow())
        .returning(User.token_version)
    ).scalar_one()
    return int(new)


def check_password(session: Session, user_id: uuid.UUID, password: str) -> bool:
    user = session.get(User, user_id)
    ok, _ = passwords.verify_password(password, user.password_hash if user else None)
    return ok


def check_password_throttled(
    session: Session,
    throttle: LoginThrottle,
    user_id: uuid.UUID,
    password: str,
    client_ip: str,
) -> bool:
    subject = f"reauth:{user_id}"
    try:
        locked = throttle.locked_for(subject, client_ip)
    except ThrottleUnavailable:
        raise ApiError(503, ProblemCode.service_unavailable, headers={"Retry-After": "5"}) from None
    if locked:
        raise ApiError(429, ProblemCode.login_locked, headers={"Retry-After": str(locked)})
    user = session.get(User, user_id)
    now = utcnow()
    if user is not None and user.locked_until is not None and user.locked_until > now:
        retry = max(1, math.ceil((user.locked_until - now).total_seconds()))
        raise ApiError(429, ProblemCode.login_locked, headers={"Retry-After": str(retry)})
    ok, _ = passwords.verify_password(password, user.password_hash if user else None)
    if not ok:
        try:
            lock_s = throttle.register_failure(subject, client_ip)
        except ThrottleUnavailable:
            raise ApiError(503, ProblemCode.service_unavailable, headers={"Retry-After": "5"}) from None
        if lock_s:
            raise ApiError(429, ProblemCode.login_locked, headers={"Retry-After": str(lock_s)})
        return False
    try:
        throttle.reset(subject, client_ip)
    except ThrottleUnavailable:
        raise ApiError(503, ProblemCode.service_unavailable, headers={"Retry-After": "5"}) from None
    return True


def get_user_summary(session: Session, user_id: uuid.UUID) -> UserSummary | None:
    user = session.get(User, user_id)
    return user_summary(user) if user else None


def begin_account_deletion(session: Session, user_id: uuid.UUID) -> None:
    """UC07 step 5: status = deletion_requested, token_version + 1, every refresh token revoked."""
    now = utcnow()
    session.execute(update(User).where(User.id == user_id).values(status="deletion_requested", updated_at=now))
    bump_token_version(session, user_id)
    _revoke_all(session, user_id, now)


def delete_user(session: Session, user_id: uuid.UUID) -> bool:
    """Hard-delete the users row via SECURITY DEFINER erase_user_account (0007). Caller sets the erasure flag."""
    deleted = session.execute(
        text("SELECT public.erase_user_account(:user_id)"),
        {"user_id": user_id},
    ).scalar_one()
    session.expire_all()
    return bool(deleted)


def export_subject_data(session: Session, user_id: uuid.UUID) -> dict[str, list[dict[str, Any]]]:
    """UC06 exporter for identity tables. No password_hash, no token hashes (FR-06-06)."""
    user = session.get(User, user_id)
    if user is None:
        return {}
    rts = session.scalars(select(RefreshToken).where(RefreshToken.user_id == user_id)).all()
    return {
        "users": [
            {"email": user.email, "role": user.role, "status": user.status, "created_at": user.created_at.isoformat()}
        ],
        "refresh_tokens": [
            {
                "issued_at": t.issued_at.isoformat(),
                "expires_at": t.expires_at.isoformat(),
                "revoked_at": t.revoked_at.isoformat() if t.revoked_at else None,
                "user_agent": t.user_agent,
            }
            for t in rts
        ],
    }


def active_user_ids(session: Session, user_ids: Iterable[uuid.UUID]) -> set[uuid.UUID]:
    wanted = list(set(user_ids))
    if not wanted:
        return set()
    return set(session.scalars(select(User.id).where(User.id.in_(wanted), User.status == "active")).all())


def purge_expired(session: Session) -> dict[str, int]:
    """UC34: delete expired refresh tokens, password-reset tokens, and email verification tokens."""
    now = utcnow()
    expired = select(RefreshToken.id).where(RefreshToken.expires_at < now)
    session.execute(update(RefreshToken).where(RefreshToken.replaced_by_id.in_(expired)).values(replaced_by_id=None))
    rt = session.execute(delete(RefreshToken).where(RefreshToken.expires_at < now)).rowcount or 0
    pr = session.execute(delete(PasswordReset).where(PasswordReset.expires_at < now)).rowcount or 0
    session.execute(delete(EmailVerificationToken).where(EmailVerificationToken.expires_at < now))
    return {"refresh_tokens": rt, "password_resets": pr}
