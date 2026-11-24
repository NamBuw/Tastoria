"""Tier 3: Pairwise cross-feature integration workflow tests (8 tests)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

import httpx
import pytest
from playwright.sync_api import Page

from fixtures import get_app_food_asset, get_nam_sample_jpeg
from rubric import assert_no_ai_separators, assert_no_banned_copy

pytestmark = pytest.mark.tier3


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
def test_T3_01_meal_estimate_disambiguation_modifiers_to_journal(
    base_url: str,
    page_factory: Callable[..., tuple[Any, Page, Any]],
    session_consented_user: dict[str, Any],
) -> None:
    _, page, telemetry = page_factory(viewport=(1440, 900), color_scheme="light")

    page.goto(f"{base_url}/dang-nhap", wait_until="networkidle")
    page.get_by_test_id("login-email").fill(session_consented_user["_email"])
    page.get_by_test_id("login-password").fill(session_consented_user["_password"])
    page.get_by_test_id("login-submit").click()
    page.wait_for_url(re.compile(r"/(bep|onboarding)"), timeout=20000)

    page.goto(f"{base_url}/quet?tab=calorie", wait_until="networkidle")
    page.get_by_test_id("calorie-search-input").fill("Cơm tấm")
    page.get_by_test_id("calorie-estimate-btn").click()
    card = page.get_by_test_id("calorie-result-card")
    card.wait_for(state="visible", timeout=15000)
    card.get_by_test_id("macro-pie-chart").wait_for(state="visible", timeout=10000)
    card.get_by_test_id("macro-nutrition-ledger").wait_for(state="visible", timeout=10000)
    assert_no_ai_separators(card.inner_text(), context="T3-01 calorie card")

    # Select disambiguation candidate if surfaced
    cand = page.locator(
        "[data-testid='calorie-disambiguation-banner'] [role='checkbox'], "
        "[data-testid='calorie-disambiguation-banner'] [role='button']"
    ).first
    if cand.count() > 0 and cand.is_visible():
        cand.click()
        page.wait_for_timeout(150)

    # Toggle a Vietnamese oil/sauce modifier
    mod = page.locator("[data-testid^='modifier-']").first
    assert mod.count() > 0, "Expected Staging Plate VN modifier chip ([data-testid^='modifier-'])"
    mod.click()
    page.wait_for_timeout(150)

    log_btn = page.get_by_test_id("calorie-log-to-journal")
    assert log_btn.count() > 0, "Expected 1-tap 'Ghi vào Nhật ký hôm nay' CTA (calorie-log-to-journal)"
    log_btn.click()
    page.get_by_test_id("calorie-logged-notice").wait_for(state="visible", timeout=5000)

    page.goto(f"{base_url}/nhat-ky", wait_until="networkidle")
    today_summary = page.get_by_test_id("journal-today-summary")
    today_summary.wait_for(state="visible", timeout=15000)
    today_summary.get_by_test_id("macro-pie-chart").wait_for(state="visible", timeout=10000)
    today_summary.get_by_test_id("macro-nutrition-ledger").wait_for(state="visible", timeout=10000)

    quick_logs = page.get_by_test_id("journal-quick-logs")
    quick_logs.wait_for(state="visible", timeout=15000)
    quick_logs_text = quick_logs.inner_text()
    assert "Chưa có món ăn" not in quick_logs_text
    assert "Cơm" in quick_logs_text
    assert re.search(r"[1-9]\d*\s*kcal", quick_logs_text), f"Expected positive logged kcal in quick logs: {quick_logs_text}"

    journal_text = page.get_by_test_id("screen-journal").inner_text()
    assert_no_banned_copy(journal_text, context="T3-01 journal")
    assert_no_ai_separators(journal_text, context="T3-01 journal")
    telemetry.assert_clean(page)


def test_T3_02_fridge_scan_nam_direction1_confirm_to_3_dish_tray(
    api_client: httpx.Client,
    helpers: Any,
    session_consented_user: dict[str, Any],
) -> None:
    token = session_consented_user["access_token"]
    h = _auth_headers(token)

    scan: dict[str, Any] | None = None
    has_nam = False
    for idx in range(3):
        candidate = helpers.submit_and_poll_scan(
            token,
            get_nam_sample_jpeg(idx),
            filename=f"fridge_nam_{idx}.jpg",
            mode="haul",
        )
        assert candidate["status"] == "done"
        if any(
            d.get("vision_class_code") == "nam"
            for it in candidate["items"]
            for d in it.get("detections", [])
        ):
            scan = candidate
            has_nam = True
            break
        scan = candidate

    assert scan is not None
    assert has_nam, "Expected Direction 1 nam detection on real yolo_v4 nam test image"

    for it in scan["items"]:
        if it["qty_level"] is None or it["needs_check"]:
            api_client.patch(
                f"/scans/{scan['id']}/items/{it['id']}",
                headers={**h, "Content-Type": "application/merge-patch+json"},
                json={"qty_level": it["qty_level"] or "vua", "user_freshness": "dung_som"},
            )

    confirm = api_client.post(f"/scans/{scan['id']}/confirm", headers=h, json={})
    assert confirm.status_code == 200
    assert len(confirm.json()["created_lot_ids"]) >= 1

    lots = helpers.list_all_pantry_lots(token, sort="urgency")
    assert any("nấm" in l["ingredient_name_vi"].lower() for l in lots)

    plan = api_client.post(
        "/meal-plans",
        headers=_auth_headers(token, idem=helpers.create_idempotency_key("t302")),
        json={"meal": "dinner", "persons": 2, "max_minutes": 45},
    )
    assert plan.status_code == 201
    active = [it for it in plan.json()["items"] if it["status"] == "active"]
    assert {it["slot"] for it in active} == {"man", "rau", "canh"}


def test_T3_03_tray_missing_to_shopping_bought_to_pantry_recompose(
    api_client: httpx.Client,
    helpers: Any,
    session_consented_user: dict[str, Any],
) -> None:
    token = session_consented_user["access_token"]
    h = _auth_headers(token)

    plan1 = api_client.post(
        "/meal-plans",
        headers=_auth_headers(token, idem=helpers.create_idempotency_key("t303p1")),
        json={"meal": "dinner", "persons": 4, "max_minutes": 60},
    )
    assert plan1.status_code == 201
    p1 = plan1.json()
    active_items = [it for it in p1["items"] if it["status"] == "active"]

    missing_items: list[dict[str, Any]] = []
    source_item_id: str | None = None
    for it in active_items:
        subs = api_client.get(f"/meal-plans/{p1['id']}/items/{it['id']}/substitutes", headers=h)
        assert subs.status_code == 200
        if subs.json()["items"]:
            missing_items.extend(subs.json()["items"])
            source_item_id = it["id"]
            break

    if missing_items:
        target_ing_id = missing_items[0]["original_ingredient_id"]
        need_g = max(100.0, float(missing_items[0]["need_g"]))
    else:
        target_ing_id = helpers.resolve_ingredient_id(token, "cà chua")
        need_g = 300.0

    shop = api_client.post(
        "/shopping-items",
        headers=h,
        json={
            "ingredient_id": target_ing_id,
            "qty_g": need_g,
            "source_meal_plan_item_id": source_item_id,
        },
    )
    assert shop.status_code in (200, 201)
    sid = shop.json()["id"]

    patched = api_client.patch(f"/shopping-items/{sid}", headers=h, json={"status": "bought"})
    assert patched.status_code == 200
    assert patched.json()["status"] == "bought"

    to_pantry = api_client.post(f"/shopping-items/{sid}/to-pantry", headers=h, json={"qty_g": need_g})
    assert to_pantry.status_code == 201
    lot_id = to_pantry.json()["pantry_lot"]["id"]

    plan2 = api_client.post(
        "/meal-plans",
        headers=_auth_headers(token, idem=helpers.create_idempotency_key("t303p2")),
        json={"meal": "dinner", "persons": 4, "max_minutes": 60, "pinned_lot_ids": [lot_id]},
    )
    assert plan2.status_code == 201


def test_T3_04_allergens_and_diet_profile_filter_meal_plan(
    api_client: httpx.Client,
    helpers: Any,
    session_consented_user: dict[str, Any],
) -> None:
    token = session_consented_user["access_token"]
    h = _auth_headers(token)
    assert api_client.put("/me/diet", headers=h, json={"diet_code": "chay"}).status_code == 200
    assert api_client.put("/me/allergens", headers=h, json={"allergen_codes": ["giap_xac"]}).status_code == 200
    try:
        helpers.seed_pantry_lot(token, "đậu phụ", grams=600.0)
        helpers.seed_pantry_lot(token, "cà chua", grams=400.0)
        helpers.seed_pantry_lot(token, "rau muống", grams=500.0)
        helpers.seed_pantry_lot(token, "hạt nêm chay", grams=100.0)
        helpers.seed_pantry_lot(token, "hành lá", grams=150.0)
        helpers.seed_pantry_lot(token, "bắp cải", grams=600.0)

        ref = api_client.get("/reference").json()
        chay_diet = next((d for d in ref["diets"] if d["code"] == "chay"), None)
        excluded_groups = set(chay_diet["excluded_food_group_codes"]) if chay_diet else set()

        plan_resp = api_client.post(
            "/meal-plans",
            headers=_auth_headers(token, idem=helpers.create_idempotency_key("t304")),
            json={"meal": "dinner", "persons": 2, "max_minutes": 60},
        )
        assert plan_resp.status_code == 201, f"Vegetarian plan failed: {plan_resp.text}"
        active = [it for it in plan_resp.json()["items"] if it["status"] == "active"]
        assert len(active) == 3

        for it in active:
            rec = api_client.get(f"/recipes/{it['recipe_id']}", headers=h).json()
            for ing in rec["ingredients"]:
                assert "giap_xac" not in ing["allergen_codes"], f"Allergen giap_xac leaked into {rec['name_vi']}"
                if excluded_groups:
                    ing_detail = api_client.get("/ingredients", headers=h, params={"q": ing["name_vi"], "limit": 20}).json()["items"]
                    exact = next((x for x in ing_detail if x["id"] == ing["ingredient_id"]), None)
                    if exact is not None:
                        assert exact["food_group_code"] not in excluded_groups, (
                            f"Excluded food group {exact['food_group_code']} leaked into vegetarian dish {rec['name_vi']}"
                        )
    finally:
        api_client.put("/me/diet", headers=h, json={"diet_code": None})
        api_client.put("/me/allergens", headers=h, json={"allergen_codes": []})


def test_T3_05_cook_complete_pantry_journal_and_undo_rollback(
    api_client: httpx.Client,
    helpers: Any,
    session_consented_user: dict[str, Any],
) -> None:
    token = session_consented_user["access_token"]
    h = _auth_headers(token)

    before_lots = {l["id"]: l["balance_g_min"] for l in helpers.list_all_pantry_lots(token)}
    week = _current_iso_week()
    before_hist = len(api_client.get("/journal", headers=h, params={"week": week}).json()["cooked_history"])

    plan = api_client.post(
        "/meal-plans",
        headers=_auth_headers(token, idem=helpers.create_idempotency_key("t305p")),
        json={"meal": "dinner", "persons": 2, "max_minutes": 60},
    ).json()
    api_client.post(f"/meal-plans/{plan['id']}/accept", headers=h)

    serve_at = (datetime.now(timezone.utc) + timedelta(minutes=65)).isoformat()
    cs = api_client.post(
        "/cook-sessions",
        headers=_auth_headers(token, idem=helpers.create_idempotency_key("t305c")),
        json={"meal_plan_id": plan["id"], "serve_at": serve_at, "confirm_over_time": True},
    ).json()

    comp = api_client.post(
        f"/cook-sessions/{cs['id']}/complete",
        headers=_auth_headers(token, idem=helpers.create_idempotency_key("t305d")),
        json={"feedback": []},
    )
    assert comp.status_code == 200
    assert len(comp.json()["deductions"]) > 0

    after_hist = len(api_client.get("/journal", headers=h, params={"week": week}).json()["cooked_history"])
    assert after_hist == before_hist + 1

    undo = api_client.post(f"/cook-sessions/{cs['id']}/undo", headers=h)
    assert undo.status_code == 200
    assert undo.json()["status"] == "reverted"

    restored_lots = {l["id"]: l["balance_g_min"] for l in helpers.list_all_pantry_lots(token)}
    for lid, orig_g in before_lots.items():
        assert restored_lots[lid] == pytest.approx(orig_g, rel=1e-3)
    restored_hist = len(api_client.get("/journal", headers=h, params={"week": week}).json()["cooked_history"])
    assert restored_hist == before_hist


@pytest.mark.browser
def test_T3_06_landing_cta_to_web_login_cookie_reload_and_csp(
    base_url: str,
    page_factory: Callable[..., tuple[Any, Page, Any]],
    session_consented_user: dict[str, Any],
) -> None:
    ctx, page, telemetry = page_factory(viewport=(1440, 900), color_scheme="light")
    page.goto(f"{base_url}/gioi-thieu/", wait_until="networkidle")

    # Click landing login/app entry link -> navigate to /dang-nhap
    login_link = page.locator("a[href='/dang-nhap']").first
    assert login_link.is_visible()
    login_link.click()
    page.wait_for_url(re.compile(r"/dang-nhap"), timeout=15000)

    page.get_by_test_id("login-email").fill(session_consented_user["_email"])
    page.get_by_test_id("login-password").fill(session_consented_user["_password"])
    page.get_by_test_id("login-submit").click()
    page.wait_for_url(re.compile(r"/(bep|onboarding)"), timeout=20000)

    # Reload and verify session persists via HttpOnly cookie with zero Web Storage tokens
    page.reload(wait_until="networkidle")
    page.goto(f"{base_url}/kho", wait_until="networkidle")
    page.get_by_test_id("screen-pantry").wait_for(state="visible", timeout=15000)
    cookies = {c["name"]: c for c in ctx.cookies()}
    assert "tastoria_refresh" in cookies and cookies["tastoria_refresh"]["httpOnly"] is True
    storage_dump = page.evaluate("() => JSON.stringify({ls: Object.entries(localStorage), ss: Object.entries(sessionStorage)})")
    assert "refresh_token" not in storage_dump.lower()
    telemetry.assert_clean(page)


@pytest.mark.browser
def test_T3_07_barcode_lookup_nutrition_score_to_ui(
    base_url: str,
    page_factory: Callable[..., tuple[Any, Page, Any]],
    session_consented_user: dict[str, Any],
) -> None:
    _, page, telemetry = page_factory(viewport=(1440, 900), color_scheme="light")
    page.goto(f"{base_url}/dang-nhap", wait_until="networkidle")
    page.get_by_test_id("login-email").fill(session_consented_user["_email"])
    page.get_by_test_id("login-password").fill(session_consented_user["_password"])
    page.get_by_test_id("login-submit").click()
    page.wait_for_url(re.compile(r"/(bep|onboarding)"), timeout=20000)

    page.goto(f"{base_url}/quet?tab=barcode", wait_until="networkidle")
    page.get_by_test_id("barcode-input").fill("8934563138165")
    page.get_by_test_id("barcode-lookup-btn").click()
    card = page.get_by_test_id("barcode-result-card")
    card.wait_for(state="visible", timeout=15000)
    card.get_by_test_id("macro-pie-chart").wait_for(state="visible", timeout=10000)
    ledger = card.get_by_test_id("macro-nutrition-ledger")
    ledger.wait_for(state="visible", timeout=10000)
    card_text = card.inner_text()
    assert "Chỉ số dinh dưỡng Mỹ Vị" in card_text
    assert_no_banned_copy(card_text, context="T3-07 barcode card")

    before_ledger = ledger.inner_text()
    unit_toggle = card.get_by_test_id("barcode-unit-toggle")
    if unit_toggle.count() > 0 and unit_toggle.is_visible():
        unit_toggle.get_by_text("Theo 100g").click()
        page.wait_for_timeout(150)
        assert ledger.inner_text() != before_ledger
        assert card.inner_text() != card_text
    telemetry.assert_clean(page)


@pytest.mark.browser
def test_T3_08_landing_tabs_app_routes_and_security_headers_consistency(
    base_url: str,
    raw_client: httpx.Client,
    page_factory: Callable[..., tuple[Any, Page, Any]],
) -> None:
    # Verify security headers match across landing, legal, and app routes
    for path in ("/", "/gioi-thieu/", "/gioi-thieu/rieng-tu.html", "/dang-nhap", "/khao-sat"):
        r = raw_client.get(path)
        assert r.status_code == 200
        assert r.headers.get("x-frame-options", "").upper() == "DENY"
        assert r.headers.get("x-content-type-options", "").lower() == "nosniff"
        assert "content-security-policy" in {k.lower() for k in r.headers.keys()}

    _, page, telemetry = page_factory(viewport=(1440, 900), color_scheme="light")
    page.goto(f"{base_url}/gioi-thieu/", wait_until="networkidle")
    for tab in ("quet", "kho", "mam", "nau"):
        page.locator(f"[data-screen-tab='{tab}']").click()
        src = page.locator("#device-preview-img").get_attribute("src") or ""
        assert f"{tab}-" in src
    telemetry.assert_clean(page)
