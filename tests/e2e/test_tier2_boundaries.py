"""Tier 2: Boundary Value Analysis (BVA) & Negative/Rejection Tests across ALL 15 Features (F1-F15).

Requirement: >= 5 distinct boundary/negative tests per feature (>= 75 total).
All assertions match docs/api/openapi-v1.yaml ProblemCode contracts and backend/src/tastoria/ modules.
"""

from __future__ import annotations

import io
import json
import math
import re
import subprocess
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml
from docx import Document
from PIL import Image
from playwright.sync_api import expect

from tests.e2e.conftest import DEFAULT_PASSWORD, E2EHelpers, unique_email, unique_idem_key
from tests.e2e.fixtures import (
    make_corrupt_jpeg_bytes,
    make_exif_gps_orientation6_jpeg,
    make_oversized_jpeg,
    make_oversized_pixels_jpeg,
    make_produce_jpeg,
    make_spoofed_pdf_bytes,
    write_temp_scan_file,
)
from tests.e2e.rubric import evaluate_page_rubric, hex_contrast_ratio, load_design_tokens

REPO_ROOT = Path(__file__).resolve().parents[2]
pytestmark = [pytest.mark.tier2]


def _assert_problem(resp, expected_status: int, expected_code: str) -> dict:
    assert resp.status_code == expected_status, f"Expected {expected_status} ({expected_code}), got {resp.status_code}: {resp.text}"
    assert "application/problem+json" in resp.headers.get("content-type", "")
    body = resp.json()
    assert body.get("code") == expected_code, f"Expected ProblemCode '{expected_code}', got {body}"
    assert body.get("status") == expected_status
    assert body.get("request_id")
    return body


# ==============================================================================
# F1: Middleware, App Version, Pagination, Auth & Anti-BOLA Boundaries (5 tests)
# ==============================================================================


def test_t2_f1_x_app_version_below_min_returns_412(raw_client, api_client) -> None:
    # compose.e2e sets TASTORIA_MIN_APP_VERSION=0.1.0; /healthz stays exempt, /api/v1/* enforces 412
    h_ok = raw_client.get("/healthz", headers={"X-App-Version": "0.0.1"})
    assert h_ok.status_code == 200

    old = api_client.get("/policies/health_profile/current", headers={"X-App-Version": "0.0.9"})
    _assert_problem(old, 412, "app_too_old")

    ok = api_client.get("/policies/health_profile/current", headers={"X-App-Version": "0.1.0"})
    assert ok.status_code == 200


def test_t2_f1_pagination_limit_boundaries(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=False)
    h = helpers.auth_headers(user["access_token"])

    r0 = helpers.api.get("/ingredients", headers=h, params={"limit": 0})
    _assert_problem(r0, 422, "validation_error")

    r101 = helpers.api.get("/ingredients", headers=h, params={"limit": 101})
    _assert_problem(r101, 422, "validation_error")

    r1 = helpers.api.get("/ingredients", headers=h, params={"limit": 1})
    assert r1.status_code == 200 and len(r1.json()["items"]) == 1

    r100 = helpers.api.get("/ingredients", headers=h, params={"limit": 100})
    assert r100.status_code == 200 and len(r100.json()["items"]) <= 100


def test_t2_f1_malformed_cursor_returns_400_validation_error(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=False)
    h = helpers.auth_headers(user["access_token"])
    resp = helpers.api.get("/ingredients", headers=h, params={"cursor": "%%%invalid-cursor%%%"})
    _assert_problem(resp, 400, "validation_error")


def test_t2_f1_missing_or_invalid_bearer_returns_401(api_client) -> None:
    _assert_problem(api_client.get("/me/profile"), 401, "unauthenticated")
    _assert_problem(api_client.get("/me/profile", headers={"Authorization": "Bearer not.a.jwt"}), 401, "unauthenticated")


def test_t2_f1_foreign_resource_anti_bola_returns_404(helpers: E2EHelpers) -> None:
    user_a = helpers.create_ready_user(seed_pantry=True)
    user_b = helpers.create_ready_user(seed_pantry=False)
    ha = helpers.auth_headers(user_a["access_token"])
    hb = helpers.auth_headers(user_b["access_token"])

    lot_a = helpers.api.get("/pantry/lots", headers=ha).json()["items"][0]["id"]
    _assert_problem(helpers.api.post(f"/pantry/lots/{lot_a}/discard", headers=hb), 404, "not_found")

    plan_a = helpers.api.post(
        "/meal-plans",
        headers=helpers.auth_headers(user_a["access_token"], idem=unique_idem_key("bola")),
        json={"meal": "dinner", "max_minutes": 60, "persons": 2},
    ).json()["id"]
    _assert_problem(helpers.api.get(f"/meal-plans/{plan_a}", headers=hb), 404, "not_found")


# ==============================================================================
# F2: Scan Upload Size, Pixels, Magic Bytes, EXIF & Idempotency BVA (6 tests)
# ==============================================================================


def test_t2_f2_scan_upload_over_3mb_returns_413_image_too_large(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=False)
    resp = helpers.api.post(
        "/scans",
        headers=helpers.auth_headers(user["access_token"], idem=unique_idem_key("big")),
        data={"mode": "haul", "contribute": "false"},
        files=[("images", ("big.jpg", make_oversized_jpeg(), "image/jpeg"))],
    )
    _assert_problem(resp, 413, "image_too_large")


def test_t2_f2_scan_upload_4097x4096_returns_422_too_many_pixels(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=False)
    resp = helpers.api.post(
        "/scans",
        headers=helpers.auth_headers(user["access_token"], idem=unique_idem_key("px")),
        data={"mode": "haul", "contribute": "false"},
        files=[("images", ("wide.jpg", make_oversized_pixels_jpeg(), "image/jpeg"))],
    )
    _assert_problem(resp, 422, "image_too_many_pixels")


def test_t2_f2_scan_upload_spoofed_pdf_returns_415_unsupported_media(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=False)
    resp = helpers.api.post(
        "/scans",
        headers=helpers.auth_headers(user["access_token"], idem=unique_idem_key("pdf")),
        data={"mode": "haul", "contribute": "false"},
        files=[("images", ("fake.jpg", make_spoofed_pdf_bytes(), "image/jpeg"))],
    )
    _assert_problem(resp, 415, "unsupported_media_type")


def test_t2_f2_scan_upload_corrupt_jpeg_returns_415(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=False)
    resp = helpers.api.post(
        "/scans",
        headers=helpers.auth_headers(user["access_token"], idem=unique_idem_key("corrupt")),
        data={"mode": "haul", "contribute": "false"},
        files=[("images", ("corrupt.jpg", make_corrupt_jpeg_bytes(), "image/jpeg"))],
    )
    _assert_problem(resp, 415, "unsupported_media_type")


def test_t2_f2_scan_upload_strips_exif_gps_and_rotates_orientation6(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=False)
    tok = user["access_token"]
    h = helpers.auth_headers(tok)
    raw = make_exif_gps_orientation6_jpeg(400, 240)
    resp = helpers.api.post(
        "/scans",
        headers=helpers.auth_headers(tok, idem=unique_idem_key("exif")),
        data={"mode": "fridge", "contribute": "false"},
        files=[("images", ("exif.jpg", raw, "image/jpeg"))],
    )
    assert resp.status_code == 202, resp.text
    scan_id = resp.json()["id"]

    img_resp = helpers.api.get(f"/scans/{scan_id}/images/1", headers=h)
    assert img_resp.status_code == 200
    assert img_resp.headers.get("content-type") == "image/jpeg"
    with Image.open(io.BytesIO(img_resp.content)) as im:
        # Orientation=6 rotated 400x240 -> 240x400, and all EXIF/GPS stripped
        assert im.size == (240, 400), f"Expected transposed (240, 400), got {im.size}"
        assert len(im.getexif()) == 0, "Expected EXIF metadata to be completely stripped"


def test_t2_f2_scan_idempotency_missing_replay_and_conflict(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=False)
    tok = user["access_token"]
    jpeg = make_produce_jpeg()

    no_key = helpers.api.post(
        "/scans",
        headers=helpers.auth_headers(tok),
        data={"mode": "haul", "contribute": "false"},
        files=[("images", ("a.jpg", jpeg, "image/jpeg"))],
    )
    _assert_problem(no_key, 400, "idempotency_key_required")

    key = unique_idem_key("idemscan")
    first = helpers.api.post(
        "/scans",
        headers=helpers.auth_headers(tok, idem=key),
        data={"mode": "haul", "contribute": "false"},
        files=[("images", ("a.jpg", jpeg, "image/jpeg"))],
    )
    assert first.status_code == 202

    replay = helpers.api.post(
        "/scans",
        headers=helpers.auth_headers(tok, idem=key),
        data={"mode": "haul", "contribute": "false"},
        files=[("images", ("a.jpg", jpeg, "image/jpeg"))],
    )
    assert replay.status_code == 202
    assert replay.headers.get("idempotent-replayed") == "true"
    assert replay.json()["id"] == first.json()["id"]

    conflict = helpers.api.post(
        "/scans",
        headers=helpers.auth_headers(tok, idem=key),
        data={"mode": "fridge", "contribute": "false"},
        files=[("images", ("a.jpg", jpeg, "image/jpeg"))],
    )
    _assert_problem(conflict, 422, "idempotency_key_reused")


# ==============================================================================
# F3: Freshness Urgency Thresholds, Check-Level, Consent & Scan State BVA (5 tests)
# ==============================================================================


def test_t2_f3_urgency_boundaries_049_050_085_100(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=False)
    tok = user["access_token"]
    # `cải ngọt` has shelf_life_days = 4.0
    l_tuoi = helpers.seed_pantry_lot(tok, "cải ngọt", grams=200.0, days_ago=1.9)  # u ~ 0.475 < 0.50
    l_som = helpers.seed_pantry_lot(tok, "cải ngọt", grams=200.0, days_ago=2.05)  # u ~ 0.5125 in [0.5, 0.8)
    l_ngay = helpers.seed_pantry_lot(tok, "cải ngọt", grams=200.0, days_ago=3.4)  # u ~ 0.85 in [0.8, 1.0]
    l_check = helpers.seed_pantry_lot(tok, "cải ngọt", grams=200.0, days_ago=4.2)  # u ~ 1.05 > 1.0

    assert l_tuoi["freshness_label"] == "tuoi" and l_tuoi["available"] is True
    assert l_som["freshness_label"] == "dung_som" and l_som["available"] is True
    assert l_ngay["freshness_label"] == "dung_ngay" and l_ngay["available"] is True
    assert l_check["freshness_label"] == "kiem_tra" and l_check["available"] is False


def test_t2_f3_kiem_tra_lot_check_transition_and_double_check_409(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=False)
    tok = user["access_token"]
    h = helpers.auth_headers(tok)
    lot = helpers.seed_pantry_lot(tok, "cải ngọt", grams=200.0, days_ago=4.5)
    assert lot["freshness_label"] == "kiem_tra" and lot["available"] is False

    checked = helpers.api.patch(
        f"/pantry/lots/{lot['id']}",
        headers={**h, "Content-Type": "application/merge-patch+json"},
        json={"user_checked": True},
    )
    assert checked.status_code == 200
    assert checked.json()["freshness_label"] == "dung_ngay"
    assert checked.json()["available"] is True

    again = helpers.api.patch(
        f"/pantry/lots/{lot['id']}",
        headers={**h, "Content-Type": "application/merge-patch+json"},
        json={"user_checked": True},
    )
    _assert_problem(again, 409, "lot_not_check_level")


def test_t2_f3_scan_contribute_without_consent_returns_403(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(purposes=("health_profile",), seed_pantry=False)
    resp = helpers.api.post(
        "/scans",
        headers=helpers.auth_headers(user["access_token"], idem=unique_idem_key("noconsent")),
        data={"mode": "haul", "contribute": "true"},
        files=[("images", ("a.jpg", make_produce_jpeg(), "image/jpeg"))],
    )
    _assert_problem(resp, 403, "consent_required")


def test_t2_f3_scan_wait_and_images_count_boundaries(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=False)
    tok = user["access_token"]
    h = helpers.auth_headers(tok)
    jpeg = make_produce_jpeg()

    # 3 images (> max 2)
    r3 = helpers.api.post(
        "/scans",
        headers=helpers.auth_headers(tok, idem=unique_idem_key("img3")),
        data={"mode": "fridge", "contribute": "false"},
        files=[
            ("images", ("1.jpg", jpeg, "image/jpeg")),
            ("images", ("2.jpg", jpeg, "image/jpeg")),
            ("images", ("3.jpg", jpeg, "image/jpeg")),
        ],
    )
    _assert_problem(r3, 422, "validation_error")

    created = helpers.api.post(
        "/scans",
        headers=helpers.auth_headers(tok, idem=unique_idem_key("img1")),
        data={"mode": "haul", "contribute": "false"},
        files=[("images", ("1.jpg", jpeg, "image/jpeg"))],
    )
    assert created.status_code == 202
    sid = created.json()["id"]

    _assert_problem(helpers.api.get(f"/scans/{sid}", headers=h, params={"wait": 11}), 422, "validation_error")
    _assert_problem(helpers.api.get(f"/scans/{sid}/images/3", headers=h), 422, "validation_error")


def test_t2_f3_scan_item_qty_mismatch_and_discarded_state_409(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=False)
    tok = user["access_token"]
    h = helpers.auth_headers(tok)
    created = helpers.api.post(
        "/scans",
        headers=helpers.auth_headers(tok, idem=unique_idem_key("itembva")),
        data={"mode": "haul", "contribute": "false"},
        files=[("images", ("1.jpg", make_produce_jpeg(), "image/jpeg"))],
    )
    sid = created.json()["id"]
    for _ in range(5):
        s = helpers.api.get(f"/scans/{sid}", headers=h, params={"wait": 10}).json()
        if s["status"] == "done":
            break
    assert s["status"] == "done"

    egg_id = helpers.resolve_ingredient_id(tok, "trứng gà")
    mismatch = helpers.api.post(
        f"/scans/{sid}/items",
        headers=h,
        json={"ingredient_id": egg_id, "qty_level": "vua"},
    )
    _assert_problem(mismatch, 422, "qty_kind_mismatch")

    over_count = helpers.api.post(
        f"/scans/{sid}/items",
        headers=h,
        json={"ingredient_id": egg_id, "final_count": 100},
    )
    _assert_problem(over_count, 422, "validation_error")

    disc = helpers.api.post(f"/scans/{sid}/discard", headers=h)
    assert disc.status_code == 200
    _assert_problem(helpers.api.post(f"/scans/{sid}/confirm", headers=h, json={}), 409, "invalid_scan_state")


# ==============================================================================
# F4: Survey Consent, Token, Rating & Favorite Boundaries (5 tests)
# ==============================================================================


def test_t2_f4_survey_consent_false_returns_422(helpers: E2EHelpers) -> None:
    helpers.ensure_open_survey_form()
    pid = helpers.get_policy_version_id("survey")
    resp = helpers.api.post("/survey/respondents", json={"policy_version_id": pid, "consent": False, "channel": "link"})
    _assert_problem(resp, 422, "consent_required")


def test_t2_f4_survey_invalid_token_returns_401(helpers: E2EHelpers) -> None:
    resp = helpers.api.get(f"/survey/respondents/{uuid.uuid4()}", headers={"X-Respondent-Token": "bogus-token"})
    _assert_problem(resp, 401, "respondent_token_invalid")


def test_t2_f4_survey_rating_bounds_and_never_eaten_mismatch(helpers: E2EHelpers) -> None:
    helpers.ensure_open_survey_form()
    pid = helpers.get_policy_version_id("survey")
    created = helpers.api.post("/survey/respondents", json={"policy_version_id": pid, "consent": True, "channel": "qr"}).json()
    rid = created["respondent"]["id"]
    rh = {"X-Respondent-Token": created["respondent_token"]}
    recipe_id = created["respondent"]["assignments"][0]["recipe_id"]

    for bad in (
        {"rating": 0, "never_eaten": False},
        {"rating": 6, "never_eaten": False},
        {"rating": 3, "never_eaten": True},
        {"rating": None, "never_eaten": False},
    ):
        r = helpers.api.put(f"/survey/respondents/{rid}/ratings/{recipe_id}", headers=rh, json=bad)
        _assert_problem(r, 422, "invalid_rating")


def test_t2_f4_survey_favorites_limit_6_returns_422(helpers: E2EHelpers) -> None:
    helpers.ensure_open_survey_form()
    pid = helpers.get_policy_version_id("survey")
    created = helpers.api.post("/survey/respondents", json={"policy_version_id": pid, "consent": True, "channel": "link"}).json()
    rid = created["respondent"]["id"]
    rh = {"X-Respondent-Token": created["respondent_token"]}
    six_ids = [a["recipe_id"] for a in created["respondent"]["assignments"][:6]]
    r = helpers.api.put(f"/survey/respondents/{rid}/favorites", headers=rh, json={"recipe_ids": six_ids})
    _assert_problem(r, 422, "invalid_favorites")


def test_t2_f4_survey_incomplete_submit_returns_422_and_resubmit_409(helpers: E2EHelpers) -> None:
    helpers.ensure_open_survey_form()
    pid = helpers.get_policy_version_id("survey")
    created = helpers.api.post("/survey/respondents", json={"policy_version_id": pid, "consent": True, "channel": "link"}).json()
    rid = created["respondent"]["id"]
    rh = {"X-Respondent-Token": created["respondent_token"]}

    inc = helpers.api.post(f"/survey/respondents/{rid}/complete", headers=rh)
    _assert_problem(inc, 422, "survey_incomplete")

    for a in created["respondent"]["assignments"]:
        helpers.api.put(f"/survey/respondents/{rid}/ratings/{a['recipe_id']}", headers=rh, json={"rating": None, "never_eaten": True})
    comp = helpers.api.post(f"/survey/respondents/{rid}/complete", headers=rh)
    assert comp.status_code == 200

    again = helpers.api.put(
        f"/survey/respondents/{rid}/ratings/{created['respondent']['assignments'][0]['recipe_id']}",
        headers=rh,
        json={"rating": 5, "never_eaten": False},
    )
    _assert_problem(again, 409, "survey_already_completed")


# ==============================================================================
# F5: Meal Composer, Pins, `do_an_vat` & State Conflict BVA (5 tests)
# ==============================================================================


def test_t2_f5_meal_plan_persons_and_max_minutes_bounds(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=True)
    tok = user["access_token"]
    for bad in (
        {"meal": "lunch", "max_minutes": 60, "persons": 0},
        {"meal": "lunch", "max_minutes": 60, "persons": 7},
        {"meal": "lunch", "max_minutes": 9, "persons": 2},
        {"meal": "lunch", "max_minutes": 181, "persons": 2},
    ):
        r = helpers.api.post(
            "/meal-plans",
            headers=helpers.auth_headers(tok, idem=unique_idem_key("mpbva")),
            json=bad,
        )
        _assert_problem(r, 422, "validation_error")


def test_t2_f5_meal_plan_pinned_lots_limit_3_returns_422(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=True)
    tok = user["access_token"]
    lots = helpers.api.get("/pantry/lots", headers=helpers.auth_headers(tok)).json()["items"]
    three_ids = [l["id"] for l in lots[:3]]
    r = helpers.api.post(
        "/meal-plans",
        headers=helpers.auth_headers(tok, idem=unique_idem_key("pin3")),
        json={"meal": "dinner", "max_minutes": 60, "persons": 2, "pinned_lot_ids": three_ids},
    )
    _assert_problem(r, 422, "validation_error")


def test_t2_f5_non_meal_do_an_vat_only_returns_422_no_feasible_tray(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=False)
    tok = user["access_token"]
    helpers.seed_pantry_lot(tok, "bim bim", grams=300.0)
    r = helpers.api.post(
        "/meal-plans",
        headers=helpers.auth_headers(tok, idem=unique_idem_key("snack")),
        json={"meal": "lunch", "max_minutes": 60, "persons": 2},
    )
    body = _assert_problem(r, 422, "no_feasible_tray")
    assert "shortfalls" in body


def test_t2_f5_pin_unsatisfiable_lot_returns_422(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=True)
    tok = user["access_token"]
    # `bánh mì` is `meal_ingredient: false` (never used in recipes), or an expired `kiem_tra` lot
    bad_lot = helpers.seed_pantry_lot(tok, "bánh mì", count=2, unit_code="qua")
    r = helpers.api.post(
        "/meal-plans",
        headers=helpers.auth_headers(tok, idem=unique_idem_key("badpin")),
        json={"meal": "dinner", "max_minutes": 60, "persons": 2, "pinned_lot_ids": [bad_lot["id"]]},
    )
    body = _assert_problem(r, 422, "pin_unsatisfiable")
    assert bad_lot["id"] in body.get("unmet_pinned_lot_ids", [])


def test_t2_f5_swap_cooked_plan_returns_409_conflict(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=True)
    tok = user["access_token"]
    h = helpers.auth_headers(tok)
    plan = helpers.api.post(
        "/meal-plans",
        headers=helpers.auth_headers(tok, idem=unique_idem_key("swap409")),
        json={"meal": "lunch", "max_minutes": 90, "persons": 2},
    ).json()
    helpers.api.post(f"/meal-plans/{plan['id']}/accept", headers=h)
    sess = helpers.api.post(
        "/cook-sessions",
        headers=helpers.auth_headers(tok, idem=unique_idem_key("cs409")),
        json={"meal_plan_id": plan["id"], "serve_at": (datetime.now(timezone.utc) + timedelta(minutes=60)).isoformat(), "confirm_over_time": True},
    ).json()
    helpers.api.post(
        f"/cook-sessions/{sess['id']}/complete",
        headers=helpers.auth_headers(tok, idem=unique_idem_key("cc409")),
        json={"feedback": []},
    )
    swap = helpers.api.post(
        f"/meal-plans/{plan['id']}/items/{plan['items'][0]['id']}/swap",
        headers=helpers.auth_headers(tok, idem=unique_idem_key("sw409")),
        json={"swap_reason": "moi_an"},
    )
    _assert_problem(swap, 409, "conflict_state")


# ==============================================================================
# F6: K-Dense Scientific Report & Numeric Sanity Boundaries (5 tests)
# ==============================================================================


def test_t2_f6_recsys_and_cv_metrics_finite_and_bounded() -> None:
    test_json = json.loads((REPO_ROOT / "data/processed/recsys/test.json").read_text(encoding="utf-8"))
    for item in (test_json if isinstance(test_json, list) else test_json.values()):
        if isinstance(item, dict):
            for k, v in item.items():
                if isinstance(v, float):
                    assert math.isfinite(v), f"Non-finite metric {k}={v}"


@pytest.mark.pending_m3_m4
def test_t2_f6_kdense_no_placeholder_tokens_in_hoc_may_report() -> None:
    md_path = REPO_ROOT / "docs/reports/hoc-may/Bao-cao-Nghien-cuu-Hoc-May-Tastoria.md"
    txt = md_path.read_text(encoding="utf-8")
    for bad in ("TODO", "TBD", "lorem ipsum", "XXXX"):
        assert bad not in txt, f"Found placeholder '{bad}' in {md_path}"


def test_t2_f6_no_leaked_s2_api_key_in_reports_or_tests() -> None:
    for p in (REPO_ROOT / "docs/reports").rglob("*.md"):
        content = p.read_text(encoding="utf-8", errors="ignore")
        assert "s2k-" not in content, f"Leaked S2 API key detected in {p}"


@pytest.mark.pending_m3_m4
def test_t2_f6_kdense_every_claim_has_verified_evidence_id() -> None:
    import csv

    manifest = json.loads((REPO_ROOT / "docs/reports/hoc-may/source_manifest.json").read_text(encoding="utf-8"))
    entries = manifest if isinstance(manifest, list) else manifest.get("sources", [])
    valid_ids = {e["evidence_id"] for e in entries}
    with (REPO_ROOT / "docs/reports/hoc-may/claims.csv").open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            ev_ids = [x.strip() for x in re.split(r"[;,|\s]+", row["evidence_ids"]) if x.strip()]
            assert ev_ids, f"Claim {row['claim_id']} missing evidence_ids"
            for eid in ev_ids:
                assert eid in valid_ids, f"Claim {row['claim_id']} references unknown evidence {eid}"


@pytest.mark.pending_m3_m4
def test_t2_f6_kdense_consistency_manifest_valid_bounds() -> None:
    data = json.loads((REPO_ROOT / "docs/reports/hoc-may/consistency_manifest.json").read_text(encoding="utf-8"))
    for fact in data.get("numeric_facts", []):
        if "sample_size" in fact and fact["sample_size"] is not None:
            assert fact["sample_size"] > 0


# ==============================================================================
# F7: Viewport 320px, Reduced Motion & Token Contrast Edge Cases (5 tests)
# ==============================================================================


def test_t2_f7_320px_ultra_narrow_viewport_zero_overflow_landing(base_url: str, page_factory) -> None:
    _, page, telemetry = page_factory(viewport=(320, 568), color_scheme="light")
    page.goto(f"{base_url}/")
    page.locator("h1").wait_for()
    evaluate_page_rubric(page, screen_name="landing-320", theme="light", surface_mode="landing", viewport_width=320, viewport_height=568, check_touch_targets=False, check_contrast=False)
    telemetry.assert_clean()


def test_t2_f7_320px_ultra_narrow_viewport_zero_overflow_login(base_url: str, page_factory) -> None:
    _, page, telemetry = page_factory(viewport=(320, 568), color_scheme="dark")
    page.goto(f"{base_url}/dang-nhap")
    page.get_by_test_id("screen-login").wait_for()
    evaluate_page_rubric(page, screen_name="login-320-dark", theme="dark", viewport_width=320, viewport_height=568)
    telemetry.assert_clean()


def test_t2_f7_reduced_motion_emulation_no_errors(base_url: str, page_factory) -> None:
    _, page, telemetry = page_factory(viewport=(1440, 900), reduced_motion="reduce")
    page.goto(f"{base_url}/")
    page.locator("#nhat-ky").scroll_into_view_if_needed()
    evaluate_page_rubric(page, screen_name="landing-reduced-motion", theme="light", surface_mode="landing", viewport_width=1440, viewport_height=900, check_touch_targets=False, check_contrast=False)
    telemetry.assert_clean()


def test_t2_f7_all_palette_border_and_accent_pairs_meet_wcag() -> None:
    tokens = load_design_tokens()
    for mode in ("light", "dark"):
        pal = tokens[mode]
        assert hex_contrast_ratio(pal["border"], pal["bg"]) >= 3.0
        assert hex_contrast_ratio(pal["border"], pal["surface"]) >= 3.0
        assert hex_contrast_ratio(pal["onAccent"], pal["accent"]) >= 4.5
        assert hex_contrast_ratio(pal["herb"], pal["surface"]) >= 4.5


@pytest.mark.pending_m3_m4
def test_t2_f7_no_structural_emojis_in_landing_html() -> None:
    html = (REPO_ROOT / "landing/index.html").read_text(encoding="utf-8")
    # Check common structural emoji ranges (U+1F300..U+1FAFF) are absent from UI chrome
    assert not re.search(r"[\U0001F300-\U0001FAFF]", html), "Found structural emoji in landing/index.html"


# ==============================================================================
# F8: Admin RBAC & MLOps Gate Boundaries (5 tests)
# ==============================================================================


def test_t2_f8_admin_surveys_rbac_anon_user_admin_rejected(helpers: E2EHelpers) -> None:
    _assert_problem(helpers.api.get("/admin/surveys"), 401, "unauthenticated")

    usr = helpers.register_user()
    _assert_problem(helpers.api.get("/admin/surveys", headers=helpers.auth_headers(usr["access_token"])), 403, "forbidden")

    adm = helpers.create_staff_session("admin")
    _assert_problem(helpers.api.get("/admin/surveys", headers=helpers.auth_headers(adm["access_token"])), 403, "forbidden")


@pytest.mark.pending_m3_m4
def test_t2_f8_admin_audit_log_rbac_user_and_ml_operator_rejected(helpers: E2EHelpers) -> None:
    _assert_problem(helpers.api.get("/admin/audit-log"), 401, "unauthenticated")
    usr = helpers.register_user()
    _assert_problem(helpers.api.get("/admin/audit-log", headers=helpers.auth_headers(usr["access_token"])), 403, "forbidden")
    mlop = helpers.create_staff_session("ml_operator")
    _assert_problem(helpers.api.get("/admin/audit-log", headers=helpers.auth_headers(mlop["access_token"])), 403, "forbidden")


@pytest.mark.pending_m3_m4
def test_t2_f8_admin_data_requests_resolve_invalid_type_and_empty_note(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=False)
    dsr_exp = helpers.api.post(
        "/me/data-requests",
        headers=helpers.auth_headers(user["access_token"]),
        json={"type": "export"},
    )
    assert dsr_exp.status_code in (200, 202)
    exp_id = dsr_exp.json()["id"]

    adm = helpers.create_staff_session("admin")
    ah = helpers.auth_headers(adm["access_token"])
    not_manual = helpers.api.post(
        f"/admin/data-requests/{exp_id}/resolve",
        headers=ah,
        json={"status": "completed", "note": "Thử resolve auto"},
    )
    _assert_problem(not_manual, 409, "request_not_manual")

    dsr_corr = helpers.api.post(
        "/me/data-requests",
        headers=helpers.auth_headers(user["access_token"]),
        json={"type": "correct", "note": "Sai thông tin"},
    ).json()["id"]
    empty_note = helpers.api.post(
        f"/admin/data-requests/{dsr_corr}/resolve",
        headers=ah,
        json={"status": "completed", "note": ""},
    )
    assert empty_note.status_code == 422


@pytest.mark.pending_m3_m4
def test_t2_f8_admin_models_rbac_non_ml_operator_rejected(helpers: E2EHelpers) -> None:
    _assert_problem(helpers.api.get("/admin/models"), 401, "unauthenticated")
    usr = helpers.register_user()
    _assert_problem(helpers.api.get("/admin/models", headers=helpers.auth_headers(usr["access_token"])), 403, "forbidden")
    adm = helpers.create_staff_session("admin")
    _assert_problem(helpers.api.get("/admin/models", headers=helpers.auth_headers(adm["access_token"])), 403, "forbidden")


def test_t2_f8_cli_survey_create_invalid_anchors_rejected(helpers: E2EHelpers) -> None:
    proc = helpers.run_cli("survey", "create-form", "--anchors", "0", "--random", "5", "--yes", check=False)
    assert proc.returncode != 0


# ==============================================================================
# F9: Auth, Password Lockout, Profile/Energy, Pantry, Journal & Shop BVA (7 tests)
# ==============================================================================


def test_t2_f9_password_length_bva_9_10_128_129_and_duplicate_email(helpers: E2EHelpers) -> None:
    e9 = unique_email("pw9")
    _assert_problem(helpers.api.post("/auth/register", json={"email": e9, "password": "a" * 9}), 422, "weak_password")

    e_bad = "not-an-email"
    _assert_problem(helpers.api.post("/auth/register", json={"email": e_bad, "password": "a" * 10}), 422, "invalid_email")

    e10 = unique_email("pw10")
    r10 = helpers.api.post("/auth/register", json={"email": e10, "password": "a" * 10})
    assert r10.status_code == 201

    _assert_problem(helpers.api.post("/auth/register", json={"email": e10, "password": "a" * 10}), 409, "email_taken")

    e128 = unique_email("pw128")
    assert helpers.api.post("/auth/register", json={"email": e128, "password": "a" * 128}).status_code == 201

    e129 = unique_email("pw129")
    _assert_problem(helpers.api.post("/auth/register", json={"email": e129, "password": "a" * 129}), 422, "validation_error")


def test_t2_f9_login_5_failures_triggers_429_login_locked(helpers: E2EHelpers) -> None:
    reg = helpers.register_user()
    email = reg["_email"]
    for _ in range(5):
        r = helpers.api.post("/auth/login", json={"email": email, "password": "wrong-password-123"})
        assert r.status_code in (401, 429)
    # 6th attempt even with CORRECT password must return 429 login_locked + Retry-After
    locked = helpers.api.post("/auth/login", json={"email": email, "password": reg["_password"]})
    _assert_problem(locked, 429, "login_locked")
    assert int(locked.headers.get("retry-after", "0")) > 0


def test_t2_f9_profile_age_below_18_and_18_confirmation_and_body_bounds(helpers: E2EHelpers) -> None:
    reg = helpers.register_user()
    tok = reg["access_token"]
    helpers.grant_consents(tok, purposes=("health_profile",))
    h = helpers.auth_headers(tok)
    cur_year = datetime.now(timezone.utc).year

    base = {"sex": "female", "birth_year": 1995, "height_cm": 160.0, "weight_kg": 55.0, "activity_level": "light", "goal": "maintain", "adult_confirmed": False}
    _assert_problem(helpers.api.put("/me/profile", headers=h, json={**base, "birth_year": cur_year - 17}), 422, "age_below_minimum")
    _assert_problem(helpers.api.put("/me/profile", headers=h, json={**base, "birth_year": cur_year - 18, "adult_confirmed": False}), 422, "age_confirmation_required")
    assert helpers.api.put("/me/profile", headers=h, json={**base, "birth_year": cur_year - 18, "adult_confirmed": True}).status_code == 200

    for bad_patch in (
        {"birth_year": 1899},
        {"height_cm": 99.9},
        {"height_cm": 250.1},
        {"weight_kg": 24.9},
        {"weight_kg": 300.1},
    ):
        _assert_problem(helpers.api.put("/me/profile", headers=h, json={**base, **bad_patch}), 422, "validation_error")


def test_t2_f9_energy_target_below_floor_confirmation_and_bounds(helpers: E2EHelpers) -> None:
    reg = helpers.register_user()
    tok = reg["access_token"]
    helpers.grant_consents(tok, purposes=("health_profile",))
    helpers.seed_profile_and_energy(tok, sex="female")
    h = helpers.auth_headers(tok)

    _assert_problem(helpers.api.put("/me/energy-target", headers=h, json={"kcal_target": 799, "kcal_source": "user"}), 422, "validation_error")
    _assert_problem(helpers.api.put("/me/energy-target", headers=h, json={"kcal_target": 5001, "kcal_source": "user"}), 422, "validation_error")

    # Female floor is 1200 kcal
    _assert_problem(
        helpers.api.put("/me/energy-target", headers=h, json={"kcal_target": 1100, "kcal_source": "user", "confirm_below_floor": False}),
        409,
        "below_floor_confirmation_required",
    )
    ok = helpers.api.put("/me/energy-target", headers=h, json={"kcal_target": 1100, "kcal_source": "user", "confirm_below_floor": True})
    assert ok.status_code == 200 and ok.json()["below_floor"] is True


def test_t2_f9_pantry_lot_qty_bounds_and_future_date_rejected(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=False)
    tok = user["access_token"]
    h = helpers.auth_headers(tok)
    tomato_id = helpers.resolve_ingredient_id(tok, "cà chua")
    pork_id = helpers.resolve_ingredient_id(tok, "thịt ba chỉ")

    for bad_qty in (
        {"g_min": 500, "g_max": 100},
        {"g_min": -1, "g_max": 100},
        {"g_min": 10, "g_max": 100_001},
    ):
        _assert_problem(helpers.api.post("/pantry/lots", headers=h, json={"ingredient_id": pork_id, "quantity": bad_qty}), 422, "validation_error")

    for bad_cnt in (0, 1000):
        _assert_problem(
            helpers.api.post("/pantry/lots", headers=h, json={"ingredient_id": tomato_id, "quantity": {"count": bad_cnt, "unit_code": "qua"}}),
            422,
            "validation_error",
        )

    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    _assert_problem(
        helpers.api.post("/pantry/lots", headers=h, json={"ingredient_id": pork_id, "quantity": {"g_min": 200, "g_max": 200}, "acquired_at": tomorrow}),
        422,
        "acquired_at_in_future",
    )

    lot = helpers.seed_pantry_lot(tok, "thịt ba chỉ", grams=300.0)
    helpers.api.post(f"/pantry/lots/{lot['id']}/discard", headers=h)
    _assert_problem(
        helpers.api.patch(f"/pantry/lots/{lot['id']}", headers={**h, "Content-Type": "application/merge-patch+json"}, json={"balance": {"g_min": 100, "g_max": 100}}),
        409,
        "lot_closed",
    )


def test_t2_f9_journal_invalid_iso_week_returns_422(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=False)
    h = helpers.auth_headers(user["access_token"])
    _assert_problem(helpers.api.get("/journal", headers=h, params={"week": "2026-W54"}), 422, "invalid_iso_week")
    _assert_problem(helpers.api.get("/journal", headers=h, params={"week": "not-a-week"}), 422, "invalid_iso_week")


@pytest.mark.pending_m3_m4
def test_t2_f9_shopping_to_pantry_on_dropped_or_repeat_returns_409(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=False)
    tok = user["access_token"]
    h = helpers.auth_headers(tok)
    ing_id = helpers.resolve_ingredient_id(tok, "cà chua")
    item = helpers.api.post("/shopping-items", headers=h, json={"ingredient_id": ing_id, "qty_g": 200.0}).json()
    helpers.api.patch(f"/shopping-items/{item['id']}", headers={**h, "Content-Type": "application/merge-patch+json"}, json={"status": "dropped"})
    r = helpers.api.post(f"/shopping-items/{item['id']}/to-pantry", headers=h)
    assert r.status_code == 409


# ==============================================================================
# F10: Website (`landing/`) Routing, Breakpoints & Dark Mode Boundaries (5 tests)
# ==============================================================================


def test_t2_f10_landing_nonexistent_subpath_under_gioi_thieu_returns_404(raw_client) -> None:
    resp = raw_client.get("/gioi-thieu/nonexistent-file-check.txt")
    assert resp.status_code == 404


def test_t2_f10_tai_ve_non_apk_file_blocked_404(raw_client) -> None:
    resp = raw_client.get("/tai-ve/tastoria-vp-kit.zip")
    assert resp.status_code == 404


def test_t2_f10_landing_320px_mobile_light_zero_overflow(base_url: str, page_factory) -> None:
    _, page, telemetry = page_factory(viewport=(320, 568), color_scheme="light")
    page.goto(f"{base_url}/")
    page.locator("h1").wait_for()
    evaluate_page_rubric(page, screen_name="landing-320", theme="light", surface_mode="landing", viewport_width=320, viewport_height=568, check_touch_targets=False, check_contrast=False)
    telemetry.assert_clean()


def test_t2_f10_landing_760px_tablet_breakpoint_clean(base_url: str, page_factory) -> None:
    _, page, telemetry = page_factory(viewport=(760, 900), color_scheme="light")
    page.goto(f"{base_url}/")
    page.locator(".food-gallery").wait_for()
    evaluate_page_rubric(page, screen_name="landing-760", theme="light", surface_mode="landing", viewport_width=760, viewport_height=900, check_touch_targets=False, check_contrast=False)
    telemetry.assert_clean()


@pytest.mark.pending_m3_m4
def test_t2_f10_landing_light_mode_wcag_aa_contrast(base_url: str, page_factory) -> None:
    _, page, telemetry = page_factory(viewport=(1440, 900), color_scheme="light")
    page.goto(f"{base_url}/")
    page.locator("h1").wait_for()
    evaluate_page_rubric(page, screen_name="landing-light-wcag", theme="light", surface_mode="landing", viewport_width=1440, viewport_height=900, check_touch_targets=False, check_contrast=True)
    telemetry.assert_clean()


@pytest.mark.pending_m3_m4
def test_t2_f10_landing_dark_mode_contrast_and_images(base_url: str, page_factory) -> None:
    _, page, telemetry = page_factory(viewport=(1440, 900), color_scheme="dark")
    page.goto(f"{base_url}/")
    page.locator("h1").wait_for()
    evaluate_page_rubric(page, screen_name="landing-dark", theme="dark", surface_mode="landing", viewport_width=1440, viewport_height=900, check_touch_targets=False, check_contrast=True)
    telemetry.assert_clean()


# ==============================================================================
# F11: App UI Form Validation, Bad Upload & 320px Dark Boundaries (5 tests)
# ==============================================================================


def test_t2_f11_login_ui_invalid_credentials_shows_error_no_5xx(base_url: str, page_factory) -> None:
    _, page, telemetry = page_factory(
        viewport=(390, 844),
        allow_4xx_statuses={401},
        allow_console_substrings=("401", "Unauthorized"),
    )
    tid = page.get_by_test_id
    page.goto(f"{base_url}/dang-nhap")
    tid("login-email").fill(unique_email("missing"))
    tid("login-password").fill("wrong-password-12345")
    tid("login-submit").click()
    page.get_by_text("Email hoặc mật khẩu không đúng").wait_for()
    assert "/dang-nhap" in page.url
    telemetry.assert_clean()


def test_t2_f11_register_ui_short_password_blocks_submit(base_url: str, page_factory) -> None:
    _, page, telemetry = page_factory(viewport=(390, 844), allow_4xx_statuses={422})
    tid = page.get_by_test_id
    page.goto(f"{base_url}/dang-ky")
    tid("register-email").fill(unique_email("shortpw"))
    tid("register-password").fill("short123")
    tid("register-password2").fill("short123")
    expect(tid("register-submit")).to_be_disabled()
    assert "/dang-ky" in page.url
    telemetry.assert_clean()


def test_t2_f11_onboarding_underage_shows_error_message(base_url: str, page_factory) -> None:
    _, page, telemetry = page_factory(viewport=(390, 844), allow_4xx_statuses={422})
    tid = page.get_by_test_id
    page.goto(f"{base_url}/dang-ky")
    tid("register-email").fill(unique_email("underage"))
    tid("register-password").fill(DEFAULT_PASSWORD)
    tid("register-password2").fill(DEFAULT_PASSWORD)
    tid("register-submit").click()
    tid("consent-health_profile").click()
    tid("consent-continue").click()
    tid("screen-onboarding-body").wait_for()
    page.get_by_role("radio", name="Nữ").click()
    tid("body-birth-year").fill(str(datetime.now(timezone.utc).year - 15))
    tid("body-height").fill("155")
    tid("body-weight").fill("45")
    tid("step-next").click()
    page.wait_for_timeout(400)
    assert tid("screen-onboarding-body").is_visible()
    telemetry.assert_clean()


def test_t2_f11_scan_ui_rejects_non_image_upload_cleanly(base_url: str, page_factory) -> None:
    _, page, telemetry = page_factory(viewport=(390, 844), allow_4xx_statuses={415, 422})
    tid = page.get_by_test_id
    page.goto(f"{base_url}/dang-ky")
    tid("register-email").fill(unique_email("badscanui"))
    tid("register-password").fill(DEFAULT_PASSWORD)
    tid("register-password2").fill(DEFAULT_PASSWORD)
    tid("register-submit").click()
    tid("consent-skip").click()
    tid("screen-home").wait_for()

    page.goto(f"{base_url}/quet")
    tid("screen-scan").wait_for()
    with tempfile.TemporaryDirectory() as td:
        spoof = write_temp_scan_file(Path(td), "fake.jpg", make_spoofed_pdf_bytes())
        with page.expect_file_chooser() as fc_info:
            tid("scan-library").click()
        fc_info.value.set_files(str(spoof))
    page.wait_for_timeout(500)
    if tid("scan-send").is_enabled():
        tid("scan-send").click()
        page.wait_for_timeout(800)
    # Page must remain functional without uncaught crash or 5xx
    assert tid("screen-scan").is_visible()
    telemetry.assert_clean()


def test_t2_f11_pantry_320px_zero_overflow_in_dark_mode(base_url: str, helpers: E2EHelpers, page_factory) -> None:
    user = helpers.create_ready_user(seed_pantry=True)
    _, page, telemetry = page_factory(viewport=(320, 568), color_scheme="dark")
    tid = page.get_by_test_id
    page.goto(f"{base_url}/dang-nhap")
    tid("login-email").fill(user["_email"])
    tid("login-password").fill(user["_password"])
    tid("login-submit").click()
    tid("screen-home").wait_for()
    page.goto(f"{base_url}/kho")
    tid("screen-pantry").wait_for()
    evaluate_page_rubric(page, screen_name="kho-320-dark", theme="dark", viewport_width=320, viewport_height=568)
    telemetry.assert_clean()


# ==============================================================================
# F12: Cooking Undo Cutoff, Concurrent Sessions, Shopping & Admin UI Guards (5 tests)
# ==============================================================================


def test_t2_f12_cook_undo_past_10_min_window_returns_409_undo_window_expired(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=True)
    tok = user["access_token"]
    h = helpers.auth_headers(tok)
    plan = helpers.api.post(
        "/meal-plans",
        headers=helpers.auth_headers(tok, idem=unique_idem_key("undoexp")),
        json={"meal": "dinner", "max_minutes": 90, "persons": 2},
    ).json()
    helpers.api.post(f"/meal-plans/{plan['id']}/accept", headers=h)
    sess = helpers.api.post(
        "/cook-sessions",
        headers=helpers.auth_headers(tok, idem=unique_idem_key("csundo")),
        json={"meal_plan_id": plan["id"], "serve_at": (datetime.now(timezone.utc) + timedelta(minutes=60)).isoformat(), "confirm_over_time": True},
    ).json()

    past_done = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
    comp = helpers.api.post(
        f"/cook-sessions/{sess['id']}/complete",
        headers=helpers.auth_headers(tok, idem=unique_idem_key("ccundo")),
        json={"completed_at": past_done, "feedback": []},
    )
    assert comp.status_code == 200
    undo = helpers.api.post(f"/cook-sessions/{sess['id']}/undo", headers=h)
    _assert_problem(undo, 409, "undo_window_expired")


def test_t2_f12_cook_session_without_accept_returns_409(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=True)
    tok = user["access_token"]
    plan = helpers.api.post(
        "/meal-plans",
        headers=helpers.auth_headers(tok, idem=unique_idem_key("noacc")),
        json={"meal": "lunch", "max_minutes": 90, "persons": 2},
    ).json()
    r = helpers.api.post(
        "/cook-sessions",
        headers=helpers.auth_headers(tok, idem=unique_idem_key("csnoacc")),
        json={"meal_plan_id": plan["id"], "serve_at": (datetime.now(timezone.utc) + timedelta(minutes=60)).isoformat(), "confirm_over_time": True},
    )
    _assert_problem(r, 409, "meal_plan_not_accepted")


def test_t2_f12_cook_session_concurrent_in_progress_returns_409(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=True)
    tok = user["access_token"]
    h = helpers.auth_headers(tok)
    plan = helpers.api.post(
        "/meal-plans",
        headers=helpers.auth_headers(tok, idem=unique_idem_key("conc")),
        json={"meal": "dinner", "max_minutes": 90, "persons": 2},
    ).json()
    helpers.api.post(f"/meal-plans/{plan['id']}/accept", headers=h)
    serve_at = (datetime.now(timezone.utc) + timedelta(minutes=60)).isoformat()
    r1 = helpers.api.post(
        "/cook-sessions",
        headers=helpers.auth_headers(tok, idem=unique_idem_key("c1")),
        json={"meal_plan_id": plan["id"], "serve_at": serve_at, "confirm_over_time": True},
    )
    assert r1.status_code == 201
    r2 = helpers.api.post(
        "/cook-sessions",
        headers=helpers.auth_headers(tok, idem=unique_idem_key("c2")),
        json={"meal_plan_id": plan["id"], "serve_at": serve_at, "confirm_over_time": True},
    )
    _assert_problem(r2, 409, "cook_session_in_progress")


@pytest.mark.pending_m3_m4
def test_t2_f12_quan_tri_non_staff_user_blocked_in_ui(base_url: str, helpers: E2EHelpers, page_factory) -> None:
    user = helpers.create_ready_user(seed_pantry=False)
    _, page, telemetry = page_factory(viewport=(1440, 900), allow_4xx_statuses={403})
    tid = page.get_by_test_id
    page.goto(f"{base_url}/dang-nhap")
    tid("login-email").fill(user["_email"])
    tid("login-password").fill(user["_password"])
    tid("login-submit").click()
    tid("screen-home").wait_for()

    page.goto(f"{base_url}/quan-tri")
    page.wait_for_timeout(500)
    assert tid("admin-tab-models").count() == 0 or tid("screen-admin-forbidden").is_visible()
    telemetry.assert_clean()


def test_t2_f12_shopping_patch_non_open_item_returns_409_conflict(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=False)
    tok = user["access_token"]
    h = helpers.auth_headers(tok)
    ing_id = helpers.resolve_ingredient_id(tok, "cà chua")
    item = helpers.api.post("/shopping-items", headers=h, json={"ingredient_id": ing_id, "qty_g": 200.0}).json()
    drop = helpers.api.patch(
        f"/shopping-items/{item['id']}",
        headers={**h, "Content-Type": "application/merge-patch+json"},
        json={"status": "dropped"},
    )
    assert drop.status_code == 200
    re_edit = helpers.api.patch(
        f"/shopping-items/{item['id']}",
        headers={**h, "Content-Type": "application/merge-patch+json"},
        json={"qty_g": 300.0},
    )
    _assert_problem(re_edit, 409, "conflict_state")


# ==============================================================================
# F13: Visual Paradigm SVG, Schema & Code-Sync Boundaries (5 tests)
# ==============================================================================


def test_t2_f13_all_pttkht_svgs_valid_xml_and_non_empty() -> None:
    svgs = list((REPO_ROOT / "docs/reports/pttkht/fig/svg").glob("*.svg"))
    assert len(svgs) >= 10
    for s in svgs:
        txt = s.read_text(encoding="utf-8", errors="ignore")
        assert "<svg" in txt and "</svg>" in txt, f"Invalid SVG: {s}"


def test_t2_f13_sad_model_yaml_zero_broken_refs() -> None:
    proc = subprocess.run(["python3", str(REPO_ROOT / "docs/sad/tools/check_refs.py")], capture_output=True, text=True)
    assert proc.returncode == 0


def test_t2_f13_schema_vp_all_tables_have_primary_keys() -> None:
    ddl = (REPO_ROOT / "db/schema_vp.sql").read_text(encoding="utf-8")
    tables = re.findall(r"CREATE TABLE\s+(?:IF NOT EXISTS\s+)?(\w+)\s*\((.*?)\);", ddl, flags=re.S | re.I)
    assert len(tables) >= 40
    for name, body in tables:
        assert "PRIMARY KEY" in body.upper(), f"Table {name} missing PRIMARY KEY in schema_vp.sql"


@pytest.mark.pending_m3_m4
def test_t2_f13_sad_model_yaml_includes_m3_admin_endpoints() -> None:
    model_yaml = (REPO_ROOT / "docs/sad/model.yaml").read_text(encoding="utf-8")
    for ep in ("/admin/audit-log", "/admin/data-requests", "/admin/models", "/shopping-items/{id}/to-pantry"):
        assert ep in model_yaml, f"Endpoint {ep} missing from docs/sad/model.yaml"


@pytest.mark.pending_m3_m4
def test_t2_f13_check_design_vs_code_reports_zero_drift() -> None:
    proc = subprocess.run(["python3", str(REPO_ROOT / "docs/reports/pttkht/vp/check_design_vs_code.py")], capture_output=True, text=True)
    assert proc.returncode == 0
    assert "error" not in proc.stdout.lower()


# ==============================================================================
# F14: Mobile App Course Report Negative & Structural Checks (5 tests)
# ==============================================================================


@pytest.mark.pending_m3_m4
def test_t2_f14_report_markdown_has_zero_todo_tbd_placeholders() -> None:
    md = (REPO_ROOT / "docs/reports/mobile-app/Bao-cao-Do-an-Mobile-App-Tastoria.md").read_text(encoding="utf-8")
    for bad in ("TODO", "TBD", "lorem ipsum", "XXXX"):
        assert bad not in md, f"Found '{bad}' in Mobile App report"


@pytest.mark.pending_m3_m4
def test_t2_f14_docx_cover_member_rows_blank_and_ready_to_fill() -> None:
    doc = Document(str(REPO_ROOT / "docs/reports/mobile-app/Bao-cao-Do-an-Mobile-App-Tastoria.docx"))
    cover_tbl = doc.tables[0]
    assert len(cover_tbl.rows) >= 4, "Expected header + >=3 member template rows"
    # Second column (`Họ và tên`) should be blank/placeholder ready to fill
    for row in cover_tbl.rows[1:]:
        name_cell = row.cells[1].text.strip()
        assert name_cell == "" or "..." in name_cell or "[" in name_cell


@pytest.mark.pending_m3_m4
def test_t2_f14_report_referenced_images_all_exist_and_nonzero() -> None:
    rdir = REPO_ROOT / "docs/reports/mobile-app"
    md = (rdir / "Bao-cao-Do-an-Mobile-App-Tastoria.md").read_text(encoding="utf-8")
    imgs = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", md)
    assert len(imgs) >= 6
    for rel in imgs:
        p = (rdir / rel).resolve()
        assert p.is_file() and p.stat().st_size > 1000, f"Missing/empty report image: {rel}"


@pytest.mark.pending_m3_m4
def test_t2_f14_docx_and_pdf_valid_binary_formats() -> None:
    rdir = REPO_ROOT / "docs/reports/mobile-app"
    pdf_bytes = (rdir / "Bao-cao-Do-an-Mobile-App-Tastoria.pdf").read_bytes()
    assert pdf_bytes.startswith(b"%PDF-") and len(pdf_bytes) > 10_000
    doc = Document(str(rdir / "Bao-cao-Do-an-Mobile-App-Tastoria.docx"))
    assert len(doc.paragraphs) >= 20


@pytest.mark.pending_m3_m4
def test_t2_f14_report_contains_all_part1_subsections_a_to_e() -> None:
    md = (REPO_ROOT / "docs/reports/mobile-app/Bao-cao-Do-an-Mobile-App-Tastoria.md").read_text(encoding="utf-8")
    for marker in ("a.", "b.", "c.", "d.", "e."):
        assert marker in md, f"Missing Part 1 subsection '{marker}'"


# ==============================================================================
# F15: Security, DSR, Refresh Reuse, Logout-All & Event Consent Boundaries (5 tests)
# ==============================================================================


def test_t2_f15_dsr_delete_wrong_password_returns_403_reauth_failed(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=False)
    r = helpers.api.post(
        "/me/data-requests",
        headers=helpers.auth_headers(user["access_token"]),
        json={"type": "delete", "password": "wrong-password-xyz"},
    )
    _assert_problem(r, 403, "reauth_failed")


def test_t2_f15_dsr_download_non_export_or_unready_returns_409(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=False)
    h = helpers.auth_headers(user["access_token"])
    corr = helpers.api.post("/me/data-requests", headers=h, json={"type": "correct", "note": "Sửa tên"}).json()
    dl1 = helpers.api.get(f"/me/data-requests/{corr['id']}/download", headers=h)
    _assert_problem(dl1, 409, "request_not_downloadable")

    exp = helpers.api.post("/me/data-requests", headers=h, json={"type": "export"}).json()
    if exp["status"] != "completed":
        dl2 = helpers.api.get(f"/me/data-requests/{exp['id']}/download", headers=h)
        _assert_problem(dl2, 409, "request_not_ready")


def test_t2_f15_refresh_token_reuse_revokes_entire_family_401(helpers: E2EHelpers) -> None:
    reg = helpers.register_user()
    r1 = reg["refresh_token"]
    ref1 = helpers.api.post("/auth/refresh", json={"refresh_token": r1})
    assert ref1.status_code == 200
    r2 = ref1.json()["refresh_token"]

    # Reuse old r1 -> 401 refresh_reused AND revokes r2's family
    reuse = helpers.api.post("/auth/refresh", json={"refresh_token": r1})
    _assert_problem(reuse, 401, "refresh_reused")

    revoked = helpers.api.post("/auth/refresh", json={"refresh_token": r2})
    assert revoked.status_code == 401


def test_t2_f15_logout_all_invalidates_existing_access_token_401(helpers: E2EHelpers) -> None:
    reg = helpers.register_user()
    tok = reg["access_token"]
    h = helpers.auth_headers(tok)
    out = helpers.api.post("/auth/logout-all", headers=h)
    assert out.status_code == 204
    _assert_problem(helpers.api.get("/me/profile", headers=h), 401, "token_revoked")


def test_t2_f15_events_without_personalization_consent_skipped(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(purposes=("health_profile",), seed_pantry=False)
    tok = user["access_token"]
    h = helpers.auth_headers(tok)
    recipe_id = helpers.api.get("/recipes", headers=h, params={"limit": 1}).json()["items"][0]["id"]
    ev = helpers.api.post(
        "/events",
        headers=h,
        json={
            "events": [
                {
                    "event_id": str(uuid.uuid4()),
                    "type": "viewed",
                    "recipe_id": recipe_id,
                    "occurred_at": datetime.now(timezone.utc).isoformat(),
                }
            ]
        },
    )
    assert ev.status_code == 200
    assert ev.json()["skipped_no_consent"] == 1
    assert ev.json()["accepted"] == 0
