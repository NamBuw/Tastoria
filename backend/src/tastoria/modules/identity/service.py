"""identity public interface (M02): accounts, passwords, sessions, password reset, current-user dependency.

Other modules import only this file (and schemas). Functions take the request's `Session`/`UnitOfWork` and never
commit (ADR 0007).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from email_validator import EmailNotValidError, validate_email
from fastapi import Request
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tastoria.core.auth import AuthUser
from tastoria.core.clock import utcnow
from tastoria.core.config import Settings
from tastoria.core.db import UnitOfWork
from tastoria.core.errors import ApiError, ProblemCode
from tastoria.modules.identity import passwords, tokens
from tastoria.modules.identity.mailer import Mailer
from tastoria.modules.identity.models import PasswordReset, RefreshToken, User
from tastoria.modules.identity.schemas import AuthSession, UserSummary
from tastoria.modules.identity.throttle import LoginThrottle, ThrottleUnavailable

log = logging.getLogger("tastoria.identity")

# One message for unknown email and wrong password (FR-02-02).
_BAD_CREDENTIALS = "Email hoặc mật khẩu không đúng."


@dataclass(frozen=True)
class IdentityDeps:
    settings: Settings
    throttle: LoginThrottle
    mailer: Mailer


def identity_deps(request: Request) -> IdentityDeps:
    st = request.app.state
    return IdentityDeps(st.settings, st.login_throttle, st.mailer)


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
        return AuthUser(user.id, user.role, user.email)


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
    return UserSummary(id=user.id, email=user.email, role=user.role, status=user.status, created_at=user.created_at)


def _open_session(
    session: Session, settings: Settings, user: User, *, user_agent: str | None, family_id: uuid.UUID | None = None
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
    )
    session.add(rt)
    session.flush()
    access = tokens.issue_access_token(
        settings, user_id=user.id, role=user.role, token_version=user.token_version, now=now
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


# ---------------------------------------------------------------- UC01 register


def register(session: Session, deps: IdentityDeps, *, email: str, password: str, user_agent: str | None) -> AuthSession:
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
    auth, _ = _open_session(session, deps.settings, user, user_agent=user_agent)
    return auth


# ---------------------------------------------------------------- UC02 login / refresh


def login(
    session: Session, deps: IdentityDeps, *, email: str, password: str, ip: str, user_agent: str | None
) -> AuthSession:
    s = deps.settings
    try:
        locked = deps.throttle.locked_for(email, ip)
    except ThrottleUnavailable:
        log.error("login throttle unavailable; refusing login (fail closed)")
        raise ApiError(503, ProblemCode.service_unavailable, headers={"Retry-After": "5"}) from None
    if locked:
        raise ApiError(429, ProblemCode.login_locked, headers={"Retry-After": str(locked)})

    user = _find_user_by_email(session, email, for_update=True)
    ok, new_hash = passwords.verify_password(password, user.password_hash if user else None)
    if not ok:
        try:
            lock_s = deps.throttle.register_failure(email, ip)
        except ThrottleUnavailable:
            raise ApiError(503, ProblemCode.service_unavailable, headers={"Retry-After": "5"}) from None
        if user is not None:
            user.failed_logins = min(user.failed_logins + 1, 32767)
            if lock_s:
                user.locked_until = utcnow() + timedelta(seconds=lock_s)
        if lock_s:
            raise ApiError(429, ProblemCode.login_locked, headers={"Retry-After": str(lock_s)}, commit=True)
        raise ApiError(401, ProblemCode.invalid_credentials, _BAD_CREDENTIALS, commit=True)

    assert user is not None
    if user.status == "deletion_requested":
        raise ApiError(403, ProblemCode.account_deletion_pending)
    try:
        deps.throttle.reset(email, ip)
    except ThrottleUnavailable:
        raise ApiError(503, ProblemCode.service_unavailable, headers={"Retry-After": "5"}) from None
    user.failed_logins = 0
    user.locked_until = None
    if new_hash:
        user.password_hash = new_hash
        user.updated_at = utcnow()
    auth, _ = _open_session(session, s, user, user_agent=user_agent)
    return auth


def refresh(session: Session, deps: IdentityDeps, *, refresh_token: str, user_agent: str | None) -> AuthSession:
    now = utcnow()
    old = session.scalars(
        select(RefreshToken).where(RefreshToken.token_sha256 == tokens.sha256(refresh_token)).with_for_update()
    ).one_or_none()
    if old is None:
        raise ApiError(401, ProblemCode.refresh_invalid)
    if old.revoked_at is not None:
        # A revoked token came back: treat the family as stolen (FR-02-07). Persist the revocation, then fail.
        session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == old.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        log.warning("refresh token reuse; family revoked", extra={"family_id": str(old.family_id)})
        raise ApiError(401, ProblemCode.refresh_reused, commit=True)
    if old.expires_at <= now:
        raise ApiError(401, ProblemCode.refresh_invalid)
    user = session.get(User, old.user_id)
    assert user is not None
    if user.status == "deletion_requested":
        raise ApiError(403, ProblemCode.account_deletion_pending)
    auth, new = _open_session(session, deps.settings, user, user_agent=user_agent, family_id=old.family_id)
    old.revoked_at = now
    old.replaced_by_id = new.id
    return auth


# ---------------------------------------------------------------- UC03 logout


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


# ---------------------------------------------------------------- UC04 password reset


def request_password_reset(uow: UnitOfWork, deps: IdentityDeps, *, email: str) -> None:
    """Always succeeds silently (no account enumeration). Mail goes out after commit."""
    s = deps.settings
    session = uow.session
    user = _find_user_by_email(session, email, for_update=True)
    if user is None or user.status != "active":
        return
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
        return  # FR-04-04: no new token, no new mail within the cooldown
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
        "Bạn (hoặc ai đó) vừa yêu cầu đặt lại mật khẩu Tastoria cho địa chỉ này.\n\n"
        f"Mở liên kết sau trong {minutes} phút để đặt mật khẩu mới:\n{link}\n\n"
        "Nếu bạn không yêu cầu, hãy bỏ qua thư này; mật khẩu hiện tại vẫn giữ nguyên.\n"
    )

    def send() -> None:
        deps.mailer.send(to, "Đặt lại mật khẩu Tastoria", body)

    uow.after_commit(send)


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
    """Hard-delete the users row; every personal table cascades (UC07 step 9). Caller sets the erasure flag."""
    user = session.get(User, user_id)
    if user is None:
        return False
    session.delete(user)
    session.flush()
    return True


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


def purge_expired(session: Session) -> dict[str, int]:
    """UC34: delete expired refresh tokens and password-reset tokens (an expired token is useless either way)."""
    now = utcnow()
    expired = select(RefreshToken.id).where(RefreshToken.expires_at < now)
    session.execute(update(RefreshToken).where(RefreshToken.replaced_by_id.in_(expired)).values(replaced_by_id=None))
    rt = session.execute(delete(RefreshToken).where(RefreshToken.expires_at < now)).rowcount or 0
    pr = session.execute(delete(PasswordReset).where(PasswordReset.expires_at < now)).rowcount or 0
    return {"refresh_tokens": rt, "password_resets": pr}
