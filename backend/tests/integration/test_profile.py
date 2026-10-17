"""UC09–UC11: profile with encrypted metrics, consent gate, age gate, energy, allergens, diet, favourites, settings."""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from pathlib import Path

import pytest
from conftest import TEST_ENC_KEY_2, insert_recipe, q
from fastapi.testclient import TestClient
from helpers import bearer, login, register

from tastoria.core.clock import local_year
from tastoria.modules.profile.crypto import FieldCipher

API = "/api/v1"
Y = local_year()


def _grant_health(client: TestClient, s: dict) -> None:
    pv = client.get(f"{API}/policies/health_profile/current").json()["id"]
    body = {"channel": "onboarding", "decisions": [{"policy_version_id": pv, "action": "grant"}]}
    assert client.post(f"{API}/me/consents", json=body, headers=bearer(s)).status_code == 200


def _profile(**kw) -> dict:
    base = {"sex": "female", "birth_year": Y - 25, "height_cm": 158, "weight_kg": 52, "activity_level": "light",
            "goal": "maintain"}  # fmt: skip
    base.update(kw)
    return base


def _put(client: TestClient, s: dict, **kw):
    return client.put(f"{API}/me/profile", json=_profile(**kw), headers=bearer(s))


def _audits(db, purpose: str = "health_profile") -> int:
    return q(db, "SELECT count(*) FROM audit_log WHERE action = 'decrypt' AND purpose = :p", p=purpose).scalar()


@pytest.fixture
def user(client: TestClient, catalog_ref) -> dict:
    s = register(client)
    _grant_health(client, s)
    return login(client, s["user"]["email"])


# ---------------------------------------------------------------- profile + consent + encryption


def test_empty_profile(client: TestClient, db) -> None:
    s = register(client)
    r = client.get(f"{API}/me/profile", headers=bearer(s))
    assert r.status_code == 200
    body = r.json()
    assert body["weight_kg"] is None and body["health_profile_consented"] is False and body["allergen_codes"] == []
    assert body["updated_at"] is None and _audits(db) == 0


def test_metrics_need_health_consent(client: TestClient, db) -> None:
    s = register(client)
    r = _put(client, s)
    assert (r.status_code, r.json()["code"]) == (403, "consent_required")
    r = client.put(
        f"{API}/me/profile", headers=bearer(s), json={k: None for k in _profile()} | {"activity_level": "light"}
    )
    assert (r.status_code, r.json()["code"]) == (403, "consent_required")  # activity level is health data too
    assert q(db, "SELECT count(*) FROM profiles WHERE weight_kg_enc IS NOT NULL").scalar() == 0


def test_metrics_are_stored_encrypted_and_audited(client: TestClient, user: dict, db) -> None:
    r = _put(client, user, weight_kg=52.5)
    assert r.status_code == 200, r.text
    assert r.json()["weight_kg"] == 52.5 and r.json()["health_profile_consented"] is True
    row = q(db, "SELECT * FROM profiles").one()
    assert row.enc_key_id == "t1"
    for col in ("sex_enc", "birth_year_enc", "height_cm_enc", "weight_kg_enc"):
        assert (
            isinstance(row._mapping[col], bytes)
            and b"52.5" not in row._mapping[col]
            and b"female" not in row._mapping[col]
        )
    import base64

    from conftest import TEST_ENC_KEY

    cipher = FieldCipher({"t1": base64.b64decode(TEST_ENC_KEY)}, "t1")
    uid = uuid.UUID(user["user"]["id"])
    assert cipher.decrypt("t1", uid, "weight_kg_enc", row.weight_kg_enc) == "52.5"
    assert _audits(db) == 0  # writing does not decrypt
    g = client.get(f"{API}/me/profile", headers=bearer(user)).json()
    assert (g["sex"], g["birth_year"], g["height_cm"], g["weight_kg"]) == ("female", Y - 25, 158, 52.5)
    a = q(db, "SELECT * FROM audit_log WHERE action = 'decrypt'").one()
    assert (a.entity, a.entity_id, a.purpose, str(a.actor_user_id)) == (
        "profiles",
        str(uid),
        "health_profile",
        str(uid),
    )
    assert a.request_id


def test_age_gate(client: TestClient, user: dict, db) -> None:
    r = _put(client, user, birth_year=Y - 17)
    assert (r.status_code, r.json()["code"]) == (422, "age_below_minimum")
    r = _put(client, user, birth_year=Y - 18)
    assert (r.status_code, r.json()["code"]) == (422, "age_confirmation_required")
    assert q(db, "SELECT count(*) FROM profiles").scalar() == 0  # nothing written on refusal
    assert (
        client.put(
            f"{API}/me/profile", headers=bearer(user), json=_profile(birth_year=Y - 18) | {"adult_confirmed": True}
        ).status_code
        == 200
    )
    assert _put(client, user, birth_year=Y - 19).status_code == 200


def test_profile_validation(client: TestClient, user: dict) -> None:
    r = _put(client, user, height_cm=90)
    assert (r.status_code, r.json()["code"]) == (422, "validation_error")
    assert r.json()["errors"][0]["pointer"] == "/height_cm"
    body = _profile()
    del body["goal"]
    r = client.put(f"{API}/me/profile", json=body, headers=bearer(user))
    assert (r.status_code, r.json()["code"]) == (422, "validation_error")
    r = _put(client, user, goal="gain")
    assert (r.status_code, r.json()["code"]) == (422, "validation_error")  # FR-11-06
    r = client.put(
        f"{API}/me/profile", content=b"{not json", headers=bearer(user) | {"content-type": "application/json"}
    )
    assert (r.status_code, r.json()["code"]) == (400, "validation_error")


def test_profiles_are_per_user(client: TestClient, user: dict, catalog_ref) -> None:
    _put(client, user)
    client.put(f"{API}/me/allergens", json={"allergen_codes": ["ca"]}, headers=bearer(user))
    other = register(client)
    body = client.get(f"{API}/me/profile", headers=bearer(other)).json()
    assert body["weight_kg"] is None and body["allergen_codes"] == [] and body["activity_level"] is None


# ---------------------------------------------------------------- energy (UC11)


def test_energy_suggestion(client: TestClient, user: dict, db) -> None:
    _put(client, user)
    r = client.post(f"{API}/me/energy-suggestion", headers=bearer(user))
    assert r.status_code == 200, r.text
    e = r.json()
    assert (e["suggested_kcal"], e["e_lunch_kcal"], e["e_dinner_kcal"], e["floor_applied"]) == (1891, 662, 567, False)
    assert (e["bmr_kcal"], e["pal"], e["tee_kcal"]) == (1260.4, 1.5, 1890.6)
    assert e["formula"] == "fao_who_unu_1985" and e["age_years"] == 25 and "1985" in e["equation"]
    assert q(db, "SELECT kcal_target FROM profiles").scalar() is None  # suggestion stores nothing
    client.post(
        f"{API}/me/energy-suggestion", json={"goal": "lose", "formula": "mifflin_st_jeor"}, headers=bearer(user)
    )
    assert _audits(db) == 2  # FR-11-15: one row per decryption


def test_energy_suggestion_lose_and_mifflin(client: TestClient, user: dict) -> None:
    _put(
        client, user, sex="male", birth_year=Y - 30, weight_kg=65, height_cm=170, activity_level="moderate", goal="lose"
    )
    e = client.post(f"{API}/me/energy-suggestion", json={"formula": "mifflin_st_jeor"}, headers=bearer(user)).json()
    assert (e["bmr_kcal"], e["tee_kcal"], e["suggested_kcal"], e["goal"]) == (1633, 2857.75, 2358, "lose")
    assert e["bmr_mifflin_kcal"] == 1569.25  # comparison only, E still from FAO


def test_energy_suggestion_preconditions(client: TestClient, catalog_ref, db) -> None:
    s = register(client)
    r = client.post(f"{API}/me/energy-suggestion", headers=bearer(s))
    assert (r.status_code, r.json()["code"]) == (403, "consent_required")
    _grant_health(client, s)
    s = login(client, s["user"]["email"])
    _put(client, s, weight_kg=None)
    r = client.post(f"{API}/me/energy-suggestion", headers=bearer(s))
    assert (r.status_code, r.json()["code"]) == (422, "profile_incomplete") and r.json()["missing"] == ["weight_kg"]
    q(db, "UPDATE profiles SET birth_year_enc = NULL")
    r = client.post(f"{API}/me/energy-suggestion", headers=bearer(s))
    assert r.json()["missing"] == ["birth_year", "weight_kg"]


def test_energy_target_sources(client: TestClient, user: dict, db) -> None:
    _put(client, user)
    r = client.put(
        f"{API}/me/energy-target", json={"kcal_target": 3000, "kcal_source": "suggested"}, headers=bearer(user)
    )
    assert r.status_code == 200 and r.json()["kcal_target"] == 1891  # FR-11-10: server recomputes
    assert q(db, "SELECT kcal_target, kcal_source FROM profiles").one() == (1891, "suggested")

    # FR-10-04: metrics change → stale flag, stored target untouched
    p = _put(client, user, weight_kg=60).json()
    assert (p["target_stale"], p["suggested_kcal"], p["kcal_target"]) == (True, 2067, 1891)

    r = client.put(f"{API}/me/energy-target", json={"kcal_target": 1600, "kcal_source": "expert"}, headers=bearer(user))
    assert r.status_code == 200 and r.json()["goal"] == "expert"
    assert q(db, "SELECT goal, kcal_target, kcal_source FROM profiles").one() == ("expert", 1600, "expert")
    p = _put(client, user, weight_kg=70, goal="expert").json()  # FR-11-11
    assert (p["kcal_target"], p["target_stale"]) == (1600, False)
    r = _put(client, user, goal="maintain")
    assert (r.status_code, r.json()["code"]) == (422, "validation_error")  # leaving expert goes through energy-target

    r = client.put(
        f"{API}/me/energy-target",
        json={"kcal_target": 1100, "kcal_source": "user", "goal": "lose"},
        headers=bearer(user),
    )
    assert (r.status_code, r.json()["code"]) == (409, "below_floor_confirmation_required") and r.json()[
        "floor_kcal"
    ] == 1200
    r = client.put(
        f"{API}/me/energy-target",
        json={"kcal_target": 1100, "kcal_source": "user", "goal": "lose", "confirm_below_floor": True},
        headers=bearer(user),
    )
    assert r.status_code == 200 and r.json()["below_floor"] is True and r.json()["e_lunch_kcal"] == 385
    r = client.put(f"{API}/me/energy-target", json={"kcal_target": 700, "kcal_source": "user"}, headers=bearer(user))
    assert (r.status_code, r.json()["code"]) == (422, "validation_error")
    r = client.put(
        f"{API}/me/energy-target",
        json={"kcal_target": 1600, "kcal_source": "expert", "goal": "lose"},
        headers=bearer(user),
    )
    assert (r.status_code, r.json()["code"]) == (422, "validation_error")


def test_energy_target_needs_consent(client: TestClient) -> None:
    s = register(client)
    r = client.put(f"{API}/me/energy-target", json={"kcal_target": 1600, "kcal_source": "expert"}, headers=bearer(s))
    assert (r.status_code, r.json()["code"]) == (403, "consent_required")


def test_withdraw_health_profile_erases_metrics(client: TestClient, user: dict, db, app) -> None:
    from tastoria.modules.profile.service import get_meal_constraints

    _put(client, user)
    client.put(f"{API}/me/energy-target", json={"kcal_target": 2000, "kcal_source": "suggested"}, headers=bearer(user))
    uid = uuid.UUID(user["user"]["id"])
    with app.state.sessionmaker() as s:
        assert get_meal_constraints(s, uid).e_meal_kcal == {"lunch": 662, "dinner": 567}
    r = client.post(f"{API}/me/consents/health_profile/withdraw", headers=bearer(user))
    assert r.status_code == 200
    row = q(db, "SELECT * FROM profiles").one()
    for col in (
        "sex_enc",
        "birth_year_enc",
        "height_cm_enc",
        "weight_kg_enc",
        "enc_key_id",
        "kcal_target",
        "kcal_source",
    ):
        assert row._mapping[col] is None, col
    s2 = login(client, user["user"]["email"])
    g = client.get(f"{API}/me/profile", headers=bearer(s2)).json()
    assert g["health_profile_consented"] is False and g["kcal_target"] is None
    with app.state.sessionmaker() as s:
        assert get_meal_constraints(s, uid).e_meal_kcal is None


def test_key_rotation_and_missing_key(make_app, client: TestClient, user: dict) -> None:
    from fakes import FakeMailer

    _put(client, user, weight_kg=61)
    rotated = make_app(health_enc_keys={"t1": __import__("conftest").TEST_ENC_KEY, "t2": TEST_ENC_KEY_2},
                       health_enc_active_key_id="t2")  # fmt: skip
    rotated.state.mailer = FakeMailer()
    with TestClient(rotated) as c:
        assert c.get(f"{API}/me/profile", headers=bearer(user)).json()["weight_kg"] == 61
    lost = make_app(health_enc_keys={"t2": TEST_ENC_KEY_2}, health_enc_active_key_id="t2")
    lost.state.mailer = FakeMailer()
    with TestClient(lost) as c:
        r = c.get(f"{API}/me/profile", headers=bearer(user))
    assert (r.status_code, r.json()["code"]) == (500, "decryption_failed")


# ---------------------------------------------------------------- allergens, diet, favourites, settings


def test_allergens_replace_and_validate(client: TestClient, user: dict, db, app) -> None:
    from tastoria.modules.profile.service import get_meal_constraints

    put = lambda codes: client.put(f"{API}/me/allergens", json={"allergen_codes": codes}, headers=bearer(user))  # noqa: E731
    assert put(["trung"]).json() == {"allergen_codes": ["trung"]}
    assert put(["giap_xac", "ca"]).json() == {"allergen_codes": ["ca", "giap_xac"]}
    r = put(["ca", "xyz"])
    assert (r.status_code, r.json()["code"], r.json()["unknown"]) == (422, "unknown_code", ["xyz"])
    for _ in range(3):
        assert put(["ca", "giap_xac"]).status_code == 200  # FR-10-12
    assert q(db, "SELECT count(*) FROM user_allergens").scalar() == 2
    with app.state.sessionmaker() as s:
        assert get_meal_constraints(s, uuid.UUID(user["user"]["id"])).allergen_codes == ["ca", "giap_xac"]  # FR-10-08
    assert put([]).json() == {"allergen_codes": []}


def test_allergens_do_not_need_health_consent(client: TestClient, catalog_ref) -> None:
    s = register(client)
    assert client.put(f"{API}/me/allergens", json={"allergen_codes": ["vung"]}, headers=bearer(s)).status_code == 200


def test_diet(client: TestClient, user: dict, db) -> None:
    put = lambda code: client.put(f"{API}/me/diet", json={"diet_code": code}, headers=bearer(user))  # noqa: E731
    assert put("chay").json() == {"diet_code": "chay"}
    assert q(db, "SELECT diet_code FROM profiles").scalar() == "chay"
    r = put("keto")
    assert (r.status_code, r.json()["code"]) == (422, "unknown_code")
    assert put(None).json() == {"diet_code": None}


def test_favorites(client: TestClient, user: dict, db) -> None:
    published = [insert_recipe(db, f"Món {i}") for i in range(6)]
    retired = insert_recipe(db, "Món cũ", status="retired")
    draft = insert_recipe(db, "Món nháp", status="draft")
    put = lambda ids: client.put(f"{API}/me/favorites", json={"recipe_ids": ids}, headers=bearer(user))  # noqa: E731
    r = put(published)
    assert (r.status_code, r.json()["code"]) == (422, "favorites_limit")
    for bad in (retired, draft, str(uuid.uuid4())):
        r = put([published[0], bad])
        assert (r.status_code, r.json()["code"], r.json()["recipe_ids"]) == (422, "recipe_not_published", [bad])
    assert q(db, "SELECT count(*) FROM user_favorite_recipes").scalar() == 0
    r = put(published[:5])
    assert r.status_code == 200 and sorted(r.json()["recipe_ids"]) == sorted(published[:5])
    assert set(put(published[1:3] + published[1:2]).json()["recipe_ids"]) == set(published[1:3])  # duplicates collapse
    assert q(db, "SELECT count(*) FROM user_favorite_recipes").scalar() == 2


def test_settings(client: TestClient, user: dict, app) -> None:
    from tastoria.modules.profile.service import get_meal_constraints

    r = client.get(f"{API}/me/settings", headers=bearer(user))
    assert r.json() == {"burners": 2, "default_persons": 2, "timezone": "Asia/Ho_Chi_Minh", "updated_at": None}
    put = lambda body: client.put(f"{API}/me/settings", json=body, headers=bearer(user))  # noqa: E731
    r = put({"burners": 5, "default_persons": 2, "timezone": "Asia/Ho_Chi_Minh"})
    assert (r.status_code, r.json()["code"]) == (422, "validation_error")
    r = put({"burners": 4, "default_persons": 6, "timezone": "Asia/Bangkok"})
    assert r.status_code == 200 and r.json()["burners"] == 4 and r.json()["updated_at"]
    r = put({"burners": 1, "default_persons": 1, "timezone": "Mars/Olympus"})
    assert (r.status_code, r.json()["code"]) == (422, "validation_error")
    with app.state.sessionmaker() as s:
        c = get_meal_constraints(s, uuid.UUID(user["user"]["id"]))
    assert (c.burners, c.default_persons, c.timezone, c.e_meal_kcal) == (4, 6, "Asia/Bangkok", None)


def test_export_contains_decrypted_profile(client: TestClient, user: dict, db, storage_dir: Path) -> None:
    _put(client, user, weight_kg=52)
    client.put(f"{API}/me/allergens", json={"allergen_codes": ["sua"]}, headers=bearer(user))
    rid = client.post(f"{API}/me/data-requests", json={"type": "export"}, headers=bearer(user)).json()["id"]
    z = zipfile.ZipFile(io.BytesIO((storage_dir / f"exports/{rid}.zip").read_bytes()))
    prof = json.loads(z.read("profiles.json"))[0]
    assert (prof["weight_kg"], prof["sex"]) == (52, "female")
    assert json.loads(z.read("user_allergens.json")) == [{"allergen_code": "sua"}]
    assert _audits(db, "dsr_export") == 1  # FR-06-05
    assert "weight_kg_enc" not in z.read("profiles.json").decode()
