"""Tier 2: Boundary, corner-case, security, and negative/error-handling E2E tests (42 tests)."""

from __future__ import annotations

import http.client
import io
import re
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx
import pytest
from playwright.sync_api import Page

from fixtures import (
    get_app_food_asset,
    get_produce_scan_jpeg,
    make_corrupt_jpeg_bytes,
    make_dish_jpeg,
    make_oversized_jpeg,
    make_oversized_pixels_jpeg,
    make_oversized_pixels_png,
    make_spoofed_pdf_bytes,
    make_valid_png_bytes,
)
from rubric import (
    assert_barcode_copy_clean,
    assert_light_parchment_locked,
    assert_no_ai_separators,
    assert_no_banned_copy,
    assert_no_brand_leak,
    assert_no_prose_hyphens,
    evaluate_page_rubric,
)

pytestmark = pytest.mark.tier2


def _auth_headers(token: str, *, idem: str | None = None) -> dict[str, str]:
    h = {"Authorization": f"Bearer {token}"}
    if idem:
        h["Idempotency-Key"] = idem
    return h


def _assert_problem_json(resp: httpx.Response, expected_status: int, expected_code: str | None = None) -> dict[str, Any]:
    assert resp.status_code == expected_status, f"Expected {expected_status}, got {resp.status_code}: {resp.text}"
    assert "application/problem+json" in resp.headers.get("content-type", "").lower()
    body = resp.json()
    assert body["status"] == expected_status
    if expected_code is not None:
        assert body["code"] == expected_code, f"Expected code={expected_code}, got {body}"
    return body


# ============================================================================
# Area 1: Infra & Nginx Boundary / Negative Cases (T2-INF-01..06)
# ============================================================================


def test_T2_INF_01_internal_protected_prefix_returns_404(raw_client: httpx.Client) -> None:
    for path in ("/_protected/anything", "/_protected/scans/test.jpg", "/_protected/"):
        resp = raw_client.get(path)
        assert resp.status_code == 404, f"Expected 404 on internal route {path}, got {resp.status_code}"


def test_T2_INF_02_custom_404_on_unknown_landing_paths(raw_client: httpx.Client) -> None:
    p404 = raw_client.get("/gioi-thieu/404.html")
    assert p404.status_code == 404, f"Expected 404 on internal /gioi-thieu/404.html, got {p404.status_code}"
    assert "text/html" in p404.headers.get("content-type", "").lower()
    assert "Mỹ Vị" in p404.text and "MỸ VỊ" in p404.text
    assert "Tastoria" not in p404.text

    for bad_path in ("/gioi-thieu/khong-ton-tai", "/gioi-thieu/nginx-snippet.conf", "/gioi-thieu/docs/secret"):
        resp = raw_client.get(bad_path)
        assert resp.status_code == 404, f"Expected 404 on {bad_path}, got {resp.status_code}"
        assert "text/html" in resp.headers.get("content-type", "").lower()
        assert "Mỹ Vị" in resp.text and "MỸ VỊ" in resp.text
        assert "Tastoria" not in resp.text


def test_T2_INF_03_disallowed_download_paths_and_traversal(raw_client: httpx.Client) -> None:
    for bad in (
        "/tai-ve/tastoria-vp-kit.zip",
        "/tai-ve/unknown.apk",
        "/tai-ve/a/../tastoria-vp-kit.zip",
        "/gioi-thieu/img/paper-bg-dark.webp",
    ):
        resp = raw_client.get(bad)
        assert resp.status_code == 404, f"Expected 404 on {bad}, got {resp.status_code}"

    # Send raw unnormalized traversal paths without client-side URL normalization (httpx strips ..).
    parsed = urlsplit(str(raw_client.base_url))
    assert parsed.hostname, f"Invalid base_url: {raw_client.base_url}"
    base_path = parsed.path.rstrip("/")
    conn_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    for traversal_path in ("/tai-ve/../../etc/passwd", "/tai-ve/..%2f..%2fetc/passwd"):
        conn = conn_cls(parsed.hostname, parsed.port, timeout=15.0)
        try:
            conn.request("GET", f"{base_path}{traversal_path}")
            raw_resp = conn.getresponse()
            body = raw_resp.read()
        finally:
            conn.close()
        assert raw_resp.status in (400, 403, 404), (
            f"Expected 400/403/404 on raw traversal {traversal_path}, got {raw_resp.status}"
        )
        assert b"root:" not in body, f"Unexpected /etc/passwd leak on {traversal_path}"


def test_T2_INF_04_strict_csp_zero_inline_scripts_and_styles_on_landing(
    raw_client: httpx.Client,
) -> None:
    for path in ("/gioi-thieu/", "/gioi-thieu/rieng-tu.html", "/gioi-thieu/dieu-khoan.html"):
        resp = raw_client.get(path)
        assert resp.status_code == 200
        html = resp.text
        # Find every <script ...> tag that is NOT external (src=) and NOT a non-executable JSON payload
        for m in re.finditer(r"<script\b([^>]*)>", html, flags=re.IGNORECASE):
            attrs = m.group(1)
            attrs_lower = attrs.lower()
            if "src=" in attrs_lower:
                continue
            if re.search(r"""\btype\s*=\s*(['"]?)application/(?:ld\+)?json\1""", attrs_lower):
                continue
            pytest.fail(f"Found inline <script> on {path} violating strict CSP: <script{attrs}>")
        assert not re.search(r"\sstyle\s*=", html, flags=re.IGNORECASE), (
            f"Found inline style= attribute on {path}"
        )


def test_T2_INF_05_nginx_rejects_oversized_body_over_8mb(
    api_client: httpx.Client,
    session_consented_user: dict[str, Any],
) -> None:
    payload = b"X" * (9 * 1024 * 1024)
    resp = api_client.post(
        "/scans",
        headers=_auth_headers(session_consented_user["access_token"], idem="oversize_nginx_body_key_01"),
        data={"mode": "fridge"},
        files=[("images", ("huge.jpg", payload, "image/jpeg"))],
    )
    assert resp.status_code == 413


def test_T2_INF_06_unknown_api_endpoint_returns_problem_json_404(api_client: httpx.Client) -> None:
    resp = api_client.get("/does-not-exist-e2e-route")
    _assert_problem_json(resp, 404)


# ============================================================================
# Area 2: Identity & Auth Edge Cases (T2-AUTH-01..06)
# ============================================================================


def test_T2_AUTH_01_duplicate_invalid_email_and_weak_password(
    api_client: httpx.Client,
    session_native_user: dict[str, Any],
) -> None:
    dup = api_client.post(
        "/auth/register",
        json={"email": session_native_user["_email"], "password": session_native_user["_password"]},
    )
    _assert_problem_json(dup, 409, "email_taken")

    bad_email = api_client.post(
        "/auth/register",
        json={"email": "not-an-email", "password": "valid-password-123"},
    )
    _assert_problem_json(bad_email, 422, "invalid_email")

    weak = api_client.post(
        "/auth/register",
        json={"email": f"weak+{uuid.uuid4().hex[:8]}@example.com", "password": "123"},
    )
    _assert_problem_json(weak, 422, "weak_password")


def test_T2_AUTH_02_refresh_token_reuse_revokes_entire_family(
    api_client: httpx.Client,
    helpers: Any,
    pooled_auth_lifecycle_user: dict[str, Any],
) -> None:
    user = helpers.login_user(pooled_auth_lifecycle_user["_email"], pooled_auth_lifecycle_user["_password"])
    old_refresh = user["refresh_token"]

    r1 = api_client.post("/auth/refresh", json={"refresh_token": old_refresh})
    assert r1.status_code == 200
    new_refresh = r1.json()["refresh_token"]

    # Within the 10s cross-tab grace window, replay returns 409 refresh_retry_conflict without revoking the family
    grace_replay = api_client.post("/auth/refresh", json={"refresh_token": old_refresh})
    _assert_problem_json(grace_replay, 409, "refresh_retry_conflict")

    r2 = api_client.post("/auth/refresh", json={"refresh_token": new_refresh})
    assert r2.status_code == 200
    new_refresh_2 = r2.json()["refresh_token"]

    # After the 10s grace window expires, replaying the revoked token revokes the entire family
    time.sleep(10.5)
    replay = api_client.post("/auth/refresh", json={"refresh_token": old_refresh})
    _assert_problem_json(replay, 401, "refresh_reused")

    # Newly rotated token in the same family must now be revoked too
    r_new = api_client.post("/auth/refresh", json={"refresh_token": new_refresh_2})
    assert r_new.status_code == 401


def test_T2_AUTH_03_extra_forbidden_fields_and_missing_bearer(
    api_client: httpx.Client,
    session_native_user: dict[str, Any],
) -> None:
    extra = api_client.post(
        "/auth/login",
        json={
            "email": session_native_user["_email"],
            "password": session_native_user["_password"],
            "role": "admin",
        },
    )
    _assert_problem_json(extra, 400, "validation_error")

    unauth = api_client.get("/me/profile")
    _assert_problem_json(unauth, 401, "unauthenticated")


def test_T2_AUTH_04_account_deletion_pending_blocks_login_and_refresh(
    api_client: httpx.Client,
    fresh_user_factory: Callable[..., dict[str, Any]],
) -> None:
    user = fresh_user_factory()
    token = user["access_token"]
    req = api_client.post(
        "/me/data-requests",
        headers=_auth_headers(token),
        json={"type": "delete", "password": user["_password"]},
    )
    assert req.status_code in (200, 202)

    login = api_client.post(
        "/auth/login",
        json={"email": user["_email"], "password": user["_password"]},
    )
    _assert_problem_json(login, 403, "account_deletion_pending")

    ref = api_client.post("/auth/refresh", json={"refresh_token": user["refresh_token"]})
    _assert_problem_json(ref, 403, "account_deletion_pending")


def test_T2_AUTH_05_password_reset_confirm_invalid_token_and_weak_password(api_client: httpx.Client) -> None:
    bad_tok = api_client.post(
        "/auth/password-reset/confirm",
        json={"token": "invalid-reset-token-000", "new_password": "strong-password-999"},
    )
    assert bad_tok.status_code in (400, 422)
    assert bad_tok.json()["code"] == "reset_token_invalid"

    weak_pw = api_client.post(
        "/auth/password-reset/confirm",
        json={"token": "invalid-reset-token-000", "new_password": "123"},
    )
    assert weak_pw.status_code in (400, 422)
    assert weak_pw.json()["code"] in ("weak_password", "reset_token_invalid")


def test_T2_AUTH_06_login_bruteforce_lockout_returns_429(
    api_client: httpx.Client,
    fresh_user_factory: Callable[..., dict[str, Any]],
) -> None:
    # Scoped to a dedicated fresh user email so session users are never locked out
    victim = fresh_user_factory()
    locked_resp: httpx.Response | None = None
    for _ in range(10):
        resp = api_client.post(
            "/auth/login",
            json={"email": victim["_email"], "password": "wrong-password-123"},
        )
        if resp.status_code == 429:
            locked_resp = resp
            break
        assert resp.status_code == 401

    assert locked_resp is not None, "Expected 429 login_locked after repeated failed login attempts"
    assert locked_resp.json()["code"] in ("login_locked", "rate_limited")
    assert "retry-after" in {k.lower() for k in locked_resp.headers.keys()}


# ============================================================================
# Area 3: Profile & Privacy Boundary Cases (T2-PRIV-01..05)
# ============================================================================


def test_T2_PRIV_01_profile_update_requires_health_profile_consent(
    api_client: httpx.Client,
    session_native_user: dict[str, Any],
) -> None:
    resp = api_client.put(
        "/me/profile",
        headers=_auth_headers(session_native_user["access_token"]),
        json={
            "sex": "female",
            "birth_year": 1995,
            "height_cm": 160.0,
            "weight_kg": 54.0,
            "activity_level": "light",
            "goal": "maintain",
            "adult_confirmed": False,
        },
    )
    _assert_problem_json(resp, 403, "consent_required")


def test_T2_PRIV_02_minor_age_and_adult_confirmation_checks(
    api_client: httpx.Client,
    helpers: Any,
    pooled_auth_lifecycle_user: dict[str, Any],
) -> None:
    user = helpers.login_user(pooled_auth_lifecycle_user["_email"], pooled_auth_lifecycle_user["_password"])
    token = user["access_token"]
    helpers.grant_consents(token, purposes=("health_profile",))
    year_now = datetime.now(timezone.utc).year

    minor = api_client.put(
        "/me/profile",
        headers=_auth_headers(token),
        json={
            "sex": "male",
            "birth_year": year_now - 15,
            "height_cm": 165.0,
            "weight_kg": 55.0,
            "activity_level": "moderate",
            "goal": "maintain",
            "adult_confirmed": False,
        },
    )
    _assert_problem_json(minor, 422, "age_below_minimum")

    borderline = api_client.put(
        "/me/profile",
        headers=_auth_headers(token),
        json={
            "sex": "male",
            "birth_year": year_now - 18,
            "height_cm": 170.0,
            "weight_kg": 62.0,
            "activity_level": "moderate",
            "goal": "maintain",
            "adult_confirmed": False,
        },
    )
    _assert_problem_json(borderline, 422, "age_confirmation_required")


def test_T2_PRIV_03_energy_target_below_floor_requires_confirmation(
    api_client: httpx.Client,
    session_consented_user: dict[str, Any],
) -> None:
    resp = api_client.put(
        "/me/energy-target",
        headers=_auth_headers(session_consented_user["access_token"]),
        json={"kcal_target": 850, "kcal_source": "user", "goal": "lose", "confirm_below_floor": False},
    )
    _assert_problem_json(resp, 409, "below_floor_confirmation_required")


def test_T2_PRIV_04_favorites_limit_unknown_code_and_outdated_policy(
    api_client: httpx.Client,
    session_consented_user: dict[str, Any],
) -> None:
    h = _auth_headers(session_consented_user["access_token"])
    recs = api_client.get("/recipes", headers=h, params={"limit": 10}).json()["items"]
    six_ids = [r["id"] for r in recs[:6]]
    fav = api_client.put("/me/favorites", headers=h, json={"recipe_ids": six_ids})
    _assert_problem_json(fav, 422, "favorites_limit")

    bad_alg = api_client.put("/me/allergens", headers=h, json={"allergen_codes": ["nonexistent_allergen_xyz"]})
    _assert_problem_json(bad_alg, 422, "unknown_code")

    bad_pol = api_client.post(
        "/me/consents",
        headers=h,
        json={"channel": "settings", "decisions": [{"policy_version_id": str(uuid.uuid4()), "action": "grant"}]},
    )
    _assert_problem_json(bad_pol, 422, "purpose_not_allowed")


def test_T2_PRIV_05_dsr_wrong_password_and_missing_correct_note(
    api_client: httpx.Client,
    session_consented_user: dict[str, Any],
) -> None:
    h = _auth_headers(session_consented_user["access_token"])
    bad_del = api_client.post("/me/data-requests", headers=h, json={"type": "delete", "password": "wrong-password"})
    assert bad_del.status_code in (401, 403)
    assert bad_del.json()["code"] == "reauth_failed"

    no_note = api_client.post("/me/data-requests", headers=h, json={"type": "correct", "note": None})
    _assert_problem_json(no_note, 422, "invalid_request")


# ============================================================================
# Area 4: Meal Calorie & Barcode Boundary Cases (T2-CAL-01..07)
# ============================================================================


def test_T2_CAL_01_oversized_image_over_3mb_returns_413(
    api_client: httpx.Client,
    session_consented_user: dict[str, Any],
) -> None:
    resp = api_client.post(
        "/meal-calorie/estimate",
        headers=_auth_headers(session_consented_user["access_token"]),
        files={"image": ("oversized.jpg", make_oversized_jpeg(), "image/jpeg")},
        data={"portion": "vua"},
    )
    _assert_problem_json(resp, 413, "image_too_large")


def test_T2_CAL_02_oversized_pixel_dimensions_return_422(
    api_client: httpx.Client,
    session_consented_user: dict[str, Any],
) -> None:
    resp = api_client.post(
        "/meal-calorie/estimate",
        headers=_auth_headers(session_consented_user["access_token"]),
        files={"image": ("huge_pixels.png", make_oversized_pixels_png(), "image/png")},
        data={"portion": "vua"},
    )
    _assert_problem_json(resp, 422, "image_too_many_pixels")


def test_T2_CAL_03_invalid_media_bytes_return_415(
    api_client: httpx.Client,
    session_consented_user: dict[str, Any],
) -> None:
    h = _auth_headers(session_consented_user["access_token"])
    pdf_resp = api_client.post(
        "/meal-calorie/estimate",
        headers=h,
        files={"image": ("fake.jpg", make_spoofed_pdf_bytes(), "image/jpeg")},
        data={"portion": "vua"},
    )
    _assert_problem_json(pdf_resp, 415, "unsupported_media_type")

    corrupt_resp = api_client.post(
        "/meal-calorie/estimate",
        headers=h,
        files={"image": ("corrupt.jpg", make_corrupt_jpeg_bytes(), "image/jpeg")},
        data={"portion": "vua"},
    )
    _assert_problem_json(corrupt_resp, 415, "unsupported_media_type")


def test_T2_CAL_04_empty_request_and_unknown_dish_slug(
    api_client: httpx.Client,
    session_consented_user: dict[str, Any],
) -> None:
    h = _auth_headers(session_consented_user["access_token"])
    empty = api_client.post("/meal-calorie/estimate", headers=h, data={"portion": "vua"})
    _assert_problem_json(empty, 422, "validation_error")

    unk = api_client.post("/meal-calorie/estimate", headers=h, data={"dish_slug": "nonexistent_dish_slug_999"})
    assert unk.status_code in (404, 422)


def test_T2_CAL_05_low_margin_ambiguous_dish_triggers_disambiguation(
    api_client: httpx.Client,
    session_consented_user: dict[str, Any],
) -> None:
    h = _auth_headers(session_consented_user["access_token"])
    # Check silken-tofu.webp (or fallback synthetic dish image) for M2 low-margin disambiguation contract
    silken = api_client.post(
        "/meal-calorie/estimate",
        headers=h,
        files={"image": ("silken-tofu.webp", get_app_food_asset("silken-tofu.webp"), "image/webp")},
        data={"portion": "vua"},
    )
    assert silken.status_code == 200
    body = silken.json()
    assert "disambiguation_required" in body
    assert "top_margin" in body
    if body["disambiguation_required"]:
        assert (
            (body["top_margin"] is not None and body["top_margin"] < 0.15)
            or (body["recognized_confidence"] is not None and body["recognized_confidence"] < 0.55)
            or len(body["top_candidates"]) >= 2
        )
        assert len(body["top_candidates"]) >= 2
    else:
        # Probe synthetic OOD dish image which must have low top1 confidence < 0.55
        ood = api_client.post(
            "/meal-calorie/estimate",
            headers=h,
            files={"image": ("ood.jpg", make_dish_jpeg(), "image/jpeg")},
            data={"portion": "vua"},
        )
        assert ood.status_code == 200
        ob = ood.json()
        assert ob["disambiguation_required"] is True, (
            f"Expected disambiguation_required=True on silken-tofu.webp or ambiguous OOD image: silken={body}, ood={ob}"
        )


def test_T2_CAL_06_malformed_and_unknown_barcode_and_no_banned_strings(
    api_client: httpx.Client,
    session_consented_user: dict[str, Any],
) -> None:
    h = _auth_headers(session_consented_user["access_token"])
    malformed = api_client.get("/meal-calorie/barcode/abc", headers=h)
    _assert_problem_json(malformed, 422, "validation_error")

    missing = api_client.get("/meal-calorie/barcode/0000000000000", headers=h)
    _assert_problem_json(missing, 404, "not_found")

    ok = api_client.get("/meal-calorie/barcode/8934563138165", headers=h)
    assert ok.status_code == 200, f"Expected 200 for local VN barcode 8934563138165, got {ok.status_code}: {ok.text}"
    assert_barcode_copy_clean(ok.json(), context="T2-CAL-06 barcode")


def test_T2_CAL_07_meal_calorie_estimate_rate_limit_429(
    api_client: httpx.Client,
    helpers: Any,
    pooled_burst_user: dict[str, Any],
) -> None:
    # Isolated pooled burst user so burst does not affect session_consented_user
    user = helpers.login_user(pooled_burst_user["_email"], pooled_burst_user["_password"])
    h = _auth_headers(user["access_token"])
    hit_429: httpx.Response | None = None
    for _ in range(45):
        r = api_client.post("/meal-calorie/estimate", headers=h, data={"dish_slug": "dau_phu_non", "portion": "vua"})
        if r.status_code == 429:
            hit_429 = r
            break
        assert r.status_code == 200
    assert hit_429 is not None, "Expected 429 rate_limited on burst POST /meal-calorie/estimate"
    assert hit_429.json()["code"] == "rate_limited"


# ============================================================================
# Area 5: Ingredient Scan & Mushroom Boundary Cases (T2-SCAN-01..05)
# ============================================================================


def test_T2_SCAN_01_idempotency_key_missing_invalid_and_reused(
    api_client: httpx.Client,
    helpers: Any,
    session_consented_user: dict[str, Any],
) -> None:
    token = session_consented_user["access_token"]
    jpg = get_produce_scan_jpeg()

    no_key = api_client.post(
        "/scans",
        headers=_auth_headers(token),
        data={"mode": "fridge"},
        files=[("images", ("a.jpg", jpg, "image/jpeg"))],
    )
    _assert_problem_json(no_key, 400, "idempotency_key_required")

    short_key = api_client.post(
        "/scans",
        headers=_auth_headers(token, idem="short"),
        data={"mode": "fridge"},
        files=[("images", ("a.jpg", jpg, "image/jpeg"))],
    )
    _assert_problem_json(short_key, 400, "validation_error")

    idem = helpers.create_idempotency_key("reuse")
    r1 = api_client.post(
        "/scans",
        headers=_auth_headers(token, idem=idem),
        data={"mode": "fridge"},
        files=[("images", ("a.jpg", jpg, "image/jpeg"))],
    )
    assert r1.status_code == 202

    r2 = api_client.post(
        "/scans",
        headers=_auth_headers(token, idem=idem),
        data={"mode": "haul"},
        files=[("images", ("b.png", make_valid_png_bytes(), "image/png"))],
    )
    _assert_problem_json(r2, 422, "idempotency_key_reused")


def test_T2_SCAN_02_scan_upload_size_pixel_count_and_media_errors(
    api_client: httpx.Client,
    helpers: Any,
    session_consented_user: dict[str, Any],
) -> None:
    token = session_consented_user["access_token"]
    png = make_valid_png_bytes()

    three = api_client.post(
        "/scans",
        headers=_auth_headers(token, idem=helpers.create_idempotency_key("three")),
        data={"mode": "fridge"},
        files=[
            ("images", ("1.png", png, "image/png")),
            ("images", ("2.png", png, "image/png")),
            ("images", ("3.png", png, "image/png")),
        ],
    )
    assert three.status_code in (400, 422)

    too_big = api_client.post(
        "/scans",
        headers=_auth_headers(token, idem=helpers.create_idempotency_key("big")),
        data={"mode": "fridge"},
        files=[("images", ("big.jpg", make_oversized_jpeg(), "image/jpeg"))],
    )
    _assert_problem_json(too_big, 413, "image_too_large")

    too_px = api_client.post(
        "/scans",
        headers=_auth_headers(token, idem=helpers.create_idempotency_key("px")),
        data={"mode": "fridge"},
        files=[("images", ("px.jpg", make_oversized_pixels_jpeg(), "image/jpeg"))],
    )
    _assert_problem_json(too_px, 422, "image_too_many_pixels")

    pdf = api_client.post(
        "/scans",
        headers=_auth_headers(token, idem=helpers.create_idempotency_key("pdf")),
        data={"mode": "fridge"},
        files=[("images", ("bad.jpg", make_spoofed_pdf_bytes(), "image/jpeg"))],
    )
    _assert_problem_json(pdf, 415, "unsupported_media_type")


def test_T2_SCAN_03_confirm_missing_qty_level_returns_422(
    api_client: httpx.Client,
    helpers: Any,
    session_consented_user: dict[str, Any],
) -> None:
    token = session_consented_user["access_token"]
    h = _auth_headers(token)
    scan = helpers.submit_and_poll_scan(token, make_valid_png_bytes(320, 240), filename="blank.png", content_type="image/png")
    assert scan["status"] == "done"

    for it in scan["items"]:
        if it.get("needs_check") and it.get("user_freshness") is None:
            p_fresh = api_client.patch(
                f"/scans/{scan['id']}/items/{it['id']}",
                headers={**h, "Content-Type": "application/merge-patch+json"},
                json={"user_freshness": "tuoi"},
            )
            assert p_fresh.status_code == 200

    ing_id = helpers.resolve_ingredient_id(token, "rau muống")
    existing = [it for it in scan["items"] if it["ingredient_id"] == ing_id]
    if not existing:
        add = api_client.post(
            f"/scans/{scan['id']}/items",
            headers=h,
            json={"ingredient_id": ing_id, "qty_level": None, "user_freshness": "tuoi"},
        )
        assert add.status_code == 201
    else:
        p_none = api_client.patch(
            f"/scans/{scan['id']}/items/{existing[0]['id']}",
            headers={**h, "Content-Type": "application/merge-patch+json"},
            json={"qty_level": None, "user_freshness": "tuoi"},
        )
        assert p_none.status_code == 200

    conf = api_client.post(f"/scans/{scan['id']}/confirm", headers=h, json={})
    _assert_problem_json(conf, 422, "qty_level_required")


def test_T2_SCAN_04_edit_after_discard_and_future_purchase_date(
    api_client: httpx.Client,
    helpers: Any,
    session_consented_user: dict[str, Any],
) -> None:
    token = session_consented_user["access_token"]
    h = _auth_headers(token)
    scan = helpers.submit_and_poll_scan(token, get_produce_scan_jpeg(), mode="haul")
    ing_id = helpers.resolve_ingredient_id(token, "hành lá")

    future_date = (date.today() + timedelta(days=2)).isoformat()
    if not any(it["ingredient_id"] == ing_id for it in scan["items"]):
        add = api_client.post(
            f"/scans/{scan['id']}/items",
            headers=h,
            json={"ingredient_id": ing_id, "qty_level": "vua", "user_freshness": "tuoi"},
        )
        assert add.status_code == 201
    for it in scan["items"]:
        patch_body: dict[str, Any] = {"user_freshness": "tuoi"}
        if it.get("final_count") is None and it.get("qty_level") is None:
            patch_body["qty_level"] = "vua"
        p_resp = api_client.patch(
            f"/scans/{scan['id']}/items/{it['id']}",
            headers={**h, "Content-Type": "application/merge-patch+json"},
            json=patch_body,
        )
        assert p_resp.status_code == 200
    fut = api_client.post(f"/scans/{scan['id']}/confirm", headers=h, json={"purchase_date": future_date})
    _assert_problem_json(fut, 422, "acquired_at_in_future")

    disc = api_client.post(f"/scans/{scan['id']}/discard", headers=h)
    assert disc.status_code == 200

    edit_after = api_client.post(
        f"/scans/{scan['id']}/items",
        headers=h,
        json={"ingredient_id": ing_id, "qty_level": "it"},
    )
    _assert_problem_json(edit_after, 409, "scan_not_editable")


def test_T2_SCAN_05_ood_mushroom_fallback_and_scan_rate_limit(
    api_client: httpx.Client,
    helpers: Any,
    pooled_burst_user: dict[str, Any],
) -> None:
    user = helpers.login_user(pooled_burst_user["_email"], pooled_burst_user["_password"])
    token = user["access_token"]

    # Non-mushroom solid PNG should complete cleanly without crashing mushroom sub-classifier
    scan = helpers.submit_and_poll_scan(
        token,
        make_valid_png_bytes(256, 256),
        filename="solid.png",
        content_type="image/png",
        mode="fridge",
    )
    assert scan["status"] == "done"

    # Burst POST /scans on isolated user -> 429 rate_limited
    jpg = get_produce_scan_jpeg()
    hit_429: httpx.Response | None = None
    for i in range(30):
        r = api_client.post(
            "/scans",
            headers=_auth_headers(token, idem=helpers.create_idempotency_key(f"rl{i}")),
            data={"mode": "fridge"},
            files=[("images", ("p.jpg", jpg, "image/jpeg"))],
        )
        if r.status_code == 429:
            hit_429 = r
            break
    assert hit_429 is not None, "Expected 429 rate_limited on burst POST /scans"
    assert hit_429.json()["code"] == "rate_limited"


# ============================================================================
# Area 6: Pantry, Meal, Cooking, Journal, Survey Boundary Cases (T2-KITCH-01..06)
# ============================================================================


def test_T2_KITCH_01_invalid_pantry_quantities_rejected(
    api_client: httpx.Client,
    helpers: Any,
    session_consented_user: dict[str, Any],
) -> None:
    token = session_consented_user["access_token"]
    h = _auth_headers(token)
    ing_id = helpers.resolve_ingredient_id(token, "cà chua")

    r1 = api_client.post("/pantry/lots", headers=h, json={"ingredient_id": ing_id, "quantity": {"g_min": 500, "g_max": 100}})
    assert r1.status_code == 422

    r2 = api_client.post("/pantry/lots", headers=h, json={"ingredient_id": ing_id, "quantity": {"g_min": -5, "g_max": 10}})
    assert r2.status_code == 422

    r3 = api_client.post("/pantry/lots", headers=h, json={"ingredient_id": ing_id, "quantity": {"count": 0, "unit_code": "qua"}})
    assert r3.status_code == 422


def test_T2_KITCH_02_infeasible_tray_and_unsatisfiable_pin(
    api_client: httpx.Client,
    helpers: Any,
    session_consented_user: dict[str, Any],
) -> None:
    token = session_consented_user["access_token"]
    h = _auth_headers(token, idem=helpers.create_idempotency_key("inf"))
    all_algs = [a["code"] for a in api_client.get("/reference").json()["allergen_groups"]]
    # Exclude every allergen + 10 min limit + bogus/impossible combo
    resp = api_client.post(
        "/meal-plans",
        headers=h,
        json={"meal": "dinner", "persons": 2, "max_minutes": 10, "coeater_allergen_codes": all_algs},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] in ("no_feasible_tray", "pin_unsatisfiable", "unknown_code")


def test_T2_KITCH_03_cook_session_state_machine_conflicts(
    api_client: httpx.Client,
    helpers: Any,
    session_consented_user: dict[str, Any],
) -> None:
    token = session_consented_user["access_token"]

    plan = api_client.post(
        "/meal-plans",
        headers=_auth_headers(token, idem=helpers.create_idempotency_key("cplan")),
        json={"meal": "dinner", "persons": 2, "max_minutes": 60},
    ).json()

    serve_at = (datetime.now(timezone.utc) + timedelta(minutes=65)).isoformat()
    before_accept = api_client.post(
        "/cook-sessions",
        headers=_auth_headers(token, idem=helpers.create_idempotency_key("preacc")),
        json={"meal_plan_id": plan["id"], "serve_at": serve_at, "confirm_over_time": True},
    )
    assert before_accept.status_code in (409, 422)

    api_client.post(f"/meal-plans/{plan['id']}/accept", headers=_auth_headers(token))
    cs = api_client.post(
        "/cook-sessions",
        headers=_auth_headers(token, idem=helpers.create_idempotency_key("cook1")),
        json={"meal_plan_id": plan["id"], "serve_at": serve_at, "confirm_over_time": True},
    ).json()

    try:
        undo_early = api_client.post(f"/cook-sessions/{cs['id']}/undo", headers=_auth_headers(token))
        assert undo_early.status_code == 409

        concurrent = api_client.post(
            "/cook-sessions",
            headers=_auth_headers(token, idem=helpers.create_idempotency_key("cook2")),
            json={"meal_plan_id": plan["id"], "serve_at": serve_at, "confirm_over_time": True},
        )
        assert concurrent.status_code == 409
    finally:
        api_client.post(f"/cook-sessions/{cs['id']}/abandon", headers=_auth_headers(token))


def test_T2_KITCH_04_invalid_iso_week_and_admin_forbidden(
    api_client: httpx.Client,
    session_consented_user: dict[str, Any],
) -> None:
    h = _auth_headers(session_consented_user["access_token"])
    bad_week = api_client.get("/journal", headers=h, params={"week": "2026-W99"})
    _assert_problem_json(bad_week, 422)

    adm_dsr = api_client.get("/admin/data-requests", headers=h)
    _assert_problem_json(adm_dsr, 403, "forbidden")

    adm_mod = api_client.get("/admin/models", headers=h)
    _assert_problem_json(adm_mod, 403, "forbidden")


def test_T2_KITCH_05_survey_invalid_token_and_invalid_rating(
    api_client: httpx.Client,
    helpers: Any,
) -> None:
    pol = helpers.get_policy_version_id("survey")
    created = api_client.post(
        "/survey/respondents",
        json={"policy_version_id": pol, "consent": True, "channel": "link"},
    ).json()
    rid = created["respondent"]["id"]
    rtok = created["respondent_token"]
    recipe_id = created["respondent"]["assignments"][0]["recipe_id"]

    bad_tok = api_client.get(f"/survey/respondents/{rid}", headers={"X-Respondent-Token": "wrong-token"})
    assert bad_tok.status_code in (401, 403)

    bad_rating = api_client.put(
        f"/survey/respondents/{rid}/ratings/{recipe_id}",
        headers={"X-Respondent-Token": rtok},
        json={"rating": 9, "never_eaten": True},
    )
    _assert_problem_json(bad_rating, 422)


def test_T2_KITCH_06_survey_endpoint_rate_limit_429(
    api_client: httpx.Client,
    helpers: Any,
) -> None:
    pol = helpers.get_policy_version_id("survey")
    created = api_client.post(
        "/survey/respondents",
        json={"policy_version_id": pol, "consent": True, "channel": "link"},
    ).json()
    rid = created["respondent"]["id"]
    rtok = created["respondent_token"]
    recipe_id = created["respondent"]["assignments"][0]["recipe_id"]

    hit_429: httpx.Response | None = None
    # survey_step bucket is limit=180 / 60s keyed by f"{client_ip}:{rid}" (never exhaust survey_create IP bucket)
    for _ in range(195):
        r = api_client.put(
            f"/survey/respondents/{rid}/ratings/{recipe_id}",
            headers={"X-Respondent-Token": rtok},
            json={"rating": 5, "never_eaten": False},
        )
        if r.status_code == 429:
            hit_429 = r
            break

    assert hit_429 is not None, "Expected 429 rate_limited on PUT /survey/respondents/{id}/ratings/{recipe_id} burst"
    assert hit_429.json()["code"] == "rate_limited"


# ============================================================================
# Area 7: Landing & App Web UI Boundary / Responsive / A11y Cases (T2-UI-01..07)
# ============================================================================


@pytest.mark.browser
def test_T2_UI_01_mobile_390x844_zero_horizontal_overflow_and_touch_targets(
    base_url: str,
    page_factory: Callable[..., tuple[Any, Page, Any]],
    session_consented_user: dict[str, Any],
) -> None:
    _, page, telemetry = page_factory(viewport=(390, 844), color_scheme="light")
    page.goto(f"{base_url}/gioi-thieu/", wait_until="networkidle")
    evaluate_page_rubric(page, screen_name="landing-mobile", theme="light", surface_mode="landing", viewport_width=390, viewport_height=844)
    landing_txt = "\n".join(page.locator("header, main, footer").all_inner_texts())
    assert_no_banned_copy(landing_txt, context="390x844:/gioi-thieu/")
    assert_no_brand_leak(landing_txt, context="390x844:/gioi-thieu/")
    assert_no_ai_separators(landing_txt, context="390x844:/gioi-thieu/")

    page.goto(f"{base_url}/dang-nhap", wait_until="networkidle")
    page.get_by_test_id("login-email").wait_for(state="visible", timeout=15000)
    evaluate_page_rubric(page, screen_name="app-/dang-nhap", theme="light", surface_mode="app", viewport_width=390, viewport_height=844)
    login_txt = page.locator("body").inner_text()
    assert_no_banned_copy(login_txt, context="390x844:/dang-nhap")
    assert_no_brand_leak(login_txt, context="390x844:/dang-nhap")
    assert_no_ai_separators(login_txt, context="390x844:/dang-nhap")

    page.get_by_test_id("login-email").fill(session_consented_user["_email"])
    page.get_by_test_id("login-password").fill(session_consented_user["_password"])
    page.get_by_test_id("login-submit").click()
    page.wait_for_url(re.compile(r"/(bep|onboarding)"), timeout=20000)

    for route in ("/bep", "/kho", "/mam", "/quet", "/nhat-ky", "/cai-dat"):
        page.goto(f"{base_url}{route}", wait_until="networkidle")
        page.wait_for_timeout(300)
        if route == "/bep":
            page.get_by_test_id("home-open-explore").wait_for(state="visible", timeout=10000)
        evaluate_page_rubric(
            page,
            screen_name=f"app-{route}",
            theme="light",
            surface_mode="app",
            viewport_width=390,
            viewport_height=844,
        )
        route_txt = page.locator("body").inner_text()
        assert_no_banned_copy(route_txt, context=f"390x844:{route}")
        assert_no_brand_leak(route_txt, context=f"390x844:{route}")
        assert_no_ai_separators(route_txt, context=f"390x844:{route}")
    telemetry.assert_clean(page)


@pytest.mark.browser
def test_T2_UI_02_landing_zero_ingredients_and_empty_search_state(
    base_url: str,
    page_factory: Callable[..., tuple[Any, Page, Any]],
) -> None:
    _, page, telemetry = page_factory(viewport=(1440, 900), color_scheme="light")
    page.goto(f"{base_url}/gioi-thieu/", wait_until="networkidle")

    # Switch to Tab 2 (Fridge-to-3-Dish Tray Simulator) so #bo-gia-lap is visible
    tray_tab = page.locator("#wb-tab-tray, [data-wb-mode='tray']").first
    tray_tab.scroll_into_view_if_needed()
    tray_tab.click()
    page.wait_for_timeout(100)

    workbench = page.locator("#bo-gia-lap, [data-testid='landing-tray-simulator']").first
    assert workbench.is_visible()

    # Uncheck every currently pressed ingredient button
    pressed = page.locator("[data-ingredient][aria-pressed='true']")
    while pressed.count() > 0:
        pressed.first.click()
        page.wait_for_timeout(50)

    recipe_title = page.locator("#recipe-name").inner_text().lower()
    assert "chọn ít nhất 1 nguyên liệu" in recipe_title
    assert page.locator("#sim-kcal").inner_text().strip() == "0"
    assert page.locator("#sim-minutes").inner_text().strip() == "0"
    assert not page.locator("#sim-hint").is_visible()

    # Switch back to Tab 1 (Calorie Breakdown) and verify dish/modifier/scale edge behavior
    cal_tab = page.locator("#wb-tab-calorie, [data-wb-mode='calorie']").first
    cal_tab.click()
    page.wait_for_timeout(100)
    page.locator("[data-cal-dish='pho']").first.click()
    assert page.locator("[data-cal-mod='nuoc_mam']").first.is_disabled()
    pho_pie_kcal = (page.locator("#cal-macro-pie .pie-center-kcal").text_content() or "").strip()
    pho_density = page.locator("#cal-density-text").inner_text().strip()
    pho_amdr_insight = page.locator("#cal-amdr-insight").inner_text().strip()

    page.locator("[data-cal-dish='dau_phu_non']").first.click()
    page.locator("[data-cal-scale='nho']").first.click()
    page.wait_for_timeout(80)
    assert "kcal" in page.locator("#cal-range-text").inner_text().lower()
    assert "Phần nhỏ (0.75×)" in page.locator("#cal-point-text").inner_text()
    tofu_pie_kcal = (page.locator("#cal-macro-pie .pie-center-kcal").text_content() or "").strip()
    tofu_density = page.locator("#cal-density-text").inner_text().strip()
    tofu_amdr_status = page.locator("#cal-amdr-status").inner_text().strip()
    tofu_amdr_insight = page.locator("#cal-amdr-insight").inner_text().strip()
    assert tofu_pie_kcal and tofu_pie_kcal != pho_pie_kcal
    assert tofu_density and tofu_density != pho_density
    assert tofu_amdr_status != ""
    assert tofu_amdr_insight and tofu_amdr_insight != pho_amdr_insight

    # Verify legal footer links and zero broken visible images
    assert page.locator("footer a[href='/gioi-thieu/rieng-tu.html']").first.is_visible()
    assert page.locator("footer a[href='/gioi-thieu/dieu-khoan.html']").first.is_visible()
    broken = page.evaluate(
        """() => Array.from(document.querySelectorAll('img')).filter(i => {
          if (i.offsetParent === null) return false;
          if (i.complete && i.naturalWidth <= 0) return true;
          const r = i.getBoundingClientRect();
          if (i.loading === 'lazy' && !i.complete && (r.top >= window.innerHeight * 1.2 || r.bottom <= 0)) return false;
          return !i.complete || i.naturalWidth <= 0;
        }).map(i => i.src)"""
    )
    assert not broken, f"Broken visible images on landing: {broken}"

    telemetry.assert_clean(page)


@pytest.mark.browser
def test_T2_UI_03_barcode_unsupported_browser_and_malformed_input_ui(
    base_url: str,
    page_factory: Callable[..., tuple[Any, Page, Any]],
    session_consented_user: dict[str, Any],
) -> None:
    ctx, page, telemetry = page_factory(viewport=(1440, 900), color_scheme="light")
    ctx.add_init_script("delete window.BarcodeDetector;")

    page.goto(f"{base_url}/dang-nhap", wait_until="networkidle")
    page.get_by_test_id("login-email").fill(session_consented_user["_email"])
    page.get_by_test_id("login-password").fill(session_consented_user["_password"])
    page.get_by_test_id("login-submit").click()
    page.wait_for_url(re.compile(r"/(bep|onboarding)"), timeout=20000)

    page.goto(f"{base_url}/quet?tab=barcode", wait_until="networkidle")
    page.get_by_test_id("scan-barcode-panel").wait_for(state="visible", timeout=15000)

    page.get_by_test_id("barcode-input").fill("123")
    btn = page.get_by_test_id("barcode-lookup-btn")
    disabled = btn.get_attribute("aria-disabled") == "true" or btn.is_disabled()
    assert disabled, "Malformed short barcode '123' should keep lookup button disabled"

    photo_btn = page.get_by_test_id("barcode-photo-btn")
    assert photo_btn.count() > 0, "Expected barcode-photo-btn to be rendered"
    photo_btn.click()
    page.wait_for_timeout(200)
    panel_text = page.get_by_test_id("scan-barcode-panel").inner_text()
    assert len(panel_text.strip()) > 0
    telemetry.assert_clean(page)


@pytest.mark.browser
def test_T2_UI_04_prefers_reduced_motion_all_sections_visible(
    base_url: str,
    page_factory: Callable[..., tuple[Any, Page, Any]],
) -> None:
    _, page, telemetry = page_factory(viewport=(1440, 900), color_scheme="light", reduced_motion="reduce")
    page.goto(f"{base_url}/gioi-thieu/", wait_until="networkidle")
    evaluate_page_rubric(
        page,
        screen_name="landing-reduced-motion",
        theme="light",
        surface_mode="landing",
        check_reduced_motion_opacity=True,
    )
    # Scroll through every lazy image so deferred images actually load and pass naturalWidth > 0
    lazy_imgs = page.locator("img[loading='lazy']")
    for idx in range(lazy_imgs.count()):
        lazy_imgs.nth(idx).scroll_into_view_if_needed()
    page.wait_for_load_state("networkidle")
    page.wait_for_function(
        "() => Array.from(document.querySelectorAll('img')).every(i => i.offsetParent === null || i.complete)",
        timeout=10000,
    )
    broken = page.evaluate(
        "() => Array.from(document.querySelectorAll('img')).filter(i => i.offsetParent !== null && (!i.complete || i.naturalWidth <= 0)).map(i => i.currentSrc || i.getAttribute('src') || '')"
    )
    assert not broken, f"Broken visible/lazy images after scroll on reduced-motion landing: {broken}"
    evaluate_page_rubric(
        page,
        screen_name="landing-reduced-motion-scrolled",
        theme="light",
        surface_mode="landing",
        check_reduced_motion_opacity=True,
    )
    telemetry.assert_clean(page)


@pytest.mark.browser
def test_T2_UI_05_light_only_broadsheet_invariance_under_os_dark_mode(
    base_url: str,
    page_factory: Callable[..., tuple[Any, Page, Any]],
    session_consented_user: dict[str, Any],
) -> None:
    # 1. Desktop (1440x900) Light baseline on landing & app /dang-nhap
    _, p_light, t_light = page_factory(viewport=(1440, 900), color_scheme="light")
    p_light.goto(f"{base_url}/gioi-thieu/", wait_until="networkidle")
    r_light = evaluate_page_rubric(p_light, screen_name="landing-theme-desktop", theme="light", surface_mode="landing")
    p_light.goto(f"{base_url}/dang-nhap", wait_until="networkidle")
    p_light.get_by_test_id("login-email").wait_for(state="visible", timeout=15000)
    r_app_light = evaluate_page_rubric(p_light, screen_name="app-dang-nhap-light", theme="light", surface_mode="app")
    t_light.assert_clean(p_light)

    # 2. Desktop (1440x900) OS color_scheme="dark" must remain locked to Light vintage parchment
    _, p_dark, t_dark = page_factory(viewport=(1440, 900), color_scheme="dark")
    dark_paper_light_200: list[str] = []
    dark_paper_dark_reqs: list[str] = []

    def _track_dark(resp: Any) -> None:
        if "paper-bg-light" in resp.url and resp.status == 200:
            dark_paper_light_200.append(resp.url)
        if "paper-bg-dark" in resp.url:
            dark_paper_dark_reqs.append(f"{resp.status} {resp.url}")

    p_dark.on("response", _track_dark)
    p_dark.goto(f"{base_url}/gioi-thieu/", wait_until="networkidle")
    r_dark = evaluate_page_rubric(p_dark, screen_name="landing-os-dark-desktop", theme="light", surface_mode="landing")
    assert_light_parchment_locked(r_light, r_dark, max_delta=15)
    assert "paper-bg-light" in r_dark.bg_image
    assert dark_paper_light_200, "Expected /gioi-thieu/ paper-bg-light.webp 200 OK under OS dark mode"
    assert not dark_paper_dark_reqs, f"Unexpected paper-bg-dark request(s): {dark_paper_dark_reqs}"
    landing_dark_txt = "\n".join(p_dark.locator("header, main, footer").all_inner_texts())
    assert_no_banned_copy(landing_dark_txt, context="os-dark-1440:/gioi-thieu/")
    assert_no_brand_leak(landing_dark_txt, context="os-dark-1440:/gioi-thieu/")
    assert_no_ai_separators(landing_dark_txt, context="os-dark-1440:/gioi-thieu/")

    # App under OS color_scheme="dark" at 1440x900 across /dang-nhap and authenticated routes
    dark_paper_light_200.clear()
    p_dark.goto(f"{base_url}/dang-nhap", wait_until="networkidle")
    p_dark.get_by_test_id("login-email").wait_for(state="visible", timeout=15000)
    r_app_dark_login = evaluate_page_rubric(p_dark, screen_name="app-dang-nhap-os-dark", theme="light", surface_mode="app")
    assert_light_parchment_locked(r_app_light, r_app_dark_login, max_delta=15)
    assert r_app_dark_login.data_theme == "light"
    assert "paper-bg-light" in r_app_dark_login.bg_image
    assert dark_paper_light_200, "Expected app paper-bg-light.webp 200 OK under OS dark mode"

    p_dark.get_by_test_id("login-email").fill(session_consented_user["_email"])
    p_dark.get_by_test_id("login-password").fill(session_consented_user["_password"])
    p_dark.get_by_test_id("login-submit").click()
    p_dark.wait_for_url(re.compile(r"/(bep|onboarding)"), timeout=20000)

    for route in ("/bep", "/kho", "/mam", "/quet", "/nhat-ky", "/cai-dat"):
        p_dark.goto(f"{base_url}{route}", wait_until="networkidle")
        p_dark.wait_for_timeout(300)
        r_route = evaluate_page_rubric(p_dark, screen_name=f"app-{route}-os-dark-desktop", theme="light", surface_mode="app")
        assert_light_parchment_locked(r_app_light, r_route, max_delta=15)
        assert r_route.data_theme == "light"
        assert "paper-bg-light" in r_route.bg_image
        route_txt = p_dark.locator("body").inner_text()
        assert_no_banned_copy(route_txt, context=f"os-dark-1440:{route}")
        if route == "/cai-dat":
            assert p_dark.get_by_test_id("theme-toggle").count() == 0, "Dark mode toggle must not exist in /cai-dat"
            assert "chế độ tối" not in route_txt.lower()
    assert not dark_paper_dark_reqs, f"Unexpected paper-bg-dark request(s) on app: {dark_paper_dark_reqs}"
    t_dark.assert_clean(p_dark)

    # 3. Mobile (390x844) OS color_scheme="dark" on landing and app /quet
    _, p_mob_dark, t_mob_dark = page_factory(viewport=(390, 844), color_scheme="dark")
    mob_light_200: list[str] = []
    mob_dark_reqs: list[str] = []

    def _track_mob(resp: Any) -> None:
        if "paper-bg-light" in resp.url and resp.status == 200:
            mob_light_200.append(resp.url)
        if "paper-bg-dark" in resp.url:
            mob_dark_reqs.append(f"{resp.status} {resp.url}")

    p_mob_dark.on("response", _track_mob)
    p_mob_dark.goto(f"{base_url}/gioi-thieu/", wait_until="networkidle")
    r_mob_landing = evaluate_page_rubric(
        p_mob_dark,
        screen_name="landing-os-dark-mobile",
        theme="light",
        surface_mode="landing",
        viewport_width=390,
        viewport_height=844,
    )
    assert_light_parchment_locked(r_light, r_mob_landing, max_delta=15)
    assert mob_light_200, "Expected mobile /gioi-thieu/ paper-bg-light.webp 200 OK"

    p_mob_dark.goto(f"{base_url}/dang-nhap", wait_until="networkidle")
    p_mob_dark.get_by_test_id("login-email").fill(session_consented_user["_email"])
    p_mob_dark.get_by_test_id("login-password").fill(session_consented_user["_password"])
    p_mob_dark.get_by_test_id("login-submit").click()
    p_mob_dark.wait_for_url(re.compile(r"/(bep|onboarding)"), timeout=20000)
    p_mob_dark.goto(f"{base_url}/quet", wait_until="networkidle")
    p_mob_dark.get_by_test_id("screen-scan").wait_for(state="visible", timeout=15000)
    r_mob_quet = evaluate_page_rubric(
        p_mob_dark,
        screen_name="app-quet-os-dark-mobile",
        theme="light",
        surface_mode="app",
        viewport_width=390,
        viewport_height=844,
    )
    assert_light_parchment_locked(r_app_light, r_mob_quet, max_delta=15)
    assert r_mob_quet.data_theme == "light"
    assert not mob_dark_reqs, f"Unexpected paper-bg-dark request(s) on mobile: {mob_dark_reqs}"
    t_mob_dark.assert_clean(p_mob_dark)


@pytest.mark.browser
def test_T2_UI_06_banned_copy_and_prose_hyphen_scan_across_surfaces(
    base_url: str,
    page_factory: Callable[..., tuple[Any, Page, Any]],
    session_consented_user: dict[str, Any],
) -> None:
    _, page, telemetry = page_factory(viewport=(1440, 900), color_scheme="light")
    for path in ("/gioi-thieu/", "/gioi-thieu/rieng-tu.html", "/gioi-thieu/dieu-khoan.html"):
        page.goto(f"{base_url}{path}", wait_until="networkidle")
        joined_landing = "\n".join(page.locator("header, main, footer").all_inner_texts())
        assert_no_banned_copy(joined_landing, context=path)
        assert_no_prose_hyphens(joined_landing, context=path)
        assert_no_brand_leak(joined_landing, context=path)
        assert_no_ai_separators(joined_landing, context=path)

    page.goto(f"{base_url}/dang-nhap", wait_until="networkidle")
    page.get_by_test_id("login-email").wait_for(state="visible", timeout=15000)
    login_txt = page.locator("body").inner_text()
    assert_no_banned_copy(login_txt, context="/dang-nhap")
    assert_no_prose_hyphens(login_txt, context="/dang-nhap")
    assert_no_brand_leak(login_txt, context="/dang-nhap")
    assert_no_ai_separators(login_txt, context="/dang-nhap")

    page.get_by_test_id("login-email").fill(session_consented_user["_email"])
    page.get_by_test_id("login-password").fill(session_consented_user["_password"])
    page.get_by_test_id("login-submit").click()
    page.wait_for_url(re.compile(r"/(bep|onboarding)"), timeout=20000)

    for route in ("/bep", "/kho", "/mam", "/quet", "/nhat-ky", "/cai-dat"):
        page.goto(f"{base_url}{route}", wait_until="networkidle")
        page.wait_for_timeout(300)
        txt = page.locator("body").inner_text()
        assert_no_banned_copy(txt, context=route)
        assert_no_prose_hyphens(txt, context=route)
        assert_no_brand_leak(txt, context=route)
        assert_no_ai_separators(txt, context=route)
    telemetry.assert_clean(page)


@pytest.mark.browser
def test_T2_UI_07_custom_404_page_mobile_responsive_and_home_link(
    base_url: str,
    page_factory: Callable[..., tuple[Any, Page, Any]],
) -> None:
    _, page, telemetry = page_factory(viewport=(390, 844), color_scheme="light", allow_4xx_statuses={404})
    resp = page.goto(f"{base_url}/gioi-thieu/duong-dan-khong-ton-tai", wait_until="networkidle")
    assert resp is not None and resp.status == 404
    assert page.locator("header.site-masthead").first.is_visible()
    body_txt = page.locator("body").inner_text()
    assert "Mỹ Vị" in body_txt
    assert_no_brand_leak(body_txt, context="404:/gioi-thieu/duong-dan-khong-ton-tai")
    assert_no_ai_separators(body_txt, context="404:/gioi-thieu/duong-dan-khong-ton-tai")
    evaluate_page_rubric(page, screen_name="landing-404", theme="light", surface_mode="landing", viewport_width=390, viewport_height=844)
    home_link = page.locator("a[href='/gioi-thieu/'], a[href='/']").first
    assert home_link.count() > 0
    telemetry.assert_clean(page)
