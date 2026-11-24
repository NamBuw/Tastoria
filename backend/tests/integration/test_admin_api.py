"""UC27, UC29, UC30: /admin/data-requests, /admin/data-requests/{id}/resolve, /admin/audit-log, /admin/models."""

from __future__ import annotations

import base64
import hashlib
import hmac
import struct
import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from helpers import PASSWORD, bearer, login, register
from kb_helpers import API, q

from tastoria.core.clock import shift_for_tests, utcnow
from tastoria.modules.admin import mlops as ops


def _user_with_role(client: TestClient, db, role: str) -> tuple[dict, dict[str, str]]:
    s = register(client)
    q(db, "UPDATE users SET role = :r WHERE id = :i", r=role, i=s["user"]["id"])
    logged = login(client, s["user"]["email"], s["password"])
    return logged, bearer(logged)


def test_admin_endpoints_require_auth_and_strict_rbac_with_audit(kb_client: TestClient, kb_db) -> None:
    rid = uuid.uuid4()
    assert kb_client.get(f"{API}/admin/data-requests").status_code == 401
    assert kb_client.post(f"{API}/admin/data-requests/{rid}/resolve", json={"status": "completed", "note": "ok"}).status_code == 401
    assert kb_client.get(f"{API}/admin/audit-log").status_code == 401
    assert kb_client.get(f"{API}/admin/models").status_code == 401

    for role in ("user", "curator", "ml_operator"):
        u, h = _user_with_role(kb_client, kb_db, role)
        r1 = kb_client.get(f"{API}/admin/data-requests", headers=h)
        r2 = kb_client.post(
            f"{API}/admin/data-requests/{rid}/resolve",
            json={"status": "completed", "note": "ok"},
            headers=h,
        )
        r3 = kb_client.get(f"{API}/admin/audit-log", headers=h)
        assert (r1.status_code, r1.json()["code"]) == (403, "forbidden"), role
        assert (r2.status_code, r2.json()["code"]) == (403, "forbidden"), role
        assert (r3.status_code, r3.json()["code"]) == (403, "forbidden"), role
        denied = q(
            kb_db,
            "SELECT count(*) FROM audit_log WHERE actor_user_id = :u AND purpose = 'forbidden'",
            u=u["user"]["id"],
        ).scalar()
        assert denied == 3

    for role in ("user", "curator", "admin"):
        u, h = _user_with_role(kb_client, kb_db, role)
        rm = kb_client.get(f"{API}/admin/models", headers=h)
        assert (rm.status_code, rm.json()["code"]) == (403, "forbidden"), role
        denied = q(
            kb_db,
            "SELECT count(*) FROM audit_log WHERE actor_user_id = :u AND action = 'model.list' AND purpose = 'forbidden'",
            u=u["user"]["id"],
        ).scalar()
        assert denied == 1


def test_admin_dsr_list_pagination_and_resolve_lifecycle(kb_client: TestClient, kb_db) -> None:
    u1 = register(kb_client)
    u2 = register(kb_client)
    h1, h2 = bearer(u1), bearer(u2)
    c_req = kb_client.post(f"{API}/me/data-requests", json={"type": "correct", "note": "Sai tên"}, headers=h1).json()
    o_req = kb_client.post(f"{API}/me/data-requests", json={"type": "object", "note": "Phản đối"}, headers=h2).json()
    e_req = kb_client.post(f"{API}/me/data-requests", json={"type": "export"}, headers=h1).json()
    # Deleted user DSR (user_id = NULL)
    del_req_id = str(uuid.uuid4())
    q(
        kb_db,
        "INSERT INTO dsr_requests (id, user_id, subject_ref, type, status, received_at, note) "
        "VALUES (:id, NULL, decode(repeat('ab', 32), 'hex'), 'restrict', 'received', now() - interval '2 days', 'deleted user')",
        id=del_req_id,
    )

    _, admin_h = _user_with_role(kb_client, kb_db, "admin")
    p1 = kb_client.get(f"{API}/admin/data-requests", params={"limit": 1, "type": ["correct", "object"]}, headers=admin_h)
    assert p1.status_code == 200, p1.text
    b1 = p1.json()
    assert len(b1["items"]) == 1 and b1["next_cursor"]
    p2 = kb_client.get(
        f"{API}/admin/data-requests",
        params={"limit": 1, "type": ["correct", "object"], "cursor": b1["next_cursor"]},
        headers=admin_h,
    ).json()
    assert len(p2["items"]) == 1 and p2["next_cursor"] is None
    assert [b1["items"][0]["id"], p2["items"][0]["id"]] == [c_req["id"], o_req["id"]]
    assert len(b1["items"][0]["subject_ref"]) == 64

    # Error paths on resolve
    assert kb_client.post(
        f"{API}/admin/data-requests/{uuid.uuid4()}/resolve",
        json={"status": "completed", "note": "x"},
        headers=admin_h,
    ).status_code == 404
    auto_err = kb_client.post(
        f"{API}/admin/data-requests/{e_req['id']}/resolve",
        json={"status": "completed", "note": "x"},
        headers=admin_h,
    )
    assert (auto_err.status_code, auto_err.json()["code"]) == (409, "request_not_manual")
    blank = kb_client.post(
        f"{API}/admin/data-requests/{c_req['id']}/resolve",
        json={"status": "rejected", "note": "   "},
        headers=admin_h,
    )
    assert (blank.status_code, blank.json()["code"]) == (422, "reason_required")

    # received -> in_progress -> completed, idempotent repeat, conflict on reverse
    r_ip = kb_client.post(
        f"{API}/admin/data-requests/{c_req['id']}/resolve",
        json={"status": "in_progress", "note": "Đang xác minh"},
        headers=admin_h,
    )
    assert r_ip.status_code == 200 and r_ip.json()["status"] == "in_progress"
    r_done = kb_client.post(
        f"{API}/admin/data-requests/{c_req['id']}/resolve",
        json={"status": "completed", "note": "Đã cập nhật"},
        headers=admin_h,
    )
    assert r_done.status_code == 200
    done_body = r_done.json()
    assert done_body["status"] == "completed" and done_body["completed_at"] is not None
    assert "[in_progress] Đang xác minh" in done_body["note"]
    assert "[completed] Đã cập nhật" in done_body["note"]

    audits_before = q(
        kb_db, "SELECT count(*) FROM audit_log WHERE action = 'dsr_resolve' AND entity_id = :i", i=c_req["id"]
    ).scalar()
    assert audits_before == 2
    idem = kb_client.post(
        f"{API}/admin/data-requests/{c_req['id']}/resolve",
        json={"status": "completed", "note": "Gửi lại"},
        headers=admin_h,
    )
    assert idem.status_code == 200 and idem.json()["note"] == done_body["note"]
    assert (
        q(kb_db, "SELECT count(*) FROM audit_log WHERE action = 'dsr_resolve' AND entity_id = :i", i=c_req["id"]).scalar()
        == 2
    )
    conflict = kb_client.post(
        f"{API}/admin/data-requests/{c_req['id']}/resolve",
        json={"status": "rejected", "note": "Đổi ý"},
        headers=admin_h,
    )
    assert (conflict.status_code, conflict.json()["code"]) == (409, "conflict_state")

    # Resolve deleted-user DSR (user_id is NULL)
    r_del = kb_client.post(
        f"{API}/admin/data-requests/{del_req_id}/resolve",
        json={"status": "rejected", "note": "Tài khoản đã xoá"},
        headers=admin_h,
    )
    assert r_del.status_code == 200 and r_del.json()["user_id"] is None and r_del.json()["status"] == "rejected"


def test_admin_audit_log_filters_and_int_keyset_pagination(kb_client: TestClient, kb_db) -> None:
    admin_u, admin_h = _user_with_role(kb_client, kb_db, "admin")
    uid = admin_u["user"]["id"]
    for i in range(4):
        q(
            kb_db,
            "INSERT INTO audit_log (actor_user_id, actor_role, action, entity, entity_id, purpose, created_at) "
            "VALUES (:u, 'admin', 'dsr_resolve', 'dsr_requests', :eid, 'completed', now() + make_interval(secs => :s))",
            u=uid,
            eid=f"e-{i}",
            s=i,
        )

    bad_range = kb_client.get(
        f"{API}/admin/audit-log",
        params={"from": (datetime.now(UTC) + timedelta(days=1)).isoformat(), "to": datetime.now(UTC).isoformat()},
        headers=admin_h,
    )
    assert (bad_range.status_code, bad_range.json()["code"]) == (422, "validation_error")

    p1 = kb_client.get(
        f"{API}/admin/audit-log",
        params={"actor_user_id": uid, "entity": "dsr_requests", "action": "dsr_resolve", "limit": 2},
        headers=admin_h,
    )
    assert p1.status_code == 200, p1.text
    b1 = p1.json()
    assert len(b1["items"]) == 2 and b1["next_cursor"]
    # SELECT ran before write_audit, so own audit_log.list row is never in the filtered dsr_resolve result
    assert all(x["action"] == "dsr_resolve" for x in b1["items"])
    p2 = kb_client.get(
        f"{API}/admin/audit-log",
        params={
            "actor_user_id": uid,
            "entity": "dsr_requests",
            "action": "dsr_resolve",
            "limit": 2,
            "cursor": b1["next_cursor"],
        },
        headers=admin_h,
    ).json()
    assert len(p2["items"]) == 2 and p2["next_cursor"] is None
    ids = [x["id"] for x in b1["items"] + p2["items"]]
    assert ids == sorted(ids, reverse=True) and len(set(ids)) == 4


def test_admin_models_lists_versions_deployments_and_pages(
    kb_client: TestClient, kb_db, kb_app, storage_dir, tmp_path
) -> None:
    sm = kb_app.state.sessionmaker
    try:
        for i in (1, 2):
            art = tmp_path / f"ranker_{i}.bin"
            art.write_bytes(f"ranker-{i}".encode())
            ops.register(
                sm,
                storage_dir,
                name="ranker",
                version=f"r-adm-{i}",
                artifact=art,
                metrics={"eval": {"ndcg": 0.8 + i * 0.01}},
                preprocess_version=None,
                class_codes=None,
                mlflow_run_id=f"run-{i}",
            )
            q(
                kb_db,
                "UPDATE model_versions SET status = 'validated', gate_report_key = :gk WHERE version = :v",
                gk=f"models/ranker/r-adm-{i}/gate.json",
                v=f"r-adm-{i}",
            )
        ops.deploy(sm, name="ranker", version="r-adm-2")

        _, op_h = _user_with_role(kb_client, kb_db, "ml_operator")
        p1 = kb_client.get(
            f"{API}/admin/models",
            params={"name": "ranker", "status": "validated", "limit": 1},
            headers=op_h,
        )
        assert p1.status_code == 200, p1.text
        b1 = p1.json()
        assert len(b1["items"]) == 1 and b1["next_cursor"]
        assert b1["deployments"] and b1["deployments"][0]["name"] == "ranker"
        assert "switched_by" in b1["deployments"][0]
        item1 = b1["items"][0]
        assert item1["version"] == "r-adm-2" and item1["is_active"] is True
        assert item1["gate_report_key"] == "models/ranker/r-adm-2/gate.json"
        assert item1["mlflow_run_id"] == "run-2"

        p2 = kb_client.get(
            f"{API}/admin/models",
            params={"name": "ranker", "status": "validated", "limit": 1, "cursor": b1["next_cursor"]},
            headers=op_h,
        ).json()
        assert len(p2["items"]) == 1 and p2["items"][0]["version"] == "r-adm-1" and p2["next_cursor"] is None
    finally:
        q(kb_db, "DELETE FROM model_deployments")
        q(kb_db, "DELETE FROM model_versions WHERE version LIKE 'r-adm-%'")


def _totp_now(secret_b32: str) -> str:
    padded = secret_b32 + "=" * ((-len(secret_b32)) % 8)
    secret = base64.b32decode(padded)
    counter = int(utcnow().timestamp()) // 30
    digest = hmac.new(secret, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{code:06d}"


def test_admin_mfa_guard_and_audit_bloat_prevention(kb_client: TestClient, kb_db, kb_app) -> None:
    admin_u, admin_h = _user_with_role(kb_client, kb_db, "admin")
    op_u, op_h = _user_with_role(kb_client, kb_db, "ml_operator")

    # 1. Repeated GET /admin/models and GET /admin/audit-log write 0 audit_log rows
    before = q(kb_db, "SELECT count(*) FROM audit_log").scalar()
    for _ in range(3):
        assert kb_client.get(f"{API}/admin/audit-log", headers=admin_h).status_code == 200
        assert kb_client.get(f"{API}/admin/models", headers=op_h).status_code == 200
    assert q(kb_db, "SELECT count(*) FROM audit_log").scalar() == before

    # 2. GET /admin/data-requests coalesces dsr.list: cursor-skip + 60s cooldown
    assert kb_client.get(f"{API}/admin/data-requests", headers=admin_h).status_code == 200
    assert kb_client.get(f"{API}/admin/data-requests", headers=admin_h).status_code == 200
    assert (
        q(
            kb_db,
            "SELECT count(*) FROM audit_log WHERE actor_user_id = :u AND action = 'dsr.list'",
            u=admin_u["user"]["id"],
        ).scalar()
        == 1
    )
    shift_for_tests(61)
    try:
        assert kb_client.get(f"{API}/admin/data-requests", headers=admin_h).status_code == 200
    finally:
        shift_for_tests(0)
    assert (
        q(
            kb_db,
            "SELECT count(*) FROM audit_log WHERE actor_user_id = :u AND action = 'dsr.list'",
            u=admin_u["user"]["id"],
        ).scalar()
        == 2
    )

    # 3. Pre-MFA token on MFA-enabled admin is rejected with 403 mfa_required; MFA-verified token succeeds
    setup = kb_client.post(f"{API}/auth/mfa/setup", headers=admin_h).json()
    mfa_s = kb_client.post(
        f"{API}/auth/mfa/verify",
        json={"code": _totp_now(setup["secret"])},
        headers=admin_h,
    ).json()
    assert kb_client.get(f"{API}/admin/data-requests", headers=bearer(mfa_s)).status_code == 200

    # Production mode blocks non-MFA staff (op_u has mfa_enabled_at IS NULL) with 403 mfa_required
    prev_env = kb_app.state.settings.env
    kb_app.state.settings.env = "production"
    try:
        r_prod_block = kb_client.get(f"{API}/admin/models", headers=op_h)
        assert (r_prod_block.status_code, r_prod_block.json()["code"]) == (403, "mfa_required")
        assert (
            q(
                kb_db,
                "SELECT count(*) FROM audit_log WHERE actor_user_id = :u AND purpose = 'mfa_required'",
                u=op_u["user"]["id"],
            ).scalar()
            == 1
        )
        # MFA-verified admin still succeeds in production
        assert kb_client.get(f"{API}/admin/audit-log", headers=bearer(mfa_s)).status_code == 200
    finally:
        kb_app.state.settings.env = prev_env
