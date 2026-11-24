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
    assert counts == {"refresh_tokens": 2, "password_resets": 1, "idempotency_keys": 1, "scans_requeued": 0,
                      "scans_expired": 0}
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


def test_drain_email_outbox_and_purge_exports_cli(
    client: TestClient, db, monkeypatch, database_url: str, storage_dir
) -> None:
    from datetime import timedelta
    import os

    from tastoria import cli
    from tastoria.core import config
    from tastoria.core.clock import utcnow
    from tastoria.jobs.service import drain_email_outbox, purge_exports

    s = register(client)
    uid = s["user"]["id"]
    ok_id = q(
        db,
        "INSERT INTO email_outbox (user_id, to_email, template, subject, body_text, status, attempts, next_attempt_at) "
        "VALUES (:u, 'ok@tastoria.local', 'verify', 'Subj 1', 'Body 1', 'pending', 0, now() - interval '1 minute') RETURNING id",
        u=uid,
    ).scalar()
    fail_id = q(
        db,
        "INSERT INTO email_outbox (user_id, to_email, template, subject, body_text, status, attempts, next_attempt_at) "
        "VALUES (:u, 'bad@tastoria.local', 'verify', 'Subj 2', 'Body 2', 'pending', 4, now() - interval '1 minute') RETURNING id",
        u=uid,
    ).scalar()
    future_id = q(
        db,
        "INSERT INTO email_outbox (user_id, to_email, template, subject, body_text, status, attempts, next_attempt_at) "
        "VALUES (:u, 'later@tastoria.local', 'verify', 'Subj 3', 'Body 3', 'pending', 0, now() + interval '10 minutes') RETURNING id",
        u=uid,
    ).scalar()

    sent_msgs: list[tuple[str, str, str]] = []

    class _FakeMailer:
        def send(self, to: str, subject: str, body: str) -> None:
            if to.startswith("bad@"):
                raise RuntimeError("smtp 421")
            sent_msgs.append((to, subject, body))

    res = drain_email_outbox(client.app.state.sessionmaker, _FakeMailer())
    assert res == {"claimed": 2, "sent": 1, "retried": 0, "failed": 1}
    assert sent_msgs == [("ok@tastoria.local", "Subj 1", "Body 1")]
    assert q(db, "SELECT status FROM email_outbox WHERE id = :i", i=ok_id).scalar() == "sent"
    assert q(db, "SELECT status, attempts FROM email_outbox WHERE id = :i", i=fail_id).one() == ("failed", 5)
    assert q(db, "SELECT status FROM email_outbox WHERE id = :i", i=future_id).scalar() == "pending"

    # Re-add one pending row to test CLI `drain-outbox` and expired/fresh export ZIPs to test `purge-exports`
    cli_id = q(
        db,
        "INSERT INTO email_outbox (user_id, to_email, template, subject, body_text, status, attempts, next_attempt_at) "
        "VALUES (:u, 'cli@tastoria.local', 'verify', 'CLI Subj', 'CLI Body', 'pending', 0, now() - interval '1 minute') RETURNING id",
        u=uid,
    ).scalar()
    exp_dir = storage_dir / "exports"
    exp_dir.mkdir(parents=True, exist_ok=True)
    old_zip = exp_dir / "old-export.zip"
    fresh_zip = exp_dir / "fresh-export.zip"
    old_tmp = exp_dir / ".crashed.zip.tmp"
    old_zip.write_bytes(b"zip-old")
    fresh_zip.write_bytes(b"zip-new")
    old_tmp.write_bytes(b"partial")
    old_ts = (utcnow() - timedelta(hours=25)).timestamp()
    stale_tmp_ts = (utcnow() - timedelta(hours=2)).timestamp()
    os.utime(old_zip, (old_ts, old_ts))
    os.utime(old_tmp, (stale_tmp_ts, stale_tmp_ts))

    monkeypatch.setenv("TASTORIA_DATABASE_URL", database_url)
    monkeypatch.setenv("TASTORIA_STORAGE_DIR", str(storage_dir))
    monkeypatch.setenv("TASTORIA_MAILER", "log")
    monkeypatch.setenv("TASTORIA_LOG_LEVEL", "WARNING")
    config.get_settings.cache_clear()
    try:
        assert cli.main(["jobs", "drain-outbox"]) == 0
        assert cli.main(["jobs", "purge-exports"]) == 0
    finally:
        config.get_settings.cache_clear()
    assert q(db, "SELECT status FROM email_outbox WHERE id = :i", i=cli_id).scalar() == "sent"
    assert not old_zip.exists() and not old_tmp.exists() and fresh_zip.exists()
    assert purge_exports(storage_dir) == {"exports_purged": 0, "tmp_removed": 0}
