"""UC01–UC04: register, login + lockout, refresh rotation + reuse detection, logout, password reset."""

from __future__ import annotations

import hashlib
import re
import time
import uuid

import jwt
import pytest
from conftest import q
from fastapi.testclient import TestClient
from helpers import PASSWORD, bearer, login, register

from tastoria.core.clock import shift_for_tests

AUTH = "/api/v1/auth"


def _sha(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def _claims(access: str) -> dict:
    return jwt.decode(access, options={"verify_signature": False})


# ---------------------------------------------------------------- UC01


def test_register_creates_user_and_session(client: TestClient, db) -> None:
    s = register(client, "a@x.vn")
    row = q(db, "SELECT role, status, token_version, password_hash FROM users WHERE email = 'a@x.vn'").one()
    assert (row.role, row.status, row.token_version) == ("user", "active", 0)
    assert row.password_hash.startswith("$argon2id$") and PASSWORD not in row.password_hash
    c = _claims(s["access_token"])
    assert c["exp"] - c["iat"] == 900 and c["tv"] == 0 and c["sub"] == s["user"]["id"]
    assert jwt.get_unverified_header(s["access_token"])["kid"] == "k1"
    assert s["token_type"] == "Bearer" and s["expires_in"] == 900
    rt = q(db, "SELECT token_sha256, expires_at - issued_at AS ttl FROM refresh_tokens").one()
    assert bytes(rt.token_sha256) == _sha(s["refresh_token"])
    assert rt.ttl.days == 30
    assert q(db, "SELECT count(*) FROM consent_events").scalar() == 0  # FR-01-08


def test_register_rejections(client: TestClient, db) -> None:
    register(client, "a@x.vn")
    r = client.post(f"{AUTH}/register", json={"email": "A@X.VN", "password": PASSWORD})
    assert (r.status_code, r.json()["code"]) == (409, "email_taken")
    r = client.post(f"{AUTH}/register", json={"email": "b@x.vn", "password": "x" * 9})
    assert (r.status_code, r.json()["code"]) == (422, "weak_password")
    r = client.post(f"{AUTH}/register", json={"email": "abc@", "password": PASSWORD})
    assert (r.status_code, r.json()["code"]) == (422, "invalid_email")
    r = client.post(f"{AUTH}/register", json={"email": "c@x.vn", "password": PASSWORD, "role": "admin"})
    assert (r.status_code, r.json()["code"]) == (400, "validation_error")
    assert r.headers["content-type"].startswith("application/problem+json")
    assert q(db, "SELECT count(*) FROM users").scalar() == 1


# ---------------------------------------------------------------- UC02 login


def test_login_success_and_uniform_failure(client: TestClient, db) -> None:
    s = register(client, "a@x.vn")
    ok = login(client, "A@x.vn")
    assert ok["user"]["id"] == s["user"]["id"]
    assert q(db, "SELECT count(DISTINCT family_id) FROM refresh_tokens").scalar() == 2
    wrong = client.post(f"{AUTH}/login", json={"email": "a@x.vn", "password": "sai-mat-khau-1"})
    unknown = client.post(f"{AUTH}/login", json={"email": "nobody@x.vn", "password": "sai-mat-khau-1"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["code"] == unknown.json()["code"] == "invalid_credentials"
    assert wrong.json()["detail"] == unknown.json()["detail"]
    assert q(db, "SELECT failed_logins FROM users").scalar() == 1


def test_lockout_after_five_failures(client: TestClient, db) -> None:
    register(client, "a@x.vn")
    for _ in range(4):
        r = client.post(f"{AUTH}/login", json={"email": "a@x.vn", "password": "sai-mat-khau-1"})
        assert r.status_code == 401
    r = client.post(f"{AUTH}/login", json={"email": "a@x.vn", "password": "sai-mat-khau-1"})
    assert (r.status_code, r.json()["code"]) == (429, "login_locked")
    assert 0 < int(r.headers["retry-after"]) <= 900
    r = client.post(f"{AUTH}/login", json={"email": "a@x.vn", "password": PASSWORD})  # correct password, still locked
    assert (r.status_code, r.json()["code"]) == (429, "login_locked")
    row = q(db, "SELECT failed_logins, locked_until FROM users").one()
    assert row.failed_logins == 5 and row.locked_until is not None


def test_lock_expires(make_app, clean_db) -> None:
    from fakes import FakeMailer

    app = make_app(login_lock_s=4)
    app.state.mailer = FakeMailer()
    with TestClient(app) as c:
        register(c, "a@x.vn")
        for _ in range(5):
            c.post(f"{AUTH}/login", json={"email": "a@x.vn", "password": "sai-mat-khau-1"})
        assert c.post(f"{AUTH}/login", json={"email": "a@x.vn", "password": PASSWORD}).status_code == 429
        time.sleep(4.2)
        assert c.post(f"{AUTH}/login", json={"email": "a@x.vn", "password": PASSWORD}).status_code == 200


def test_success_resets_counter(client: TestClient) -> None:
    register(client, "a@x.vn")
    for _ in range(3):
        client.post(f"{AUTH}/login", json={"email": "a@x.vn", "password": "sai-mat-khau-1"})
    login(client, "a@x.vn")
    codes = [
        client.post(f"{AUTH}/login", json={"email": "a@x.vn", "password": "sai-1234567"}).status_code for _ in range(4)
    ]
    assert codes == [401, 401, 401, 401]


def test_lock_is_per_email_and_ip(client: TestClient) -> None:
    register(client, "a@x.vn")
    register(client, "b@x.vn")
    for _ in range(5):
        client.post(f"{AUTH}/login", json={"email": "a@x.vn", "password": "sai-mat-khau-1"})
    login(client, "b@x.vn")  # another email from the same IP is not locked


def test_login_fails_closed_without_valkey(make_app, clean_db) -> None:
    app = make_app(valkey_url="redis://127.0.0.1:1/0")
    with TestClient(app) as c:
        register(c, "a@x.vn")
        r = c.post(f"{AUTH}/login", json={"email": "a@x.vn", "password": PASSWORD})
        assert (r.status_code, r.json()["code"]) == (503, "service_unavailable")


def test_deletion_pending_cannot_login_or_refresh(client: TestClient, db) -> None:
    s = register(client, "a@x.vn")
    q(db, "UPDATE users SET status = 'deletion_requested'")
    r = client.post(f"{AUTH}/login", json={"email": "a@x.vn", "password": PASSWORD})
    assert (r.status_code, r.json()["code"]) == (403, "account_deletion_pending")
    r = client.post(f"{AUTH}/refresh", json={"refresh_token": s["refresh_token"]})
    assert (r.status_code, r.json()["code"]) == (403, "account_deletion_pending")
    assert q(db, "SELECT count(*) FROM refresh_tokens").scalar() == 1


# ---------------------------------------------------------------- UC02 refresh


def test_refresh_rotates_within_family(client: TestClient, db) -> None:
    s = register(client, "a@x.vn")
    r = client.post(f"{AUTH}/refresh", json={"refresh_token": s["refresh_token"]})
    assert r.status_code == 200, r.text
    t2 = r.json()["refresh_token"]
    old = q(db, "SELECT * FROM refresh_tokens WHERE token_sha256 = :h", h=_sha(s["refresh_token"])).one()
    new = q(db, "SELECT * FROM refresh_tokens WHERE token_sha256 = :h", h=_sha(t2)).one()
    assert old.revoked_at is not None and old.replaced_by_id == new.id and old.family_id == new.family_id
    assert new.revoked_at is None


def test_refresh_reuse_revokes_family(client: TestClient, db) -> None:
    s = register(client, "a@x.vn")
    other = login(client, "a@x.vn")  # a second family on another device
    t2 = client.post(f"{AUTH}/refresh", json={"refresh_token": s["refresh_token"]}).json()["refresh_token"]
    r = client.post(f"{AUTH}/refresh", json={"refresh_token": s["refresh_token"]})
    assert (r.status_code, r.json()["code"]) == (401, "refresh_reused")
    r = client.post(f"{AUTH}/refresh", json={"refresh_token": t2})
    assert (r.status_code, r.json()["code"]) == (401, "refresh_reused")
    assert client.post(f"{AUTH}/refresh", json={"refresh_token": other["refresh_token"]}).status_code == 200


def test_refresh_unknown_or_expired(client: TestClient, db) -> None:
    s = register(client, "a@x.vn")
    r = client.post(f"{AUTH}/refresh", json={"refresh_token": "khong-ton-tai"})
    assert (r.status_code, r.json()["code"]) == (401, "refresh_invalid")
    shift_for_tests(31 * 86400)
    try:
        r = client.post(f"{AUTH}/refresh", json={"refresh_token": s["refresh_token"]})
    finally:
        shift_for_tests(0)
    assert (r.status_code, r.json()["code"]) == (401, "refresh_invalid")


# ---------------------------------------------------------------- access token checks


@pytest.mark.parametrize(
    "header",
    [None, "Bearer", "Bearer abc.def.ghi", "Basic dXNlcjpwYXNz"],
)
def test_bad_access_tokens(client: TestClient, header: str | None) -> None:
    headers = {"Authorization": header} if header else {}
    r = client.post(f"{AUTH}/logout-all", headers=headers)
    assert (r.status_code, r.json()["code"]) == (401, "unauthenticated")


def test_access_token_with_unknown_kid_or_expired(client: TestClient) -> None:
    s = register(client, "a@x.vn")
    c = _claims(s["access_token"])
    forged = jwt.encode(c, "other-secret-0123456789-abcdefghijklmn", algorithm="HS256", headers={"kid": "zz"})
    r = client.post(f"{AUTH}/logout-all", headers={"Authorization": f"Bearer {forged}"})
    assert (r.status_code, r.json()["code"]) == (401, "unauthenticated")
    expired = jwt.encode(
        {**c, "iat": c["iat"] - 2000, "exp": c["iat"] - 1000},
        "test-jwt-secret-0123456789-abcdefghijklmnop",
        algorithm="HS256",
        headers={"kid": "k1"},
    )
    r = client.post(f"{AUTH}/logout-all", headers={"Authorization": f"Bearer {expired}"})
    assert (r.status_code, r.json()["code"]) == (401, "unauthenticated")
    assert client.post(f"{AUTH}/logout-all", headers=bearer(s)).status_code == 204


# ---------------------------------------------------------------- UC03 logout


def test_logout_revokes_only_that_family(client: TestClient, db) -> None:
    a = register(client, "a@x.vn")
    a2 = login(client, "a@x.vn")
    r = client.post(f"{AUTH}/logout", json={"refresh_token": a["refresh_token"]}, headers=bearer(a))
    assert r.status_code == 204
    assert client.post(f"{AUTH}/refresh", json={"refresh_token": a2["refresh_token"]}).status_code == 200
    # again with the revoked token: still 204, nothing else revoked
    before = q(db, "SELECT count(*) FROM refresh_tokens WHERE revoked_at IS NULL").scalar()
    r = client.post(f"{AUTH}/logout", json={"refresh_token": a["refresh_token"]}, headers=bearer(a))
    assert r.status_code == 204
    assert q(db, "SELECT count(*) FROM refresh_tokens WHERE revoked_at IS NULL").scalar() == before


def test_logout_ignores_other_users_token(client: TestClient, db) -> None:
    a = register(client, "a@x.vn")
    b = register(client, "b@x.vn")
    r = client.post(f"{AUTH}/logout", json={"refresh_token": b["refresh_token"]}, headers=bearer(a))
    assert r.status_code == 204
    assert client.post(f"{AUTH}/refresh", json={"refresh_token": b["refresh_token"]}).status_code == 200


def test_logout_all_bumps_version_and_revokes(client: TestClient, db) -> None:
    a = register(client, "a@x.vn")
    login(client, "a@x.vn")
    login(client, "a@x.vn")
    assert client.post(f"{AUTH}/logout-all", headers=bearer(a)).status_code == 204
    assert q(db, "SELECT token_version FROM users").scalar() == 1
    assert q(db, "SELECT count(*) FROM refresh_tokens WHERE revoked_at IS NULL").scalar() == 0
    r = client.post(f"{AUTH}/logout-all", headers=bearer(a))
    assert (r.status_code, r.json()["code"]) == (401, "token_revoked")


# ---------------------------------------------------------------- UC04 password reset


def _reset_token(mail_body: str) -> str:
    m = re.search(r"token=([A-Za-z0-9_-]+)", mail_body)
    assert m
    return m.group(1)


def test_password_reset_flow(client: TestClient, db) -> None:
    a = register(client, "a@x.vn")
    other = login(client, "a@x.vn")
    for _ in range(5):
        client.post(f"{AUTH}/login", json={"email": "a@x.vn", "password": "sai-mat-khau-1"})
    r1 = client.post(f"{AUTH}/password-reset/request", json={"email": "a@x.vn"})
    r2 = client.post(f"{AUTH}/password-reset/request", json={"email": "nobody@x.vn"})
    assert r1.status_code == r2.status_code == 204 and r1.content == r2.content == b""
    mails = client.app.state.mailer.sent
    assert len(mails) == 1 and mails[0].to == "a@x.vn"
    token = _reset_token(mails[0].body)
    row = q(db, "SELECT token_sha256, expires_at - created_at AS ttl FROM password_resets").one()
    assert bytes(row.token_sha256) == _sha(token) and row.ttl.total_seconds() == 1800

    # cooldown: no new token, no new mail
    client.post(f"{AUTH}/password-reset/request", json={"email": "a@x.vn"})
    assert len(mails) == 1 and q(db, "SELECT count(*) FROM password_resets").scalar() == 1

    # weak password does not consume the token
    r = client.post(f"{AUTH}/password-reset/confirm", json={"token": token, "new_password": "short"})
    assert (r.status_code, r.json()["code"]) == (422, "weak_password")
    r = client.post(f"{AUTH}/password-reset/confirm", json={"token": token, "new_password": "mat-khau-moi-123"})
    assert r.status_code == 204

    assert client.post(f"{AUTH}/login", json={"email": "a@x.vn", "password": PASSWORD}).status_code == 401
    login(client, "a@x.vn", "mat-khau-moi-123")  # lock cleared (FR-04-08), new password works
    assert q(db, "SELECT token_version FROM users").scalar() == 1
    assert client.post(f"{AUTH}/logout-all", headers=bearer(a)).json()["code"] == "token_revoked"
    for t in (a["refresh_token"], other["refresh_token"]):
        assert client.post(f"{AUTH}/refresh", json={"refresh_token": t}).status_code == 401
    r = client.post(f"{AUTH}/password-reset/confirm", json={"token": token, "new_password": "mat-khau-moi-456"})
    assert (r.status_code, r.json()["code"]) == (400, "reset_token_invalid")


def test_new_reset_token_invalidates_old(make_app, clean_db, engine) -> None:
    from fakes import FakeMailer

    app = make_app(reset_resend_cooldown_s=0)
    app.state.mailer = FakeMailer()
    with TestClient(app) as c:
        register(c, "a@x.vn")
        c.post(f"{AUTH}/password-reset/request", json={"email": "a@x.vn"})
        c.post(f"{AUTH}/password-reset/request", json={"email": "a@x.vn"})
        t1, t2 = (_reset_token(m.body) for m in app.state.mailer.sent)
        r = c.post(f"{AUTH}/password-reset/confirm", json={"token": t1, "new_password": "mat-khau-moi-123"})
        assert (r.status_code, r.json()["code"]) == (400, "reset_token_invalid")
        assert (
            c.post(f"{AUTH}/password-reset/confirm", json={"token": t2, "new_password": "mat-khau-moi-123"}).status_code
            == 204
        )


def test_reset_token_invalid_cases(client: TestClient, db) -> None:
    register(client, "a@x.vn")
    client.post(f"{AUTH}/password-reset/request", json={"email": "a@x.vn"})
    token = _reset_token(client.app.state.mailer.sent[0].body)
    q(db, "UPDATE password_resets SET created_at = now() - interval '2 hours', expires_at = now() - interval '1 hour'")
    for t in (token, uuid.uuid4().hex):
        r = client.post(f"{AUTH}/password-reset/confirm", json={"token": t, "new_password": "mat-khau-moi-123"})
        assert (r.status_code, r.json()["code"]) == (400, "reset_token_invalid")
