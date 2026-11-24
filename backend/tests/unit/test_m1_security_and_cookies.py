"""Unit tests for M1 security hardening: config guards, client_ip, rate limiting, CORS, HttpOnly cookies, mailer."""

from __future__ import annotations

import logging
import ssl
import time
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import jwt
import pytest
import valkey
from fastapi.testclient import TestClient
from pydantic import TypeAdapter
from starlette.requests import Request

from tastoria.app import create_app
from tastoria.core.auth import AuthUser, current_user
from tastoria.core.config import Settings
from tastoria.core.db import UnitOfWork, get_uow
from tastoria.core.errors import ApiError, ProblemCode
from tastoria.core.ratelimit import MemoryRateLimiter, ValkeyRateLimiter, client_ip
from tastoria.modules.admin.schemas import ModelName
from tastoria.modules.identity import service as identity_service
from tastoria.modules.identity import tokens as identity_tokens
from tastoria.modules.identity.mailer import LogMailer, SmtpMailer
from tastoria.modules.identity.schemas import AuthSession, UserSummary
from tastoria.modules.meal_calorie import service as meal_calorie_service
from tastoria.modules.meal_calorie.schemas import BarcodeNutritionOut
from tastoria.modules.survey import service as survey_service


def _make_request(peer: str, headers: dict[str, str] | None = None) -> Request:
    raw_headers = [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in (headers or {}).items()]
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/auth/login",
        "headers": raw_headers,
        "client": (peer, 12345),
    }
    return Request(scope)


def _dummy_session(refresh_token: str = "rt-opaque-123") -> AuthSession:
    now = datetime.now(UTC)
    return AuthSession(
        access_token="jwt.access.token",
        expires_in=900,
        refresh_token=refresh_token,
        refresh_expires_at=now + timedelta(days=30),
        user=UserSummary(
            id=uuid.uuid4(),
            email="u@tastoria.local",
            role="user",
            status="active",
            created_at=now,
        ),
    )


def _fake_uow() -> UnitOfWork:
    return UnitOfWork(session=SimpleNamespace())  # type: ignore[arg-type]


# ---------------------------------------------------------------- config & MLOps schema


def test_config_production_guards_and_preload_defaults() -> None:
    prod_base = dict(
        env="production",
        database_url="postgresql+psycopg://app_prod:super-secret-db-pass@db.internal:5432/tastoria_prod",
        valkey_url="redis://:super-secret-valkey-pass@valkey.internal:6379/0",
        jwt_keys={"p1": "prod-jwt-secret-key-0123456789abcdef"},
        jwt_active_kid="p1",
        survey_jwt_keys={"s1": "prod-survey-jwt-secret-0123456789abcd"},
        survey_jwt_active_kid="s1",
        health_enc_keys={"p1": "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE="},
        health_enc_active_key_id="p1",
        dsr_hmac_key="prod-dsr-hmac-secret-0123456789abcdef",
        training_export_hmac_key="prod-export-hmac-secret-0123456789ab",
        smtp_starttls=True,
    )
    ok = Settings(**prod_base)
    ok.check_production()
    assert ok.should_preload_meal_calorie is True
    assert ok.effective_cors_origins == ["https://tastoria.ctslab.net"]

    dev = Settings(env="development")
    assert dev.should_preload_meal_calorie is False
    assert Settings(env="development", preload_meal_calorie=True).should_preload_meal_calorie is True

    csv_cors = Settings(cors_allowed_origins="https://a.example, https://b.example")
    assert csv_cors.effective_cors_origins == ["https://a.example", "https://b.example"]

    with pytest.raises(RuntimeError, match="TASTORIA_CORS_ALLOWED_ORIGINS"):
        Settings(**prod_base, cors_allowed_origins=["*"]).check_production()
    with pytest.raises(RuntimeError, match="TASTORIA_LOGIN_THROTTLE_BACKEND"):
        Settings(**prod_base, login_throttle_backend="memory").check_production()
    with pytest.raises(RuntimeError, match="TASTORIA_RATE_LIMIT_BACKEND"):
        Settings(**prod_base, rate_limit_backend="memory").check_production()
    with pytest.raises(RuntimeError, match="TASTORIA_RATE_LIMIT_ENABLED"):
        Settings(**prod_base, rate_limit_enabled=False).check_production()


def test_admin_model_name_includes_all_seven_models() -> None:
    ta = TypeAdapter(ModelName)
    for name in (
        "detector",
        "freshness",
        "ranker",
        "substitution",
        "meal_calorie",
        "dish_classifier",
        "mushroom_classifier",
    ):
        assert ta.validate_python(name) == name
    with pytest.raises(Exception):
        ta.validate_python("unknown_model")


# ---------------------------------------------------------------- client_ip spoofing & canonicalization


def test_client_ip_trusts_only_configured_proxies_and_canonicalizes() -> None:
    s = Settings(trusted_proxies=["127.0.0.1/32", "172.16.0.0/12"])

    # Untrusted public peer: forwarded headers MUST be ignored.
    req_untrusted = _make_request(
        "203.0.113.9",
        {"CF-Connecting-IP": "1.2.3.4", "X-Forwarded-For": "5.6.7.8", "X-Real-IP": "9.9.9.9"},
    )
    assert client_ip(req_untrusted, s) == "203.0.113.9"

    # Non-IP peer ("testclient"): forwarded headers MUST be ignored.
    req_tc = _make_request("testclient", {"X-Forwarded-For": "1.2.3.4"})
    assert client_ip(req_tc, s) == "testclient"

    # Trusted proxy with CF-Connecting-IP: canonicalized.
    req_cf = _make_request("172.18.0.5", {"CF-Connecting-IP": "2001:0db8:0000:0000::1"})
    assert client_ip(req_cf, s) == "2001:db8::1"

    # Trusted proxy with malicious injection in CF-Connecting-IP falls back cleanly to valid XFF or peer.
    req_inject = _make_request(
        "127.0.0.1",
        {"CF-Connecting-IP": "1.2.3.4:*", "X-Forwarded-For": "198.51.100.7, 172.18.0.2"},
    )
    assert client_ip(req_inject, s) == "198.51.100.7"


# ---------------------------------------------------------------- rate limiters (Memory & Valkey)


def test_memory_rate_limiter_sliding_window_and_retry_after() -> None:
    rl = MemoryRateLimiter(enabled=True)
    rl.hit("b", "s1", limit=2, window_s=1)
    rl.hit("b", "s1", limit=2, window_s=1)
    with pytest.raises(ApiError) as exc:
        rl.hit("b", "s1", limit=2, window_s=1)
    assert exc.value.status == 429
    assert exc.value.code == ProblemCode.rate_limited
    assert int(exc.value.headers["Retry-After"]) >= 1

    # Different subject is unaffected
    rl.hit("b", "s2", limit=2, window_s=1)
    time.sleep(1.05)
    rl.hit("b", "s1", limit=2, window_s=1)


def test_valkey_rate_limiter_allows_blocks_and_fails_closed() -> None:
    class FakeKV:
        def __init__(self, reply=None, err: Exception | None = None):
            self.reply = reply
            self.err = err

        def eval(self, script, numkeys, *args):  # noqa: ANN001, ANN202
            if self.err:
                raise self.err
            return self.reply

    ValkeyRateLimiter(FakeKV(reply=[1, 0])).hit("auth", "1.2.3.4", limit=5, window_s=60)  # type: ignore[arg-type]

    with pytest.raises(ApiError) as exc_429:
        ValkeyRateLimiter(FakeKV(reply=[0, 1500])).hit("auth", "1.2.3.4", limit=5, window_s=60)  # type: ignore[arg-type]
    assert exc_429.value.status == 429
    assert exc_429.value.code == ProblemCode.rate_limited
    assert exc_429.value.headers["Retry-After"] == "2"

    with pytest.raises(ApiError) as exc_503:
        ValkeyRateLimiter(FakeKV(err=valkey.ConnectionError("down"))).hit(  # type: ignore[arg-type]
            "auth", "1.2.3.4", limit=5, window_s=60
        )
    assert exc_503.value.status == 503
    assert exc_503.value.code == ProblemCode.service_unavailable


# ---------------------------------------------------------------- HttpOnly cookie + native compat + CORS + endpoint RL


def test_cors_and_httponly_cookie_dual_mode_and_rate_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app(
        Settings(
            env="test",
            login_throttle_backend="memory",
            rate_limit_backend="memory",
            cors_allowed_origins=["https://tastoria.ctslab.net"],
        ),
        configure_logs=False,
    )
    fake_user = AuthUser(id=uuid.uuid4(), email="u@tastoria.local", role="user")
    app.dependency_overrides[get_uow] = _fake_uow
    app.dependency_overrides[current_user] = lambda: fake_user

    monkeypatch.setattr(identity_service, "register", lambda *a, **kw: _dummy_session("rt-reg-1"))
    monkeypatch.setattr(identity_service, "login", lambda *a, **kw: _dummy_session("rt-login-1"))
    monkeypatch.setattr(identity_service, "refresh", lambda *a, **kw: _dummy_session("rt-rot-2"))
    revoked_tokens: list[str] = []
    monkeypatch.setattr(identity_service, "logout", lambda s, *, user_id, refresh_token: revoked_tokens.append(refresh_token))
    logout_all_users: list[uuid.UUID] = []
    monkeypatch.setattr(identity_service, "logout_all", lambda s, *, user_id: logout_all_users.append(user_id))
    monkeypatch.setattr(identity_service, "request_password_reset", lambda *a, **kw: None)

    client = TestClient(app)

    # 1. CORS preflight succeeds for allowed origin even without X-App-Version, and rejects evil origin.
    preflight = client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": "https://tastoria.ctslab.net",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type, X-Client-Platform",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers.get("access-control-allow-origin") == "https://tastoria.ctslab.net"
    assert preflight.headers.get("access-control-allow-credentials") == "true"

    bad_preflight = client.options(
        "/api/v1/auth/login",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in bad_preflight.headers

    # 2. Native login returns JSON refresh_token and NO Set-Cookie.
    r_native = client.post("/api/v1/auth/login", json={"email": "u@tastoria.local", "password": "pw"})
    assert r_native.status_code == 200
    assert r_native.json()["refresh_token"] == "rt-login-1"
    assert "set-cookie" not in r_native.headers

    # 3. Web login sets HttpOnly cookie (with Secure when X-Forwarded-Proto: https) and hides refresh_token in JSON.
    r_web = client.post(
        "/api/v1/auth/login",
        json={"email": "u@tastoria.local", "password": "pw"},
        headers={"X-Client-Platform": "web", "X-Forwarded-Proto": "https", "Origin": "https://tastoria.ctslab.net"},
    )
    assert r_web.status_code == 200
    assert r_web.json()["refresh_token"] is None
    assert r_web.headers.get("access-control-allow-origin") == "https://tastoria.ctslab.net"
    sc = r_web.headers["set-cookie"]
    assert "tastoria_refresh=rt-login-1" in sc
    assert "HttpOnly" in sc and "SameSite=lax" in sc.lower() or "samesite=lax" in sc.lower()
    assert "Path=/api/v1/auth" in sc
    assert "Max-Age=2592000" in sc
    assert "Secure" in sc

    # 4. Web refresh using cookie rotates cookie and returns refresh_token=None.
    r_ref = client.post(
        "/api/v1/auth/refresh",
        json={},
        headers={"X-Client-Platform": "web", "Cookie": "tastoria_refresh=rt-login-1"},
    )
    assert r_ref.status_code == 200
    assert r_ref.json()["refresh_token"] is None
    assert "tastoria_refresh=rt-rot-2" in r_ref.headers["set-cookie"]

    # Refresh with neither body nor cookie -> 401 refresh_invalid.
    client.cookies.clear()
    r_no_rt = client.post("/api/v1/auth/refresh", json={})
    assert (r_no_rt.status_code, r_no_rt.json()["code"]) == (401, "refresh_invalid")

    # 5. Web logout revokes cookie token and clears cookie (Max-Age=0).
    r_out = client.post(
        "/api/v1/auth/logout",
        headers={"X-Client-Platform": "web", "Cookie": "tastoria_refresh=rt-rot-2"},
    )
    assert r_out.status_code == 204
    assert revoked_tokens == ["rt-rot-2"]
    assert "Max-Age=0" in r_out.headers["set-cookie"]

    # 6. Logout-all clears cookie for web client.
    r_out_all = client.post("/api/v1/auth/logout-all", headers={"X-Client-Platform": "web"})
    assert r_out_all.status_code == 204
    assert logout_all_users == [fake_user.id]
    assert "Max-Age=0" in r_out_all.headers["set-cookie"]

    # 7. Rate limit on POST /auth/register (10/300s per IP).
    for _ in range(10):
        assert client.post("/api/v1/auth/register", json={"email": "a@b.vn", "password": "x" * 10}).status_code == 201
    r_reg_429 = client.post("/api/v1/auth/register", json={"email": "a@b.vn", "password": "x" * 10})
    assert (r_reg_429.status_code, r_reg_429.json()["code"]) == (429, "rate_limited")
    assert int(r_reg_429.headers["retry-after"]) >= 1

    # 8. Rate limit on POST /auth/password-reset/request (5/900s per email).
    for _ in range(5):
        assert client.post("/api/v1/auth/password-reset/request", json={"email": "Target@x.vn"}).status_code == 204
    r_rst_429 = client.post("/api/v1/auth/password-reset/request", json={"email": "target@x.vn"})
    assert (r_rst_429.status_code, r_rst_429.json()["code"]) == (429, "rate_limited")

    # 9. Rate limit on POST /scans (20/60s per user) triggers BEFORE reading invalid/missing image body.
    app.state.rate_limiter = MemoryRateLimiter(enabled=True)
    for _ in range(20):
        app.state.rate_limiter.hit("scan_create", str(fake_user.id), limit=20, window_s=60)
    r_scan_429 = client.post(
        "/api/v1/scans",
        data={"mode": "fridge"},
        files=[("images", ("a.jpg", b"abc", "image/jpeg"))],
    )
    assert (r_scan_429.status_code, r_scan_429.json()["code"]) == (429, "rate_limited")

    # 10. Rate limit on POST /survey/respondents (50/300s per IP).
    monkeypatch.setattr(survey_service, "create_respondent", lambda *a, **kw: None)
    for _ in range(50):
        app.state.rate_limiter.hit("survey_create", "testclient", limit=50, window_s=300)
    r_surv_429 = client.post(
        "/api/v1/survey/respondents",
        json={"policy_version_id": str(uuid.uuid4()), "consent": True, "channel": "link"},
    )
    assert (r_surv_429.status_code, r_surv_429.json()["code"]) == (429, "rate_limited")


# ---------------------------------------------------------------- secret / mailer safety


def test_log_mailer_never_logs_reset_token_or_recipient(caplog: pytest.LogCaptureFixture) -> None:
    secret_token = "super-secret-reset-token-xyz987"
    recipient = "victim-private@tastoria.vn"
    body = f"Click https://tastoria.ctslab.net/dat-lai-mat-khau?token={secret_token}"

    for env_name, dev_flag in [("production", True), ("test", True), ("development", False)]:
        caplog.clear()
        with caplog.at_level(logging.DEBUG, logger="tastoria.mail"):
            mailer = LogMailer(Settings(env=env_name, mailer="log", log_reset_tokens_in_dev=dev_flag))  # type: ignore[arg-type]
            mailer.send(recipient, "Đặt lại mật khẩu Mỹ Vị", body)
        joined = "\n".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
        assert secret_token not in joined
        assert recipient not in joined
        assert "Đặt lại mật khẩu Mỹ Vị" in joined


def test_smtp_mailer_passes_default_ssl_context_on_starttls() -> None:
    fake_smtp = MagicMock()
    fake_smtp.__enter__.return_value = fake_smtp
    with patch("tastoria.modules.identity.mailer.smtplib.SMTP", return_value=fake_smtp):
        SmtpMailer(Settings(mailer="smtp", smtp_starttls=True)).send("u@example.vn", "Sub", "Body")
    fake_smtp.starttls.assert_called_once()
    ctx = fake_smtp.starttls.call_args.kwargs.get("context")
    assert isinstance(ctx, ssl.SSLContext)


# ---------------------------------------------------------------- cookie refresh CSRF & defense-in-depth rate limits


def test_cookie_refresh_csrf_defenses(monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app(
        Settings(
            env="test",
            login_throttle_backend="memory",
            rate_limit_backend="memory",
            cors_allowed_origins=["https://tastoria.ctslab.net"],
        ),
        configure_logs=False,
    )
    app.dependency_overrides[get_uow] = _fake_uow

    refresh_calls = 0

    def fake_refresh(*a, **kw):  # noqa: ANN001, ANN202
        nonlocal refresh_calls
        refresh_calls += 1
        return _dummy_session(f"rt-rot-{refresh_calls}")

    monkeypatch.setattr(identity_service, "refresh", fake_refresh)
    client = TestClient(app)

    # 1. Cookie-only refresh WITHOUT X-Client-Platform: web -> 403 forbidden (service.refresh NOT called)
    r_no_hdr = client.post("/api/v1/auth/refresh", json={}, headers={"Cookie": "tastoria_refresh=rt-cookie-1"})
    assert (r_no_hdr.status_code, r_no_hdr.json()["code"]) == (403, "forbidden")
    assert refresh_calls == 0

    # 2. Cookie-only refresh with wrong X-Client-Platform -> 403 forbidden
    r_bad_hdr = client.post(
        "/api/v1/auth/refresh",
        json={},
        headers={"X-Client-Platform": "android", "Cookie": "tastoria_refresh=rt-cookie-1"},
    )
    assert (r_bad_hdr.status_code, r_bad_hdr.json()["code"]) == (403, "forbidden")
    assert refresh_calls == 0

    # 3. Cookie-only refresh with Sec-Fetch-Site: cross-site -> 403 forbidden
    r_cross = client.post(
        "/api/v1/auth/refresh",
        json={},
        headers={
            "X-Client-Platform": "web",
            "Sec-Fetch-Site": "cross-site",
            "Origin": "https://tastoria.ctslab.net",
            "Cookie": "tastoria_refresh=rt-cookie-1",
        },
    )
    assert (r_cross.status_code, r_cross.json()["code"]) == (403, "forbidden")
    assert refresh_calls == 0

    # 4. Cookie-only refresh with untrusted Origin -> 403 forbidden
    r_evil = client.post(
        "/api/v1/auth/refresh",
        json={},
        headers={
            "X-Client-Platform": "web",
            "Origin": "https://evil.com",
            "Sec-Fetch-Site": "same-origin",
            "Cookie": "tastoria_refresh=rt-cookie-1",
        },
    )
    assert (r_evil.status_code, r_evil.json()["code"]) == (403, "forbidden")
    assert refresh_calls == 0

    # 5. Cookie-only refresh with Origin: null -> 403 forbidden
    r_null_origin = client.post(
        "/api/v1/auth/refresh",
        json={},
        headers={
            "X-Client-Platform": "web",
            "Origin": "null",
            "Cookie": "tastoria_refresh=rt-cookie-1",
        },
    )
    assert (r_null_origin.status_code, r_null_origin.json()["code"]) == (403, "forbidden")
    assert refresh_calls == 0

    # 6. Cookie-only refresh with X-Client-Platform: web + valid Origin + Sec-Fetch-Site: same-origin -> 200
    r_ok_origin = client.post(
        "/api/v1/auth/refresh",
        json={},
        headers={
            "X-Client-Platform": "web",
            "Origin": "HTTPS://TASTORIA.CTSLAB.NET:443/",
            "Sec-Fetch-Site": "same-origin",
            "Cookie": "tastoria_refresh=rt-cookie-1",
        },
    )
    assert r_ok_origin.status_code == 200
    assert r_ok_origin.json()["refresh_token"] is None
    assert "tastoria_refresh=rt-rot-1" in r_ok_origin.headers["set-cookie"]
    assert refresh_calls == 1

    # 7. Cookie-only refresh with X-Client-Platform: web + omitted Origin + Sec-Fetch-Site: same-origin -> 200
    r_ok_no_origin = client.post(
        "/api/v1/auth/refresh",
        json={},
        headers={
            "X-Client-Platform": "web",
            "Sec-Fetch-Site": "same-origin",
            "Cookie": "tastoria_refresh=rt-rot-1",
        },
    )
    assert r_ok_no_origin.status_code == 200
    assert r_ok_no_origin.json()["refresh_token"] is None
    assert refresh_calls == 2

    # 8. Native JSON refresh works without X-Client-Platform: web and returns JSON refresh_token
    client.cookies.clear()
    r_native = client.post("/api/v1/auth/refresh", json={"refresh_token": "rt-native-1"})
    assert r_native.status_code == 200
    assert r_native.json()["refresh_token"] == "rt-rot-3"
    assert "set-cookie" not in r_native.headers
    assert refresh_calls == 3


def test_cookie_refresh_csrf_same_origin_loopback_and_prod_secure(monkeypatch: pytest.MonkeyPatch) -> None:
    refresh_calls = 0

    def fake_refresh(*a, **kw):  # noqa: ANN001, ANN202
        nonlocal refresh_calls
        refresh_calls += 1
        return _dummy_session(f"rt-loop-{refresh_calls}")

    monkeypatch.setattr(identity_service, "refresh", fake_refresh)

    # 1. In development/test, same-origin loopback over HTTP omits Secure; HTTPS sets Secure.
    dev_app = create_app(
        Settings(env="development", login_throttle_backend="memory", rate_limit_backend="memory"),
        configure_logs=False,
    )
    dev_app.dependency_overrides[get_uow] = _fake_uow
    dev_client = TestClient(dev_app)

    r_127 = dev_client.post(
        "/api/v1/auth/refresh",
        json={},
        headers={
            "X-Client-Platform": "web",
            "Host": "127.0.0.1:6880",
            "Origin": "http://127.0.0.1:6880",
            "Cookie": "tastoria_refresh=rt-1",
        },
    )
    assert r_127.status_code == 200
    assert "Secure" not in r_127.headers["set-cookie"]

    r_lh = dev_client.post(
        "/api/v1/auth/refresh",
        json={},
        headers={
            "X-Client-Platform": "web",
            "Host": "localhost:6880",
            "Origin": "http://localhost:6880",
            "Cookie": "tastoria_refresh=rt-1",
        },
    )
    assert r_lh.status_code == 200
    assert "Secure" not in r_lh.headers["set-cookie"]

    r_127_https = dev_client.post(
        "/api/v1/auth/refresh",
        json={},
        headers={
            "X-Client-Platform": "web",
            "Host": "127.0.0.1:6880",
            "Origin": "https://127.0.0.1:6880",
            "X-Forwarded-Proto": "https",
            "Cookie": "tastoria_refresh=rt-1",
        },
    )
    assert r_127_https.status_code == 200
    assert "Secure" in r_127_https.headers["set-cookie"]

    # 2. In production, Secure=True is ALWAYS forced on refresh cookies even without X-Forwarded-Proto.
    prod_app = create_app(
        Settings(env="production", login_throttle_backend="memory", rate_limit_backend="memory"),
        configure_logs=False,
    )
    prod_app.dependency_overrides[get_uow] = _fake_uow
    prod_client = TestClient(prod_app)

    r_prod_no_proto = prod_client.post(
        "/api/v1/auth/refresh",
        json={},
        headers={
            "X-Client-Platform": "web",
            "Host": "127.0.0.1:6880",
            "Origin": "http://127.0.0.1:6880",
            "Cookie": "tastoria_refresh=rt-1",
        },
    )
    assert r_prod_no_proto.status_code == 200
    assert "Secure" in r_prod_no_proto.headers["set-cookie"]

    # 3. Mismatched port, mismatched scheme, arbitrary Host, and lookalike hostname are rejected with 403
    bad_cases = [
        {"Host": "127.0.0.1:6880", "Origin": "http://127.0.0.1:9999"},
        {"Host": "127.0.0.1:6880", "Origin": "https://127.0.0.1:6880"},
        {"Host": "127.0.0.1:6880", "Origin": "http://localhost:6880"},
        {"Host": "evil.com", "Origin": "http://evil.com"},
        {"Host": "127.0.0.1.evil.com", "Origin": "http://127.0.0.1.evil.com"},
    ]
    calls_before = refresh_calls
    for extra_hdrs in bad_cases:
        r_bad = prod_client.post(
            "/api/v1/auth/refresh",
            json={},
            headers={"X-Client-Platform": "web", "Cookie": "tastoria_refresh=rt-1", **extra_hdrs},
        )
        assert (r_bad.status_code, r_bad.json()["code"]) == (403, "forbidden")
    assert refresh_calls == calls_before

    # 4. Production origin https://tastoria.ctslab.net remains allowed
    r_prod = prod_client.post(
        "/api/v1/auth/refresh",
        json={},
        headers={
            "X-Client-Platform": "web",
            "Host": "tastoria.ctslab.net",
            "Origin": "https://tastoria.ctslab.net",
            "X-Forwarded-Proto": "https",
            "Cookie": "tastoria_refresh=rt-1",
        },
    )
    assert r_prod.status_code == 200
    assert "Secure" in r_prod.headers["set-cookie"]


def test_login_ip_and_barcode_user_rate_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app(
        Settings(
            env="test",
            login_throttle_backend="memory",
            rate_limit_backend="memory",
        ),
        configure_logs=False,
    )
    fake_user = AuthUser(id=uuid.uuid4(), email="u@tastoria.local", role="user")
    app.dependency_overrides[get_uow] = _fake_uow
    app.dependency_overrides[current_user] = lambda: fake_user

    login_calls = 0

    def fake_login(*a, **kw):  # noqa: ANN001, ANN202
        nonlocal login_calls
        login_calls += 1
        return _dummy_session("rt-login")

    barcode_calls = 0

    def fake_barcode(*a, **kw):  # noqa: ANN001, ANN202
        nonlocal barcode_calls
        barcode_calls += 1
        return BarcodeNutritionOut(barcode="8930000000001", product_name="Sữa", source="Tastoria VN Label Catalog")

    monkeypatch.setattr(identity_service, "login", fake_login)
    monkeypatch.setattr(meal_calorie_service, "lookup_barcode", fake_barcode)

    client = TestClient(app)

    # 1. Per-IP sliding-window rate limit on POST /auth/login (60 / 300s across distinct emails)
    for i in range(60):
        r = client.post("/api/v1/auth/login", json={"email": f"u{i}@tastoria.local", "password": "pw"})
        assert r.status_code == 200
    assert login_calls == 60
    r_login_429 = client.post("/api/v1/auth/login", json={"email": "u60@tastoria.local", "password": "pw"})
    assert (r_login_429.status_code, r_login_429.json()["code"]) == (429, "rate_limited")
    assert int(r_login_429.headers["retry-after"]) >= 1
    assert login_calls == 60

    # 2. Per-user sliding-window rate limit on GET /meal-calorie/barcode/{barcode} (30 / 60s)
    for _ in range(30):
        r = client.get("/api/v1/meal-calorie/barcode/8930000000001")
        assert r.status_code == 200
    assert barcode_calls == 30
    r_bc_429 = client.get("/api/v1/meal-calorie/barcode/8930000000001")
    assert (r_bc_429.status_code, r_bc_429.json()["code"]) == (429, "rate_limited")
    assert int(r_bc_429.headers["retry-after"]) >= 1
    assert barcode_calls == 30


def test_survey_and_user_jwt_keys_are_strictly_isolated() -> None:
    s = Settings(
        jwt_keys={"u1": "user-jwt-secret-key-0123456789abcdef"},
        jwt_active_kid="u1",
        survey_jwt_keys={"s1": "survey-jwt-secret-key-0123456789abcd"},
        survey_jwt_active_kid="s1",
    )
    now = datetime.now(UTC)
    rid = uuid.uuid4()
    uid = uuid.uuid4()

    survey_tok = survey_service.issue_token(s, rid)
    assert jwt.get_unverified_header(survey_tok)["kid"] == "s1"
    survey_service.verify_token(s, survey_tok, rid)

    user_tok = identity_tokens.issue_access_token(s, user_id=uid, role="user", token_version=0, now=now, mfa=True)
    assert jwt.get_unverified_header(user_tok)["kid"] == "u1"
    assert identity_tokens.decode_access_token(s, user_tok).mfa is True

    # User key cannot sign a valid survey token (even with survey audience/issuer)
    forged_survey = jwt.encode(
        {
            "sub": str(rid),
            "aud": survey_service.TOKEN_AUDIENCE,
            "iss": s.jwt_issuer,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=1)).timestamp()),
        },
        s.jwt_keys["u1"],
        algorithm="HS256",
        headers={"kid": "u1"},
    )
    with pytest.raises(ApiError) as exc_s:
        survey_service.verify_token(s, forged_survey, rid)
    assert exc_s.value.code == ProblemCode.respondent_token_invalid

    # Survey key cannot sign a valid user access token (even with user audience/issuer)
    forged_user = jwt.encode(
        {
            "iss": s.jwt_issuer,
            "aud": s.jwt_audience,
            "sub": str(uid),
            "role": "admin",
            "tv": 0,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=1)).timestamp()),
        },
        s.survey_jwt_keys["s1"],
        algorithm="HS256",
        headers={"kid": "s1"},
    )
    with pytest.raises(identity_tokens.InvalidAccessToken):
        identity_tokens.decode_access_token(s, forged_user)


def test_auth_refresh_reset_confirm_and_admin_rate_limits_and_mfa_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app(
        Settings(env="test", login_throttle_backend="memory", rate_limit_backend="memory"),
        configure_logs=False,
    )
    app.dependency_overrides[get_uow] = _fake_uow
    monkeypatch.setattr(identity_service, "refresh", lambda *a, **kw: _dummy_session("rt-1"))
    monkeypatch.setattr(identity_service, "confirm_password_reset", lambda *a, **kw: None)

    client = TestClient(app)

    # 1. POST /auth/refresh rate limit (60/60s IP)
    for _ in range(60):
        assert client.post("/api/v1/auth/refresh", json={"refresh_token": "tok"}).status_code == 200
    r_ref_429 = client.post("/api/v1/auth/refresh", json={"refresh_token": "tok"})
    assert (r_ref_429.status_code, r_ref_429.json()["code"]) == (429, "rate_limited")

    # 2. POST /auth/password-reset/confirm rate limit (10/300s IP)
    for _ in range(10):
        assert client.post("/api/v1/auth/password-reset/confirm", json={"token": "t", "new_password": "x" * 10}).status_code == 204
    r_rst_429 = client.post("/api/v1/auth/password-reset/confirm", json={"token": "t", "new_password": "x" * 10})
    assert (r_rst_429.status_code, r_rst_429.json()["code"]) == (429, "rate_limited")

    # 3. Admin MFA guard (mfa_enabled=True without mfa_verified=True -> 403 mfa_required; production blocks non-MFA too)
    from tastoria.modules.admin import service as admin_service
    from tastoria.modules.privacy import service as privacy_service

    audit_calls: list[str] = []
    monkeypatch.setattr(privacy_service, "write_audit", lambda *a, **kw: audit_calls.append(kw.get("purpose", "")))
    monkeypatch.setattr(
        admin_service,
        "list_data_requests",
        lambda *a, **kw: SimpleNamespace(items=[], next_cursor=None),
    )
    monkeypatch.setattr(
        admin_service,
        "list_audit_log",
        lambda *a, **kw: SimpleNamespace(items=[], next_cursor=None),
    )
    monkeypatch.setattr(
        admin_service,
        "list_models",
        lambda *a, **kw: SimpleNamespace(items=[], next_cursor=None, deployments=[]),
    )
    monkeypatch.setattr(
        admin_service,
        "list_surveys",
        lambda *a, **kw: SimpleNamespace(items=[], next_cursor=None),
    )

    unverified_admin = AuthUser(id=uuid.uuid4(), role="admin", email="a@x.vn", mfa_verified=False, mfa_enabled=True)
    app.dependency_overrides[current_user] = lambda: unverified_admin
    app.state.rate_limiter = MemoryRateLimiter(enabled=True)

    for path in ("/api/v1/admin/data-requests", "/api/v1/admin/audit-log"):
        r = client.get(path)
        assert (r.status_code, r.json()["code"]) == (403, "mfa_required")
    assert audit_calls == ["mfa_required", "mfa_required"]

    unverified_op = AuthUser(id=uuid.uuid4(), role="ml_operator", email="o@x.vn", mfa_verified=False, mfa_enabled=True)
    app.dependency_overrides[current_user] = lambda: unverified_op
    r_m = client.get("/api/v1/admin/models")
    assert (r_m.status_code, r_m.json()["code"]) == (403, "mfa_required")
    r_s = client.get("/api/v1/admin/surveys")
    assert (r_s.status_code, r_s.json()["code"]) == (403, "mfa_required")
    # admin/models writes audit, surveys_router writes nothing
    assert audit_calls == ["mfa_required", "mfa_required", "mfa_required"]

    # Rate limit on all 5 /admin/* endpoints triggers 429 without calling write_audit
    verified_admin = AuthUser(id=uuid.uuid4(), role="admin", email="a@x.vn", mfa_verified=True, mfa_enabled=True)
    app.dependency_overrides[current_user] = lambda: verified_admin
    for bucket, method, path, limit in [
        ("admin_dsr_list", "GET", "/api/v1/admin/data-requests", 60),
        ("admin_dsr_resolve", "POST", f"/api/v1/admin/data-requests/{uuid.uuid4()}/resolve", 30),
        ("admin_audit_log_list", "GET", "/api/v1/admin/audit-log", 60),
    ]:
        app.state.rate_limiter = MemoryRateLimiter(enabled=True)
        for _ in range(limit):
            app.state.rate_limiter.hit(bucket, str(verified_admin.id), limit=limit, window_s=60)
        audits_before = len(audit_calls)
        r = client.post(path, json={"status": "completed", "note": "ok"}) if method == "POST" else client.get(path)
        assert (r.status_code, r.json()["code"]) == (429, "rate_limited")
        assert len(audit_calls) == audits_before

    verified_op = AuthUser(id=uuid.uuid4(), role="ml_operator", email="o@x.vn", mfa_verified=True, mfa_enabled=True)
    app.dependency_overrides[current_user] = lambda: verified_op
    for bucket, path in [
        ("admin_models_list", "/api/v1/admin/models"),
        ("admin_surveys_list", "/api/v1/admin/surveys"),
    ]:
        app.state.rate_limiter = MemoryRateLimiter(enabled=True)
        for _ in range(60):
            app.state.rate_limiter.hit(bucket, str(verified_op.id), limit=60, window_s=60)
        r = client.get(path)
        assert (r.status_code, r.json()["code"]) == (429, "rate_limited")


def test_verify_totp_rejects_non_ascii_unicode_digits() -> None:
    secret = identity_tokens.generate_totp_secret()
    now = datetime(2026, 11, 24, 10, 0, tzinfo=UTC)
    counter = int(now.timestamp()) // 30
    valid_code = identity_tokens._hotp(secret, counter)
    assert identity_tokens.verify_totp(secret, valid_code, now=now) is True

    for bad_code in ("١٢٣٤٥٦", "²²²²²²", "１２３４５６", "12345é", "12345a", "12345"):
        assert identity_tokens.verify_totp(secret, bad_code, now=now) is False

