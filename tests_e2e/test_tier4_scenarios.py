"""Tier 4: Real-world Vietnamese household end-to-end scenario journeys (5 tests)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

import httpx
import pytest
from playwright.sync_api import Page

from fixtures import get_app_food_asset, get_nam_sample_jpeg
from rubric import (
    assert_barcode_copy_clean,
    assert_light_parchment_locked,
    assert_meal_estimate_copy_clean,
    assert_no_ai_separators,
    assert_no_banned_copy,
    assert_no_brand_leak,
    evaluate_page_rubric,
)

pytestmark = pytest.mark.tier4


def _current_iso_week() -> str:
    now_vn = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
    y, w, _ = now_vn.isocalendar()
    return f"{y}-W{w:02d}"


def _auth_headers(token: str, *, idem: str | None = None) -> dict[str, str]:
    h = {"Authorization": f"Bearer {token}"}
    if idem:
        h["Idempotency-Key"] = idem
    return h


@pytest.mark.browser
def test_T4_01_com_tam_lunch_nam_rom_fridge_3dish_dinner_and_dsr_export(
    base_url: str,
    api_client: httpx.Client,
    helpers: Any,
    page_factory: Callable[..., tuple[Any, Page, Any]],
    session_consented_user: dict[str, Any],
) -> None:
    token = session_consented_user["access_token"]
    email = session_consented_user["_email"]
    password = session_consented_user["_password"]
    h = _auth_headers(token)

    # Set 1800 kcal daily target
    t_resp = api_client.put(
        "/me/energy-target",
        headers=h,
        json={"kcal_target": 1800, "kcal_source": "user", "goal": "maintain"},
    )
    assert t_resp.status_code == 200

    # Lunch: browser Staging Plate on /quet?tab=calorie -> Cơm tấm + VN modifiers -> Log to Journal
    ctx, page, telemetry = page_factory(viewport=(1440, 900), color_scheme="light")
    page.goto(f"{base_url}/dang-nhap", wait_until="networkidle")
    page.get_by_test_id("login-email").fill(email)
    page.get_by_test_id("login-password").fill(password)
    page.get_by_test_id("login-submit").click()
    page.wait_for_url(re.compile(r"/(bep|onboarding)"), timeout=20000)

    cookies = {c["name"]: c for c in ctx.cookies()}
    assert "tastoria_refresh" in cookies and cookies["tastoria_refresh"]["httpOnly"] is True

    page.goto(f"{base_url}/quet?tab=calorie", wait_until="networkidle")
    page.get_by_test_id("calorie-search-input").fill("Cơm tấm")
    page.get_by_test_id("calorie-estimate-btn").click()
    cal_card = page.get_by_test_id("calorie-result-card")
    cal_card.wait_for(state="visible", timeout=15000)
    cal_card.get_by_test_id("macro-pie-chart").wait_for(state="visible", timeout=10000)
    cal_card.get_by_test_id("macro-nutrition-ledger").wait_for(state="visible", timeout=10000)
    mod = page.locator("[data-testid^='modifier-']").first
    assert mod.count() > 0, "Expected Staging Plate VN modifier chip ([data-testid^='modifier-'])"
    mod.click()
    log_cta = page.get_by_test_id("calorie-log-to-journal")
    assert log_cta.count() > 0, "Expected 1-tap 'Ghi vào Nhật ký hôm nay' CTA (calorie-log-to-journal)"
    log_cta.click()
    page.get_by_test_id("calorie-logged-notice").wait_for(state="visible", timeout=5000)
    telemetry.assert_clean(page)

    # Evening: haul scan with real nam image -> Direction 1 -> confirm pantry (without wiping existing household lots)
    scan: dict[str, Any] | None = None
    for idx in range(3):
        candidate = helpers.submit_and_poll_scan(
            token,
            get_nam_sample_jpeg(idx),
            filename=f"evening_nam_{idx}.jpg",
            mode="haul",
        )
        assert candidate["status"] == "done"
        if any(d.get("vision_class_code") == "nam" for it in candidate["items"] for d in it.get("detections", [])):
            scan = candidate
            break
        scan = candidate
    assert scan is not None
    for it in scan["items"]:
        if it["qty_level"] is None or it["needs_check"]:
            api_client.patch(
                f"/scans/{scan['id']}/items/{it['id']}",
                headers={**h, "Content-Type": "application/merge-patch+json"},
                json={"qty_level": it["qty_level"] or "vua", "user_freshness": "dung_som"},
            )
    conf = api_client.post(f"/scans/{scan['id']}/confirm", headers=h, json={})
    assert conf.status_code == 200

    # Compose dinner 3-dish tray -> accept -> parallel cook -> complete
    plan = api_client.post(
        "/meal-plans",
        headers=_auth_headers(token, idem=helpers.create_idempotency_key("t401plan")),
        json={"meal": "dinner", "persons": 2, "max_minutes": 60},
    ).json()
    assert {it["slot"] for it in plan["items"] if it["status"] == "active"} == {"man", "rau", "canh"}
    api_client.post(f"/meal-plans/{plan['id']}/accept", headers=h)

    serve_at = (datetime.now(timezone.utc) + timedelta(minutes=65)).isoformat()
    cs = api_client.post(
        "/cook-sessions",
        headers=_auth_headers(token, idem=helpers.create_idempotency_key("t401cook")),
        json={"meal_plan_id": plan["id"], "serve_at": serve_at, "confirm_over_time": True},
    ).json()
    assert len(cs["schedule"]) > 0

    before_hist = len(api_client.get("/journal", headers=h, params={"week": _current_iso_week()}).json()["cooked_history"])
    comp = api_client.post(
        f"/cook-sessions/{cs['id']}/complete",
        headers=_auth_headers(token, idem=helpers.create_idempotency_key("t401done")),
        json={"feedback": []},
    )
    assert comp.status_code == 200

    # Verify Journal updated & submit DSR export
    journal = api_client.get("/journal", headers=h, params={"week": _current_iso_week()}).json()
    assert len(journal["cooked_history"]) == before_hist + 1

    dsr = api_client.post("/me/data-requests", headers=h, json={"type": "export"})
    assert dsr.status_code in (200, 202)
    assert dsr.json()["type"] == "export"


def test_T4_02_silken_tofu_disambiguation_shopping_and_cook_undo(
    api_client: httpx.Client,
    helpers: Any,
    session_consented_user: dict[str, Any],
) -> None:
    token = session_consented_user["access_token"]
    h = _auth_headers(token)

    # Photo check on silken-tofu + decoupled plain dau_phu_non KB pricing (~95 kcal)
    silken_est = api_client.post(
        "/meal-calorie/estimate",
        headers=h,
        files={"image": ("silken-tofu.webp", get_app_food_asset("silken-tofu.webp"), "image/webp")},
        data={"portion": "vua"},
    )
    assert silken_est.status_code == 200
    assert_meal_estimate_copy_clean(silken_est.json(), context="T4-02 silken-tofu")

    plain_tofu = api_client.post(
        "/meal-calorie/estimate",
        headers=h,
        data={"dish_slug": "dau_phu_non", "portion": "vua"},
    ).json()
    sauce_tofu = api_client.post(
        "/meal-calorie/estimate",
        headers=h,
        data={"dish_slug": "dau-phu-non-sot-nam", "portion": "vua"},
    ).json()
    assert plain_tofu["estimated_kcal"] < 130.0
    assert plain_tofu["estimated_kcal"] < sauce_tofu["estimated_kcal"] - 40.0

    # 4-person tray -> shopping -> bought -> to-pantry
    plan = api_client.post(
        "/meal-plans",
        headers=_auth_headers(token, idem=helpers.create_idempotency_key("t402plan")),
        json={"meal": "dinner", "persons": 4, "max_minutes": 60},
    ).json()
    api_client.post(f"/meal-plans/{plan['id']}/accept", headers=h)

    ing_id = helpers.resolve_ingredient_id(token, "đậu phụ")
    shop = api_client.post("/shopping-items", headers=h, json={"ingredient_id": ing_id, "qty_g": 400.0}).json()
    api_client.patch(f"/shopping-items/{shop['id']}", headers=h, json={"status": "bought"})
    api_client.post(f"/shopping-items/{shop['id']}/to-pantry", headers=h, json={"qty_g": 400.0})

    before_lots = {l["id"]: l["balance_g_min"] for l in helpers.list_all_pantry_lots(token)}
    before_hist = len(api_client.get("/journal", headers=h, params={"week": _current_iso_week()}).json()["cooked_history"])
    serve_at = (datetime.now(timezone.utc) + timedelta(minutes=65)).isoformat()
    cs = api_client.post(
        "/cook-sessions",
        headers=_auth_headers(token, idem=helpers.create_idempotency_key("t402cook")),
        json={"meal_plan_id": plan["id"], "serve_at": serve_at, "confirm_over_time": True},
    ).json()
    api_client.post(
        f"/cook-sessions/{cs['id']}/complete",
        headers=_auth_headers(token, idem=helpers.create_idempotency_key("t402done")),
        json={"feedback": []},
    )
    undo = api_client.post(f"/cook-sessions/{cs['id']}/undo", headers=h)
    assert undo.status_code == 200
    assert undo.json()["status"] == "reverted"

    after_lots = {l["id"]: l["balance_g_min"] for l in helpers.list_all_pantry_lots(token)}
    for lid, orig in before_lots.items():
        assert after_lots[lid] == pytest.approx(orig, rel=1e-3)
    journal = api_client.get("/journal", headers=h, params={"week": _current_iso_week()}).json()
    assert len(journal["cooked_history"]) == before_hist


def test_T4_03_allergy_and_diet_multi_meal_safe_planning(
    api_client: httpx.Client,
    helpers: Any,
    session_consented_user: dict[str, Any],
) -> None:
    token = session_consented_user["access_token"]
    h = _auth_headers(token)
    assert api_client.put("/me/allergens", headers=h, json={"allergen_codes": ["giap_xac", "dau_phong"]}).status_code == 200
    try:
        for name_vi, val in (("đậu phụ", 600.0), ("cà chua", 500.0), ("rau muống", 700.0), ("bắp cải", 800.0)):
            helpers.seed_pantry_lot(token, name_vi, grams=val)
        helpers.seed_pantry_lot(token, "trứng gà", count=10, unit_code="qua")

        before_hist = len(api_client.get("/journal", headers=h, params={"week": _current_iso_week()}).json()["cooked_history"])

        lunch = api_client.post(
            "/meal-plans",
            headers=_auth_headers(token, idem=helpers.create_idempotency_key("t403l")),
            json={"meal": "lunch", "persons": 2, "max_minutes": 45, "coeater_allergen_codes": ["vung"]},
        )
        assert lunch.status_code == 201
        lb = lunch.json()
        man_item = next(it for it in lb["items"] if it["status"] == "active" and it["slot"] == "man")
        swapped = api_client.post(
            f"/meal-plans/{lb['id']}/items/{man_item['id']}/swap",
            headers=_auth_headers(token, idem=helpers.create_idempotency_key("t403sw")),
            json={"swap_reason": "moi_an"},
        )
        assert swapped.status_code == 200

        dinner = api_client.post(
            "/meal-plans",
            headers=_auth_headers(token, idem=helpers.create_idempotency_key("t403d")),
            json={"meal": "dinner", "persons": 2, "max_minutes": 45, "coeater_allergen_codes": ["vung"]},
        )
        assert dinner.status_code == 201

        forbidden = {"giap_xac", "dau_phong", "vung"}
        for plan_body in (swapped.json(), dinner.json()):
            for it in plan_body["items"]:
                if it["status"] != "active":
                    continue
                rec = api_client.get(f"/recipes/{it['recipe_id']}", headers=h).json()
                for ing in rec["ingredients"]:
                    assert forbidden.isdisjoint(set(ing["allergen_codes"])), (
                        f"Forbidden allergen in {rec['name_vi']}: {ing['allergen_codes']}"
                    )

        api_client.post(f"/meal-plans/{dinner.json()['id']}/accept", headers=h)
        serve_at = (datetime.now(timezone.utc) + timedelta(minutes=50)).isoformat()
        cs = api_client.post(
            "/cook-sessions",
            headers=_auth_headers(token, idem=helpers.create_idempotency_key("t403cook")),
            json={"meal_plan_id": dinner.json()["id"], "serve_at": serve_at, "confirm_over_time": True},
        ).json()
        api_client.post(
            f"/cook-sessions/{cs['id']}/complete",
            headers=_auth_headers(token, idem=helpers.create_idempotency_key("t403done")),
            json={"feedback": []},
        )
        journal = api_client.get("/journal", headers=h, params={"week": _current_iso_week()}).json()
        assert len(journal["cooked_history"]) == before_hist + 1
    finally:
        api_client.put("/me/allergens", headers=h, json={"allergen_codes": []})


@pytest.mark.browser
def test_T4_04_mobile_dark_landing_workbench_survey_and_3_barcodes(
    base_url: str,
    api_client: httpx.Client,
    helpers: Any,
    page_factory: Callable[..., tuple[Any, Page, Any]],
    session_consented_user: dict[str, Any],
) -> None:
    _, p_light, t_light = page_factory(viewport=(390, 844), color_scheme="light")
    p_light.goto(f"{base_url}/gioi-thieu/", wait_until="networkidle")
    r_light = evaluate_page_rubric(
        p_light,
        screen_name="t404-landing-light-mobile",
        theme="light",
        surface_mode="landing",
        viewport_width=390,
        viewport_height=844,
    )
    t_light.assert_clean(p_light)

    _, page, telemetry = page_factory(viewport=(390, 844), color_scheme="dark")
    paper_light_200: list[str] = []

    def _on_resp(resp: Any) -> None:
        if "paper-bg-light.webp" in resp.url and resp.status == 200:
            paper_light_200.append(resp.url)

    page.on("response", _on_resp)
    page.goto(f"{base_url}/gioi-thieu/", wait_until="networkidle")
    r_dark_os = evaluate_page_rubric(
        page,
        screen_name="t404-landing-os-dark-mobile",
        theme="light",
        surface_mode="landing",
        viewport_width=390,
        viewport_height=844,
    )
    assert_light_parchment_locked(r_light, r_dark_os, max_delta=15)
    assert "paper-bg-light" in r_dark_os.bg_image
    assert paper_light_200, "Expected paper-bg-light.webp 200 OK under OS dark mode at 390x844"
    pie = page.locator("#cal-macro-pie, [data-testid='macro-pie-chart']").first
    pie.scroll_into_view_if_needed()
    assert pie.is_visible(), "Expected #cal-macro-pie visible on 390x844 mobile landing"
    landing_txt = "\n".join(page.locator("header, main, footer").all_inner_texts())
    assert_no_banned_copy(landing_txt, context="T4-04 landing")
    assert_no_brand_leak(landing_txt, context="T4-04 landing")
    assert_no_ai_separators(landing_txt, context="T4-04 landing")

    # Visit legal page & /khao-sat page cleanly
    page.goto(f"{base_url}/gioi-thieu/rieng-tu.html", wait_until="networkidle")
    legal_txt = "\n".join(page.locator("header, main, footer").all_inner_texts())
    assert_no_banned_copy(legal_txt, context="T4-04 rieng-tu")
    assert_no_brand_leak(legal_txt, context="T4-04 rieng-tu")
    assert_no_ai_separators(legal_txt, context="T4-04 rieng-tu")

    page.goto(f"{base_url}/khao-sat", wait_until="networkidle")
    page.wait_for_timeout(300)
    telemetry.assert_clean(page)

    # Complete anonymous taste survey via public API
    pol = helpers.get_policy_version_id("survey")
    created = api_client.post(
        "/survey/respondents",
        json={"policy_version_id": pol, "consent": True, "channel": "qr"},
    ).json()
    rid = created["respondent"]["id"]
    rh = {"X-Respondent-Token": created["respondent_token"]}
    assignments = created["respondent"]["assignments"]
    assert assignments
    for assignment in assignments:
        r_rate = api_client.put(
            f"/survey/respondents/{rid}/ratings/{assignment['recipe_id']}",
            headers=rh,
            json={"rating": 5, "never_eaten": False},
        )
        assert r_rate.status_code == 200
    recipe_id = assignments[0]["recipe_id"]
    r_fav = api_client.put(f"/survey/respondents/{rid}/favorites", headers=rh, json={"recipe_ids": [recipe_id]})
    assert r_fav.status_code == 200
    comp = api_client.post(f"/survey/respondents/{rid}/complete", headers=rh)
    assert comp.status_code == 200 and comp.json()["completed_at"] is not None

    # Look up 3 deterministic local VN packaged barcodes and verify zero banned copy leak
    h = _auth_headers(session_consented_user["access_token"])
    for bc in ("8934563138165", "8936017360015", "8934673100113"):
        r = api_client.get(f"/meal-calorie/barcode/{bc}", headers=h)
        assert r.status_code == 200, f"Expected 200 for local VN barcode {bc}, got {r.status_code}: {r.text}"
        assert_barcode_copy_clean(r.json(), context=f"T4-04 barcode {bc}")


def test_T4_05_web_session_lifecycle_consent_withdraw_and_pdpl_erasure(
    api_client: httpx.Client,
    helpers: Any,
    web_client_factory: Callable[[], httpx.Client],
    fresh_user_factory: Callable[..., dict[str, Any]],
) -> None:
    wc1 = web_client_factory()
    user = fresh_user_factory(consented=False, web_client=wc1)
    assert user.get("refresh_token") is None
    assert "tastoria_refresh" in wc1.cookies

    # Refresh rotation on web client 1
    ref = wc1.post("/auth/refresh", json={})
    assert ref.status_code == 200
    assert ref.json().get("refresh_token") is None
    tok1 = ref.json()["access_token"]

    # Open second web device session and call logout-all
    wc2 = web_client_factory()
    login2 = helpers.login_user(user["_email"], user["_password"], web_client=wc2)
    out_all = wc2.post("/auth/logout-all", headers=_auth_headers(login2["access_token"]))
    assert out_all.status_code == 204
    assert wc1.post("/auth/refresh", json={}).status_code == 401
    assert wc2.post("/auth/refresh", json={}).status_code == 401

    # Re-login, grant & withdraw photo_contribution, then submit PDPL erasure
    login3 = helpers.login_user(user["_email"], user["_password"], web_client=wc1)
    tok3 = login3["access_token"]
    helpers.grant_consents(tok3, purposes=("health_profile", "photo_contribution"))
    w = api_client.post(
        "/me/consents/photo_contribution/withdraw",
        headers=_auth_headers(tok3),
        json={"channel": "settings"},
    )
    assert w.status_code == 200
    assert w.json()["state"] == "withdrawn"

    ref_w = wc1.post("/auth/refresh", json={})
    assert ref_w.status_code == 200
    tok_refreshed = ref_w.json()["access_token"]

    erase = api_client.post(
        "/me/data-requests",
        headers=_auth_headers(tok_refreshed),
        json={"type": "delete", "password": user["_password"]},
    )
    assert erase.status_code in (200, 202)
    assert erase.json()["type"] == "delete"

    blocked_login = wc1.post("/auth/login", json={"email": user["_email"], "password": user["_password"]})
    assert blocked_login.status_code == 403
    assert blocked_login.json()["code"] == "account_deletion_pending"

    blocked_ref = wc1.post("/auth/refresh", json={})
    assert blocked_ref.status_code == 403
    assert blocked_ref.json()["code"] == "account_deletion_pending"
