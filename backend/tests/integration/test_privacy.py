"""UC05–UC08: consents by purpose, withdrawal, data-subject requests (export, delete cascade, manual types)."""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import uuid
import zipfile
from pathlib import Path

from conftest import q
from fastapi.testclient import TestClient
from helpers import bearer, login, register

from tastoria.modules.privacy.service import POLICY_DIR

API = "/api/v1"


def _policy(client: TestClient, purpose: str) -> dict:
    r = client.get(f"{API}/policies/{purpose}/current")
    assert r.status_code == 200, r.text
    return r.json()


def _grant(client: TestClient, s: dict, *purposes: str, channel: str = "onboarding") -> dict:
    decisions = [{"policy_version_id": _policy(client, p)["id"], "action": "grant"} for p in purposes]
    r = client.post(f"{API}/me/consents", json={"channel": channel, "decisions": decisions}, headers=bearer(s))
    assert r.status_code == 200, r.text
    return {i["purpose_code"]: i for i in r.json()["items"]}


def _states(client: TestClient, s: dict) -> dict[str, str]:
    r = client.get(f"{API}/me/consents", headers=bearer(s))
    assert r.status_code == 200, r.text
    return {i["purpose_code"]: i["state"] for i in r.json()["items"]}


# ---------------------------------------------------------------- policies


def test_current_policy_text_and_hash(client: TestClient) -> None:
    p = _policy(client, "health_profile")
    assert p["version"] == "2026-10-17" and p["purpose_code"] == "health_profile"
    assert p["purpose"]["is_sensitive"] is True and p["purpose"]["is_required"] is False
    raw = (POLICY_DIR / "health_profile-2026-10-17.md").read_bytes()
    assert p["text_vi"] == raw.decode() and p["text_sha256"] == hashlib.sha256(raw).hexdigest()
    r = client.get(f"{API}/policies/marketing/current")
    assert (r.status_code, r.json()["code"]) == (404, "purpose_not_found")


def test_future_policy_is_not_current(client: TestClient, db) -> None:
    q(
        db,
        "INSERT INTO policy_versions (purpose_code, version, text_sha256, effective_from) "
        "VALUES ('personalization', 'test-future', '\\x00', now() + interval '1 day')",
    )
    assert _policy(client, "personalization")["version"] == "2026-10-17"


# ---------------------------------------------------------------- consents


def test_new_user_has_no_consent(client: TestClient) -> None:
    s = register(client)
    assert _states(client, s) == {
        p: "none" for p in ("health_profile", "personalization", "photo_contribution", "survey")
    }


def test_grant_is_recorded_once(client: TestClient, db) -> None:
    s = register(client)
    items = _grant(client, s, "health_profile", "personalization")
    assert items["health_profile"]["state"] == items["personalization"]["state"] == "granted"
    assert items["photo_contribution"]["state"] == "none"
    rows = q(db, "SELECT action, channel, app_version FROM consent_events").all()
    assert len(rows) == 2 and all(r.action == "grant" and r.channel == "onboarding" for r in rows)
    _grant(client, s, "health_profile")  # FR-05-05: resend → no new event
    assert q(db, "SELECT count(*) FROM consent_events").scalar() == 2


def test_outdated_policy_and_superseded_state(client: TestClient, db) -> None:
    s = register(client)
    old_id = _policy(client, "health_profile")["id"]
    _grant(client, s, "health_profile")
    q(
        db,
        "INSERT INTO policy_versions (purpose_code, version, text_sha256, effective_from) "
        "VALUES ('health_profile', 'test-v2', '\\x00', now() - interval '1 second')",
    )
    assert _states(client, s)["health_profile"] == "superseded"
    body = {"channel": "settings", "decisions": [{"policy_version_id": old_id, "action": "grant"}]}
    r = client.post(f"{API}/me/consents", json=body, headers=bearer(s))
    assert (r.status_code, r.json()["code"]) == (409, "policy_outdated")
    assert q(db, "SELECT count(*) FROM consent_events").scalar() == 1


def test_survey_and_unknown_policy_are_not_allowed(client: TestClient, db) -> None:
    s = register(client)
    for pv in (_policy(client, "survey")["id"], str(uuid.uuid4())):
        body = {"channel": "settings", "decisions": [{"policy_version_id": pv, "action": "grant"}]}
        r = client.post(f"{API}/me/consents", json=body, headers=bearer(s))
        assert (r.status_code, r.json()["code"]) == (422, "purpose_not_allowed")
    # one bad decision rejects the whole batch
    body = {
        "channel": "settings",
        "decisions": [
            {"policy_version_id": _policy(client, "personalization")["id"], "action": "grant"},
            {"policy_version_id": _policy(client, "survey")["id"], "action": "grant"},
        ],
    }
    assert client.post(f"{API}/me/consents", json=body, headers=bearer(s)).status_code == 422
    assert q(db, "SELECT count(*) FROM consent_events").scalar() == 0


def test_withdraw_takes_effect_immediately(client: TestClient, db) -> None:
    s = register(client)
    _grant(client, s, "personalization")
    s2 = login(client, s["user"]["email"])
    r = client.post(f"{API}/me/consents/personalization/withdraw", json={"channel": "settings"}, headers=bearer(s2))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"] == "withdrawn" and body["data_request_id"]
    assert q(db, "SELECT token_version FROM users").scalar() == 1
    assert client.get(f"{API}/me/consents", headers=bearer(s2)).json()["code"] == "token_revoked"
    dsr = q(db, "SELECT * FROM dsr_requests").one()
    assert (dsr.type, dsr.note, dsr.status) == ("withdraw", "personalization", "completed")
    assert dsr.received_at is not None and dsr.acknowledged_at is not None and dsr.completed_at is not None
    expected_ref = hmac.new(b"test-hmac-key", uuid.UUID(s["user"]["id"]).bytes, hashlib.sha256).digest()
    assert bytes(dsr.subject_ref) == expected_ref
    assert [r.action for r in q(db, "SELECT action FROM consent_events ORDER BY created_at")] == ["grant", "withdraw"]


def test_withdraw_without_consent_is_a_noop(client: TestClient, db) -> None:
    s = register(client)
    for _ in range(2):
        r = client.post(f"{API}/me/consents/photo_contribution/withdraw", headers=bearer(s))
        assert r.status_code == 200 and r.json()["state"] == "none" and r.json()["data_request_id"] is None
    assert q(db, "SELECT token_version FROM users").scalar() == 0
    assert q(db, "SELECT count(*) FROM consent_events").scalar() == 0
    assert q(db, "SELECT count(*) FROM dsr_requests").scalar() == 0
    r = client.post(f"{API}/me/consents/nope/withdraw", headers=bearer(s))
    assert (r.status_code, r.json()["code"]) == (404, "purpose_not_found")


def test_withdraw_through_batch(client: TestClient, db) -> None:
    s = register(client)
    _grant(client, s, "health_profile")
    pv = _policy(client, "health_profile")["id"]
    body = {"channel": "settings", "decisions": [{"policy_version_id": pv, "action": "withdraw"}]}
    r = client.post(f"{API}/me/consents", json=body, headers=bearer(s))
    assert r.status_code == 200
    assert q(db, "SELECT token_version FROM users").scalar() == 1
    assert q(db, "SELECT type FROM dsr_requests").scalar() == "withdraw"


def test_consent_events_are_append_only(db) -> None:
    import pytest
    from sqlalchemy.exc import DBAPIError

    # FR-05-15: the row trigger refuses UPDATE/DELETE outside an erasure transaction
    u = q(db, "INSERT INTO users (email, password_hash) VALUES ('x@x.vn', 'h') RETURNING id").scalar()
    pv = q(db, "SELECT id FROM policy_versions WHERE purpose_code = 'health_profile'").scalar()
    q(db, "INSERT INTO consent_events (user_id, policy_version_id, action, channel) VALUES (:u, :p, 'grant', 'settings')",
      u=u, p=pv)  # fmt: skip
    with pytest.raises(DBAPIError):
        q(db, "UPDATE consent_events SET action = 'withdraw'")
    with pytest.raises(DBAPIError):
        q(db, "DELETE FROM consent_events")


# ---------------------------------------------------------------- data requests


def test_export_request_end_to_end(client: TestClient, db, storage_dir: Path) -> None:
    s = register(client)
    _grant(client, s, "personalization")
    r = client.post(f"{API}/me/data-requests", json={"type": "export"}, headers=bearer(s))
    assert r.status_code == 202, r.text
    rid = r.json()["id"]
    assert r.headers["location"] == f"/api/v1/me/data-requests/{rid}"
    got = client.get(f"{API}/me/data-requests/{rid}", headers=bearer(s)).json()
    assert got["status"] == "completed" and got["download_available"] is True
    dl = client.get(f"{API}/me/data-requests/{rid}/download", headers=bearer(s))
    assert dl.status_code == 200
    assert dl.headers["x-accel-redirect"] == f"/_protected/exports/{rid}.zip"
    assert q(db, "SELECT count(*) FROM audit_log WHERE action = 'dsr_download' AND entity_id = :i", i=rid).scalar() == 1

    archive = zipfile.ZipFile(io.BytesIO((storage_dir / f"exports/{rid}.zip").read_bytes()))
    names = set(archive.namelist())
    assert {"README.json", "users.json", "refresh_tokens.json", "consent_events.json", "dsr_requests.json"} <= names
    users = json.loads(archive.read("users.json"))
    assert users == [
        {"email": s["user"]["email"], "role": "user", "status": "active", "created_at": users[0]["created_at"]}
    ]
    blob = b"".join(archive.read(n) for n in names)
    hashes = [bytes(r.token_sha256).hex() for r in q(db, "SELECT token_sha256 FROM refresh_tokens")]
    for forbidden in (
        b"password_hash",
        b"token_sha256",
        b"request_sha256",
        b"$argon2id$",
        *[h.encode() for h in hashes],
    ):
        assert forbidden not in blob
    readme = json.loads(archive.read("README.json"))
    assert readme["exported_at"] and all(f["description_vi"] for f in readme["files"])


def test_open_request_is_returned_not_duplicated(client: TestClient, db) -> None:
    s = register(client)
    uid = s["user"]["id"]
    rid = q(
        db,
        "INSERT INTO dsr_requests (user_id, subject_ref, type, status, received_at, acknowledged_at) "
        "VALUES (:u, '\\x01', 'export', 'received', now(), now()) RETURNING id",
        u=uid,
    ).scalar()
    r = client.post(f"{API}/me/data-requests", json={"type": "export"}, headers=bearer(s))
    assert r.status_code == 200 and r.json()["id"] == str(rid)
    assert q(db, "SELECT count(*) FROM dsr_requests").scalar() == 1


def test_access_and_manual_requests(client: TestClient, db) -> None:
    s = register(client)
    r = client.post(f"{API}/me/data-requests", json={"type": "access"}, headers=bearer(s))
    assert (r.status_code, r.json()["code"]) == (422, "invalid_request") and "export" in r.json()["detail"]
    r = client.post(f"{API}/me/data-requests", json={"type": "correct", "note": "  "}, headers=bearer(s))
    assert (r.status_code, r.json()["code"]) == (422, "invalid_request")
    assert q(db, "SELECT count(*) FROM dsr_requests").scalar() == 0
    c = client.post(f"{API}/me/data-requests", json={"type": "correct", "note": "Sai năm sinh"}, headers=bearer(s))
    o = client.post(f"{API}/me/data-requests", json={"type": "object", "note": "Phản đối"}, headers=bearer(s))
    assert c.status_code == o.status_code == 202
    for resp, days in ((c, 10), (o, 15)):
        body = resp.json()
        assert body["status"] == "received"  # manual types wait for an admin (UC08)
        from datetime import datetime

        delta = datetime.fromisoformat(body["due_at"]) - datetime.fromisoformat(body["received_at"])
        assert delta.days == days
    again = client.post(f"{API}/me/data-requests", json={"type": "object", "note": "Lần nữa"}, headers=bearer(s))
    assert again.status_code == 200 and again.json()["id"] == o.json()["id"]


def test_data_requests_are_owner_only(client: TestClient) -> None:
    a, b = register(client), register(client)
    rid = client.post(f"{API}/me/data-requests", json={"type": "export"}, headers=bearer(a)).json()["id"]
    for path in (f"{API}/me/data-requests/{rid}", f"{API}/me/data-requests/{rid}/download"):
        r = client.get(path, headers=bearer(b))
        assert (r.status_code, r.json()["code"]) == (404, "not_found")
    r = client.get(f"{API}/me/data-requests/{uuid.uuid4()}", headers=bearer(a))
    assert (r.status_code, r.json()["code"]) == (404, "not_found")


def test_download_preconditions(client: TestClient, db, storage_dir: Path) -> None:
    s = register(client)
    uid = s["user"]["id"]
    pending = q(
        db,
        "INSERT INTO dsr_requests (user_id, subject_ref, type, status, received_at) "
        "VALUES (:u, '\\x01', 'export', 'in_progress', now()) RETURNING id",
        u=uid,
    ).scalar()
    r = client.get(f"{API}/me/data-requests/{pending}/download", headers=bearer(s))
    assert (r.status_code, r.json()["code"]) == (409, "request_not_ready")
    manual = client.post(f"{API}/me/data-requests", json={"type": "restrict", "note": "x"}, headers=bearer(s)).json()
    r = client.get(f"{API}/me/data-requests/{manual['id']}/download", headers=bearer(s))
    assert (r.status_code, r.json()["code"]) == (409, "request_not_downloadable")
    q(db, "UPDATE dsr_requests SET status = 'completed', completed_at = now() WHERE id = :i", i=pending)
    done = client.post(f"{API}/me/data-requests", json={"type": "export"}, headers=bearer(s)).json()
    (storage_dir / f"exports/{done['id']}.zip").unlink()
    r = client.get(f"{API}/me/data-requests/{done['id']}/download", headers=bearer(s))
    assert (r.status_code, r.json()["code"]) == (410, "export_expired")
    assert client.get(f"{API}/me/data-requests/{done['id']}", headers=bearer(s)).json()["download_available"] is False
