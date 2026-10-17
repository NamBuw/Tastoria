"""UC07: account deletion really erases every personal row (also in append-only tables) and keeps the evidence."""

from __future__ import annotations

import uuid
from pathlib import Path

from conftest import insert_recipe, q
from fastapi.testclient import TestClient
from helpers import PASSWORD, bearer, login, register

API = "/api/v1"

# Every table holding personal data, with how to count one user's rows in it.
PERSONAL = {
    "users": "SELECT count(*) FROM users WHERE id = :u",
    "refresh_tokens": "SELECT count(*) FROM refresh_tokens WHERE user_id = :u",
    "password_resets": "SELECT count(*) FROM password_resets WHERE user_id = :u",
    "idempotency_keys": "SELECT count(*) FROM idempotency_keys WHERE user_id = :u",
    "consent_events": "SELECT count(*) FROM consent_events WHERE user_id = :u",
    "profiles": "SELECT count(*) FROM profiles WHERE user_id = :u",
    "user_allergens": "SELECT count(*) FROM user_allergens WHERE user_id = :u",
    "user_favorite_recipes": "SELECT count(*) FROM user_favorite_recipes WHERE user_id = :u",
    "user_settings": "SELECT count(*) FROM user_settings WHERE user_id = :u",
    "pantry_lots": "SELECT count(*) FROM pantry_lots WHERE user_id = :u",
    "pantry_transactions": "SELECT count(*) FROM pantry_transactions t JOIN pantry_lots l ON l.id = t.lot_id "
    "WHERE l.user_id = :u",
    "scans": "SELECT count(*) FROM scans WHERE user_id = :u",
    "scan_images": "SELECT count(*) FROM scan_images i JOIN scans s ON s.id = i.scan_id WHERE s.user_id = :u",
    "shopping_items": "SELECT count(*) FROM shopping_items WHERE user_id = :u",
    "meal_plans": "SELECT count(*) FROM meal_plans WHERE user_id = :u",
    "meal_plan_items": "SELECT count(*) FROM meal_plan_items i JOIN meal_plans m ON m.id = i.meal_plan_id "
    "WHERE m.user_id = :u",
    "cook_sessions": "SELECT count(*) FROM cook_sessions c JOIN meal_plans m ON m.id = c.meal_plan_id "
    "WHERE m.user_id = :u",
    "interactions": "SELECT count(*) FROM interactions WHERE user_id = :u",
}


def _seed_everywhere(db, uid: str, recipe_id: str) -> dict[str, str]:
    """One row in every personal table, written the way the later slices will write them."""
    q(db, "INSERT INTO food_groups (code, name_vi) VALUES ('rau', 'Rau') ON CONFLICT DO NOTHING")
    ing = q(db, "INSERT INTO ingredients (name_vi, food_group_code) VALUES (:n, 'rau') RETURNING id",
            n=f"rau-{uuid.uuid4().hex[:6]}").scalar()  # fmt: skip
    q(db, "INSERT INTO password_resets (user_id, token_sha256, expires_at) "
          "VALUES (:u, :h, now() + interval '1 hour')", u=uid, h=uuid.uuid4().bytes)  # fmt: skip
    q(db, "INSERT INTO idempotency_keys (user_id, key, request_sha256, status_code, response_body) "
          "VALUES (:u, 'k-0123456789abcdef', '\\x01', 201, '{}')", u=uid)  # fmt: skip
    q(db, "INSERT INTO consent_events (user_id, policy_version_id, action, channel) SELECT :u, id, 'grant', 'settings' "
          "FROM policy_versions WHERE purpose_code = 'photo_contribution'", u=uid)  # fmt: skip
    q(db, "INSERT INTO profiles (user_id, diet_code) VALUES (:u, NULL)", u=uid)
    q(db, "INSERT INTO user_allergens (user_id, allergen_code) VALUES (:u, 'ca')", u=uid)
    q(db, "INSERT INTO user_favorite_recipes (user_id, recipe_id) VALUES (:u, :r)", u=uid, r=recipe_id)
    q(db, "INSERT INTO user_settings (user_id) VALUES (:u)", u=uid)
    lot = q(db, "INSERT INTO pantry_lots (user_id, ingredient_id, initial_g_min, initial_g_max, acquired_at, "
                "acquired_basis) VALUES (:u, :i, 100, 200, now(), 'first_seen') RETURNING id", u=uid, i=ing).scalar()  # fmt: skip
    q(db, "INSERT INTO pantry_transactions (lot_id, delta_g_min, delta_g_max, reason, ref_type, ref_id) "
          "VALUES (:l, -10, -10, 'manual_edit', 'user', :u)", l=lot, u=uid)  # fmt: skip
    scan = q(db, "INSERT INTO scans (user_id, mode, status) VALUES (:u, 'fridge', 'done') RETURNING id", u=uid).scalar()
    q(db, "INSERT INTO scan_images (scan_id, ordinal, storage_key, width, height) VALUES (:s, 1, :k, 10, 10)",
      s=scan, k=f"tmp/{scan}-1.jpg")  # fmt: skip
    q(db, "INSERT INTO shopping_items (user_id, ingredient_id) VALUES (:u, :i)", u=uid, i=ing)
    plan = q(db, "INSERT INTO meal_plans (user_id, meal, persons, max_minutes, reason_vi, params_version) "
                 "VALUES (:u, 'dinner', 2, 45, 'lý do', 'p1') RETURNING id", u=uid).scalar()  # fmt: skip
    item = q(db, "INSERT INTO meal_plan_items (meal_plan_id, slot, recipe_id, rank_score, servings_scale) "
                 "VALUES (:p, 'man', :r, 0.5, 1) RETURNING id", p=plan, r=recipe_id).scalar()  # fmt: skip
    q(db, "INSERT INTO cook_sessions (meal_plan_id, serve_at, burners, started_at) VALUES (:p, now(), 2, now())",
      p=plan)  # fmt: skip
    q(db, "INSERT INTO interactions (id, user_id, recipe_id, meal_plan_id, meal_plan_item_id, type, occurred_at, "
          "received_at) VALUES (:id, :u, :r, :p, :it, 'cooked', now(), now())",
      id=str(uuid.uuid4()), u=uid, r=recipe_id, p=plan, it=item)  # fmt: skip
    q(db, "INSERT INTO audit_log (actor_user_id, actor_role, action, entity) VALUES (:u, 'user', 'decrypt', 'profiles')",
      u=uid)  # fmt: skip
    return {"ingredient": str(ing)}


def _catalog_counts(db) -> dict[str, int]:
    tables = ["recipes", "ingredients", "food_groups", "allergen_groups", "diets", "cooking_methods"]
    return {t: q(db, f"SELECT count(*) FROM {t}").scalar() for t in tables}


def test_wrong_password_changes_nothing(client: TestClient, db) -> None:
    s = register(client)
    r = client.post(f"{API}/me/data-requests", json={"type": "delete", "password": "sai-mat-khau-1"}, headers=bearer(s))
    assert (r.status_code, r.json()["code"]) == (403, "reauth_failed")
    r = client.post(f"{API}/me/data-requests", json={"type": "delete"}, headers=bearer(s))
    assert (r.status_code, r.json()["code"]) == (403, "reauth_failed")
    assert q(db, "SELECT status FROM users").scalar() == "active"
    assert q(db, "SELECT count(*) FROM dsr_requests").scalar() == 0


def test_delete_account_cascades_and_keeps_evidence(client: TestClient, db, catalog_ref, storage_dir: Path) -> None:
    s = register(client)
    uid = s["user"]["id"]
    other = register(client)
    recipe = insert_recipe(db, "Rau muống xào tỏi")
    _seed_everywhere(db, uid, recipe)
    _seed_everywhere(db, other["user"]["id"], recipe)
    client.post(f"{API}/me/consents", headers=bearer(s), json={
        "channel": "onboarding",
        "decisions": [{"policy_version_id": client.get(f"{API}/policies/personalization/current").json()["id"],
                       "action": "grant"}],
    })  # fmt: skip
    exp = client.post(f"{API}/me/data-requests", json={"type": "export"}, headers=bearer(s)).json()
    export_file = storage_dir / f"exports/{exp['id']}.zip"
    assert export_file.is_file()
    s2 = login(client, s["user"]["email"])  # a second session that must die too
    for table, sql in PERSONAL.items():
        assert q(db, sql, u=uid).scalar() >= 1, table
    catalog_before = _catalog_counts(db)

    r = client.post(f"{API}/me/data-requests", json={"type": "delete", "password": PASSWORD}, headers=bearer(s2))
    assert r.status_code == 202, r.text
    rid = r.json()["id"]

    for table, sql in PERSONAL.items():
        assert q(db, sql, u=uid).scalar() == 0, f"{table} still has rows of the deleted user"
    assert not export_file.exists()
    dsr = q(db, "SELECT * FROM dsr_requests WHERE id = :i", i=rid).one()
    assert dsr.user_id is None and dsr.status == "completed" and dsr.completed_at is not None
    assert len(bytes(dsr.subject_ref)) == 32
    assert q(db, "SELECT count(*) FROM dsr_requests WHERE user_id IS NULL").scalar() == 2  # the delete and the export
    assert q(db, "SELECT actor_user_id FROM audit_log WHERE action = 'decrypt' AND actor_user_id IS NULL "
                 "LIMIT 1").first() is not None  # fmt: skip
    assert q(db, "SELECT count(*) FROM audit_log WHERE action = 'dsr_delete_completed' AND entity_id = :i",
             i=rid).scalar() == 1  # fmt: skip
    assert _catalog_counts(db) == catalog_before  # FR-07-08
    for table, sql in PERSONAL.items():  # the other user is untouched
        assert q(db, sql, u=other["user"]["id"]).scalar() >= 1, table

    for sess in (s, s2):
        assert client.get(f"{API}/me/consents", headers=bearer(sess)).status_code == 401
    r = client.post(f"{API}/auth/login", json={"email": s["user"]["email"], "password": PASSWORD})
    assert (r.status_code, r.json()["code"]) == (401, "invalid_credentials")
    register(client, s["user"]["email"])  # the email is free again (UC07 *a)


def test_deletion_pending_state_blocks_everything(client: TestClient, db, app) -> None:
    """Between acceptance and the job (here: job not run), the account is locked out (FR-07-03)."""
    from tastoria.modules.privacy.service import PrivacyDeps

    s = register(client)
    real = app.state.privacy
    app.state.privacy = PrivacyDeps(real.settings, real.sessionmaker, handlers=real.handlers)
    app.state.privacy.schedule = lambda uow, rid: None  # type: ignore[method-assign]
    try:
        r = client.post(f"{API}/me/data-requests", json={"type": "delete", "password": PASSWORD}, headers=bearer(s))
    finally:
        app.state.privacy = real
    assert r.status_code == 202
    row = q(db, "SELECT status, token_version FROM users").one()
    assert (row.status, row.token_version) == ("deletion_requested", 1)
    assert q(db, "SELECT count(*) FROM refresh_tokens WHERE revoked_at IS NULL").scalar() == 0
    assert client.get(f"{API}/me/consents", headers=bearer(s)).json()["code"] == "token_revoked"
    r = client.post(f"{API}/auth/login", json={"email": s["user"]["email"], "password": PASSWORD})
    assert (r.status_code, r.json()["code"]) == (403, "account_deletion_pending")

    # the recovery job finishes it, and running it twice is harmless (FR-07-09)
    from tastoria.modules.privacy.service import process_pending

    assert process_pending(real) == 1
    assert process_pending(real) == 0
    assert q(db, "SELECT count(*) FROM users").scalar() == 0
    assert q(db, "SELECT status FROM dsr_requests").scalar() == "completed"
