"""Pure unit tests for M4-1 core/ hardening (db, config, errors, idempotency, pagination, middleware)."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tastoria.core import idempotency, pagination
from tastoria.core.config import Settings
from tastoria.core.db import get_uow, make_engine
from tastoria.core.errors import TITLES, ApiError, ProblemCode
from tastoria.core.middleware import RequestContextMiddleware


def test_make_engine_postgresql_options_and_pool_params() -> None:
    captured: list[tuple[str, dict[str, object]]] = []

    def fake_create_engine(url: str, **kwargs: object) -> object:
        captured.append((url, kwargs))
        return SimpleNamespace(url=url, kwargs=kwargs)

    with patch("tastoria.core.db.create_engine", side_effect=fake_create_engine):
        make_engine(
            "postgresql+psycopg://u:p@127.0.0.1:5432/db",
            pool_size=4,
            pool_recycle=900,
            pool_timeout=7,
            statement_timeout_ms=12_000,
            lock_timeout_ms=3_000,
            idle_in_transaction_session_timeout_ms=25_000,
        )
        make_engine("sqlite:///:memory:", pool_size=2)

    pg_url, pg_kw = captured[0]
    assert pg_url.startswith("postgresql+psycopg://")
    assert pg_kw["pool_size"] == 4
    assert pg_kw["max_overflow"] == 4
    assert pg_kw["pool_recycle"] == 900
    assert pg_kw["pool_timeout"] == 7
    assert pg_kw["connect_args"] == {
        "options": "-c statement_timeout=12000 -c lock_timeout=3000 -c idle_in_transaction_session_timeout=25000"
    }
    _, sq_kw = captured[1]
    assert "connect_args" not in sq_kw


def test_get_uow_runs_after_commit_on_api_error_commit_true() -> None:
    events: list[str] = []

    class FakeSession:
        def __init__(self, fail_commit: bool = False) -> None:
            self.fail_commit = fail_commit

        def __enter__(self) -> FakeSession:
            return self

        def __exit__(self, *args: object) -> None:
            events.append("close")

        def commit(self) -> None:
            if self.fail_commit:
                events.append("commit_fail")
                raise RuntimeError("commit exploded")
            events.append("commit")

        def rollback(self) -> None:
            events.append("rollback")

    def fake_req(fail_commit: bool = False) -> object:
        return SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(sessionmaker=lambda: FakeSession(fail_commit=fail_commit)))
        )

    # 1. Normal success: commit -> close -> hook
    events.clear()
    gen = get_uow(fake_req())  # type: ignore[arg-type]
    uow = next(gen)
    uow.after_commit(lambda: events.append("hook"))
    with pytest.raises(StopIteration):
        next(gen)
    assert events == ["commit", "close", "hook"]

    # 2. ApiError(commit=False): rollback -> close (no hook)
    events.clear()
    gen = get_uow(fake_req())  # type: ignore[arg-type]
    uow = next(gen)
    uow.after_commit(lambda: events.append("hook"))
    with pytest.raises(ApiError):
        gen.throw(ApiError(409, ProblemCode.conflict_state, commit=False))
    assert events == ["rollback", "close"]

    # 3. ApiError(commit=True): commit -> close -> hook
    events.clear()
    gen = get_uow(fake_req())  # type: ignore[arg-type]
    uow = next(gen)
    uow.after_commit(lambda: events.append("hook"))
    with pytest.raises(ApiError):
        gen.throw(ApiError(401, ProblemCode.refresh_reused, commit=True))
    assert events == ["commit", "close", "hook"]

    # 4. ApiError(commit=True) when commit itself raises: close only (no hook)
    events.clear()
    gen = get_uow(fake_req(fail_commit=True))  # type: ignore[arg-type]
    uow = next(gen)
    uow.after_commit(lambda: events.append("hook"))
    with pytest.raises(RuntimeError, match="commit exploded"):
        gen.throw(ApiError(401, ProblemCode.refresh_reused, commit=True))
    assert events == ["commit_fail", "close"]

    # 5. Unexpected RuntimeError: rollback -> close (no hook)
    events.clear()
    gen = get_uow(fake_req())  # type: ignore[arg-type]
    uow = next(gen)
    uow.after_commit(lambda: events.append("hook"))
    with pytest.raises(RuntimeError):
        gen.throw(RuntimeError("boom"))
    assert events == ["rollback", "close"]


def test_mail_from_default_and_check_production_guards() -> None:
    assert Settings().mail_from == "Mỹ Vị <no-reply@tastoria.ctslab.net>"

    valid = dict(
        env="production",
        database_url="postgresql+psycopg://app_prod:strong-db-password@db.internal:5432/tastoria",
        valkey_url="redis://:strong-valkey-pass@valkey.internal:6379/0",
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
    Settings(**valid).check_production()
    # mailer=log does not require smtp_starttls
    Settings(**(valid | {"mailer": "log", "smtp_starttls": False})).check_production()

    bad_cases = [
        ({"jwt_keys": {"p1": "too-short"}}, "TASTORIA_JWT_KEYS"),
        ({"jwt_active_kid": "missing"}, "TASTORIA_JWT_ACTIVE_KID"),
        ({"survey_jwt_keys": {"s1": "short"}}, "TASTORIA_SURVEY_JWT_KEYS"),
        ({"survey_jwt_keys": {"s1": valid["jwt_keys"]["p1"]}}, "TASTORIA_SURVEY_JWT_KEYS"),
        ({"survey_jwt_active_kid": "missing"}, "TASTORIA_SURVEY_JWT_ACTIVE_KID"),
        ({"health_enc_keys": {"p1": "not-32-bytes"}}, "TASTORIA_HEALTH_ENC_KEYS"),
        ({"health_enc_active_key_id": "missing"}, "TASTORIA_HEALTH_ENC_ACTIVE_KEY_ID"),
        ({"dsr_hmac_key": "short"}, "TASTORIA_DSR_HMAC_KEY"),
        ({"training_export_hmac_key": "short"}, "TASTORIA_TRAINING_EXPORT_HMAC_KEY"),
        ({"database_url": "postgresql+psycopg://tastoria:tastoria@127.0.0.1:5432/tastoria"}, "TASTORIA_DATABASE_URL"),
        ({"database_url": "postgresql+psycopg://u:change-me@db.internal:5432/tastoria"}, "TASTORIA_DATABASE_URL"),
        ({"valkey_url": "redis://valkey.internal:6379/0"}, "TASTORIA_VALKEY_URL"),
        ({"mailer": "smtp", "smtp_starttls": False}, "TASTORIA_SMTP_STARTTLS"),
    ]
    for overrides, expected_key in bad_cases:
        with pytest.raises(RuntimeError, match=expected_key):
            Settings(**(valid | overrides)).check_production()


def test_every_problem_code_has_vietnamese_title_without_brand_or_jargon() -> None:
    assert set(TITLES) == set(ProblemCode)
    for code, title in TITLES.items():
        assert title.strip(), code
        for forbidden in ("Tastoria", "app", "chip", "–", "—"):
            assert forbidden not in title, f"{code}: {title!r} contains {forbidden!r}"


def test_idempotency_persists_and_replays_response_headers_and_no_en_dash() -> None:
    stored: list[object] = []

    class FakeSession:
        def execute(self, *args: object, **kwargs: object) -> object:
            return SimpleNamespace(scalar_one=lambda: True)

        def scalars(self, *args: object, **kwargs: object) -> object:
            row = stored[0] if stored else None
            return SimpleNamespace(one_or_none=lambda: row)

        def add(self, obj: object) -> None:
            stored.append(obj)

        def flush(self) -> None:
            return None

    sess = FakeSession()
    uid = uuid.uuid4()
    idem = idempotency.IdempotencyRequest(key="abcdefghijklmnop", request_sha256=b"hash-bytes")

    assert idempotency.begin(sess, uid, idem) is None  # type: ignore[arg-type]
    first = idempotency.finish(
        sess, uid, idem, 201, {"id": "123"}, headers={"Location": "/api/v1/meal-plans/123"}  # type: ignore[arg-type]
    )
    assert first.headers["location"] == "/api/v1/meal-plans/123"
    assert stored[0].response_headers == {"Location": "/api/v1/meal-plans/123"}  # type: ignore[attr-defined]

    replayed = idempotency.begin(sess, uid, idem)  # type: ignore[arg-type]
    assert replayed is not None
    assert replayed.status_code == 201
    assert replayed.headers["location"] == "/api/v1/meal-plans/123"
    assert replayed.headers["idempotent-replayed"] == "true"

    req_bad = SimpleNamespace(headers={"idempotency-key": "bad"})
    with pytest.raises(ApiError) as exc_info:
        idempotency.header_key(req_bad)  # type: ignore[arg-type]
    assert "–" not in json.dumps(exc_info.value.errors, ensure_ascii=False)


def test_decode_created_rejects_wrong_arity_types_and_naive_datetime() -> None:
    dt = datetime(2026, 11, 24, 9, 0, 0, tzinfo=UTC)
    uid = uuid.uuid4()
    c = pagination.encode_created(dt, uid)
    assert pagination.decode_created(c) == (dt, uid)
    assert pagination.decode_created(None) is None

    c_int = pagination.encode([dt.isoformat(), 42])
    assert pagination.decode_created_int(c_int) == (dt, 42)
    assert pagination.decode_created_int(None) is None

    bad_payloads = [
        [dt.isoformat()],
        [dt.isoformat(), str(uid), "extra"],
        [123, str(uid)],
        [dt.isoformat(), 456],
        ["2026-11-24T10:00:00", str(uid)],
        ["2026-11-24", str(uid)],
        [dt.isoformat(), "not-a-uuid"],
    ]
    for payload in bad_payloads:
        with pytest.raises(ApiError) as exc_info:
            pagination.decode_created(pagination.encode(payload))
        assert (exc_info.value.status, exc_info.value.code) == (400, ProblemCode.validation_error)

    with pytest.raises(ApiError):
        pagination.decode_created("%%%not-base64%%%")

    for bad_int in ([dt.isoformat(), True], [dt.isoformat(), "42"], ["2026-11-24T10:00:00", 1]):
        with pytest.raises(ApiError) as exc_info:
            pagination.decode_created_int(pagination.encode(bad_int))
        assert (exc_info.value.status, exc_info.value.code) == (400, ProblemCode.validation_error)


def test_middleware_skips_second_response_start_when_streaming_already_started() -> None:
    async def run_case(start_before_raise: bool) -> tuple[list[dict[str, object]], bool]:
        sent: list[dict[str, object]] = []

        async def app(scope, receive, send):  # noqa: ANN001
            if start_before_raise:
                await send({"type": "http.response.start", "status": 200, "headers": []})
            raise RuntimeError("stream failed")

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(msg):  # noqa: ANN001
            sent.append(msg)

        mw = RequestContextMiddleware(app)
        scope = {"type": "http", "method": "GET", "path": "/api/v1/test", "headers": []}
        raised = False
        try:
            await mw(scope, receive, send)
        except RuntimeError:
            raised = True
        return sent, raised

    sent_started, raised_started = asyncio.run(run_case(True))
    assert raised_started is True
    starts = [m for m in sent_started if m["type"] == "http.response.start"]
    assert len(starts) == 1
    assert starts[0]["status"] == 200

    sent_pre, raised_pre = asyncio.run(run_case(False))
    assert raised_pre is False
    starts_pre = [m for m in sent_pre if m["type"] == "http.response.start"]
    assert len(starts_pre) == 1
    assert starts_pre[0]["status"] == 500
    headers = {k.lower(): v for k, v in starts_pre[0]["headers"]}  # type: ignore[arg-type]
    assert b"x-request-id" in headers
