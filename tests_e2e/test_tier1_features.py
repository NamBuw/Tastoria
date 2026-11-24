"""Tier 1: Isolated happy-path feature coverage across all 7 Tastoria feature areas (42 tests)."""

from __future__ import annotations

import io
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import httpx
import pytest
from PIL import Image
from playwright.sync_api import Page

from fixtures import (
    REPO_ROOT,
    get_app_food_asset,
    get_nam_sample_jpeg,
    get_produce_scan_jpeg,
    make_exif_gps_orientation6_jpeg,
    make_valid_png_bytes,
)
from rubric import (
    assert_barcode_copy_clean,
    assert_meal_estimate_copy_clean,
    assert_no_ai_separators,
    assert_no_banned_copy,
    assert_no_brand_leak,
    assert_no_prose_hyphens,
    evaluate_page_rubric,
)

pytestmark = pytest.mark.tier1

MUSHROOM_SLUGS = {
    "nam-rom",
    "nam-huong-tuoi",
    "nam-kim-cham",
    "nam-dui-ga",
    "nam-so",
    "nam-mo",
}
VALID_FUSION_MODES = {"kb_exact", "variance_weighted", "top3_blend", "visual_fallback"}


def _current_iso_week() -> str:
    now_vn = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
    iso_year, iso_week, _ = now_vn.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def _auth_headers(token: str, *, idem: str | None = None) -> dict[str, str]:
    h = {"Authorization": f"Bearer {token}"}
    if idem:
        h["Idempotency-Key"] = idem
    return h


# ============================================================================
# Area 1: Health, Readiness, Nginx Security & Public Routes (T1-INF-01..06)
# ============================================================================


def test_T1_INF_01_health_and_readiness_probes(raw_client: httpx.Client) -> None:
    hz = raw_client.get("/healthz")
    assert hz.status_code == 200
    assert hz.json() == {"status": "ok"}
    assert "no-store" in hz.headers.get("cache-control", "").lower()

    rz = raw_client.get("/readyz")
    assert rz.status_code == 200
    body = rz.json()
    assert body["status"] == "ready"
    checks = body["checks"]
    assert checks["database"] == "ok"
    assert checks["valkey"] == "ok"
    assert checks["models"] == "ok"
    assert "no-store" in rz.headers.get("cache-control", "").lower()


def test_T1_INF_02_openapi_spec_reachable_at_v1(raw_client: httpx.Client) -> None:
    """In production M6 hardening, OpenAPI/Swagger endpoints return 404 and external /metrics is blocked."""
    spec_resp = raw_client.get("/api/v1/openapi.json")
    docs_resp = raw_client.get("/api/v1/docs")
    assert spec_resp.status_code == 404, f"Expected 404 for prod openapi.json, got {spec_resp.status_code}"
    assert docs_resp.status_code == 404, f"Expected 404 for prod docs, got {docs_resp.status_code}"

    ext_metrics = raw_client.get("/metrics", headers={"CF-Connecting-IP": "1.2.3.4"})
    assert ext_metrics.status_code == 403, f"Expected 403 for external /metrics, got {ext_metrics.status_code}"


def test_T1_INF_03_landing_and_legal_security_headers(raw_client: httpx.Client) -> None:
    for path in ("/", "/gioi-thieu/", "/gioi-thieu/rieng-tu.html", "/gioi-thieu/dieu-khoan.html"):
        resp = raw_client.get(path)
        assert resp.status_code == 200, f"GET {path} -> {resp.status_code}"
        assert "text/html" in resp.headers.get("content-type", "").lower()
        assert "no-cache" in resp.headers.get("cache-control", "").lower(), f"Missing no-cache on {path}"
        assert resp.headers.get("x-content-type-options", "").lower() == "nosniff"
        assert resp.headers.get("x-frame-options", "").upper() == "DENY"
        assert resp.headers.get("referrer-policy", "").lower() == "strict-origin-when-cross-origin"
        assert "permissions-policy" in {k.lower() for k in resp.headers.keys()}, f"Missing Permissions-Policy on {path}"
        csp = resp.headers.get("content-security-policy", "")
        assert csp, f"Missing Content-Security-Policy on {path}"
        assert "frame-ancestors 'none'" in csp.lower()
        assert "object-src 'none'" in csp.lower()
        script_src = next((d for d in csp.split(";") if d.strip().lower().startswith("script-src")), "")
        assert "'unsafe-inline'" not in script_src.lower(), f"Landing script-src must forbid unsafe-inline: {csp}"


def test_T1_INF_04_gioi_thieu_trailing_slash_redirect(raw_client: httpx.Client) -> None:
    resp = raw_client.get("/gioi-thieu")
    assert resp.status_code == 301
    assert resp.headers.get("location") == "/gioi-thieu/"


def test_T1_INF_05_app_web_spa_routes_and_cache_control(raw_client: httpx.Client) -> None:
    for path in ("/kho", "/mam", "/quet", "/nhat-ky", "/cai-dat"):
        resp = raw_client.get(path)
        assert resp.status_code == 200, f"SPA route {path} -> {resp.status_code}"
        assert "text/html" in resp.headers.get("content-type", "").lower()
        cc = resp.headers.get("cache-control", "").lower()
        assert "no-cache" in cc or "no-store" in cc, f"HTML SPA route {path} cached aggressively: {cc}"
        assert resp.headers.get("x-content-type-options", "").lower() == "nosniff"
        assert resp.headers.get("x-frame-options", "").upper() == "DENY"


def test_T1_INF_06_static_asset_caching_and_mime_types(raw_client: httpx.Client) -> None:
    css = raw_client.get("/gioi-thieu/style.css")
    assert css.status_code == 200
    assert "text/css" in css.headers.get("content-type", "").lower()
    assert css.headers.get("x-content-type-options", "").lower() == "nosniff"
    assert "max-age=" in css.headers.get("cache-control", "").lower()

    js = raw_client.get("/gioi-thieu/story.js")
    assert js.status_code == 200
    assert "javascript" in js.headers.get("content-type", "").lower()
    assert js.headers.get("x-content-type-options", "").lower() == "nosniff"

    for asset_path, expected_mime in (
        ("/gioi-thieu/img/paper-bg-light.webp", "image/webp"),
        ("/gioi-thieu/fonts/newsreader-vietnamese-var.woff2", "font/woff2"),
        ("/gioi-thieu/fonts/be-vietnam-pro-vietnamese-400.woff2", "font/woff2"),
        ("/gioi-thieu/img/trong-dong-dong-son.webp", "image/webp"),
    ):
        asset = raw_client.get(asset_path)
        assert asset.status_code == 200, f"GET {asset_path} -> {asset.status_code}"
        assert expected_mime in asset.headers.get("content-type", "").lower(), (
            f"Expected {expected_mime} on {asset_path}, got {asset.headers.get('content-type')}"
        )
        assert asset.headers.get("x-content-type-options", "").lower() == "nosniff"

    spa_html = raw_client.get("/kho").text
    match = re.search(r'(/_expo/static/js/web/[^"\']+)', spa_html)
    assert match is not None, "Expected hashed /_expo/ bundle reference in SPA index.html"
    bundle = raw_client.get(match.group(1))
    assert bundle.status_code == 200
    assert "immutable" in bundle.headers.get("cache-control", "").lower()


# ============================================================================
# Area 2: Identity & Auth — Web Cookie vs Native JSON (T1-AUTH-01..06)
# ============================================================================


def test_T1_AUTH_01_native_register_and_login(
    api_client: httpx.Client,
    session_native_user: dict[str, Any],
    fresh_user_factory: Callable[..., dict[str, Any]],
) -> None:
    reg = session_native_user if not session_native_user.get("_from_cache") else fresh_user_factory()
    assert reg["token_type"] == "Bearer"
    assert reg["access_token"]
    assert reg["refresh_token"]

    login_resp = api_client.post(
        "/auth/login",
        json={"email": reg["_email"], "password": reg["_password"]},
    )
    assert login_resp.status_code == 200
    body = login_resp.json()
    assert body["token_type"] == "Bearer"
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["user"]["email"] == reg["_email"].lower()


def test_T1_AUTH_02_web_httponly_cookie_register_and_login(
    session_web_user: tuple[dict[str, Any], httpx.Client],
    web_client_factory: Callable[[], httpx.Client],
    fresh_user_factory: Callable[..., dict[str, Any]],
) -> None:
    cached_reg, cached_wc = session_web_user
    if not cached_reg.get("_from_cache"):
        reg, wc = cached_reg, cached_wc
    else:
        wc = web_client_factory()
        reg = fresh_user_factory(web_client=wc)
    assert reg["access_token"]
    assert reg.get("refresh_token") is None, "Web auth JSON must omit/null refresh_token"
    set_cookies = "\n".join(reg.get("_set_cookie", []))
    assert "tastoria_refresh=" in set_cookies
    assert "httponly" in set_cookies.lower()
    assert "samesite=lax" in set_cookies.lower()
    assert "path=/api/v1/auth" in set_cookies.lower()

    login_resp = wc.post(
        "/auth/login",
        json={"email": reg["_email"], "password": reg["_password"]},
    )
    assert login_resp.status_code == 200
    login_body = login_resp.json()
    assert login_body.get("refresh_token") is None
    login_cookies = "\n".join(login_resp.headers.get_list("set-cookie"))
    assert "tastoria_refresh=" in login_cookies
    assert "httponly" in login_cookies.lower()


def test_T1_AUTH_03_native_refresh_token_rotation(
    api_client: httpx.Client,
    helpers: Any,
    pooled_auth_lifecycle_user: dict[str, Any],
) -> None:
    user = helpers.login_user(pooled_auth_lifecycle_user["_email"], pooled_auth_lifecycle_user["_password"])
    r1 = api_client.post("/auth/refresh", json={"refresh_token": user["refresh_token"]})
    assert r1.status_code == 200
    b1 = r1.json()
    assert b1["access_token"]
    assert b1["refresh_token"]
    assert b1["refresh_token"] != user["refresh_token"]


def test_T1_AUTH_04_web_cookie_refresh_rotation(
    helpers: Any,
    web_client_factory: Callable[[], httpx.Client],
    pooled_auth_lifecycle_user: dict[str, Any],
) -> None:
    wc = web_client_factory()
    user = helpers.login_user(
        pooled_auth_lifecycle_user["_email"],
        pooled_auth_lifecycle_user["_password"],
        web_client=wc,
    )
    assert user.get("refresh_token") is None

    r1 = wc.post("/auth/refresh", json={})
    assert r1.status_code == 200, f"Web cookie refresh failed ({r1.status_code}): {r1.text}"
    b1 = r1.json()
    assert b1["access_token"]
    assert b1.get("refresh_token") is None
    sc = "\n".join(r1.headers.get_list("set-cookie"))
    assert "tastoria_refresh=" in sc
    assert "httponly" in sc.lower()


def test_T1_AUTH_05_web_logout_and_logout_all_clear_cookie(
    helpers: Any,
    web_client_factory: Callable[[], httpx.Client],
    pooled_auth_lifecycle_user: dict[str, Any],
) -> None:
    wc = web_client_factory()
    email = pooled_auth_lifecycle_user["_email"]
    password = pooled_auth_lifecycle_user["_password"]
    user = helpers.login_user(email, password, web_client=wc)
    token = user["access_token"]

    out = wc.post("/auth/logout", headers=_auth_headers(token))
    assert out.status_code == 204
    sc_out = "\n".join(out.headers.get_list("set-cookie")).lower()
    assert "tastoria_refresh=" in sc_out
    assert "max-age=0" in sc_out

    ref_after = wc.post("/auth/refresh", json={})
    assert ref_after.status_code == 401

    login2 = helpers.login_user(email, password, web_client=wc)
    out_all = wc.post("/auth/logout-all", headers=_auth_headers(login2["access_token"]))
    assert out_all.status_code == 204
    sc_all = "\n".join(out_all.headers.get_list("set-cookie")).lower()
    assert "tastoria_refresh=" in sc_all
    assert "max-age=0" in sc_all


def test_T1_AUTH_06_password_reset_request_non_leaking(
    api_client: httpx.Client,
    session_native_user: dict[str, Any],
) -> None:
    r_known = api_client.post("/auth/password-reset/request", json={"email": session_native_user["_email"]})
    assert r_known.status_code == 204
    assert r_known.content == b""

    r_unknown = api_client.post("/auth/password-reset/request", json={"email": "nonexistent-e2e@example.com"})
    assert r_unknown.status_code == 204
    assert r_unknown.content == b""


# ============================================================================
# Area 3: Profile, PDPL Consents & DSR Privacy (T1-PRIV-01..05)
# ============================================================================


def test_T1_PRIV_01_policies_and_grant_consents(
    api_client: httpx.Client,
    helpers: Any,
    pooled_auth_lifecycle_user: dict[str, Any],
) -> None:
    for purpose in ("health_profile", "personalization", "photo_contribution", "survey"):
        p = api_client.get(f"/policies/{purpose}/current")
        assert p.status_code == 200
        body = p.json()
        assert body["purpose_code"] == purpose
        assert body["text_sha256"]
        assert body["text_vi"]

    user = helpers.login_user(pooled_auth_lifecycle_user["_email"], pooled_auth_lifecycle_user["_password"])
    token = user["access_token"]
    granted = helpers.grant_consents(token, purposes=("health_profile", "personalization"))
    states = {it["purpose_code"]: it["state"] for it in granted["items"]}
    assert states["health_profile"] == "granted"
    assert states["personalization"] == "granted"

    fetched = api_client.get("/me/consents", headers=_auth_headers(token))
    assert fetched.status_code == 200
    f_states = {it["purpose_code"]: it["state"] for it in fetched.json()["items"]}
    assert f_states["health_profile"] == "granted"


def test_T1_PRIV_02_encrypted_profile_roundtrip_and_energy_target(
    api_client: httpx.Client,
    session_consented_user: dict[str, Any],
) -> None:
    token = session_consented_user["access_token"]
    prof = api_client.get("/me/profile", headers=_auth_headers(token))
    assert prof.status_code == 200
    p = prof.json()
    assert p["health_profile_consented"] is True
    assert p["sex"] == "female"
    assert p["birth_year"] == 1995
    assert p["height_cm"] == pytest.approx(158.0)
    assert p["weight_kg"] == pytest.approx(52.0)
    assert p["kcal_target"] is not None and p["kcal_target"] >= 1000

    sugg = api_client.post("/me/energy-suggestion", headers=_auth_headers(token), json={"goal": "maintain"})
    assert sugg.status_code == 200
    sb = sugg.json()
    assert sb["bmr_kcal"] > 800
    assert sb["tee_kcal"] >= sb["bmr_kcal"]
    assert sb["e_lunch_kcal"] > 0 and sb["e_dinner_kcal"] > 0


def test_T1_PRIV_03_allergens_diet_favorites_and_settings(
    api_client: httpx.Client,
    helpers: Any,
    session_consented_user: dict[str, Any],
) -> None:
    token = session_consented_user["access_token"]
    h = _auth_headers(token)

    r_alg = api_client.put("/me/allergens", headers=h, json={"allergen_codes": ["dau_phong"]})
    assert r_alg.status_code == 200
    assert r_alg.json()["allergen_codes"] == ["dau_phong"]

    r_diet = api_client.put("/me/diet", headers=h, json={"diet_code": None})
    assert r_diet.status_code == 200

    rec_resp = api_client.get("/recipes", headers=h, params={"limit": 2})
    assert rec_resp.status_code == 200
    rec_ids = [r["id"] for r in rec_resp.json()["items"][:2]]
    r_fav = api_client.put("/me/favorites", headers=h, json={"recipe_ids": rec_ids})
    assert r_fav.status_code == 200
    assert len(r_fav.json()["recipe_ids"]) == len(rec_ids)

    r_set = api_client.put(
        "/me/settings",
        headers=h,
        json={"burners": 2, "default_persons": 3, "timezone": "Asia/Ho_Chi_Minh"},
    )
    assert r_set.status_code == 200
    assert r_set.json()["default_persons"] == 3

    # Restore clean allergens/settings for downstream session reuse
    api_client.put("/me/allergens", headers=h, json={"allergen_codes": []})
    api_client.put("/me/settings", headers=h, json={"burners": 2, "default_persons": 2, "timezone": "Asia/Ho_Chi_Minh"})


def test_T1_PRIV_04_withdraw_consent_creates_dsr(
    api_client: httpx.Client,
    helpers: Any,
    pooled_auth_lifecycle_user: dict[str, Any],
) -> None:
    user = helpers.login_user(pooled_auth_lifecycle_user["_email"], pooled_auth_lifecycle_user["_password"])
    token = user["access_token"]
    helpers.grant_consents(token, purposes=("health_profile", "personalization"))

    w = api_client.post(
        "/me/consents/personalization/withdraw",
        headers=_auth_headers(token),
        json={"channel": "settings"},
    )
    assert w.status_code == 200
    wb = w.json()
    assert wb["purpose_code"] == "personalization"
    assert wb["state"] == "withdrawn"
    assert wb["data_request_id"] is not None


def test_T1_PRIV_05_dsr_export_request_and_status_poll(
    api_client: httpx.Client,
    session_consented_user: dict[str, Any],
) -> None:
    token = session_consented_user["access_token"]
    h = _auth_headers(token)
    req = api_client.post("/me/data-requests", headers=h, json={"type": "export"})
    assert req.status_code in (200, 202)
    body = req.json()
    assert body["type"] == "export"
    assert body["status"] in ("received", "in_progress", "completed")
    if req.status_code == 202:
        assert req.headers.get("location")
        assert req.headers.get("retry-after") == "60"

    poll = api_client.get(f"/me/data-requests/{body['id']}", headers=h)
    assert poll.status_code == 200
    assert poll.json()["id"] == body["id"]


# ============================================================================
# Area 4: Meal Calorie Fusion, KB Fixes, Disambiguation & Barcode (T1-CAL-01..07)
# ============================================================================


def test_T1_CAL_01_list_extended_dishes(
    api_client: httpx.Client,
    session_consented_user: dict[str, Any],
) -> None:
    resp = api_client.get(
        "/meal-calorie/dishes",
        headers=_auth_headers(session_consented_user["access_token"]),
        params={"include_extended": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["dishes"]) >= 200
    sample = data["dishes"][0]
    assert sample["slot"] in ("man", "rau", "canh")
    assert sample["kcal_per_serving"] > 0


def test_T1_CAL_02_photo_estimate_m2_fusion_contract(
    api_client: httpx.Client,
    session_consented_user: dict[str, Any],
) -> None:
    pho_bytes = get_app_food_asset("pho.webp")
    resp = api_client.post(
        "/meal-calorie/estimate",
        headers=_auth_headers(session_consented_user["access_token"]),
        files={"image": ("pho.webp", pho_bytes, "image/webp")},
        data={"portion": "vua"},
    )
    assert resp.status_code == 200, f"estimate failed ({resp.status_code}): {resp.text}"
    out = resp.json()
    assert out["estimated_kcal"] > 0
    assert out["kcal_low"] <= out["estimated_kcal"] <= out["kcal_high"]
    assert isinstance(out["disambiguation_required"], bool)
    assert out["top_margin"] is None or isinstance(out["top_margin"], (int, float))
    assert isinstance(out["provenance_label_vi"], str) and len(out["provenance_label_vi"].strip()) > 0
    assert out["fusion_mode"] in VALID_FUSION_MODES
    assert isinstance(out["suggested_modifiers"], list)
    split = out["macro_kcal_split"]
    assert split is not None
    total_pct = split["protein_pct"] + split["carbs_pct"] + split["fat_pct"]
    assert 97 <= total_pct <= 103
    assert_meal_estimate_copy_clean(out, context="MealCalorieEstimateOut")


def test_T1_CAL_03_kb_hijack_fix_dau_phu_non(
    api_client: httpx.Client,
    session_consented_user: dict[str, Any],
) -> None:
    h = _auth_headers(session_consented_user["access_token"])
    plain = api_client.post(
        "/meal-calorie/estimate",
        headers=h,
        data={"dish_slug": "dau_phu_non", "portion": "vua"},
    )
    assert plain.status_code == 200, f"dau_phu_non estimate failed: {plain.text}"
    plain_out = plain.json()

    sauce = api_client.post(
        "/meal-calorie/estimate",
        headers=h,
        data={"dish_slug": "dau-phu-non-sot-nam", "portion": "vua"},
    )
    assert sauce.status_code == 200, f"dau-phu-non-sot-nam estimate failed: {sauce.text}"
    sauce_out = sauce.json()

    assert 70.0 <= plain_out["estimated_kcal"] <= 130.0, f"dau_phu_non hijacked: {plain_out}"
    assert 150.0 <= sauce_out["estimated_kcal"] <= 215.0, f"dau-phu-non-sot-nam unexpected: {sauce_out}"
    assert plain_out["estimated_kcal"] < sauce_out["estimated_kcal"] - 40.0


def test_T1_CAL_04_kb_hijack_fix_omelette(
    api_client: httpx.Client,
    session_consented_user: dict[str, Any],
) -> None:
    h = _auth_headers(session_consented_user["access_token"])
    omelette = api_client.post(
        "/meal-calorie/estimate",
        headers=h,
        data={"dish_slug": "omelette", "portion": "vua"},
    )
    assert omelette.status_code == 200, f"omelette estimate failed: {omelette.text}"
    om_out = omelette.json()

    trung = api_client.post(
        "/meal-calorie/estimate",
        headers=h,
        data={"dish_slug": "trung-chien-hanh", "portion": "vua"},
    )
    assert trung.status_code == 200, f"trung-chien-hanh estimate failed: {trung.text}"
    tr_out = trung.json()

    assert 220.0 <= om_out["estimated_kcal"] <= 300.0, f"omelette hijacked: {om_out}"
    assert 140.0 <= tr_out["estimated_kcal"] <= 195.0, f"trung-chien-hanh unexpected: {tr_out}"
    assert om_out["estimated_kcal"] > tr_out["estimated_kcal"] + 30.0


def test_T1_CAL_05_portion_scaling_nho_vua_lon(
    api_client: httpx.Client,
    session_consented_user: dict[str, Any],
    session_native_user: dict[str, Any],
) -> None:
    h = _auth_headers(session_consented_user["access_token"])
    kcals: dict[str, float] = {}
    for portion in ("nho", "vua", "lon"):
        r = api_client.post(
            "/meal-calorie/estimate",
            headers=h,
            data={"dish_name": "Phở bò", "portion": portion},
        )
        assert r.status_code == 200
        kcals[portion] = r.json()["estimated_kcal"]

    assert kcals["nho"] < kcals["vua"] < kcals["lon"]
    assert kcals["nho"] == pytest.approx(kcals["vua"] * 0.75, rel=0.05)
    assert kcals["lon"] == pytest.approx(kcals["vua"] * 1.35, rel=0.05)

    # T5-1 regression: exact recognized match ("Phở", "Pho") & word-boundary guards ("Phởn", "Cơm", "Bún")
    h_nat = _auth_headers(session_native_user["access_token"])
    for pho_query in ("Phở", "Pho"):
        pho_r = api_client.post(
            "/meal-calorie/estimate",
            headers=h_nat,
            data={"dish_name": pho_query, "portion": "vua"},
        )
        assert pho_r.status_code == 200, f"{pho_query!r} estimate failed: {pho_r.text}"
        pho_b = pho_r.json()
        assert pho_b["dish_name_vi"] == "Phở", f"{pho_query!r} hijacked: {pho_b}"
        assert pho_b["estimated_kcal"] >= 350.0, f"{pho_query!r} kcal too low: {pho_b}"

    phon_r = api_client.post(
        "/meal-calorie/estimate",
        headers=h_nat,
        data={"dish_name": "Phởn", "portion": "vua"},
    )
    assert phon_r.status_code == 404, f"Expected 404 for unknown 'Phởn', got {phon_r.status_code}: {phon_r.text}"
    assert "Canh bí đỏ đậu phộng" not in phon_r.text

    com_r = api_client.post("/meal-calorie/estimate", headers=h_nat, data={"dish_name": "Cơm", "portion": "vua"})
    assert com_r.status_code == 200
    assert com_r.json()["dish_name_vi"].startswith("Cơm")
    assert com_r.json()["dish_name_vi"] != "Cá cơm rim mặn ngọt"

    bun_r = api_client.post("/meal-calorie/estimate", headers=h_nat, data={"dish_name": "Bún", "portion": "vua"})
    assert bun_r.status_code == 200
    assert bun_r.json()["dish_name_vi"].startswith("Bún")
    assert bun_r.json()["dish_name_vi"] != "Cà bung"


def test_T1_CAL_06_multiple_vn_dish_photos_and_provenance(
    api_client: httpx.Client,
    session_consented_user: dict[str, Any],
) -> None:
    h = _auth_headers(session_consented_user["access_token"])
    for asset in ("omelette.webp", "bun-thit-nuong.webp", "beef-pho.webp"):
        r = api_client.post(
            "/meal-calorie/estimate",
            headers=h,
            files={"image": (asset, get_app_food_asset(asset), "image/webp")},
            data={"portion": "vua"},
        )
        assert r.status_code == 200, f"estimate failed for {asset}: {r.text}"
        body = r.json()
        assert body["estimated_kcal"] > 50
        assert body["fusion_mode"] in VALID_FUSION_MODES
        assert body["provenance_label_vi"]
        assert_meal_estimate_copy_clean(body, context=f"estimate:{asset}")


def test_T1_CAL_07_barcode_lookup_vietnamese_product(
    api_client: httpx.Client,
    session_consented_user: dict[str, Any],
) -> None:
    r = api_client.get(
        "/meal-calorie/barcode/8934563138165",
        headers=_auth_headers(session_consented_user["access_token"]),
    )
    assert r.status_code == 200, f"Barcode lookup failed: {r.text}"
    body = r.json()
    assert body["barcode"] == "8934563138165"
    assert body["product_name"]
    assert (body["kcal_per_serving"] or 0) > 0 or (body["kcal_per_100g"] or 0) > 0
    assert body["nutrition_grade"] in ("A", "B", "C", "D")
    assert_barcode_copy_clean(body, context="BarcodeNutritionOut")


# ============================================================================
# Area 5: Ingredient Scan & Direction 1 Mushroom Sub-Classifier (T1-SCAN-01..05)
# ============================================================================


def test_T1_SCAN_01_submit_scan_and_poll_done(
    helpers: Any,
    session_consented_user: dict[str, Any],
) -> None:
    scan = helpers.submit_and_poll_scan(
        session_consented_user["access_token"],
        get_produce_scan_jpeg(),
        filename="fridge_produce.jpg",
        mode="fridge",
    )
    assert scan["status"] == "done"
    assert len(scan["images"]) == 1
    assert isinstance(scan["items"], list)


def test_T1_SCAN_02_direction1_mushroom_sub_species(
    helpers: Any,
    session_consented_user: dict[str, Any],
) -> None:
    token = session_consented_user["access_token"]
    nam_detections: list[dict[str, Any]] = []
    classified: list[dict[str, Any]] = []
    # Probe up to 5 real nam test images from yolo_v4/images/test/ until Direction 1 classifies a mushroom species
    for idx in range(5):
        scan = helpers.submit_and_poll_scan(
            token,
            get_nam_sample_jpeg(idx),
            filename=f"nam_test_{idx}.jpg",
            mode="fridge",
        )
        assert scan["status"] == "done"
        for item in scan["items"]:
            for det in item.get("detections", []):
                if det.get("vision_class_code") == "nam":
                    nam_detections.append(det)
                    if det.get("sub_species_slug") is not None:
                        classified.append(det)
        if classified:
            break

    assert nam_detections, "Expected detector to emit vision_class_code=='nam' on real yolo_v4 nam test photo"
    for det in nam_detections:
        assert "sub_species_slug" in det, f"Missing Direction 1 field sub_species_slug: {det}"
        assert "sub_species_conf" in det, f"Missing Direction 1 field sub_species_conf: {det}"
    assert classified, (
        f"Expected at least one real nam detection with non-null sub_species_slug in {MUSHROOM_SLUGS}: {nam_detections}"
    )
    top_det = classified[0]
    assert top_det["sub_species_slug"] in MUSHROOM_SLUGS
    assert top_det["sub_species_conf"] is not None
    assert 0.0 <= float(top_det["sub_species_conf"]) <= 1.0


def test_T1_SCAN_03_scan_item_add_patch_delete(
    api_client: httpx.Client,
    helpers: Any,
    session_consented_user: dict[str, Any],
) -> None:
    token = session_consented_user["access_token"]
    h = _auth_headers(token)
    scan = helpers.submit_and_poll_scan(token, get_produce_scan_jpeg(), mode="haul")
    assert scan["status"] == "done"

    ing = helpers.resolve_ingredient(token, "cải ngọt")
    ing_id = ing["id"]
    is_countable = bool(ing.get("countable"))
    existing = [it for it in scan["items"] if it["ingredient_id"] == ing_id]
    if existing:
        item_id = existing[0]["id"]
    else:
        add_payload: dict[str, Any] = {"ingredient_id": ing_id, "user_freshness": "tuoi"}
        if is_countable:
            add_payload["final_count"] = 3
        else:
            add_payload["qty_level"] = "vua"
        add = api_client.post(
            f"/scans/{scan['id']}/items",
            headers=h,
            json=add_payload,
        )
        assert add.status_code == 201
        item_id = add.json()["id"]

    if is_countable:
        patch_payload: dict[str, Any] = {"final_count": 5, "user_freshness": "dung_som"}
        expected_field, expected_value = "final_count", 5
    else:
        patch_payload = {"qty_level": "nhieu", "user_freshness": "dung_som"}
        expected_field, expected_value = "qty_level", "nhieu"

    patch = api_client.patch(
        f"/scans/{scan['id']}/items/{item_id}",
        headers={**h, "Content-Type": "application/merge-patch+json"},
        json=patch_payload,
    )
    assert patch.status_code == 200
    assert patch.json()[expected_field] == expected_value
    assert patch.json()["user_freshness"] == "dung_som"

    delete = api_client.delete(f"/scans/{scan['id']}/items/{item_id}", headers=h)
    assert delete.status_code == 204


def test_T1_SCAN_04_confirm_scan_creates_pantry_lots(
    api_client: httpx.Client,
    helpers: Any,
    session_consented_user: dict[str, Any],
    fresh_user_factory: Callable[..., dict[str, Any]],
) -> None:
    token = session_consented_user["access_token"]
    h = _auth_headers(token)
    scan = helpers.submit_and_poll_scan(token, get_produce_scan_jpeg(), mode="haul")
    assert scan["status"] == "done"

    # Ensure at least one valid editable item with qty_level & freshness
    ing_id = helpers.resolve_ingredient_id(token, "cải ngọt")
    if not any(it["ingredient_id"] == ing_id for it in scan["items"]):
        add = api_client.post(
            f"/scans/{scan['id']}/items",
            headers=h,
            json={"ingredient_id": ing_id, "qty_level": "vua", "user_freshness": "tuoi"},
        )
        assert add.status_code == 201

    for it in scan["items"]:
        if it["qty_level"] is None or it["needs_check"]:
            api_client.patch(
                f"/scans/{scan['id']}/items/{it['id']}",
                headers={**h, "Content-Type": "application/merge-patch+json"},
                json={"qty_level": it["qty_level"] or "vua", "user_freshness": "tuoi"},
            )

    confirm = api_client.post(f"/scans/{scan['id']}/confirm", headers=h, json={})
    assert confirm.status_code == 200, f"confirm failed: {confirm.text}"
    cb = confirm.json()
    assert cb["status"] == "confirmed"
    assert len(cb["created_lot_ids"]) >= 1

    all_lots = helpers.list_all_pantry_lots(token)
    lot_ids = {l["id"] for l in all_lots}
    assert set(cb["created_lot_ids"]).issubset(lot_ids)

    # Isolated mode="fridge" scan verification: non-staple unseen lot becomes not_seen; staple stays in_stock
    iso = fresh_user_factory(consented=True, seed_pantry=False)
    iso_tok = iso["access_token"]
    iso_h = _auth_headers(iso_tok)
    lot_carrot = helpers.seed_pantry_lot(iso_tok, "cà rốt", grams=300.0)
    lot_oil = helpers.seed_pantry_lot(iso_tok, "dầu ăn", grams=500.0)

    fridge_scan = helpers.submit_and_poll_scan(
        iso_tok,
        make_valid_png_bytes(),
        filename="fridge_rescan.png",
        content_type="image/png",
        mode="fridge",
    )
    assert fridge_scan["status"] == "done"
    cai_ngot_id = helpers.resolve_ingredient_id(iso_tok, "cải ngọt")
    if not any(it["ingredient_id"] == cai_ngot_id for it in fridge_scan["items"]):
        add_f = api_client.post(
            f"/scans/{fridge_scan['id']}/items",
            headers=iso_h,
            json={"ingredient_id": cai_ngot_id, "qty_level": "vua", "user_freshness": "tuoi"},
        )
        assert add_f.status_code == 201
    for it in fridge_scan["items"]:
        if it["qty_level"] is None or it["needs_check"]:
            api_client.patch(
                f"/scans/{fridge_scan['id']}/items/{it['id']}",
                headers={**iso_h, "Content-Type": "application/merge-patch+json"},
                json={"qty_level": it["qty_level"] or "vua", "user_freshness": "tuoi"},
            )
    f_conf = api_client.post(f"/scans/{fridge_scan['id']}/confirm", headers=iso_h, json={})
    assert f_conf.status_code == 200, f"fridge confirm failed: {f_conf.text}"
    fcb = f_conf.json()
    assert fcb["status"] == "confirmed"
    assert lot_carrot["id"] in fcb["not_seen_lot_ids"], f"Expected non-staple lot in not_seen_lot_ids: {fcb}"
    assert lot_oil["id"] not in fcb["not_seen_lot_ids"], f"Staple lot should never be marked not_seen: {fcb}"

    iso_lots = {l["id"]: l for l in helpers.list_all_pantry_lots(iso_tok)}
    assert iso_lots[lot_carrot["id"]]["status"] == "not_seen"
    assert iso_lots[lot_oil["id"]]["status"] == "in_stock"


def test_T1_SCAN_05_fetch_sanitized_image_and_discard(
    api_client: httpx.Client,
    helpers: Any,
    session_consented_user: dict[str, Any],
) -> None:
    token = session_consented_user["access_token"]
    h = _auth_headers(token)
    exif_jpg = make_exif_gps_orientation6_jpeg(400, 240)
    scan = helpers.submit_and_poll_scan(token, exif_jpg, filename="exif_gps.jpg", mode="fridge")
    assert scan["status"] == "done"

    img_resp = api_client.get(f"/scans/{scan['id']}/images/1", headers=h)
    assert img_resp.status_code == 200
    assert "image/jpeg" in img_resp.headers.get("content-type", "").lower()
    loaded = Image.open(io.BytesIO(img_resp.content))
    exif = loaded.getexif()
    assert 0x8825 not in exif, "GPS IFD (0x8825) was not stripped from stored scan image"
    assert exif.get(0x0112) in (None, 1), "EXIF Orientation was not normalized"

    disc = api_client.post(f"/scans/{scan['id']}/discard", headers=h)
    assert disc.status_code == 200
    assert disc.json()["status"] == "discarded"


# ============================================================================
# Area 6: Pantry, Catalog, Meal Composer, Cooking, Shopping, Journal, Survey
# ============================================================================


def test_T1_KITCH_01_pantry_lot_crud_and_urgency_sort(
    api_client: httpx.Client,
    helpers: Any,
    session_consented_user: dict[str, Any],
) -> None:
    token = session_consented_user["access_token"]
    h = _auth_headers(token)
    lot = helpers.seed_pantry_lot(token, "cà rốt", grams=450.0, days_ago=1.5)
    assert lot["status"] == "in_stock"

    all_lots = helpers.list_all_pantry_lots(token, sort="urgency")
    assert any(l["id"] == lot["id"] for l in all_lots)

    patched = api_client.patch(
        f"/pantry/lots/{lot['id']}",
        headers={**h, "Content-Type": "application/merge-patch+json"},
        json={"balance": {"g_min": 250.0, "g_max": 250.0}},
    )
    assert patched.status_code == 200
    assert patched.json()["balance_g_min"] == pytest.approx(250.0)

    disc = api_client.post(f"/pantry/lots/{lot['id']}/discard", headers=h)
    assert disc.status_code == 200
    assert disc.json()["status"] == "discarded"


def test_T1_KITCH_02_catalog_etag_304_and_recipe_filters(
    api_client: httpx.Client,
    session_consented_user: dict[str, Any],
) -> None:
    ref1 = api_client.get("/reference")
    assert ref1.status_code == 200
    etag = ref1.headers.get("etag")
    assert etag
    ref2 = api_client.get("/reference", headers={"If-None-Match": etag})
    assert ref2.status_code == 304

    h = _auth_headers(session_consented_user["access_token"])
    snap1 = api_client.get("/catalog/snapshot", headers=h)
    assert snap1.status_code == 200
    snap_etag = snap1.headers.get("etag")
    assert snap_etag
    snap2 = api_client.get("/catalog/snapshot", headers={**h, "If-None-Match": snap_etag})
    assert snap2.status_code == 304

    canh = api_client.get("/recipes", headers=h, params={"slot": "canh", "max_minutes": 30})
    assert canh.status_code == 200
    items = canh.json()["items"]
    assert len(items) > 0
    for r in items:
        assert r["slot"] == "canh"
        assert r["total_minutes"] <= 30


def test_T1_KITCH_03_compose_3_dish_tray_swap_and_accept(
    api_client: httpx.Client,
    helpers: Any,
    session_consented_user: dict[str, Any],
) -> None:
    token = session_consented_user["access_token"]
    plan_resp = api_client.post(
        "/meal-plans",
        headers=_auth_headers(token, idem=helpers.create_idempotency_key("plan")),
        json={"meal": "dinner", "persons": 2, "max_minutes": 45},
    )
    assert plan_resp.status_code == 201, f"POST /meal-plans failed: {plan_resp.text}"
    plan = plan_resp.json()
    active = [it for it in plan["items"] if it["status"] == "active"]
    assert {it["slot"] for it in active} == {"man", "rau", "canh"}

    man_item = next(it for it in active if it["slot"] == "man")
    swap = api_client.post(
        f"/meal-plans/{plan['id']}/items/{man_item['id']}/swap",
        headers=_auth_headers(token, idem=helpers.create_idempotency_key("swap")),
        json={"swap_reason": "moi_an"},
    )
    assert swap.status_code == 200
    swapped_active = [it for it in swap.json()["items"] if it["status"] == "active" and it["slot"] == "man"]
    assert swapped_active[0]["id"] != man_item["id"]

    acc = api_client.post(f"/meal-plans/{plan['id']}/accept", headers=_auth_headers(token))
    assert acc.status_code == 200
    assert acc.json()["status"] == "accepted"


def test_T1_KITCH_04_parallel_cook_session_complete_and_undo(
    api_client: httpx.Client,
    helpers: Any,
    session_consented_user: dict[str, Any],
) -> None:
    token = session_consented_user["access_token"]
    plan = api_client.post(
        "/meal-plans",
        headers=_auth_headers(token, idem=helpers.create_idempotency_key("plan")),
        json={"meal": "dinner", "persons": 2, "max_minutes": 60},
    ).json()
    api_client.post(f"/meal-plans/{plan['id']}/accept", headers=_auth_headers(token))

    serve_at = (datetime.now(timezone.utc) + timedelta(minutes=65)).isoformat()
    cook = api_client.post(
        "/cook-sessions",
        headers=_auth_headers(token, idem=helpers.create_idempotency_key("cook")),
        json={"meal_plan_id": plan["id"], "serve_at": serve_at, "confirm_over_time": True},
    )
    assert cook.status_code == 201, f"POST /cook-sessions failed: {cook.text}"
    cs = cook.json()
    assert len(cs["schedule"]) > 0
    assert all(s["end_offset_s"] >= s["start_offset_s"] for s in cs["schedule"])

    done = api_client.post(
        f"/cook-sessions/{cs['id']}/complete",
        headers=_auth_headers(token, idem=helpers.create_idempotency_key("done")),
        json={"feedback": []},
    )
    assert done.status_code == 200
    assert done.json()["cook_session"]["status"] == "completed"

    undo = api_client.post(f"/cook-sessions/{cs['id']}/undo", headers=_auth_headers(token))
    assert undo.status_code == 200
    assert undo.json()["status"] == "reverted"


def test_T1_KITCH_05_shopping_to_pantry_and_weekly_journal(
    api_client: httpx.Client,
    helpers: Any,
    session_consented_user: dict[str, Any],
) -> None:
    token = session_consented_user["access_token"]
    h = _auth_headers(token)
    ing_id = helpers.resolve_ingredient_id(token, "cà rốt")
    shop = api_client.post(
        "/shopping-items",
        headers=h,
        json={"ingredient_id": ing_id, "qty_g": 300.0, "note": "mua chợ chiều"},
    )
    assert shop.status_code in (200, 201)
    sid = shop.json()["id"]

    to_pantry = api_client.post(
        f"/shopping-items/{sid}/to-pantry",
        headers=h,
        json={"qty_g": 300.0},
    )
    assert to_pantry.status_code == 201
    assert to_pantry.json()["shopping_item"]["status"] == "bought"
    assert to_pantry.json()["pantry_lot"]["status"] == "in_stock"

    j = api_client.get("/journal", headers=h, params={"week": _current_iso_week()})
    assert j.status_code == 200
    jb = j.json()
    assert len(jb["days"]) == 7
    assert "macros" in jb
    assert isinstance(jb["cooked_history"], list)


def test_T1_KITCH_06_anonymous_taste_survey_flow(
    api_client: httpx.Client,
    helpers: Any,
) -> None:
    policy_id = helpers.get_policy_version_id("survey")
    create = api_client.post(
        "/survey/respondents",
        json={"policy_version_id": policy_id, "consent": True, "channel": "link"},
    )
    assert create.status_code == 201, f"POST /survey/respondents failed: {create.text}"
    created = create.json()
    rid = created["respondent"]["id"]
    rtok = created["respondent_token"]
    rh = {"X-Respondent-Token": rtok}

    fetched = api_client.get(f"/survey/respondents/{rid}", headers=rh)
    assert fetched.status_code == 200
    assignments = fetched.json()["assignments"]
    assert len(assignments) > 0

    for idx, assignment in enumerate(assignments):
        recipe_id = assignment["recipe_id"]
        rating_val = 4 if idx == 0 else 5
        rate = api_client.put(
            f"/survey/respondents/{rid}/ratings/{recipe_id}",
            headers=rh,
            json={"rating": rating_val, "never_eaten": False},
        )
        assert rate.status_code == 200
        assert rate.json()["rating"] == rating_val
    first_recipe = assignments[0]["recipe_id"]

    fav = api_client.put(
        f"/survey/respondents/{rid}/favorites",
        headers=rh,
        json={"recipe_ids": [first_recipe]},
    )
    assert fav.status_code == 200

    comp = api_client.post(f"/survey/respondents/{rid}/complete", headers=rh)
    assert comp.status_code == 200
    assert comp.json()["completed_at"] is not None


# ============================================================================
# Area 7: Landing Editorial Workbench, Legal/404, App Staging Plate & A11y
# ============================================================================


@pytest.mark.browser
def test_T1_UI_01_landing_dual_mode_workbench(
    base_url: str,
    page_factory: Callable[..., tuple[Any, Page, Any]],
) -> None:
    _, page, telemetry = page_factory(viewport=(1440, 900), color_scheme="light")
    page.goto(f"{base_url}/gioi-thieu/", wait_until="networkidle")

    masthead = page.locator("header.site-masthead").first
    assert masthead.is_visible(), "Expected broadsheet header.site-masthead to be visible"
    masthead_text = masthead.inner_text()
    assert "THỜI BÁO" in masthead_text
    assert "MỸ VỊ" in masthead_text

    # Tab 1: Calorie Breakdown is active by default
    cal_tab = page.locator("#wb-tab-calorie, [data-wb-mode='calorie']").first
    assert cal_tab.count() > 0, "Expected M3 Dual-Mode Workbench Calorie Breakdown tab"
    cal_tab.scroll_into_view_if_needed()
    assert cal_tab.get_attribute("aria-selected") == "true"

    cal_panel = page.locator("[data-testid='landing-calorie-workbench']").first
    assert cal_panel.is_visible()

    pie = page.locator("[data-testid='macro-pie-chart']#cal-macro-pie, [data-testid='macro-pie-chart']").first
    assert pie.is_visible(), "Expected Pure-SVG [data-testid='macro-pie-chart'] visible on #can-bep"
    before_pie_aria = pie.get_attribute("aria-label") or ""
    assert len(before_pie_aria.strip()) > 0
    before_center_kcal = (pie.locator(".pie-center-kcal").text_content() or "").strip()

    before_point = page.locator("#cal-point-text").inner_text()
    before_range = page.locator("#cal-range-text").inner_text()
    page.locator("[data-cal-dish='pho']").first.click()
    page.locator("[data-cal-scale='lon']").first.click()
    page.locator("[data-cal-mod='mo_hanh']").first.click()
    page.wait_for_timeout(100)

    assert "Phở" in page.locator("#cal-dish-title").inner_text()
    after_point = page.locator("#cal-point-text").inner_text()
    after_range = page.locator("#cal-range-text").inner_text()
    assert "kcal" in after_range.lower()
    assert "Phần lớn (1.35×)" in after_point
    assert after_point != before_point and after_range != before_range

    after_pie_aria = pie.get_attribute("aria-label") or ""
    after_center_kcal = (pie.locator(".pie-center-kcal").text_content() or "").strip()
    assert after_pie_aria and after_pie_aria != before_pie_aria
    assert after_center_kcal and after_center_kcal != before_center_kcal
    assert pie.locator(".pie-seg-carb").count() >= 1
    assert pie.locator(".pie-seg-protein").count() >= 1
    assert pie.locator(".pie-seg-lipid").count() >= 1

    c_pct = int(page.locator("#cal-carbs-pct").inner_text().replace("%", "").strip())
    p_pct = int(page.locator("#cal-protein-pct").inner_text().replace("%", "").strip())
    f_pct = int(page.locator("#cal-fat-pct").inner_text().replace("%", "").strip())
    assert c_pct + p_pct + f_pct == 100

    for led_id in (
        "#cal-density-text",
        "#cal-fiber-dv",
        "#cal-fiber-note",
        "#cal-amdr-status",
        "#cal-amdr-insight",
        "#cal-mod-summary",
    ):
        el = page.locator(led_id)
        assert el.count() == 1, f"Expected exact ledger element {led_id}"
        assert el.inner_text().strip() != "", f"Expected non-empty text in {led_id}"

    # Switch to ca_kho_to and dau_phu_non to verify live pie & ledger reactivity
    page.locator("[data-cal-dish='ca_kho_to']").first.click()
    page.wait_for_timeout(80)
    assert "Cá kho tộ" in page.locator("#cal-dish-title").inner_text()
    ca_kcal = (pie.locator(".pie-center-kcal").text_content() or "").strip()
    assert ca_kcal != after_center_kcal
    assert (
        int(page.locator("#cal-carbs-pct").inner_text().replace("%", "").strip())
        + int(page.locator("#cal-protein-pct").inner_text().replace("%", "").strip())
        + int(page.locator("#cal-fat-pct").inner_text().replace("%", "").strip())
    ) == 100

    page.locator("[data-cal-dish='dau_phu_non']").first.click()
    page.wait_for_timeout(80)
    assert "Đậu phụ non" in page.locator("#cal-dish-title").inner_text()
    assert (pie.locator(".pie-center-kcal").text_content() or "").strip() != ca_kcal
    assert page.locator("#cal-amdr-status").inner_text().strip() != ""

    # Switch to Tab 2: Fridge-to-3-Dish Tray Simulator (#bo-gia-lap)
    tray_tab = page.locator("#wb-tab-tray, [data-wb-mode='tray']").first
    assert tray_tab.count() > 0, "Expected M3 Dual-Mode Workbench Tray Simulator tab"
    tray_tab.click()
    page.wait_for_timeout(100)
    assert tray_tab.get_attribute("aria-selected") == "true"

    workbench = page.locator("#bo-gia-lap, [data-testid='landing-tray-simulator']").first
    assert workbench.is_visible()

    before_kcal = page.locator("#sim-kcal").inner_text()
    page.locator("[data-ingredient='pork']").first.click()
    page.locator("[data-servings='4']").first.click()
    page.locator("[data-max-minutes='70']").first.click()
    page.wait_for_timeout(100)
    after_kcal = page.locator("#sim-kcal").inner_text()
    assert "Thịt kho tiêu" in page.locator("#recipe-name").inner_text()
    assert "caramel-pork.webp" in (page.locator("#sim-dish-photo").get_attribute("src") or "")
    assert page.locator("#sim-minutes").inner_text().strip() != ""
    assert page.locator("[data-servings='4']").first.get_attribute("aria-pressed") == "true"
    assert before_kcal != after_kcal or "4 người" in page.locator("#recipe-description").inner_text()

    telemetry.assert_clean(page)


@pytest.mark.browser
def test_T1_UI_02_landing_b11_tagline_reveal_and_screen_tabs(
    base_url: str,
    page_factory: Callable[..., tuple[Any, Page, Any]],
) -> None:
    _, page, telemetry = page_factory(viewport=(1440, 900), color_scheme="light")
    page.goto(f"{base_url}/gioi-thieu/", wait_until="networkidle")

    tab_kho = page.locator("[data-screen-tab='kho']").first
    tab_kho.scroll_into_view_if_needed()
    tab_kho.click()
    assert "kho-" in (page.locator("#device-preview-img").get_attribute("src") or "")

    # Scroll to B11 Tagline Reveal section and verify visibility
    tagline = page.locator("[data-testid='tagline-reveal'], .tagline-reveal, #tagline-reveal").first
    assert tagline.count() > 0, "Expected M3 B11 Tagline Reveal section"
    tagline.scroll_into_view_if_needed()
    page.wait_for_timeout(300)
    assert tagline.is_visible()

    full_text = "\n".join(page.locator("header, main, footer").all_inner_texts())
    assert "MỸ VỊ" in full_text and "Mỹ Vị" in full_text
    assert_no_brand_leak(full_text, context="T1_UI_02:/gioi-thieu/")
    assert_no_ai_separators(full_text, context="T1_UI_02:/gioi-thieu/")

    rubric = evaluate_page_rubric(page, screen_name="landing-desktop", theme="light", surface_mode="landing")
    assert rubric.has_newsreader and rubric.has_be_vietnam_pro
    assert not rubric.has_geist_mono and not rubric.has_manrope
    assert rubric.has_expected_font
    telemetry.assert_clean(page)


@pytest.mark.browser
def test_T1_UI_03_landing_legal_pages_render_with_rubric(
    base_url: str,
    page_factory: Callable[..., tuple[Any, Page, Any]],
) -> None:
    _, page, telemetry = page_factory(viewport=(1440, 900), color_scheme="light")
    for path in ("/gioi-thieu/rieng-tu.html", "/gioi-thieu/dieu-khoan.html"):
        page.goto(f"{base_url}{path}", wait_until="networkidle")
        full_text = "\n".join(page.locator("header, main, footer").all_inner_texts())
        body_text = page.locator("main, body").first.inner_text()
        assert len(body_text.strip()) > 100
        assert "Mỹ Vị" in full_text
        assert "MỸ VỊ" in full_text
        if path.endswith("rieng-tu.html"):
            assert "30 ngày" not in full_text, "Stale '30 ngày' claim must not appear on rieng-tu.html"
        assert_no_banned_copy(full_text, context=path)
        assert_no_prose_hyphens(full_text, context=path)
        assert_no_brand_leak(full_text, context=path)
        assert_no_ai_separators(full_text, context=path)
        rubric = evaluate_page_rubric(page, screen_name=path, theme="light", surface_mode="landing")
        assert rubric.has_newsreader and rubric.has_be_vietnam_pro and not rubric.has_geist_mono
    telemetry.assert_clean(page)


@pytest.mark.browser
def test_T1_UI_04_app_web_login_httponly_cookie_and_navigation(
    base_url: str,
    page_factory: Callable[..., tuple[Any, Page, Any]],
    session_consented_user: dict[str, Any],
) -> None:
    ctx, page, telemetry = page_factory(viewport=(1440, 900), color_scheme="light")
    page.goto(f"{base_url}/dang-nhap", wait_until="networkidle")
    page.get_by_test_id("login-email").wait_for(state="visible", timeout=15000)
    login_text = page.locator("body").inner_text()
    assert "Mỹ Vị" in login_text
    assert_no_brand_leak(login_text, context="T1_UI_04:/dang-nhap")
    assert_no_ai_separators(login_text, context="T1_UI_04:/dang-nhap")

    page.get_by_test_id("login-email").fill(session_consented_user["_email"])
    page.get_by_test_id("login-password").fill(session_consented_user["_password"])
    page.get_by_test_id("login-submit").click()

    page.wait_for_url(re.compile(r"/(bep|onboarding)"), timeout=20000)

    # Verify M1+M4 HttpOnly cookie contract: zero refresh tokens in Web Storage
    storage_dump = page.evaluate(
        "() => JSON.stringify({ls: Object.entries(localStorage), ss: Object.entries(sessionStorage)})"
    )
    assert "refresh_token" not in storage_dump.lower()
    assert "tastoria_refresh" not in storage_dump.lower()

    cookies = ctx.cookies()
    refresh_cookies = [c for c in cookies if c["name"] == "tastoria_refresh"]
    assert refresh_cookies, "Expected HttpOnly tastoria_refresh cookie after web login"
    assert refresh_cookies[0]["httpOnly"] is True

    # Verify 5-item streamlined sidebar + utility items & retired kham-pha sidebar entry
    page.get_by_test_id("desktop-sidebar-rail").wait_for(state="visible", timeout=15000)
    bep_text = page.locator("body").inner_text()
    assert "Mỹ Vị" in bep_text
    assert_no_brand_leak(bep_text, context="T1_UI_04:/bep")
    assert_no_ai_separators(bep_text, context="T1_UI_04:/bep")

    for nav_tid in (
        "sidebar-nav-bep",
        "sidebar-nav-quet",
        "sidebar-nav-mam",
        "sidebar-nav-kho",
        "sidebar-nav-nhat-ky",
        "sidebar-nav-di-cho",
        "sidebar-nav-cai-dat",
    ):
        assert page.get_by_test_id(nav_tid).is_visible(), f"Expected sidebar nav {nav_tid} visible"
    assert page.get_by_test_id("sidebar-nav-kham-pha").count() == 0, "Retired sidebar-nav-kham-pha must not render"

    # Navigate /bep -> home-open-explore-desktop -> /kham-pha -> explore-recipe-card -> /mon/[id]
    explore_btn = page.get_by_test_id("home-open-explore-desktop")
    explore_btn.wait_for(state="visible", timeout=15000)
    explore_btn.click()
    page.get_by_test_id("screen-explore").wait_for(state="visible", timeout=15000)

    first_card = page.get_by_test_id("explore-recipe-card").first
    first_card.wait_for(state="visible", timeout=15000)
    assert page.evaluate(
        """() => {
          const imgs = document.querySelectorAll('[data-testid="explore-recipe-card"] img');
          return Array.from(imgs).some(i => i.complete && i.naturalWidth > 0);
        }"""
    ), "Expected real dish <img> with naturalWidth > 0 on /kham-pha"

    first_card.click()
    page.get_by_test_id("screen-recipe").wait_for(state="visible", timeout=15000)
    assert page.evaluate(
        """() => {
          const imgs = document.querySelectorAll('[data-testid="screen-recipe"] img');
          return Array.from(imgs).some(i => i.complete && i.naturalWidth > 0);
        }"""
    ), "Expected real hero <img> with naturalWidth > 0 on /mon/[id]"
    page.get_by_test_id("macro-pie-chart").wait_for(state="visible", timeout=15000)
    page.get_by_test_id("macro-nutrition-ledger").wait_for(state="visible", timeout=15000)
    recipe_text = page.get_by_test_id("screen-recipe").inner_text()
    assert "Tài liệu nội bộ" not in recipe_text
    assert "Chi tiết dinh dưỡng mỗi người" not in recipe_text
    assert_no_brand_leak(recipe_text, context="T1_UI_04:/mon/[id]")

    for route, tid in (("/kho", "screen-pantry"), ("/mam", "screen-tray"), ("/nhat-ky", "screen-journal")):
        page.goto(f"{base_url}{route}", wait_until="networkidle")
        page.get_by_test_id(tid).wait_for(state="visible", timeout=15000)
    telemetry.assert_clean(page)


@pytest.mark.browser
def test_T1_UI_05_app_staging_plate_estimate_and_vn_modifier(
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
    page.get_by_test_id("calorie-search-input").wait_for(state="visible", timeout=15000)

    # Verify "Trà sữa" quick-pick is visible and NOT clipped horizontally
    tra_sua = page.locator("[role='button']", has_text="Trà sữa").first
    assert tra_sua.is_visible(), "Expected 'Trà sữa' quick-pick visible on /quet?tab=calorie"
    tra_sua_metrics = tra_sua.evaluate(
        """el => {
          const r = el.getBoundingClientRect();
          const child = el.firstElementChild;
          return {
            width: r.width,
            scrollWidth: el.scrollWidth,
            clientWidth: el.clientWidth,
            childScrollWidth: child ? child.scrollWidth : el.scrollWidth,
            childClientWidth: child ? child.clientWidth : el.clientWidth,
          };
        }"""
    )
    assert tra_sua_metrics["width"] >= 45
    assert tra_sua_metrics["scrollWidth"] <= tra_sua_metrics["clientWidth"] + 1
    assert tra_sua_metrics["childScrollWidth"] <= tra_sua_metrics["childClientWidth"] + 1

    page.get_by_test_id("calorie-search-input").fill("Cơm tấm")
    page.get_by_test_id("calorie-estimate-btn").click()
    card = page.get_by_test_id("calorie-result-card")
    card.wait_for(state="visible", timeout=15000)
    page.get_by_test_id("plate-portion-selector").wait_for(state="visible", timeout=10000)
    page.get_by_test_id("plate-modifiers").wait_for(state="visible", timeout=10000)
    pie = card.get_by_test_id("macro-pie-chart")
    ledger = card.get_by_test_id("macro-nutrition-ledger")
    pie.wait_for(state="visible", timeout=10000)
    ledger.wait_for(state="visible", timeout=10000)
    assert pie.locator("circle").count() >= 2

    before_text = card.inner_text()
    before_ledger = ledger.inner_text()
    assert_no_banned_copy(before_text, context="Staging Plate card")

    # Toggle a 1-tap VN oil/sauce modifier row (M4 Staging Plate)
    mod_chip = page.locator("[data-testid^='modifier-']").first
    assert mod_chip.count() > 0, "Expected M4 Staging Plate 1-tap VN modifier row ([data-testid^='modifier-'])"
    mod_chip.click()
    page.wait_for_timeout(150)
    after_mod_text = card.inner_text()
    after_mod_ledger = ledger.inner_text()
    assert before_text != after_mod_text
    assert before_ledger != after_mod_ledger

    # Select "Lớn 1.35×" in plate-portion-selector and verify live update
    page.get_by_test_id("plate-portion-selector").get_by_text("Lớn 1.35×").click()
    page.wait_for_function(
        """(prev) => {
          const el = document.querySelector('[data-testid="macro-nutrition-ledger"]');
          return el && el.innerText !== prev;
        }""",
        arg=after_mod_ledger,
        timeout=10000,
    )
    assert card.inner_text() != after_mod_text
    telemetry.assert_clean(page)


@pytest.mark.browser
def test_T1_UI_06_app_staging_plate_log_to_journal_cta(
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
    # T5-1 UI regression: click the first quick-pick chip "Phở" and verify it resolves to Phở (>= 350 kcal), NOT Canh bí đỏ đậu phộng
    page.get_by_role("button", name="Phở", exact=True).click()
    result_card = page.get_by_test_id("calorie-result-card")
    result_card.wait_for(state="visible", timeout=15000)
    card_text = result_card.inner_text()
    assert "Phở" in card_text, f"Quick-pick 'Phở' did not display Phở: {card_text}"
    assert "Canh bí đỏ đậu phộng" not in card_text, f"Quick-pick 'Phở' hijacked: {card_text}"
    kcal_match = re.search(r"(\d+(?:\.\d+)?)\s*kcal", card_text)
    assert kcal_match is not None and float(kcal_match.group(1)) >= 350.0, f"Expected >= 350 kcal for Phở: {card_text}"

    log_cta = page.get_by_test_id("calorie-log-to-journal")
    assert log_cta.count() > 0, "Expected M4 1-tap 'Ghi vào Nhật ký hôm nay' CTA (calorie-log-to-journal)"
    log_cta.click()
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
    assert "Phở" in quick_logs_text
    assert re.search(r"[1-9]\d*\s*kcal", quick_logs_text), f"Expected positive logged kcal in quick logs: {quick_logs_text}"
    telemetry.assert_clean(page)


def test_T1_UI_07_wcag_contrast_script_exits_zero() -> None:
    script = Path(REPO_ROOT) / "app" / "scripts" / "contrast.py"
    assert script.is_file()
    proc = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, f"contrast.py failed ({proc.returncode}):\n{proc.stdout}\n{proc.stderr}"
    assert "FAIL" not in proc.stdout
