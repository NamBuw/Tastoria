"""Reusable Idempotency-Key dependency and Unit-of-Work semantics, exercised through a test-only router."""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import q
from fastapi import APIRouter, Response
from fastapi.testclient import TestClient
from helpers import bearer, register
from pydantic import BaseModel
from sqlalchemy import text

from tastoria.core import idempotency
from tastoria.core.db import UnitOfWork, Uow
from tastoria.core.errors import ApiError, ProblemCode
from tastoria.core.idempotency import IdempotencyKeyDep
from tastoria.modules.identity.service import CurrentUser


class Thing(BaseModel):
    name: str
    sleep_s: float = 0.0


def _record(uow: UnitOfWork, action: str, entity_id: str) -> None:
    uow.session.execute(
        text("INSERT INTO audit_log (actor_role, action, entity, entity_id) VALUES ('test', :a, 'thing', :e)"),
        {"a": action, "e": entity_id},
    )


def _router(hooks: list[str]) -> APIRouter:
    r = APIRouter(prefix="/api/v1/_test")

    @r.post("/things", status_code=201)
    def create_thing(body: Thing, user: CurrentUser, uow: Uow, idem: IdempotencyKeyDep) -> Response:
        if (replayed := idempotency.begin(uow.session, user.id, idem)) is not None:
            return replayed
        thing_id = str(uuid.uuid4())
        _record(uow, "create_thing", thing_id)
        if body.sleep_s:
            time.sleep(body.sleep_s)
        if body.name == "boom":
            raise ApiError(409, ProblemCode.conflict_state)
        return idempotency.finish(uow.session, user.id, idem, 201, {"id": thing_id, "name": body.name})

    @r.post("/uow/{mode}")
    def uow_mode(mode: str, uow: Uow) -> dict[str, str]:
        _record(uow, f"uow_{mode}", mode)
        uow.after_commit(lambda: hooks.append(mode))
        if mode == "fail":
            raise ApiError(409, ProblemCode.conflict_state)
        if mode == "fail_keep":
            raise ApiError(401, ProblemCode.refresh_reused, commit=True)
        if mode == "crash":
            raise RuntimeError("boom")
        if mode == "commit_fails":  # a deferred constraint makes COMMIT itself fail after the endpoint returned
            uow.session.execute(text("CREATE TEMP TABLE t_defer (x int UNIQUE DEFERRABLE INITIALLY DEFERRED)"))
            uow.session.execute(text("INSERT INTO t_defer VALUES (1), (1)"))
        return {"ok": mode}

    return r


@pytest.fixture
def tclient(make_app, clean_db):
    from fakes import FakeMailer

    hooks: list[str] = []
    app = make_app()
    app.state.mailer = FakeMailer()
    app.include_router(_router(hooks))
    with TestClient(app, raise_server_exceptions=False) as c:
        c.hooks = hooks  # type: ignore[attr-defined]
        yield c


def _count(db, action: str = "create_thing") -> int:
    return q(db, "SELECT count(*) FROM audit_log WHERE action = :a", a=action).scalar()


KEY = "key-0123456789abcdef"


def test_replay_returns_stored_response(tclient: TestClient, db) -> None:
    s = register(tclient)
    h = {**bearer(s), "Idempotency-Key": KEY}
    r1 = tclient.post("/api/v1/_test/things", json={"name": "a"}, headers=h)
    r2 = tclient.post("/api/v1/_test/things", json={"name": "a"}, headers=h)
    assert r1.status_code == r2.status_code == 201
    assert r1.json() == r2.json()
    assert "idempotent-replayed" not in r1.headers and r2.headers["idempotent-replayed"] == "true"
    assert _count(db) == 1
    row = q(db, "SELECT status_code, response_body FROM idempotency_keys").one()
    assert row.status_code == 201 and row.response_body == r1.json()


def test_same_key_other_body_is_rejected(tclient: TestClient, db) -> None:
    s = register(tclient)
    h = {**bearer(s), "Idempotency-Key": KEY}
    tclient.post("/api/v1/_test/things", json={"name": "a"}, headers=h)
    r = tclient.post("/api/v1/_test/things", json={"name": "b"}, headers=h)
    assert (r.status_code, r.json()["code"]) == (422, "idempotency_key_reused")
    assert _count(db) == 1


def test_key_is_scoped_per_user(tclient: TestClient, db) -> None:
    a, b = register(tclient), register(tclient)
    for s in (a, b):
        r = tclient.post("/api/v1/_test/things", json={"name": "a"}, headers={**bearer(s), "Idempotency-Key": KEY})
        assert r.status_code == 201 and "idempotent-replayed" not in r.headers
    assert _count(db) == 2


def test_missing_or_malformed_key(tclient: TestClient) -> None:
    s = register(tclient)
    r = tclient.post("/api/v1/_test/things", json={"name": "a"}, headers=bearer(s))
    assert (r.status_code, r.json()["code"]) == (400, "idempotency_key_required")
    r = tclient.post("/api/v1/_test/things", json={"name": "a"}, headers={**bearer(s), "Idempotency-Key": "short"})
    assert (r.status_code, r.json()["code"]) == (400, "validation_error")


def test_failed_attempt_stores_nothing(tclient: TestClient, db) -> None:
    s = register(tclient)
    h = {**bearer(s), "Idempotency-Key": KEY}
    r = tclient.post("/api/v1/_test/things", json={"name": "boom"}, headers=h)
    assert r.status_code == 409
    assert q(db, "SELECT count(*) FROM idempotency_keys").scalar() == 0
    assert _count(db) == 0  # the side effect was rolled back with it


def test_concurrent_duplicate_is_told_to_retry(tclient: TestClient, db) -> None:
    s = register(tclient)
    h = {**bearer(s), "Idempotency-Key": KEY}
    body = {"name": "slow", "sleep_s": 1.0}
    start = threading.Barrier(2)

    def call(delay: float):
        start.wait()
        time.sleep(delay)
        return tclient.post("/api/v1/_test/things", json=body, headers=h)

    with ThreadPoolExecutor(2) as ex:
        first, second = ex.map(call, (0.0, 0.3))
    assert first.status_code == 201
    assert (second.status_code, second.json()["code"]) == (409, "idempotency_in_progress")
    assert second.headers["retry-after"] == "1"
    again = tclient.post("/api/v1/_test/things", json=body, headers=h)
    assert again.status_code == 201 and again.json() == first.json() and again.headers["idempotent-replayed"] == "true"
    assert _count(db) == 1


def test_uow_commit_rollback_and_hooks(tclient: TestClient, db) -> None:
    assert tclient.post("/api/v1/_test/uow/ok").status_code == 200
    assert tclient.post("/api/v1/_test/uow/fail").status_code == 409
    assert tclient.post("/api/v1/_test/uow/fail_keep").status_code == 401
    r = tclient.post("/api/v1/_test/uow/crash")
    assert (r.status_code, r.json()["code"]) == (500, "internal_error")
    assert r.headers["x-request-id"] == r.json()["request_id"]
    assert _count(db, "uow_ok") == 1
    assert _count(db, "uow_fail") == 0
    assert _count(db, "uow_fail_keep") == 1  # ApiError(commit=True) keeps the writes
    assert _count(db, "uow_crash") == 0
    assert tclient.hooks == ["ok"]  # after-commit hooks run only on success


def test_commit_failure_is_not_reported_as_success(tclient: TestClient, db) -> None:
    r = tclient.post("/api/v1/_test/uow/commit_fails")
    assert r.status_code == 500
    assert _count(db, "uow_commit_fails") == 0
    assert tclient.hooks == []
