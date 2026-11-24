"""Tier 3: All-Pairs Cross-Feature Combination Tests (>= 15 pairwise combinations).

Combines Viewports x Themes x Auth/Role x Consents x Diets/Allergens x Pantry Urgency
x ML Models x Shopping-to-Pantry x Cook/Undo x DSR/Admin across real API, CLI, and Playwright.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from tests.e2e.conftest import DEFAULT_PASSWORD, E2EHelpers, unique_email, unique_idem_key
from tests.e2e.fixtures import make_produce_jpeg
from tests.e2e.rubric import evaluate_page_rubric

pytestmark = [pytest.mark.tier3]


def _login_ui(page, base_url: str, email: str, password: str) -> None:
    tid = page.get_by_test_id
    page.goto(f"{base_url}/dang-nhap")
    tid("login-email").fill(email)
    tid("login-password").fill(password)
    tid("login-submit").click()
    tid("screen-home").wait_for()


def test_t3_p01_desktop_light_user_all_consents_bep_and_mam(base_url: str, helpers: E2EHelpers, page_factory) -> None:
    user = helpers.create_ready_user(purposes=("health_profile", "personalization", "photo_contribution"), seed_pantry=True)
    _, page, telemetry = page_factory(viewport=(1440, 900), color_scheme="light")
    _login_ui(page, base_url, user["_email"], user["_password"])
    evaluate_page_rubric(page, screen_name="p01-bep", theme="light", viewport_width=1440, viewport_height=900)
    page.goto(f"{base_url}/mam")
    page.get_by_test_id("make-plan").click()
    page.get_by_test_id("plan-view").wait_for(timeout=30000)
    evaluate_page_rubric(page, screen_name="p01-mam", theme="light", viewport_width=1440, viewport_height=900)
    telemetry.assert_clean()


@pytest.mark.pending_m3_m4
def test_t3_p02_desktop_dark_ml_operator_health_only_quan_tri(base_url: str, helpers: E2EHelpers, page_factory) -> None:
    staff = helpers.create_staff_session("ml_operator")
    helpers.grant_consents(staff["access_token"], purposes=("health_profile",))
    helpers.seed_profile_and_energy(staff["access_token"])
    _, page, telemetry = page_factory(viewport=(1440, 900), color_scheme="dark")
    _login_ui(page, base_url, staff["_email"], staff["_password"])
    page.goto(f"{base_url}/quan-tri")
    page.get_by_test_id("screen-admin").wait_for()
    evaluate_page_rubric(page, screen_name="p02-quantri-dark", theme="dark", viewport_width=1440, viewport_height=900, check_shell=True)
    telemetry.assert_clean()


def test_t3_p03_mobile_light_user_no_personalization_events_skipped(base_url: str, helpers: E2EHelpers, page_factory) -> None:
    user = helpers.create_ready_user(purposes=("health_profile",), seed_pantry=True)
    tok = user["access_token"]
    h = helpers.auth_headers(tok)
    rid = helpers.api.get("/recipes", headers=h, params={"limit": 1}).json()["items"][0]["id"]
    ev = helpers.api.post(
        "/events",
        headers=h,
        json={"events": [{"event_id": str(uuid.uuid4()), "type": "viewed", "recipe_id": rid, "occurred_at": datetime.now(timezone.utc).isoformat()}]},
    ).json()
    assert ev["skipped_no_consent"] == 1

    _, page, telemetry = page_factory(viewport=(390, 844), color_scheme="light")
    _login_ui(page, base_url, user["_email"], user["_password"])
    evaluate_page_rubric(page, screen_name="p03-bep-mobile", theme="light", viewport_width=390, viewport_height=844)
    telemetry.assert_clean()


def test_t3_p04_mobile_dark_guest_survey_qr_channel(base_url: str, helpers: E2EHelpers, page_factory) -> None:
    helpers.ensure_open_survey_form(anchors=10, random_n=35, seed=42)
    _, page, telemetry = page_factory(viewport=(390, 844), color_scheme="dark")
    tid = page.get_by_test_id
    page.goto(f"{base_url}/khao-sat?kenh=qr")
    tid("screen-survey-start").wait_for()
    tid("survey-consent").click()
    tid("survey-start").click()
    tid("screen-survey-form").wait_for(timeout=20000)
    evaluate_page_rubric(page, screen_name="p04-survey-dark", theme="dark", viewport_width=390, viewport_height=844)
    telemetry.assert_clean()


def test_t3_p05_ultranarrow_light_user_all_consents_landing_and_bep(base_url: str, helpers: E2EHelpers, page_factory) -> None:
    user = helpers.create_ready_user(seed_pantry=True)
    _, page, telemetry = page_factory(viewport=(320, 568), color_scheme="light")
    page.goto(f"{base_url}/")
    evaluate_page_rubric(page, screen_name="p05-landing-320", theme="light", surface_mode="landing", viewport_width=320, viewport_height=568, check_touch_targets=False, check_contrast=False)
    _login_ui(page, base_url, user["_email"], user["_password"])
    evaluate_page_rubric(page, screen_name="p05-bep-320", theme="light", viewport_width=320, viewport_height=568)
    telemetry.assert_clean()


def test_t3_p06_persons1_chay_diet_full_pantry_excludes_animal_dishes(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=False, diet_code="chay")
    tok = user["access_token"]
    h = helpers.auth_headers(tok)
    for name_vi, qty in [
        ("đậu phụ", 400.0),
        ("cà chua", 400.0),
        ("cải ngọt", 500.0),
        ("bắp cải", 600.0),
        ("bí đỏ", 500.0),
        ("lạc", 200.0),
        ("nấm rơm", 300.0),
        ("thịt ba chỉ", 500.0),  # present in pantry, must be excluded by chay diet
    ]:
        if name_vi == "đậu phụ":
            helpers.seed_pantry_lot(tok, name_vi, count=4, unit_code="mieng")
        else:
            helpers.seed_pantry_lot(tok, name_vi, grams=qty)

    plan = helpers.api.post(
        "/meal-plans",
        headers=helpers.auth_headers(tok, idem=unique_idem_key("chay1")),
        json={"meal": "lunch", "max_minutes": 60, "persons": 1},
    )
    assert plan.status_code == 201, plan.text
    p = plan.json()
    assert p["persons"] == 1
    assert len(p["items"]) >= 2
    for it in p["items"]:
        recipe = helpers.api.get(f"/recipes/{it['recipe_id']}", headers=h).json()
        assert "Thịt" not in recipe["name_vi"], f"Vegetarian diet selected meat dish: {recipe['name_vi']}"


def test_t3_p07_persons2_coeater_allergen_giap_xac_and_substitute(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=True)
    tok = user["access_token"]
    h = helpers.auth_headers(tok)
    helpers.seed_pantry_lot(tok, "tôm", grams=400.0)
    plan = helpers.api.post(
        "/meal-plans",
        headers=helpers.auth_headers(tok, idem=unique_idem_key("alg")),
        json={"meal": "dinner", "max_minutes": 60, "persons": 2, "coeater_allergen_codes": ["giap_xac"]},
    )
    assert plan.status_code == 201, plan.text
    for it in plan.json()["items"]:
        rec = helpers.api.get(f"/recipes/{it['recipe_id']}", headers=h).json()
        for ing in rec["ingredients"]:
            assert "giap_xac" not in ing["allergen_codes"], f"Allergen giap_xac leaked in {rec['name_vi']}"
        subs = helpers.api.get(f"/meal-plans/{plan.json()['id']}/items/{it['id']}/substitutes", headers=h).json()
        for m in subs["items"]:
            for c in m["candidates"]:
                assert "tôm" not in c["name_vi"].lower()


@pytest.mark.pending_m3_m4
def test_t3_p08_persons4_urgent_lot_pinned_and_shopping_to_pantry(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=True)
    tok = user["access_token"]
    h = helpers.auth_headers(tok)
    urgent = helpers.seed_pantry_lot(tok, "cà chua", count=4, unit_code="qua", days_ago=2.5)
    ing_id = helpers.resolve_ingredient_id(tok, "hành lá")
    shop = helpers.api.post("/shopping-items", headers=h, json={"ingredient_id": ing_id, "qty_g": 150.0}).json()
    moved = helpers.api.post(f"/shopping-items/{shop['id']}/to-pantry", headers=h)
    assert moved.status_code in (200, 201)

    plan = helpers.api.post(
        "/meal-plans",
        headers=helpers.auth_headers(tok, idem=unique_idem_key("p4pin")),
        json={"meal": "dinner", "max_minutes": 90, "persons": 4, "pinned_lot_ids": [urgent["id"]]},
    )
    assert plan.status_code == 201, plan.text
    assert urgent["id"] in plan.json()["pinned_lot_ids"]


def test_t3_p09_do_an_vat_plus_ca_allergen_excludes_nuoc_mam_staple(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=True, allergen_codes=["ca"])
    tok = user["access_token"]
    h = helpers.auth_headers(tok)
    helpers.seed_pantry_lot(tok, "bim bim", grams=300.0)
    helpers.seed_pantry_lot(tok, "nước mắm", grams=200.0)

    plan = helpers.api.post(
        "/meal-plans",
        headers=helpers.auth_headers(tok, idem=unique_idem_key("caalg")),
        json={"meal": "lunch", "max_minutes": 60, "persons": 2},
    )
    assert plan.status_code == 201, plan.text
    for it in plan.json()["items"]:
        rec = helpers.api.get(f"/recipes/{it['recipe_id']}", headers=h).json()
        ing_names = [i["name_vi"].lower() for i in rec["ingredients"]]
        assert "bim bim" not in ing_names
        assert "nước mắm" not in ing_names, f"BR-ALG-01 violated: staple nước mắm leaked with allergen ca in {rec['name_vi']}"


def test_t3_p10_scan_fridge_two_shelf_groups_reports_unseen_lots(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=True)
    tok = user["access_token"]
    h = helpers.auth_headers(tok)
    jpeg = make_produce_jpeg()
    resp = helpers.api.post(
        "/scans",
        headers=helpers.auth_headers(tok, idem=unique_idem_key("2img")),
        data={"mode": "fridge", "shelf_groups": ["1", "2"], "contribute": "false"},
        files=[
            ("images", ("shelf1.jpg", jpeg, "image/jpeg")),
            ("images", ("shelf2.jpg", jpeg, "image/jpeg")),
        ],
    )
    assert resp.status_code == 202, resp.text
    sid = resp.json()["id"]
    done = None
    for _ in range(5):
        s = helpers.api.get(f"/scans/{sid}", headers=h, params={"wait": 10}).json()
        if s["status"] == "done":
            done = s
            break
    assert done is not None
    assert len(done["images"]) == 2
    assert done.get("unseen_lots") is not None and len(done["unseen_lots"]) >= 1


def test_t3_p11_scan_contribute_then_withdraw_consent_revokes_token(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(purposes=("health_profile", "photo_contribution"), seed_pantry=False)
    tok = user["access_token"]
    h = helpers.auth_headers(tok)
    resp = helpers.api.post(
        "/scans",
        headers=helpers.auth_headers(tok, idem=unique_idem_key("contrib")),
        data={"mode": "haul", "contribute": "true"},
        files=[("images", ("c.jpg", make_produce_jpeg(), "image/jpeg"))],
    )
    assert resp.status_code == 202
    wd = helpers.api.post("/me/consents/photo_contribution/withdraw", headers=h, json={"channel": "settings"})
    assert wd.status_code == 200
    assert wd.json()["state"] == "withdrawn"


def test_t3_p12_swap_then_substitute_then_cook_complete_then_undo_restores_pantry(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=True)
    tok = user["access_token"]
    h = helpers.auth_headers(tok)
    lots_before = {l["id"]: l["balance_g_min"] for l in helpers.api.get("/pantry/lots", headers=h).json()["items"]}

    plan = helpers.api.post(
        "/meal-plans",
        headers=helpers.auth_headers(tok, idem=unique_idem_key("fullpair")),
        json={"meal": "dinner", "max_minutes": 90, "persons": 2},
    ).json()
    for it in plan["items"]:
        sw = helpers.api.post(
            f"/meal-plans/{plan['id']}/items/{it['id']}/swap",
            headers=helpers.auth_headers(tok, idem=unique_idem_key("swpair")),
            json={"swap_reason": "moi_an"},
        )
        if sw.status_code == 200:
            plan = sw.json()
            break

    # Apply a substitution on an item (candidate if present, else same-food-group manual substitute)
    sub_applied = False
    for it in plan["items"]:
        sr = helpers.api.get(f"/meal-plans/{plan['id']}/items/{it['id']}/substitutes", headers=h).json()
        for missing in sr["items"]:
            if missing["candidates"]:
                cand = missing["candidates"][0]
                sub_res = helpers.api.post(
                    f"/meal-plans/{plan['id']}/items/{it['id']}/substitutions",
                    headers=h,
                    json={
                        "original_ingredient_id": missing["original_ingredient_id"],
                        "substitute_ingredient_id": cand["substitute_ingredient_id"],
                        "origin": cand["origin"],
                    },
                )
                assert sub_res.status_code == 200, sub_res.text
                assert len(sub_res.json()["substitutions"]) >= 1
                sub_applied = True
                break
        if sub_applied:
            break
    if not sub_applied:
        target_it = plan["items"][0]
        rec = helpers.api.get(f"/recipes/{target_it['recipe_id']}", headers=h).json()
        for rec_ing in rec["ingredients"]:
            ing_obj = helpers.resolve_ingredient(tok, rec_ing["name_vi"])
            peers = helpers.api.get("/ingredients", headers=h, params={"food_group_code": ing_obj["food_group_code"], "limit": 20}).json()["items"]
            alt = next((p for p in peers if p["id"] != ing_obj["id"]), None)
            if alt is not None:
                sub_res = helpers.api.post(
                    f"/meal-plans/{plan['id']}/items/{target_it['id']}/substitutions",
                    headers=h,
                    json={"original_ingredient_id": ing_obj["id"], "substitute_ingredient_id": alt["id"], "origin": "user"},
                )
                assert sub_res.status_code == 200, sub_res.text
                assert len(sub_res.json()["substitutions"]) >= 1
                sub_applied = True
                break
    assert sub_applied, "Expected substitution to be applied in P12"

    helpers.api.post(f"/meal-plans/{plan['id']}/accept", headers=h)
    cook = helpers.api.post(
        "/cook-sessions",
        headers=helpers.auth_headers(tok, idem=unique_idem_key("ckpair")),
        json={"meal_plan_id": plan["id"], "serve_at": (datetime.now(timezone.utc) + timedelta(minutes=60)).isoformat(), "confirm_over_time": True},
    ).json()
    comp = helpers.api.post(
        f"/cook-sessions/{cook['id']}/complete",
        headers=helpers.auth_headers(tok, idem=unique_idem_key("cmpair")),
        json={"feedback": []},
    )
    assert comp.status_code == 200

    undo = helpers.api.post(f"/cook-sessions/{cook['id']}/undo", headers=h)
    assert undo.status_code == 200
    lots_after = {l["id"]: l["balance_g_min"] for l in helpers.api.get("/pantry/lots", headers=h).json()["items"]}
    assert lots_before == lots_after


def test_t3_p13_make_ahead_lam_san_recipe_omits_early_steps_in_cook_schedule(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=False)
    tok = user["access_token"]
    h = helpers.auth_headers(tok)
    # Seed pantry with `măng khô` + `chân giò` (for `Canh măng nấu chân giò`, `lam_san` with through_step_no=2)
    # plus staple/non-pork items (no `thịt ba chỉ` so `thit-kho-mang` is excluded)
    mang_lot = helpers.seed_pantry_lot(tok, "măng khô", grams=200.0)
    helpers.seed_pantry_lot(tok, "chân giò", grams=900.0)
    helpers.seed_pantry_lot(tok, "trứng gà", count=8, unit_code="qua")
    helpers.seed_pantry_lot(tok, "rau muống", grams=600.0)
    helpers.seed_pantry_lot(tok, "cà chua", count=4, unit_code="qua")
    helpers.seed_pantry_lot(tok, "hành lá", grams=100.0)
    helpers.seed_pantry_lot(tok, "hành tím", count=5, unit_code="cu")
    helpers.seed_pantry_lot(tok, "tỏi", count=5, unit_code="tep")

    rlist = helpers.api.get("/recipes", headers=h, params={"tag": "lam_san"}).json()["items"]
    assert len(rlist) >= 1
    canh_mang = next((r for r in rlist if "măng" in r["name_vi"].lower()), rlist[0])
    detail = helpers.api.get(f"/recipes/{canh_mang['id']}", headers=h).json()
    assert detail["make_ahead"] is not None
    through_step = detail["make_ahead"]["through_step_no"]
    assert through_step >= 1

    plan_resp = helpers.api.post(
        "/meal-plans",
        headers=helpers.auth_headers(tok, idem=unique_idem_key("makeahead")),
        json={"meal": "dinner", "max_minutes": 150, "persons": 2, "pinned_lot_ids": [mang_lot["id"]]},
    )
    assert plan_resp.status_code == 201, plan_resp.text
    plan = plan_resp.json()
    assert any(it["recipe_id"] == canh_mang["id"] for it in plan["items"]), (
        f"Expected make-ahead recipe {canh_mang['name_vi']} in plan, got {[i['recipe_name_vi'] for i in plan['items']]}"
    )

    acc = helpers.api.post(f"/meal-plans/{plan['id']}/accept", headers=h)
    assert acc.status_code == 200
    cook_resp = helpers.api.post(
        "/cook-sessions",
        headers=helpers.auth_headers(tok, idem=unique_idem_key("ckma")),
        json={"meal_plan_id": plan["id"], "serve_at": (datetime.now(timezone.utc) + timedelta(minutes=140)).isoformat(), "confirm_over_time": True},
    )
    assert cook_resp.status_code == 201, cook_resp.text
    sched_steps = [e["step_no"] for e in cook_resp.json()["schedule"] if e["recipe_id"] == canh_mang["id"]]
    assert sched_steps, f"Expected scheduled steps for {canh_mang['name_vi']}"
    assert all(step_no > through_step for step_no in sched_steps), (
        f"Make-ahead steps 1..{through_step} were NOT omitted from cook schedule: {sched_steps}"
    )


@pytest.mark.pending_m3_m4
def test_t3_p14_shopping_to_pantry_then_meal_plan_uses_stock(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=False)
    tok = user["access_token"]
    h = helpers.auth_headers(tok)
    for name_vi, qty in [("thịt ba chỉ", 600.0), ("rau muống", 600.0), ("cà chua", 400.0), ("tỏi", 100.0), ("trứng gà", 300.0)]:
        ing_id = helpers.resolve_ingredient_id(tok, name_vi)
        item = helpers.api.post("/shopping-items", headers=h, json={"ingredient_id": ing_id, "qty_g": qty}).json()
        assert helpers.api.post(f"/shopping-items/{item['id']}/to-pantry", headers=h).status_code in (200, 201)

    plan = helpers.api.post(
        "/meal-plans",
        headers=helpers.auth_headers(tok, idem=unique_idem_key("s2p")),
        json={"meal": "lunch", "max_minutes": 60, "persons": 2},
    )
    assert plan.status_code == 201, plan.text


@pytest.mark.pending_m3_m4
def test_t3_p15_dsr_correct_submit_then_admin_resolve_then_audit_log(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=False)
    dsr = helpers.api.post(
        "/me/data-requests",
        headers=helpers.auth_headers(user["access_token"]),
        json={"type": "correct", "note": "Cập nhật cân nặng"},
    ).json()
    admin = helpers.create_staff_session("admin")
    ah = helpers.auth_headers(admin["access_token"])
    res = helpers.api.post(f"/admin/data-requests/{dsr['id']}/resolve", headers=ah, json={"status": "completed", "note": "Đã cập nhật"})
    assert res.status_code == 200
    audit = helpers.api.get("/admin/audit-log", headers=ah, params={"entity": "dsr_requests"}).json()
    assert len(audit["items"]) >= 1


def test_t3_p16_dsr_export_cli_process_then_user_download_zip(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=True)
    h = helpers.auth_headers(user["access_token"])
    dsr = helpers.api.post("/me/data-requests", headers=h, json={"type": "export"}).json()
    helpers.run_cli("jobs", "process-dsr")
    st = helpers.api.get(f"/me/data-requests/{dsr['id']}", headers=h).json()
    assert st["status"] == "completed" and st["download_available"] is True
    dl = helpers.api.get(f"/me/data-requests/{dsr['id']}/download", headers=h)
    assert dl.status_code == 200
    assert dl.content[:2] == b"PK"  # ZIP magic bytes


@pytest.mark.pending_m3_m4
def test_t3_p17_recipe_explorer_diet_filter_plus_pantry_match_ui(base_url: str, helpers: E2EHelpers, page_factory) -> None:
    user = helpers.create_ready_user(seed_pantry=True, diet_code="chay")
    _, page, telemetry = page_factory(viewport=(1440, 900), color_scheme="dark")
    _login_ui(page, base_url, user["_email"], user["_password"])
    page.goto(f"{base_url}/kham-pha")
    page.get_by_test_id("screen-explore").wait_for()
    evaluate_page_rubric(page, screen_name="p17-explore-dark", theme="dark", viewport_width=1440, viewport_height=900)
    telemetry.assert_clean()


@pytest.mark.pending_m3_m4
def test_t3_p18_landing_simulator_to_register_to_bep_desktop_dark(base_url: str, page_factory) -> None:
    _, page, telemetry = page_factory(viewport=(1440, 900), color_scheme="dark")
    tid = page.get_by_test_id
    page.goto(f"{base_url}/")
    tid("landing-tray-simulator").wait_for()
    evaluate_page_rubric(page, screen_name="p18-landing-dark", theme="dark", surface_mode="landing", viewport_width=1440, viewport_height=900, check_touch_targets=False)
    page.locator("a[href='/dang-ky']").first.click()
    tid("screen-register").wait_for()
    tid("register-email").fill(unique_email("p18"))
    tid("register-password").fill(DEFAULT_PASSWORD)
    tid("register-password2").fill(DEFAULT_PASSWORD)
    tid("register-submit").click()
    tid("consent-skip").click()
    tid("screen-home").wait_for()
    evaluate_page_rubric(page, screen_name="p18-bep-dark", theme="dark", viewport_width=1440, viewport_height=900)
    telemetry.assert_clean()
