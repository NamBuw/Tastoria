"""UC34 sweeper and the DSR recovery command."""

from __future__ import annotations

import uuid

from conftest import q
from fastapi.testclient import TestClient
from helpers import register

from tastoria.jobs.sweep import sweep


def test_sweep_removes_only_expired_rows(client: TestClient, db, app) -> None:
    s = register(client)
    uid = s["user"]["id"]
    fam = uuid.uuid4()
    newer = q(db, "INSERT INTO refresh_tokens (user_id, family_id, token_sha256, issued_at, expires_at) "
                  "VALUES (:u, :f, :h, now() - interval '40 days', now() - interval '10 days') RETURNING id",
              u=uid, f=fam, h=uuid.uuid4().bytes).scalar()  # fmt: skip
    q(db, "INSERT INTO refresh_tokens (user_id, family_id, token_sha256, issued_at, expires_at, revoked_at, replaced_by_id) "
          "VALUES (:u, :f, :h, now() - interval '41 days', now() - interval '11 days', now(), :n)",
      u=uid, f=fam, h=uuid.uuid4().bytes, n=newer)  # fmt: skip
    q(db, "INSERT INTO password_resets (user_id, token_sha256, created_at, expires_at) "
          "VALUES (:u, :h, now() - interval '2 hours', now() - interval '1 hour')", u=uid, h=uuid.uuid4().bytes)  # fmt: skip
    q(db, "INSERT INTO idempotency_keys (user_id, key, request_sha256, status_code, response_body, created_at) "
          "VALUES (:u, 'old-0123456789abcdef', '\\x01', 201, '{}', now() - interval '49 hours'), "
          "(:u, 'new-0123456789abcdef', '\\x01', 201, '{}', now() - interval '47 hours')", u=uid)  # fmt: skip
    counts = sweep(app.state.sessionmaker)
    assert counts == {"refresh_tokens": 2, "password_resets": 1, "idempotency_keys": 1}
    assert q(db, "SELECT count(*) FROM refresh_tokens").scalar() == 1  # the live session from register
    assert q(db, "SELECT key FROM idempotency_keys").scalar() == "new-0123456789abcdef"


def test_cli_process_dsr(client: TestClient, db, monkeypatch, database_url: str, storage_dir) -> None:
    from tastoria import cli
    from tastoria.core import config

    s = register(client)
    rid = q(db, "INSERT INTO dsr_requests (user_id, subject_ref, type, status, received_at, acknowledged_at) "
                "VALUES (:u, '\\x01', 'export', 'received', now(), now()) RETURNING id", u=s["user"]["id"]).scalar()  # fmt: skip
    monkeypatch.setenv("TASTORIA_DATABASE_URL", database_url)
    monkeypatch.setenv("TASTORIA_STORAGE_DIR", str(storage_dir))
    monkeypatch.setenv("TASTORIA_LOG_LEVEL", "WARNING")
    config.get_settings.cache_clear()
    try:
        assert cli.main(["jobs", "process-dsr"]) == 0
    finally:
        config.get_settings.cache_clear()
    assert q(db, "SELECT status FROM dsr_requests WHERE id = :i", i=rid).scalar() == "completed"
    assert (storage_dir / f"exports/{rid}.zip").is_file()
