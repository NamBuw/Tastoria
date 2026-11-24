"""M4-2 P2-3 integration tests: email verification, change-password, sessions, and TOTP MFA lifecycle."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import struct
import uuid

import jwt
from conftest import q
from fastapi.testclient import TestClient
from helpers import PASSWORD, bearer, login, register

from tastoria.core.clock import shift_for_tests, utcnow

AUTH = "/api/v1/auth"


def _totp_now(secret_b32: str) -> str:
    padded = secret_b32 + "=" * ((-len(secret_b32)) % 8)
    secret = base64.b32decode(padded)
    counter = int(utcnow().timestamp()) // 30
    digest = hmac.new(secret, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{code:06d}"


def _verify_token(mail_body: str) -> str:
    m = re.search(r"token=([A-Za-z0-9_-]+)", mail_body)
    assert m
    return m.group(1)


def _claims(access: str) -> dict:
    return jwt.decode(access, options={"verify_signature": False})


def test_email_verification_register_cooldown_resend_and_confirm(client: TestClient, db) -> None:
    s = register(client, "verify@example.vn")
    assert s["user"]["email_verified"] is False
    mails = [m for m in client.app.state.mailer.sent if "Xác minh email" in m.subject]
    assert len(mails) == 1
    t1 = _verify_token(mails[0].body)

    # Immediate resend within 60s cooldown is a clean no-op (204, no duplicate email, t1 still valid)
    r_cool = client.post(f"{AUTH}/verify-email/request", headers=bearer(s))
    assert r_cool.status_code == 204
    assert len([m for m in client.app.state.mailer.sent if "Xác minh email" in m.subject]) == 1

    # After 60s cooldown, resend invalidates t1 and sends t2
    shift_for_tests(61)
    try:
        r_resend = client.post(f"{AUTH}/verify-email/request", headers=bearer(s))
    finally:
        shift_for_tests(0)
    assert r_resend.status_code == 204
    mails = [m for m in client.app.state.mailer.sent if "Xác minh email" in m.subject]
    assert len(mails) == 2
    t2 = _verify_token(mails[1].body)
    assert t2 != t1

    # Old token t1 was invalidated by resend
    r_old = client.post(f"{AUTH}/verify-email/confirm", json={"token": t1})
    assert (r_old.status_code, r_old.json()["code"]) == (400, "verification_token_invalid")

    # Confirm with t2 succeeds and updates user summary
    r_ok = client.post(f"{AUTH}/verify-email/confirm", json={"token": t2})
    assert r_ok.status_code == 204
    assert q(db, "SELECT email_verified_at FROM users WHERE id = :u", u=s["user"]["id"]).scalar() is not None
    s2 = login(client, "verify@example.vn")
    assert s2["user"]["email_verified"] is True

    # Reusing t2 fails; requesting verification when already verified is idempotent 204 with no new mail
    r_reuse = client.post(f"{AUTH}/verify-email/confirm", json={"token": t2})
    assert (r_reuse.status_code, r_reuse.json()["code"]) == (400, "verification_token_invalid")
    assert client.post(f"{AUTH}/verify-email/request", headers=bearer(s2)).status_code == 204
    assert len([m for m in client.app.state.mailer.sent if "Xác minh email" in m.subject]) == 2


def test_change_password_throttling_and_session_revocation(client: TestClient, db) -> None:
    s1 = register(client, "cpw@example.vn")
    s2 = login(client, "cpw@example.vn")

    # Weak new password does not succeed
    r_weak = client.post(
        f"{AUTH}/change-password",
        json={"current_password": PASSWORD, "new_password": "short"},
        headers=bearer(s1),
    )
    assert (r_weak.status_code, r_weak.json()["code"]) == (422, "weak_password")

    # Wrong current password -> 401 invalid_credentials, then 5th wrong -> 429 login_locked
    for _ in range(4):
        r_bad = client.post(
            f"{AUTH}/change-password",
            json={"current_password": "wrong-password-1", "new_password": "new-password-123"},
            headers=bearer(s1),
        )
        assert (r_bad.status_code, r_bad.json()["code"]) == (401, "invalid_credentials")
    r_lock = client.post(
        f"{AUTH}/change-password",
        json={"current_password": "wrong-password-1", "new_password": "new-password-123"},
        headers=bearer(s1),
    )
    assert (r_lock.status_code, r_lock.json()["code"]) == (429, "login_locked")
    assert int(r_lock.headers["retry-after"]) > 0

    # Clear Valkey reauth lock so change-password can succeed with the right current password
    client.app.state.login_throttle.clear_email(f"reauth:{s1['user']['id']}")
    r_ok = client.post(
        f"{AUTH}/change-password",
        json={"current_password": PASSWORD, "new_password": "new-password-123"},
        headers=bearer(s1),
    )
    assert r_ok.status_code == 200
    s_new = r_ok.json()
    assert s_new["refresh_token"] is not None

    # All prior access and refresh tokens (both s1 and s2) are revoked
    assert client.get(f"{AUTH}/sessions", headers=bearer(s1)).json()["code"] == "token_revoked"
    assert client.post(f"{AUTH}/refresh", json={"refresh_token": s2["refresh_token"]}).status_code == 401
    # New session works
    assert client.get(f"{AUTH}/sessions", headers=bearer(s_new)).status_code == 200


def test_list_and_revoke_sessions(client: TestClient, db) -> None:
    s1 = register(client, "sess@example.vn")
    # Web login sets cookie so we can verify is_current
    r_web = client.post(
        f"{AUTH}/login",
        json={"email": "sess@example.vn", "password": PASSWORD},
        headers={"X-Client-Platform": "web", "User-Agent": "WebBrowser/1.0"},
    )
    assert r_web.status_code == 200
    s2 = r_web.json()
    assert s2["refresh_token"] is None

    other_user = register(client, "other-sess@example.vn")

    r_list = client.get(f"{AUTH}/sessions", headers=bearer(s2))
    assert r_list.status_code == 200
    items = r_list.json()["items"]
    assert len(items) == 2
    current_items = [x for x in items if x["is_current"]]
    other_items = [x for x in items if not x["is_current"]]
    assert len(current_items) == 1 and current_items[0]["user_agent"] == "WebBrowser/1.0"
    assert len(other_items) == 1 and items[0]["ip_address"] is not None and items[0]["last_used_at"] is not None

    # Revoking another user's or nonexistent session returns 404 session_not_found
    assert (
        client.delete(f"{AUTH}/sessions/{other_items[0]['id']}", headers=bearer(other_user)).status_code == 404
    )
    r_404 = client.delete(f"{AUTH}/sessions/{uuid.uuid4()}", headers=bearer(s2))
    assert (r_404.status_code, r_404.json()["code"]) == (404, "session_not_found")

    # Revoke s1 by session_id -> s1 refresh fails, s2 stays active
    r_del = client.delete(f"{AUTH}/sessions/{other_items[0]['id']}", headers=bearer(s2))
    assert r_del.status_code == 204
    assert client.post(f"{AUTH}/refresh", json={"refresh_token": s1["refresh_token"]}).status_code == 401
    assert len(client.get(f"{AUTH}/sessions", headers=bearer(s2)).json()["items"]) == 1


def test_totp_mfa_full_lifecycle(client: TestClient, db) -> None:
    s0 = register(client, "mfa@example.vn")
    assert _claims(s0["access_token"])["mfa"] is False

    # Verify before setup -> 409 mfa_not_enabled
    r_pre = client.post(f"{AUTH}/mfa/verify", json={"code": "123456"}, headers=bearer(s0))
    assert (r_pre.status_code, r_pre.json()["code"]) == (409, "mfa_not_enabled")

    # Setup TOTP
    r_setup = client.post(f"{AUTH}/mfa/setup", headers=bearer(s0))
    assert r_setup.status_code == 200
    setup = r_setup.json()
    assert setup["secret"] and setup["otpauth_uri"].startswith("otpauth://totp/")
    assert "M%E1%BB%B9%20V%E1%BB%8B" in setup["otpauth_uri"]

    # Wrong code on verify -> 401 mfa_invalid
    r_bad_code = client.post(f"{AUTH}/mfa/verify", json={"code": "000000"}, headers=bearer(s0))
    # (Tiny 1-in-1e6 chance 000000 matches, use deterministic bad string)
    r_bad_code = client.post(f"{AUTH}/mfa/verify", json={"code": "abcdef"}, headers=bearer(s0))
    assert (r_bad_code.status_code, r_bad_code.json()["code"]) == (401, "mfa_invalid")

    # Valid code activates MFA, revokes pre-MFA sessions, and returns mfa=True session
    code = _totp_now(setup["secret"])
    r_ver = client.post(f"{AUTH}/mfa/verify", json={"code": code}, headers=bearer(s0))
    assert r_ver.status_code == 200
    s_mfa = r_ver.json()
    assert s_mfa["user"]["mfa_enabled"] is True
    assert _claims(s_mfa["access_token"])["mfa"] is True
    assert client.get(f"{AUTH}/sessions", headers=bearer(s0)).json()["code"] == "token_revoked"
    assert client.post(f"{AUTH}/refresh", json={"refresh_token": s0["refresh_token"]}).status_code == 401

    # Setup again while already enabled -> 409 conflict_state
    r_dup = client.post(f"{AUTH}/mfa/setup", headers=bearer(s_mfa))
    assert (r_dup.status_code, r_dup.json()["code"]) == (409, "conflict_state")

    # Login without totp_code -> 403 mfa_required; wrong totp_code -> 401 mfa_invalid; valid -> 200 mfa=True
    r_no_totp = client.post(f"{AUTH}/login", json={"email": "mfa@example.vn", "password": PASSWORD})
    assert (r_no_totp.status_code, r_no_totp.json()["code"]) == (403, "mfa_required")
    r_bad_totp = client.post(
        f"{AUTH}/login", json={"email": "mfa@example.vn", "password": PASSWORD, "totp_code": "abcdef"}
    )
    assert (r_bad_totp.status_code, r_bad_totp.json()["code"]) == (401, "mfa_invalid")
    r_ok_login = client.post(
        f"{AUTH}/login",
        json={"email": "mfa@example.vn", "password": PASSWORD, "totp_code": _totp_now(setup["secret"])},
    )
    assert r_ok_login.status_code == 200
    s_login = r_ok_login.json()
    assert _claims(s_login["access_token"])["mfa"] is True

    # Refresh preserves mfa=True
    r_ref = client.post(f"{AUTH}/refresh", json={"refresh_token": s_login["refresh_token"]})
    assert r_ref.status_code == 200
    assert _claims(r_ref.json()["access_token"])["mfa"] is True

    # Disable MFA: wrong password or wrong TOTP fails; valid disables MFA and revokes sessions
    r_dis_pw = client.post(
        f"{AUTH}/mfa/disable",
        json={"password": "wrong-password-1", "code": _totp_now(setup["secret"])},
        headers=bearer(s_login),
    )
    assert (r_dis_pw.status_code, r_dis_pw.json()["code"]) == (401, "invalid_credentials")
    r_dis_code = client.post(
        f"{AUTH}/mfa/disable",
        json={"password": PASSWORD, "code": "abcdef"},
        headers=bearer(s_login),
    )
    assert (r_dis_code.status_code, r_dis_code.json()["code"]) == (401, "mfa_invalid")

    r_dis_ok = client.post(
        f"{AUTH}/mfa/disable",
        json={"password": PASSWORD, "code": _totp_now(setup["secret"])},
        headers=bearer(s_login),
    )
    assert r_dis_ok.status_code == 204
    assert client.get(f"{AUTH}/sessions", headers=bearer(s_login)).json()["code"] == "token_revoked"
    s_after = login(client, "mfa@example.vn")
    assert s_after["user"]["mfa_enabled"] is False
    assert _claims(s_after["access_token"])["mfa"] is False


def test_totp_non_ascii_unicode_digits_return_401_and_throttle(client: TestClient, db) -> None:
    s0 = register(client, "mfa-unicode@example.vn")
    setup = client.post(f"{AUTH}/mfa/setup", headers=bearer(s0)).json()

    # Non-ASCII Unicode digits on mfa/verify must return 401 mfa_invalid (never 500)
    for bad_code in ("١٢٣٤٥٦", "²²²²²²"):
        r_ver = client.post(f"{AUTH}/mfa/verify", json={"code": bad_code}, headers=bearer(s0))
        assert (r_ver.status_code, r_ver.json()["code"]) == (401, "mfa_invalid")

    # Activate MFA with valid ASCII TOTP code
    s_mfa = client.post(
        f"{AUTH}/mfa/verify",
        json={"code": _totp_now(setup["secret"])},
        headers=bearer(s0),
    ).json()

    # Non-ASCII Unicode digits on mfa/disable must return 401 mfa_invalid (never 500) and keep MFA active
    for bad_code in ("١٢٣٤٥٦", "²²²²²²"):
        r_dis = client.post(
            f"{AUTH}/mfa/disable",
            json={"password": PASSWORD, "code": bad_code},
            headers=bearer(s_mfa),
        )
        assert (r_dis.status_code, r_dis.json()["code"]) == (401, "mfa_invalid")
    assert (
        q(db, "SELECT mfa_enabled_at FROM users WHERE id = :u", u=s_mfa["user"]["id"]).scalar() is not None
    )

    # Non-ASCII Unicode digits on login must return 401 mfa_invalid and increment failure throttling to 429 lockout
    for expected_fails, bad_code in enumerate(("١٢٣٤٥٦", "²²²²²²", "١٢٣٤٥٦", "²²²²²²"), start=1):
        r_login = client.post(
            f"{AUTH}/login",
            json={"email": "mfa-unicode@example.vn", "password": PASSWORD, "totp_code": bad_code},
        )
        assert (r_login.status_code, r_login.json()["code"]) == (401, "mfa_invalid")
        assert (
            q(db, "SELECT failed_logins FROM users WHERE id = :u", u=s_mfa["user"]["id"]).scalar() == expected_fails
        )

    r_locked = client.post(
        f"{AUTH}/login",
        json={"email": "mfa-unicode@example.vn", "password": PASSWORD, "totp_code": "١٢٣٤٥٦"},
    )
    assert (r_locked.status_code, r_locked.json()["code"]) == (429, "login_locked")
    assert int(r_locked.headers["retry-after"]) > 0
    row = q(db, "SELECT failed_logins, locked_until FROM users WHERE id = :u", u=s_mfa["user"]["id"]).one()
    assert row.failed_logins == 5 and row.locked_until is not None

