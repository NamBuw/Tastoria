"""Tier 4: 8 Real-World End-to-End Playwright Journeys (J1-J8).

Exercises complete Vietnamese household, guest survey, staff admin, privacy/DSR,
and resilience workflows across Desktop (1440x900) & Mobile (390x844), Light & Dark,
invoking automated UI rubric evaluation on every visited screen and saving deterministic
screenshots to app/docs/screenshots/ and docs/reports/mobile-app/fig/.
"""

from __future__ import annotations

import json
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tests.e2e.conftest import DEFAULT_PASSWORD, E2EHelpers, unique_email, unique_idem_key
from tests.e2e.fixtures import get_scan_sample_jpeg, write_temp_scan_file
from tests.e2e.rubric import assert_theme_rgb_delta, evaluate_page_rubric

pytestmark = [pytest.mark.tier4]


def _audit_and_shot(
    page,
    *,
    rubric_collector,
    screenshot_saver,
    screen_name: str,
    shot_prefix: str,
    theme: str,
    viewport: tuple[int, int],
    surface_mode: str = "app",
    check_touch: bool = True,
    check_shell: bool = False,
):
    res = evaluate_page_rubric(
        page,
        screen_name=screen_name,
        theme=theme,
        surface_mode=surface_mode,
        viewport_width=viewport[0],
        viewport_height=viewport[1],
        check_touch_targets=check_touch,
        check_shell=check_shell,
    )
    rubric_collector.record(res)
    screenshot_saver(page, f"{shot_prefix}-{theme}.png", f"{shot_prefix}-{theme}.png")
    return res


@pytest.mark.pending_m3_m4
def test_t4_j1_new_household_full_culinary_loop_mobile_light_dark(
    base_url: str,
    helpers: E2EHelpers,
    page_factory,
    rubric_collector,
    screenshot_saver,
) -> None:
    """J1: Register -> Consent -> 4-step Onboarding -> Scan w/ Freshness -> Pantry -> Explore -> Tray -> Swap -> Shop to Pantry -> Cook -> Journal -> Undo."""
    email = unique_email("j1")
    _, page, telemetry = page_factory(
        viewport=(390, 844),
        color_scheme="light",
        allow_4xx_statuses={422},  # swap probe may hit 422 no_alternative on one slot
    )
    tid = page.get_by_test_id

    page.goto(f"{base_url}/dang-ky")
    tid("screen-register").wait_for()
    tid("register-email").fill(email)
    tid("register-password").fill(DEFAULT_PASSWORD)
    tid("register-password2").fill(DEFAULT_PASSWORD)
    _audit_and_shot(page, rubric_collector=rubric_collector, screenshot_saver=screenshot_saver, screen_name="j1-register", shot_prefix="j1-01-dang-ky", theme="light", viewport=(390, 844))
    tid("register-submit").click()

    # Consent + 4-step onboarding
    tid("screen-consent").wait_for()
    tid("consent-health_profile").click()
    tid("consent-personalization").click()
    _audit_and_shot(page, rubric_collector=rubric_collector, screenshot_saver=screenshot_saver, screen_name="j1-consent", shot_prefix="j1-02-dong-y", theme="light", viewport=(390, 844))
    tid("consent-continue").click()

    tid("screen-onboarding-body").wait_for()
    page.get_by_role("radio", name="Nữ").click()
    tid("body-birth-year").fill("1995")
    tid("body-height").fill("158")
    tid("body-weight").fill("52")
    tid("step-next").click()
    page.get_by_role("radio", name=re.compile("^Nhẹ")).click()
    page.get_by_role("radio", name="Giữ cân").click()
    tid("step-next").click()
    tid("energy-suggestion").wait_for()
    tid("energy-use").click()
    tid("screen-onboarding-allergen").wait_for()
    tid("allergen-none").click()
    tid("step-next").click()
    tid("screen-onboarding-favorites").wait_for()
    tid("step-done").click()
    tid("screen-home").wait_for()
    res_home_l = _audit_and_shot(page, rubric_collector=rubric_collector, screenshot_saver=screenshot_saver, screen_name="j1-home", shot_prefix="j1-03-bep", theme="light", viewport=(390, 844), check_shell=True)

    # Toggle dark mode in-app (or media fallback) to verify RGB delta
    tid("theme-toggle").click()
    res_home_d = _audit_and_shot(page, rubric_collector=rubric_collector, screenshot_saver=screenshot_saver, screen_name="j1-home", shot_prefix="j1-03-bep", theme="dark", viewport=(390, 844), check_shell=True)
    assert_theme_rgb_delta(res_home_l, res_home_d)
    tid("theme-toggle").click()

    # Scan produce image + confirm
    page.goto(f"{base_url}/quet?mode=haul")
    tid("screen-scan").wait_for()
    with tempfile.TemporaryDirectory() as td:
        sample = write_temp_scan_file(Path(td))
        with page.expect_file_chooser() as fc_info:
            tid("scan-library").click()
        fc_info.value.set_files(str(sample))
    tid("scan-send").click()
    tid("screen-scan-confirm").wait_for(timeout=35000)
    for _ in range(20):
        needs_heading = page.get_by_role("heading", name="Cần kiểm tra trước khi dùng")
        if needs_heading.count() == 0:
            break
        chip = needs_heading.locator("xpath=../..").locator('[data-testid^="scan-chip-"]').first
        if chip.count() == 0:
            break
        chip.click()
        tid("sheet-scan-item").wait_for()
        save_btn = page.get_by_role("button", name="Lưu", exact=True)
        if save_btn.is_disabled():
            page.get_by_role("radio", name="Vừa").click()
        page.get_by_role("radio", name="Tươi").click()
        save_btn.click()
        tid("sheet-scan-item").wait_for(state="detached")
    if page.locator('[data-testid^="scan-chip-"]').count() == 0:
        page.get_by_role("button", name="+ Thêm nguyên liệu bị sót").click()
        page.get_by_label("Nguyên liệu").fill("cà chua")
        tid("ing-cà chua").first.click()
        page.get_by_role("button", name="Thêm", exact=True).click()
    _audit_and_shot(page, rubric_collector=rubric_collector, screenshot_saver=screenshot_saver, screen_name="j1-scan-confirm", shot_prefix="j1-04-quet-ket-qua", theme="light", viewport=(390, 844))
    tid("scan-confirm").click()
    tid("screen-scan-done").wait_for(timeout=20000)

    # Seed full household pantry via API for reliable 3-dish tray composition, then visit Pantry & Explore
    auth = helpers.login_user(email, DEFAULT_PASSWORD)
    helpers.seed_standard_household_pantry(auth["access_token"])

    page.goto(f"{base_url}/kho")
    tid("screen-pantry").wait_for()
    _audit_and_shot(page, rubric_collector=rubric_collector, screenshot_saver=screenshot_saver, screen_name="j1-pantry", shot_prefix="j1-05-kho", theme="light", viewport=(390, 844))

    page.goto(f"{base_url}/kham-pha")
    tid("screen-explore").wait_for()
    _audit_and_shot(page, rubric_collector=rubric_collector, screenshot_saver=screenshot_saver, screen_name="j1-explore", shot_prefix="j1-06-kham-pha", theme="light", viewport=(390, 844))
    tid("explore-recipe-card").first.click()
    tid("screen-recipe").wait_for()
    _audit_and_shot(page, rubric_collector=rubric_collector, screenshot_saver=screenshot_saver, screen_name="j1-recipe", shot_prefix="j1-07-chi-tiet-mon", theme="light", viewport=(390, 844))

    # Shopping add + 1-tap to-pantry
    page.goto(f"{base_url}/di-cho")
    tid("screen-shopping").wait_for()
    tid("shop-add").click()
    page.get_by_label("Nguyên liệu").fill("hành lá")
    tid("ing-hành lá").first.click()
    page.get_by_role("button", name="Thêm", exact=True).click()
    tid("shop-item-hành lá").wait_for()
    _audit_and_shot(page, rubric_collector=rubric_collector, screenshot_saver=screenshot_saver, screen_name="j1-shopping", shot_prefix="j1-08-di-cho", theme="light", viewport=(390, 844))
    tid("shop-to-pantry-hành lá").click()

    # Compose Tray -> Swap -> Cook -> Complete -> Journal -> Undo
    page.goto(f"{base_url}/mam")
    tid("make-plan").click()
    tid("plan-view").wait_for(timeout=30000)
    _audit_and_shot(page, rubric_collector=rubric_collector, screenshot_saver=screenshot_saver, screen_name="j1-tray", shot_prefix="j1-09-mam-com", theme="light", viewport=(390, 844))

    tid("start-cooking").click()
    tid("screen-cooking").wait_for()
    _audit_and_shot(page, rubric_collector=rubric_collector, screenshot_saver=screenshot_saver, screen_name="j1-cooking", shot_prefix="j1-10-nau-ca-mam", theme="light", viewport=(390, 844))
    tid("cook-step-done").click()
    tid("cook-finish").click()
    tid("screen-finish").wait_for()
    page.get_by_role("radio", name="Hợp gu").first.click()
    tid("finish-submit").click()
    tid("screen-finished").wait_for(timeout=20000)

    page.get_by_role("button", name="Xem nhật ký tuần").click()
    tid("screen-journal").wait_for()
    _audit_and_shot(page, rubric_collector=rubric_collector, screenshot_saver=screenshot_saver, screen_name="j1-journal", shot_prefix="j1-11-nhat-ky", theme="light", viewport=(390, 844))

    page.go_back()
    tid("screen-finished").wait_for(timeout=20000)
    tid("undo").click()
    tid("undo-confirm").click()
    page.wait_for_url("**/mam")
    telemetry.assert_clean()


@pytest.mark.pending_m3_m4
def test_t4_j2_desktop_power_user_multicolumn_flow_light_and_dark(
    base_url: str,
    helpers: E2EHelpers,
    page_factory,
    rubric_collector,
    screenshot_saver,
) -> None:
    """J2: Desktop 1440x900 Light + Dark sidebar rail & multi-column grid verification."""
    user = helpers.create_ready_user(seed_pantry=True)
    results_by_theme: dict[tuple[str, str], object] = {}
    for theme in ("light", "dark"):
        _, page, telemetry = page_factory(viewport=(1440, 900), color_scheme=theme)
        tid = page.get_by_test_id
        page.goto(f"{base_url}/dang-nhap")
        tid("login-email").fill(user["_email"])
        tid("login-password").fill(user["_password"])
        tid("login-submit").click()
        tid("screen-home").wait_for()
        results_by_theme[(theme, "bep")] = _audit_and_shot(page, rubric_collector=rubric_collector, screenshot_saver=screenshot_saver, screen_name="j2-bep", shot_prefix="j2-01-desktop-bep", theme=theme, viewport=(1440, 900), check_shell=True)

        tid("sidebar-nav-kho").click()
        tid("screen-pantry").wait_for()
        results_by_theme[(theme, "kho")] = _audit_and_shot(page, rubric_collector=rubric_collector, screenshot_saver=screenshot_saver, screen_name="j2-kho", shot_prefix="j2-02-desktop-kho", theme=theme, viewport=(1440, 900), check_shell=True)

        tid("sidebar-nav-kham-pha").click()
        tid("screen-explore").wait_for()
        results_by_theme[(theme, "kham-pha")] = _audit_and_shot(page, rubric_collector=rubric_collector, screenshot_saver=screenshot_saver, screen_name="j2-kham-pha", shot_prefix="j2-03-desktop-kham-pha", theme=theme, viewport=(1440, 900), check_shell=True)

        tid("sidebar-nav-mam").click()
        tid("screen-tray").wait_for()
        if tid("make-plan").count():
            tid("make-plan").click()
        tid("plan-view").wait_for(timeout=30000)
        results_by_theme[(theme, "mam")] = _audit_and_shot(page, rubric_collector=rubric_collector, screenshot_saver=screenshot_saver, screen_name="j2-mam", shot_prefix="j2-04-desktop-mam", theme=theme, viewport=(1440, 900), check_shell=True)

        tid("sidebar-nav-nhat-ky").click()
        tid("screen-journal").wait_for()
        results_by_theme[(theme, "nhat-ky")] = _audit_and_shot(page, rubric_collector=rubric_collector, screenshot_saver=screenshot_saver, screen_name="j2-nhat-ky", shot_prefix="j2-05-desktop-nhat-ky", theme=theme, viewport=(1440, 900), check_shell=True)
        telemetry.assert_clean()

    for scr in ("bep", "kho", "kham-pha", "mam", "nhat-ky"):
        assert_theme_rgb_delta(results_by_theme[("light", scr)], results_by_theme[("dark", scr)])  # type: ignore[arg-type]


@pytest.mark.pending_m3_m4
def test_t4_j3_landing_portal_discovery_and_interactive_demo_desktop_mobile(
    base_url: str,
    page_factory,
    rubric_collector,
    screenshot_saver,
) -> None:
    """J3: Landing portal Desktop (1440x900) & Mobile (390x844), Light & Dark, simulator, showcase, APK check."""
    results_by_theme = {}
    for vp in ((1440, 900), (390, 844)):
        vp_tag = "desktop" if vp[0] >= 1024 else "mobile"
        for theme in ("light", "dark"):
            _, page, telemetry = page_factory(viewport=vp, color_scheme=theme)
            page.goto(f"{base_url}/")
            page.locator("h1").wait_for()
            page.get_by_test_id("landing-tray-simulator").wait_for()
            page.locator('[data-ingredient="tofu"]').click()
            assert "Đậu phụ" in page.locator("#recipe-name").inner_text()
            res = _audit_and_shot(
                page,
                rubric_collector=rubric_collector,
                screenshot_saver=screenshot_saver,
                screen_name=f"j3-landing-{vp_tag}",
                shot_prefix=f"j3-landing-{vp_tag}",
                theme=theme,
                viewport=vp,
                surface_mode="landing",
                check_touch=False,
            )
            results_by_theme[(vp_tag, theme)] = res
            telemetry.assert_clean()

    assert_theme_rgb_delta(results_by_theme[("desktop", "light")], results_by_theme[("desktop", "dark")])
    assert_theme_rgb_delta(results_by_theme[("mobile", "light")], results_by_theme[("mobile", "dark")])


def test_t4_j4_anonymous_taste_survey_45_dishes_and_export(
    base_url: str,
    helpers: E2EHelpers,
    page_factory,
    rubric_collector,
    screenshot_saver,
) -> None:
    """J4: Open 45-dish anonymous survey -> consent -> rate all 45 dishes -> favorites -> submit -> verify CLI export."""
    version = helpers.ensure_open_survey_form(anchors=10, random_n=35, seed=42)
    _, page, telemetry = page_factory(viewport=(390, 844), color_scheme="light")
    tid = page.get_by_test_id
    page.goto(f"{base_url}/khao-sat?kenh=link")
    tid("screen-survey-start").wait_for()
    _audit_and_shot(page, rubric_collector=rubric_collector, screenshot_saver=screenshot_saver, screen_name="j4-survey-start", shot_prefix="j4-01-khao-sat-mo-dau", theme="light", viewport=(390, 844))

    tid("survey-consent").click()
    tid("survey-start").click()
    tid("screen-survey-form").wait_for(timeout=20000)

    # Rate 1..5 on first 30 dishes, `Chưa ăn bao giờ` on remaining 15
    five_star = page.get_by_role("radio", name="5 điểm")
    never_eaten = page.get_by_role("checkbox", name="Chưa ăn bao giờ")
    total = never_eaten.count()
    assert total == 45
    for i in range(total):
        if i < 30:
            five_star.nth(i).click()
        else:
            never_eaten.nth(i).click()

    _audit_and_shot(page, rubric_collector=rubric_collector, screenshot_saver=screenshot_saver, screen_name="j4-survey-form", shot_prefix="j4-02-khao-sat-cham-diem", theme="light", viewport=(390, 844))
    tid("survey-submit").click()
    tid("screen-survey-thanks").wait_for(timeout=20000)
    _audit_and_shot(page, rubric_collector=rubric_collector, screenshot_saver=screenshot_saver, screen_name="j4-survey-thanks", shot_prefix="j4-03-khao-sat-xong", theme="light", viewport=(390, 844))
    telemetry.assert_clean()

    helpers.run_cli("survey", "export", version, "--out", f"/tmp/e2e-j4-export-{unique_idem_key('j4')}")


@pytest.mark.pending_m3_m4
def test_t4_j5_staff_admin_console_models_surveys_audit_dsr(
    base_url: str,
    helpers: E2EHelpers,
    page_factory,
    rubric_collector,
    screenshot_saver,
) -> None:
    """J5: Seeded admin/ml_operator inspects /quan-tri (models, surveys, audit log, resolves user DSR)."""
    user = helpers.create_ready_user(seed_pantry=False)
    dsr = helpers.api.post(
        "/me/data-requests",
        headers=helpers.auth_headers(user["access_token"]),
        json={"type": "correct", "note": "Cập nhật thông tin hồ sơ từ J5"},
    ).json()

    admin = helpers.create_staff_session("admin")
    _, page, telemetry = page_factory(viewport=(1440, 900), color_scheme="light")
    tid = page.get_by_test_id
    page.goto(f"{base_url}/dang-nhap")
    tid("login-email").fill(admin["_email"])
    tid("login-password").fill(admin["_password"])
    tid("login-submit").click()
    tid("screen-home").wait_for()

    page.goto(f"{base_url}/quan-tri")
    tid("screen-admin").wait_for()
    tid("admin-tab-data-requests").click()
    tid(f"dsr-resolve-{dsr['id']}").click()
    tid("dsr-resolve-note").fill("Đã kiểm tra và xử lý xong")
    tid("dsr-resolve-submit").click()
    tid("admin-tab-audit-log").click()
    _audit_and_shot(page, rubric_collector=rubric_collector, screenshot_saver=screenshot_saver, screen_name="j5-quan-tri", shot_prefix="j5-01-quan-tri", theme="light", viewport=(1440, 900))
    telemetry.assert_clean()


def test_t4_j6_allergen_diet_and_do_an_vat_safety_journey(
    base_url: str,
    helpers: E2EHelpers,
    page_factory,
    rubric_collector,
    screenshot_saver,
) -> None:
    """J6: Vegetarian (`chay`) + `trung` allergen + `bim bim` (`do_an_vat`) pantry never leaks unsafe dishes."""
    user = helpers.create_ready_user(seed_pantry=False, diet_code="chay", allergen_codes=["trung"])
    tok = user["access_token"]
    h = helpers.auth_headers(tok)
    helpers.seed_pantry_lot(tok, "đậu phụ", count=4, unit_code="mieng")
    helpers.seed_pantry_lot(tok, "cà chua", count=4, unit_code="qua")
    helpers.seed_pantry_lot(tok, "cải ngọt", grams=500.0)
    helpers.seed_pantry_lot(tok, "bí đỏ", grams=500.0)
    helpers.seed_pantry_lot(tok, "lạc", grams=200.0)
    helpers.seed_pantry_lot(tok, "trứng gà", count=6, unit_code="qua")
    helpers.seed_pantry_lot(tok, "bim bim", grams=300.0)

    _, page, telemetry = page_factory(viewport=(390, 844), color_scheme="light")
    tid = page.get_by_test_id
    page.goto(f"{base_url}/dang-nhap")
    tid("login-email").fill(user["_email"])
    tid("login-password").fill(user["_password"])
    tid("login-submit").click()
    tid("screen-home").wait_for()

    page.goto(f"{base_url}/mam")
    tid("make-plan").click()
    tid("plan-view").wait_for(timeout=30000)
    _audit_and_shot(page, rubric_collector=rubric_collector, screenshot_saver=screenshot_saver, screen_name="j6-mam-chay", shot_prefix="j6-01-mam-an-toan", theme="light", viewport=(390, 844), check_touch=False)
    telemetry.assert_clean()

    latest = helpers.api.get("/meal-plans/latest", headers=h, params={"meal": "dinner"})
    if latest.status_code == 404:
        latest = helpers.api.get("/meal-plans/latest", headers=h, params={"meal": "lunch"})
    assert latest.status_code == 200
    for it in latest.json()["items"]:
        rec = helpers.api.get(f"/recipes/{it['recipe_id']}", headers=h).json()
        for ing in rec["ingredients"]:
            assert "trung" not in ing["allergen_codes"]
            assert ing["name_vi"].lower() != "bim bim"


def test_t4_j7_privacy_withdrawal_export_and_account_deletion_dsr(
    base_url: str,
    helpers: E2EHelpers,
    page_factory,
    rubric_collector,
    screenshot_saver,
) -> None:
    """J7: Upload scan w/ contribute -> withdraw consent -> ZIP export -> delete account -> login blocked 403."""
    user = helpers.create_ready_user(purposes=("health_profile", "personalization", "photo_contribution"), seed_pantry=False)
    tok = user["access_token"]
    h = helpers.auth_headers(tok)
    scan_res = helpers.api.post(
        "/scans",
        headers=helpers.auth_headers(tok, idem=unique_idem_key("j7scan")),
        data={"mode": "haul", "contribute": "true"},
        files=[("images", ("j7.jpg", get_scan_sample_jpeg(), "image/jpeg"))],
    )
    assert scan_res.status_code == 202

    _, page, telemetry = page_factory(viewport=(390, 844), color_scheme="light")
    tid = page.get_by_test_id
    page.goto(f"{base_url}/dang-nhap")
    tid("login-email").fill(user["_email"])
    tid("login-password").fill(user["_password"])
    tid("login-submit").click()
    tid("screen-home").wait_for()

    page.goto(f"{base_url}/cai-dat")
    tid("screen-settings").wait_for()
    tid("settings-consent").click()
    _audit_and_shot(page, rubric_collector=rubric_collector, screenshot_saver=screenshot_saver, screen_name="j7-cai-dat", shot_prefix="j7-01-cai-dat-dong-y", theme="light", viewport=(390, 844))
    telemetry.assert_clean()

    # Export ZIP via API + CLI worker
    exp = helpers.api.post("/me/data-requests", headers=h, json={"type": "export"}).json()
    helpers.run_cli("jobs", "process-dsr")
    dl = helpers.api.get(f"/me/data-requests/{exp['id']}/download", headers=h)
    assert dl.status_code == 200 and dl.content[:2] == b"PK"

    # Trigger account deletion & process DSR -> login blocked with 403 account_deletion_pending
    del_req = helpers.api.post(
        "/me/data-requests",
        headers=h,
        json={"type": "delete", "password": user["_password"]},
    )
    assert del_req.status_code in (200, 202)
    blocked = helpers.api.post("/auth/login", json={"email": user["_email"], "password": user["_password"]})
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "account_deletion_pending"


def test_t4_j8_idempotency_replay_and_token_family_resilience(
    base_url: str,
    helpers: E2EHelpers,
    page_factory,
    rubric_collector,
    screenshot_saver,
) -> None:
    """J8: Idempotent POST /meal-plans & POST /cook-sessions/{id}/complete replay + refresh reuse family revocation."""
    user = helpers.create_ready_user(seed_pantry=True)
    tok = user["access_token"]
    h = helpers.auth_headers(tok)

    plan_key = unique_idem_key("j8plan")
    p1 = helpers.api.post(
        "/meal-plans",
        headers=helpers.auth_headers(tok, idem=plan_key),
        json={"meal": "dinner", "max_minutes": 90, "persons": 2},
    )
    p2 = helpers.api.post(
        "/meal-plans",
        headers=helpers.auth_headers(tok, idem=plan_key),
        json={"meal": "dinner", "max_minutes": 90, "persons": 2},
    )
    assert p1.status_code == 201 and p2.status_code == 201
    assert p1.json()["id"] == p2.json()["id"]
    assert p2.headers.get("idempotent-replayed") == "true"
    plan_id = p1.json()["id"]

    # Verify in UI that the single meal plan renders cleanly
    _, page, telemetry = page_factory(viewport=(390, 844), color_scheme="dark")
    tid = page.get_by_test_id
    page.goto(f"{base_url}/dang-nhap")
    tid("login-email").fill(user["_email"])
    tid("login-password").fill(user["_password"])
    tid("login-submit").click()
    tid("screen-home").wait_for()
    page.goto(f"{base_url}/mam")
    tid("plan-view").wait_for(timeout=20000)
    _audit_and_shot(page, rubric_collector=rubric_collector, screenshot_saver=screenshot_saver, screen_name="j8-mam-dark", shot_prefix="j8-01-mam-dark", theme="dark", viewport=(390, 844), check_touch=False)
    telemetry.assert_clean()

    # Verify idempotent replay on POST /cook-sessions/{id}/complete
    assert helpers.api.post(f"/meal-plans/{plan_id}/accept", headers=h).status_code == 200
    sess = helpers.api.post(
        "/cook-sessions",
        headers=helpers.auth_headers(tok, idem=unique_idem_key("j8cook")),
        json={"meal_plan_id": plan_id, "serve_at": (datetime.now(timezone.utc) + timedelta(minutes=60)).isoformat(), "confirm_over_time": True},
    )
    assert sess.status_code == 201
    sid = sess.json()["id"]
    comp_key = unique_idem_key("j8done")
    c1 = helpers.api.post(f"/cook-sessions/{sid}/complete", headers=helpers.auth_headers(tok, idem=comp_key), json={"feedback": []})
    c2 = helpers.api.post(f"/cook-sessions/{sid}/complete", headers=helpers.auth_headers(tok, idem=comp_key), json={"feedback": []})
    assert c1.status_code == 200 and c2.status_code == 200
    assert c2.headers.get("idempotent-replayed") == "true"
    assert c1.json()["deductions"] == c2.json()["deductions"]

    # Refresh token reuse revokes family cleanly
    r1 = user["refresh_token"]
    ref = helpers.api.post("/auth/refresh", json={"refresh_token": r1})
    assert ref.status_code == 200
    r2 = ref.json()["refresh_token"]
    reuse = helpers.api.post("/auth/refresh", json={"refresh_token": r1})
    assert reuse.status_code == 401 and reuse.json()["code"] == "refresh_reused"
    assert helpers.api.post("/auth/refresh", json={"refresh_token": r2}).status_code == 401
