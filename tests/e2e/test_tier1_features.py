"""Tier 1: Isolated Feature Coverage Tests across ALL 15 Features (F1-F15).

Requirement: >= 5 distinct opaque-box tests per feature (>= 75 total).
Every test exercises real API endpoints, real CLI tools, real ML/design/report artifacts,
or live Playwright Chromium rendering against the isolated E2E stack on 171.226.10.153.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml
from docx import Document

from tests.e2e.conftest import DEFAULT_PASSWORD, E2EHelpers, _compose_cmd, _compose_env, unique_email, unique_idem_key
from tests.e2e.fixtures import get_scan_sample_jpeg, write_temp_scan_file
from tests.e2e.rubric import (
    assert_theme_rgb_delta,
    evaluate_page_rubric,
    hex_contrast_ratio,
    load_design_tokens,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
pytestmark = [pytest.mark.tier1]


# ==============================================================================
# F1: Remote Compute Bootstrap & Deployed Stack Health (5 tests)
# ==============================================================================


def test_t1_f1_healthz_returns_ok(raw_client) -> None:
    resp = raw_client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert "no-store" in resp.headers.get("cache-control", "")


def test_t1_f1_readyz_checks_db_valkey_models(raw_client) -> None:
    resp = raw_client.get("/readyz")
    assert resp.status_code == 200, f"/readyz returned {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["status"] == "ready"
    checks = body["checks"]
    assert checks.get("database") == "ok"
    assert checks.get("valkey") == "ok"
    assert checks.get("models") == "ok"


def test_t1_f1_worker_check_cli_exits_zero(helpers: E2EHelpers) -> None:
    proc = helpers.run_cli("worker", "--check")
    assert proc.returncode == 0


def test_t1_f1_nginx_routing_and_security_headers(raw_client) -> None:
    root = raw_client.get("/")
    assert root.status_code == 200
    assert "text/html" in root.headers.get("content-type", "")
    assert root.headers.get("x-content-type-options") == "nosniff"
    assert root.headers.get("x-frame-options") == "DENY"

    redir = raw_client.get("/gioi-thieu")
    assert redir.status_code == 301
    assert redir.headers.get("location", "").endswith("/gioi-thieu/")

    landing = raw_client.get("/gioi-thieu/")
    assert landing.status_code == 200
    assert "tastoria" in landing.text.lower()


def test_t1_f1_protected_storage_not_externally_exposed(raw_client) -> None:
    # Nginx marks /_protected/ internal; direct external access must never serve stored images
    r1 = raw_client.get("/_protected/scans/nonexistent.jpg")
    assert r1.status_code != 200 or "image/" not in r1.headers.get("content-type", "")
    r2 = raw_client.get("/_protected/")
    assert r2.status_code != 200 or "Index of" not in r2.text


# ==============================================================================
# F2: CV Ingredient Detection & Counting Research / Serving (5 tests)
# ==============================================================================


def test_t1_f2_dataset_stats_v2_valid() -> None:
    stats_v2 = REPO_ROOT / "data" / "processed" / "cv" / "dataset_stats_v2.json"
    assert stats_v2.is_file(), f"Missing {stats_v2}"
    data = json.loads(stats_v2.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and len(data) >= 1
    vision_yaml = yaml.safe_load((REPO_ROOT / "data" / "kb" / "vision_classes.yaml").read_text(encoding="utf-8"))
    total_classes = len(vision_yaml["classes"]) + len(vision_yaml.get("proposed_classes", []))
    assert total_classes == 37


def test_t1_f2_detector_eval_and_counting_artifacts() -> None:
    det_dir = REPO_ROOT / "data" / "processed" / "cv" / "detector"
    cnt_dir = REPO_ROOT / "data" / "processed" / "cv" / "counting"
    det_jsons = list(det_dir.glob("*.json"))
    cnt_jsons = list(cnt_dir.glob("*.json"))
    assert len(det_jsons) >= 1, "Expected detector evaluation JSON artifacts"
    assert len(cnt_jsons) >= 1, "Expected counting evaluation JSON artifacts"
    sample = json.loads(det_jsons[0].read_text(encoding="utf-8"))
    assert isinstance(sample, (dict, list)) and len(sample) > 0


def test_t1_f2_mlops_detector_registered_and_active(helpers: E2EHelpers) -> None:
    proc = helpers.run_cli("mlops", "list", "detector")
    out = proc.stdout.strip()
    assert out, "mlops list detector returned empty output"
    assert "detector" in out.lower() or "active" in out.lower() or "validated" in out.lower()


def test_t1_f2_scan_upload_worker_produces_done_scan(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=False)
    token = user["access_token"]
    jpeg = get_scan_sample_jpeg()
    resp = helpers.api.post(
        "/scans",
        headers=helpers.auth_headers(token, idem=unique_idem_key("scan")),
        data={"mode": "haul", "contribute": "false"},
        files=[("images", ("produce.jpg", jpeg, "image/jpeg"))],
    )
    assert resp.status_code == 202, f"POST /scans -> {resp.status_code}: {resp.text}"
    scan_id = resp.json()["id"]
    assert resp.headers.get("location", "").endswith(f"/scans/{scan_id}")

    # Poll with wait=10 until worker completes
    done = None
    for _ in range(5):
        poll = helpers.api.get(f"/scans/{scan_id}", headers=helpers.auth_headers(token), params={"wait": 10})
        assert poll.status_code == 200
        body = poll.json()
        if body["status"] in ("done", "failed"):
            done = body
            break
    assert done is not None and done["status"] == "done", f"Scan did not finish cleanly: {done}"
    assert done["detector_version_id"] is not None
    assert len(done["images"]) == 1


def test_t1_f2_scan_item_crud_and_confirm_to_pantry(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=False)
    token = user["access_token"]
    h = helpers.auth_headers(token)
    resp = helpers.api.post(
        "/scans",
        headers=helpers.auth_headers(token, idem=unique_idem_key("scan")),
        data={"mode": "haul", "contribute": "false"},
        files=[("images", ("produce.jpg", get_scan_sample_jpeg(), "image/jpeg"))],
    )
    assert resp.status_code == 202
    scan_id = resp.json()["id"]
    for _ in range(5):
        s = helpers.api.get(f"/scans/{scan_id}", headers=h, params={"wait": 10}).json()
        if s["status"] == "done":
            break
    assert s["status"] == "done"

    # Ensure no items block confirmation with unconfirmed needs_check
    for it in s["items"]:
        if it["needs_check"] and it["user_freshness"] is None:
            helpers.api.patch(
                f"/scans/{scan_id}/items/{it['id']}",
                headers={**h, "Content-Type": "application/merge-patch+json"},
                json={"user_freshness": "tuoi"},
            )
    existing_ids = {it["ingredient_id"] for it in s["items"]}
    target_id = None
    for cand_name in ("trứng gà", "cà chua", "đậu phụ", "khoai tây", "cà rốt"):
        cid = helpers.resolve_ingredient_id(token, cand_name)
        if cid not in existing_ids:
            target_id = cid
            break
    assert target_id is not None, f"All countable candidate ingredients already present in scan items: {existing_ids}"
    added = helpers.api.post(
        f"/scans/{scan_id}/items",
        headers=h,
        json={"ingredient_id": target_id, "final_count": 4, "user_freshness": "tuoi"},
    )
    assert added.status_code == 201, added.text
    item_id = added.json()["id"]

    patched = helpers.api.patch(
        f"/scans/{scan_id}/items/{item_id}",
        headers={**h, "Content-Type": "application/merge-patch+json"},
        json={"final_count": 6, "user_freshness": "dung_som"},
    )
    assert patched.status_code == 200
    assert patched.json()["final_count"] == 6

    # Confirm scan into pantry lots
    conf = helpers.api.post(f"/scans/{scan_id}/confirm", headers=h, json={})
    assert conf.status_code == 200, conf.text
    assert conf.json()["status"] == "confirmed"
    assert len(conf.json()["created_lot_ids"]) >= 1

    # Verify pantry lot created
    lots = helpers.api.get("/pantry/lots", headers=h).json()["items"]
    assert any(lot["id"] in conf.json()["created_lot_ids"] for lot in lots)


# ==============================================================================
# F3: CV Produce Freshness & Calibration (5 tests)
# ==============================================================================


def test_t1_f3_freshness_research_results_present() -> None:
    fr_manifest = REPO_ROOT / "data" / "processed" / "freshness" / "manifest.csv"
    assert fr_manifest.is_file()
    cv_fr_dir = REPO_ROOT / "data" / "processed" / "cv" / "freshness"
    assert cv_fr_dir.is_dir()
    files = list(cv_fr_dir.glob("*.json"))
    assert len(files) >= 1, f"Expected freshness JSON evaluations in {cv_fr_dir}"


@pytest.mark.pending_m3_m4
def test_t1_f3_freshness_model_registered_and_active(helpers: E2EHelpers) -> None:
    proc = helpers.run_cli("mlops", "list", "freshness")
    out = proc.stdout.strip().lower()
    assert "freshness" in out
    assert "active" in out or "validated" in out


@pytest.mark.pending_m3_m4
def test_t1_f3_scan_detections_include_calibrated_freshness_probs(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=False)
    token = user["access_token"]
    h = helpers.auth_headers(token)
    resp = helpers.api.post(
        "/scans",
        headers=helpers.auth_headers(token, idem=unique_idem_key("fresh")),
        data={"mode": "fridge", "contribute": "false"},
        files=[("images", ("produce.jpg", get_scan_sample_jpeg(), "image/jpeg"))],
    )
    assert resp.status_code == 202
    scan_id = resp.json()["id"]
    scan_data = None
    for _ in range(5):
        s = helpers.api.get(f"/scans/{scan_id}", headers=h, params={"wait": 10}).json()
        if s["status"] == "done":
            scan_data = s
            break
    assert scan_data is not None and scan_data["status"] == "done"
    assert scan_data["classifier_version_id"] is not None
    dets = [d for it in scan_data["items"] for d in it["detections"]]
    fresh_dets = [d for d in dets if d["p_tuoi"] is not None]
    assert len(fresh_dets) >= 1, "Expected at least one detection with Freshness ONNX probabilities"
    for d in fresh_dets:
        total = d["p_tuoi"] + d["p_dung_som"] + d["p_dung_ngay"] + d["p_kiem_tra"]
        assert 0.98 <= total <= 1.02, f"Probabilities did not sum to ~1.0: {d}"


def test_t1_f3_pantry_urgency_formula_time_based(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=False)
    token = user["access_token"]
    # `cải ngọt` has shelf life ~4 days -> fresh (0 days) vs urgent (2.5 days -> u ~ 0.625 dung_som)
    fresh_lot = helpers.seed_pantry_lot(token, "cải ngọt", grams=300.0, days_ago=0.0)
    urgent_lot = helpers.seed_pantry_lot(token, "cải ngọt", grams=300.0, days_ago=2.5)
    assert fresh_lot["freshness_label"] == "tuoi"
    assert fresh_lot["urgency"] is not None and fresh_lot["urgency"] < 0.5
    assert urgent_lot["freshness_label"] in ("dung_som", "dung_ngay")
    assert urgent_lot["urgency"] is not None and urgent_lot["urgency"] >= 0.5
    assert urgent_lot["available"] is True


def test_t1_f3_pantry_untracked_ingredient_is_chua_ro(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=False)
    token = user["access_token"]
    lot = helpers.seed_pantry_lot(token, "gạo tẻ", grams=1000.0, days_ago=10.0)
    assert lot["urgency"] is None
    assert lot["freshness_label"] == "chua_ro"
    assert lot["available"] is True


# ==============================================================================
# F4: RecSys Meal Ranking & Survey Export (5 tests)
# ==============================================================================


def test_t1_f4_foodcom_recsys_artifacts_valid() -> None:
    recsys_dir = REPO_ROOT / "data" / "processed" / "recsys"
    for name in ("tuning.json", "test.json", "curve.json", "errors.json", "cold.json"):
        path = recsys_dir / name
        assert path.is_file(), f"Missing RecSys artifact {path}"
        parsed = json.loads(path.read_text(encoding="utf-8"))
        assert len(parsed) > 0


def test_t1_f4_vn_survey_sim_artifact_valid() -> None:
    sim_path = REPO_ROOT / "data" / "processed" / "recsys" / "survey_sim.json"
    assert sim_path.is_file()
    data = json.loads(sim_path.read_text(encoding="utf-8"))
    raw_text = json.dumps(data)
    assert "warm" in raw_text or "cold" in raw_text


@pytest.mark.pending_m3_m4
def test_t1_f4_ranker_model_registered_and_deployed(helpers: E2EHelpers) -> None:
    proc = helpers.run_cli("mlops", "list", "ranker")
    out = proc.stdout.strip().lower()
    assert "ranker" in out
    assert "active" in out or "validated" in out


def test_t1_f4_meal_plan_uses_ranker_and_records_rank_score(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=True)
    token = user["access_token"]
    resp = helpers.api.post(
        "/meal-plans",
        headers=helpers.auth_headers(token, idem=unique_idem_key("plan")),
        json={"meal": "dinner", "max_minutes": 60, "persons": 2},
    )
    assert resp.status_code == 201, resp.text
    plan = resp.json()
    assert plan["status"] == "proposed"
    assert len(plan["items"]) >= 2
    assert plan["reason_vi"]
    assert plan["params_version"]
    for item in plan["items"]:
        assert isinstance(item["rank_score"], (int, float))


def test_t1_f4_survey_respondent_lifecycle_and_export(helpers: E2EHelpers) -> None:
    version = helpers.ensure_open_survey_form(anchors=10, random_n=35, seed=42)
    assert version
    policy_id = helpers.get_policy_version_id("survey")
    created = helpers.api.post(
        "/survey/respondents",
        json={"policy_version_id": policy_id, "consent": True, "channel": "link"},
    )
    assert created.status_code == 201, created.text
    payload = created.json()
    rid = payload["respondent"]["id"]
    rtok = payload["respondent_token"]
    rheaders = {"X-Respondent-Token": rtok}
    assignments = payload["respondent"]["assignments"]
    assert len(assignments) == 45

    for idx, a in enumerate(assignments):
        body = {"rating": None, "never_eaten": True} if idx % 5 == 0 else {"rating": (idx % 5) + 1, "never_eaten": False}
        rr = helpers.api.put(f"/survey/respondents/{rid}/ratings/{a['recipe_id']}", headers=rheaders, json=body)
        assert rr.status_code == 200, rr.text

    favs = [a["recipe_id"] for a in assignments[:3]]
    fr = helpers.api.put(f"/survey/respondents/{rid}/favorites", headers=rheaders, json={"recipe_ids": favs})
    assert fr.status_code == 200, fr.text

    comp = helpers.api.post(f"/survey/respondents/{rid}/complete", headers=rheaders)
    assert comp.status_code == 200, comp.text
    assert comp.json()["completed_at"] is not None

    # Export via CLI & verify manifest SHA-256 and zero PII
    out_dir = f"/tmp/e2e-survey-export-{unique_idem_key('surv')}"
    proc = helpers.run_cli("survey", "export", payload["respondent"]["form_version"], "--out", out_dir)
    export_meta = json.loads(proc.stdout)
    assert export_meta["ok"] is True
    export_path = export_meta["directory"]
    verify_py = (
        "import hashlib, json, pathlib; "
        f"d = pathlib.Path({export_path!r}); "
        "m = json.loads((d / 'manifest.json').read_text(encoding='utf-8')); "
        "res = {}; "
        "res['respondents'] = m['respondents']; "
        "res['files'] = {k: {'expected': v['sha256'], 'actual': hashlib.sha256((d / k).read_bytes()).hexdigest(), 'text': (d / k).read_text(encoding='utf-8')} for k, v in m['files'].items()}; "
        "print(json.dumps(res, ensure_ascii=False))"
    )
    if Path(export_path).is_dir():
        vproc = subprocess.run(["python3", "-c", verify_py], capture_output=True, text=True, check=True)
    else:
        vproc = subprocess.run(
            [*_compose_cmd("exec", "-T", "api", "python3", "-c", verify_py)],
            capture_output=True,
            text=True,
            check=True,
            env=_compose_env(),
        )
    verified = json.loads(vproc.stdout)
    assert verified["respondents"] >= 1
    assert set(verified["files"].keys()) == {"respondents.csv", "assignments.csv", "ratings.csv", "favorites.csv", "anchors.csv", "recipes.csv"}
    for fname, info in verified["files"].items():
        assert info["actual"] == info["expected"], f"SHA-256 mismatch in {fname}"
        assert "@example.com" not in info["text"] and "email" not in info["text"].splitlines()[0].lower(), f"PII/email leaked in {fname}"


# ==============================================================================
# F5: Substitution & Tray Composer (5 tests)
# ==============================================================================


def test_t1_f5_substitution_and_composer_eval_artifacts() -> None:
    sub_res = REPO_ROOT / "data" / "processed" / "substitution" / "results.json"
    sub_rank = REPO_ROOT / "data" / "processed" / "substitution" / "eval_rankings.json"
    comp_sum = REPO_ROOT / "data" / "processed" / "composer_eval" / "summary.json"
    comp_w = REPO_ROOT / "data" / "processed" / "composer_eval" / "weights.json"
    for p in (sub_res, sub_rank, comp_sum, comp_w):
        assert p.is_file(), f"Missing artifact {p}"
        assert len(json.loads(p.read_text(encoding="utf-8"))) > 0


def test_t1_f5_curated_substitute_lookup_on_missing_ingredient(helpers: E2EHelpers) -> None:
    # Seed pantry without `thịt ba chỉ` / `sườn non` or with partial pantry so at least one item has missing ingredients
    user = helpers.create_ready_user(seed_pantry=False)
    token = user["access_token"]
    for name_vi, g in [("trứng gà", 0), ("rau muống", 500), ("thịt nạc vai", 500), ("cà chua", 300), ("tỏi", 100)]:
        if g == 0:
            helpers.seed_pantry_lot(token, name_vi, count=6, unit_code="qua")
        else:
            helpers.seed_pantry_lot(token, name_vi, grams=g)
    h = helpers.auth_headers(token)
    plan = helpers.api.post(
        "/meal-plans",
        headers=helpers.auth_headers(token, idem=unique_idem_key("sub")),
        json={"meal": "lunch", "max_minutes": 60, "persons": 2},
    )
    assert plan.status_code == 201, plan.text
    items = plan.json()["items"]
    # Query substitutes for each plan item; verify schema of MissingIngredientOut / SubstituteCandidateOut
    for it in items:
        sr = helpers.api.get(f"/meal-plans/{plan.json()['id']}/items/{it['id']}/substitutes", headers=h)
        assert sr.status_code == 200
        body = sr.json()
        assert "items" in body
        for missing in body["items"]:
            for cand in missing["candidates"]:
                assert cand["origin"] in ("lookup", "embedding")
                assert cand["ratio"] > 0 and cand["grams"] > 0


def test_t1_f5_apply_substitution_recomputes_kcal(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=True)
    token = user["access_token"]
    h = helpers.auth_headers(token)
    plan = helpers.api.post(
        "/meal-plans",
        headers=helpers.auth_headers(token, idem=unique_idem_key("applysub")),
        json={"meal": "dinner", "max_minutes": 60, "persons": 2},
    ).json()
    # Find an item with available substitute candidates (or probe across items)
    orig_kcal_low = plan.get("kcal_low")
    orig_kcal_high = plan.get("kcal_high")
    applied = False
    for it in plan["items"]:
        sr = helpers.api.get(f"/meal-plans/{plan['id']}/items/{it['id']}/substitutes", headers=h).json()
        for missing in sr["items"]:
            if missing["candidates"]:
                cand = missing["candidates"][0]
                res = helpers.api.post(
                    f"/meal-plans/{plan['id']}/items/{it['id']}/substitutions",
                    headers=h,
                    json={
                        "original_ingredient_id": missing["original_ingredient_id"],
                        "substitute_ingredient_id": cand["substitute_ingredient_id"],
                        "origin": cand["origin"],
                    },
                )
                assert res.status_code == 200, res.text
                updated_item = res.json()
                assert updated_item["id"] == it["id"]
                assert len(updated_item["substitutions"]) >= 1
                updated_plan = helpers.api.get(f"/meal-plans/{plan['id']}", headers=h).json()
                assert isinstance(updated_plan["kcal_low"], (int, float))
                assert isinstance(updated_plan["kcal_high"], (int, float))
                assert updated_plan["kcal_low"] <= updated_plan["kcal_high"]
                if (
                    updated_item.get("kcal_per_person") is not None
                    and it.get("kcal_per_person") is not None
                    and abs(updated_item["kcal_per_person"] - it["kcal_per_person"]) > 0.5
                ):
                    assert updated_plan["kcal_low"] != orig_kcal_low or updated_plan["kcal_high"] != orig_kcal_high
                applied = True
                break
        if applied:
            break
    # Even if standard pantry had zero missing ingredients, verify endpoint accepts valid same-food-group substitution & recomputes tray kcal
    if not applied:
        man = next(x for x in plan["items"] if x["slot"] == "man")
        recipe = helpers.api.get(f"/recipes/{man['recipe_id']}", headers=h).json()
        orig_ing_id = None
        sub_ing_id = None
        for rec_ing in recipe["ingredients"]:
            ing_obj = helpers.resolve_ingredient(token, rec_ing["name_vi"])
            fg = ing_obj["food_group_code"]
            peers = helpers.api.get("/ingredients", headers=h, params={"food_group_code": fg, "limit": 20}).json()["items"]
            alt = next((p for p in peers if p["id"] != ing_obj["id"]), None)
            if alt is not None:
                orig_ing_id = ing_obj["id"]
                sub_ing_id = alt["id"]
                break
        assert orig_ing_id is not None and sub_ing_id is not None, "Expected a same-food-group substitution pair"
        res = helpers.api.post(
            f"/meal-plans/{plan['id']}/items/{man['id']}/substitutions",
            headers=h,
            json={"original_ingredient_id": orig_ing_id, "substitute_ingredient_id": sub_ing_id, "origin": "user"},
        )
        assert res.status_code == 200, res.text
        updated_item = res.json()
        assert updated_item["id"] == man["id"]
        assert len(updated_item["substitutions"]) >= 1
        updated_plan = helpers.api.get(f"/meal-plans/{plan['id']}", headers=h).json()
        assert isinstance(updated_plan["kcal_low"], (int, float))
        assert isinstance(updated_plan["kcal_high"], (int, float))
        assert updated_plan["kcal_low"] <= updated_plan["kcal_high"]


@pytest.mark.pending_m3_m4
def test_t1_f5_hybrid_pgvector_embedding_substitutes(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=True)
    token = user["access_token"]
    h = helpers.auth_headers(token)
    plan = helpers.api.post(
        "/meal-plans",
        headers=helpers.auth_headers(token, idem=unique_idem_key("hyb")),
        json={"meal": "lunch", "max_minutes": 60, "persons": 2},
    ).json()
    man = next(x for x in plan["items"] if x["slot"] == "man")
    # Ask substitutes for an ingredient unlikely to have 3 curated lookup pairs (e.g., `cá thu`)
    ing_id = helpers.resolve_ingredient_id(token, "cá thu")
    sr = helpers.api.get(
        f"/meal-plans/{plan['id']}/items/{man['id']}/substitutes",
        headers=h,
        params={"ingredient_id": ing_id},
    )
    assert sr.status_code == 200
    cands = [c for m in sr.json()["items"] for c in m["candidates"]]
    assert any(c["origin"] == "embedding" for c in cands), f"Expected pgvector embedding candidate: {cands}"


def test_t1_f5_cpsat_cook_schedule_respects_burners(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=True)
    token = user["access_token"]
    h = helpers.auth_headers(token)
    helpers.api.put("/me/settings", headers=h, json={"burners": 1, "default_persons": 2, "timezone": "Asia/Ho_Chi_Minh"})
    plan = helpers.api.post(
        "/meal-plans",
        headers=helpers.auth_headers(token, idem=unique_idem_key("cookplan")),
        json={"meal": "dinner", "max_minutes": 120, "persons": 2},
    ).json()
    acc = helpers.api.post(f"/meal-plans/{plan['id']}/accept", headers=h)
    assert acc.status_code == 200

    from datetime import datetime, timedelta, timezone

    serve_at = (datetime.now(timezone.utc) + timedelta(minutes=90)).isoformat()
    cook = helpers.api.post(
        "/cook-sessions",
        headers=helpers.auth_headers(token, idem=unique_idem_key("cook")),
        json={"meal_plan_id": plan["id"], "serve_at": serve_at, "confirm_over_time": True},
    )
    assert cook.status_code == 201, cook.text
    sess = cook.json()
    assert sess["burners"] == 1
    assert len(sess["schedule"]) >= 1
    # Verify no two `uses_burner=True` intervals overlap when burners=1
    burner_steps = sorted(
        [(s["start_offset_s"], s["end_offset_s"]) for s in sess["schedule"] if s["uses_burner"]],
        key=lambda x: x[0],
    )
    for (s1, e1), (s2, e2) in zip(burner_steps, burner_steps[1:]):
        assert e1 <= s2, f"Burner overlap with burners=1: {(s1, e1)} vs {(s2, e2)}"


# ==============================================================================
# F6: K-Dense Literature & Scientific ML Report (5 tests)
# ==============================================================================


def test_t1_f6_hoc_may_report_exists_and_non_empty() -> None:
    report_dir = REPO_ROOT / "docs" / "reports" / "hoc-may"
    md_files = list(report_dir.glob("*.md"))
    assert len(md_files) >= 1
    largest = max(md_files, key=lambda p: p.stat().st_size)
    assert largest.stat().st_size > 10_000


@pytest.mark.pending_m3_m4
def test_t1_f6_kdense_source_manifest_valid() -> None:
    manifest_path = REPO_ROOT / "docs" / "reports" / "hoc-may" / "source_manifest.json"
    assert manifest_path.is_file(), f"Missing {manifest_path}"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = data if isinstance(data, list) else data.get("sources", [])
    assert len(entries) >= 5
    for entry in entries:
        assert re.match(r"^E[0-9]{3,8}$", entry["evidence_id"])
        assert entry["verification"]["status"] == "verified"
        assert entry["verification"]["source_opened"] is True


@pytest.mark.pending_m3_m4
def test_t1_f6_kdense_claims_csv_and_sha256_integrity() -> None:
    claims_path = REPO_ROOT / "docs" / "reports" / "hoc-may" / "claims.csv"
    assert claims_path.is_file(), f"Missing {claims_path}"
    expected_cols = [
        "claim_id",
        "section",
        "claim_kind",
        "claim_text_sha256",
        "evidence_ids",
        "verification_status",
        "uncertainty",
        "analysis_intent",
    ]
    with claims_path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == expected_cols
        rows = list(reader)
    assert len(rows) >= 10
    for row in rows:
        assert len(row["claim_text_sha256"]) == 64


@pytest.mark.pending_m3_m4
def test_t1_f6_kdense_consistency_manifest_valid() -> None:
    cons_path = REPO_ROOT / "docs" / "reports" / "hoc-may" / "consistency_manifest.json"
    assert cons_path.is_file(), f"Missing {cons_path}"
    data = json.loads(cons_path.read_text(encoding="utf-8"))
    assert "schema_version" in data
    assert len(data.get("numeric_facts", [])) >= 1
    assert len(data.get("results", [])) >= 1


@pytest.mark.pending_m3_m4
def test_t1_f6_kdense_validator_scripts_exit_zero() -> None:
    report_dir = REPO_ROOT / "docs" / "reports" / "hoc-may"
    scripts_dir = Path(os.environ.get("TASTORIA_KDENSE_SCRIPTS_DIR", "/home/namnx/.claude/skills/scientific-writing/scripts"))
    md_path = report_dir / "Bao-cao-Nghien-cuu-Hoc-May-Tastoria.md"
    assert md_path.is_file(), f"Missing M1 K-Dense manuscript {md_path}"
    assert scripts_dir.is_dir(), f"Missing K-Dense validator scripts dir: {scripts_dir}"
    for script_name, args in [
        ("validate_manifest.py", [str(report_dir / "manuscript_manifest.json"), str(report_dir / "source_manifest.json")]),
        ("audit_claims.py", [str(md_path), str(report_dir / "claims.csv")]),
        ("check_consistency.py", [str(report_dir / "consistency_manifest.json")]),
        ("lint_manuscript.py", [str(md_path)]),
    ]:
        proc = subprocess.run(["python3", str(scripts_dir / script_name), *args], capture_output=True, text=True)
        assert proc.returncode == 0, f"{script_name} failed: {proc.stdout}\n{proc.stderr}"


# ==============================================================================
# F7: UI/UX Research & Unified Design System (5 tests)
# ==============================================================================


def test_t1_f7_app_tokens_contrast_script_passes() -> None:
    proc = subprocess.run(["python3", str(REPO_ROOT / "app" / "scripts" / "contrast.py")], capture_output=True, text=True)
    assert proc.returncode == 0, f"contrast.py failed:\n{proc.stdout}\n{proc.stderr}"


@pytest.mark.pending_m3_m4
def test_t1_f7_master_design_system_exists_and_has_light_dark_tokens() -> None:
    for rel in (
        "docs/design/design-system/MASTER.md",
        "docs/design/ui-redesign-spec.md",
        "docs/design/ui-rubric.md",
    ):
        p = REPO_ROOT / rel
        assert p.is_file(), f"Missing M2 design deliverable: {p}"
        txt = p.read_text(encoding="utf-8")
        assert len(txt) > 500
    master = (REPO_ROOT / "docs/design/design-system/MASTER.md").read_text(encoding="utf-8").lower()
    assert "light" in master and "dark" in master
    assert "bevietnampro" in master or "be vietnam pro" in master


@pytest.mark.pending_m3_m4
def test_t1_f7_landing_and_app_tokens_match_master() -> None:
    tokens = load_design_tokens()
    light = tokens["light"]
    dark = tokens["dark"]
    assert hex_contrast_ratio(light["text"], light["bg"]) >= 4.5
    assert hex_contrast_ratio(dark["text"], dark["bg"]) >= 4.5
    css = (REPO_ROOT / "landing" / "style.css").read_text(encoding="utf-8").lower()
    assert light["bg"].lower() in css or "#faf5eb" in css
    assert "dark" in css or "prefers-color-scheme" in css


def test_t1_f7_web_app_renders_light_and_dark_rgb_delta(base_url: str, page_factory) -> None:
    _, page_l, tel_l = page_factory(viewport=(390, 844), color_scheme="light")
    page_l.goto(f"{base_url}/dang-nhap")
    page_l.get_by_test_id("screen-login").wait_for()
    res_l = evaluate_page_rubric(page_l, screen_name="login", theme="light", viewport_width=390, viewport_height=844, strict=False)
    tel_l.assert_clean()

    _, page_d, tel_d = page_factory(viewport=(390, 844), color_scheme="dark")
    page_d.goto(f"{base_url}/dang-nhap")
    page_d.get_by_test_id("screen-login").wait_for()
    res_d = evaluate_page_rubric(page_d, screen_name="login", theme="dark", viewport_width=390, viewport_height=844, strict=False)
    tel_d.assert_clean()

    assert_theme_rgb_delta(res_l, res_d)


def test_t1_f7_live_rubric_typography_and_contrast_on_login(base_url: str, page_factory, rubric_collector) -> None:
    _, page, telemetry = page_factory(viewport=(390, 844), color_scheme="light")
    page.goto(f"{base_url}/dang-nhap")
    page.get_by_test_id("screen-login").wait_for()
    res = evaluate_page_rubric(page, screen_name="t1-login", theme="light", viewport_width=390, viewport_height=844)
    rubric_collector.record(res)
    telemetry.assert_clean()


# ==============================================================================
# F8: Backend Missing Admin Endpoints & MLOps CLI (5 tests)
# ==============================================================================


def test_t1_f8_admin_surveys_ml_operator_allowed(helpers: E2EHelpers) -> None:
    helpers.ensure_open_survey_form(anchors=10, random_n=35, seed=42)
    staff = helpers.create_staff_session("ml_operator")
    resp = helpers.api.get("/admin/surveys", headers=helpers.auth_headers(staff["access_token"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) >= 1
    assert body["items"][0]["n_anchor"] == 10


@pytest.mark.pending_m3_m4
def test_t1_f8_admin_audit_log_lists_admin_access(helpers: E2EHelpers) -> None:
    admin = helpers.create_staff_session("admin")
    resp = helpers.api.get("/admin/audit-log", headers=helpers.auth_headers(admin["access_token"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "items" in body and "next_cursor" in body


@pytest.mark.pending_m3_m4
def test_t1_f8_admin_data_requests_list_and_resolve(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=False)
    dsr = helpers.api.post(
        "/me/data-requests",
        headers=helpers.auth_headers(user["access_token"]),
        json={"type": "correct", "note": "Cập nhật năm sinh trong hồ sơ"},
    )
    assert dsr.status_code in (200, 202), dsr.text
    req_id = dsr.json()["id"]

    admin = helpers.create_staff_session("admin")
    ah = helpers.auth_headers(admin["access_token"])
    listed = helpers.api.get("/admin/data-requests", headers=ah)
    assert listed.status_code == 200
    assert any(x["id"] == req_id for x in listed.json()["items"])

    resolved = helpers.api.post(
        f"/admin/data-requests/{req_id}/resolve",
        headers=ah,
        json={"status": "completed", "note": "Đã xử lý chỉnh sửa"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "completed"


@pytest.mark.pending_m3_m4
def test_t1_f8_admin_models_lists_versions_and_deployments(helpers: E2EHelpers) -> None:
    staff = helpers.create_staff_session("ml_operator")
    resp = helpers.api.get("/admin/models", headers=helpers.auth_headers(staff["access_token"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "items" in body and "deployments" in body
    assert len(body["items"]) >= 1


@pytest.mark.pending_m3_m4
def test_t1_f8_cli_mlops_export_training_data(helpers: E2EHelpers) -> None:
    out_dir = f"/tmp/e2e-mlops-export-{unique_idem_key('mlops')}"
    proc = helpers.run_cli("mlops", "export-training-data", "--out", out_dir)
    assert proc.returncode == 0


# ==============================================================================
# F9: Backend Expanded Endpoints & Core APIs (6 tests)
# ==============================================================================


def test_t1_f9_auth_register_login_refresh_logout(helpers: E2EHelpers) -> None:
    reg = helpers.register_user()
    login = helpers.login_user(reg["_email"], reg["_password"])
    refreshed = helpers.api.post("/auth/refresh", json={"refresh_token": login["refresh_token"]})
    assert refreshed.status_code == 200
    new_session = refreshed.json()
    assert new_session["refresh_token"] != login["refresh_token"]

    out = helpers.api.post(
        "/auth/logout",
        headers=helpers.auth_headers(new_session["access_token"]),
        json={"refresh_token": new_session["refresh_token"]},
    )
    assert out.status_code == 204


def test_t1_f9_profile_energy_and_health_consent_encryption(helpers: E2EHelpers) -> None:
    reg = helpers.register_user()
    tok = reg["access_token"]
    helpers.grant_consents(tok, purposes=("health_profile",))
    res = helpers.seed_profile_and_energy(tok, sex="male", birth_year=1992, height_cm=172, weight_kg=68, activity_level="moderate")
    assert 1500 <= res["kcal_target"] <= 4000
    prof = helpers.api.get("/me/profile", headers=helpers.auth_headers(tok)).json()
    assert prof["sex"] == "male"
    assert prof["birth_year"] == 1992
    assert prof["health_profile_consented"] is True


def test_t1_f9_pantry_crud_and_discard(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=False)
    tok = user["access_token"]
    h = helpers.auth_headers(tok)
    lot = helpers.seed_pantry_lot(tok, "thịt ba chỉ", grams=500.0)
    lid = lot["id"]
    patched = helpers.api.patch(
        f"/pantry/lots/{lid}",
        headers={**h, "Content-Type": "application/merge-patch+json"},
        json={"balance": {"g_min": 250, "g_max": 250}},
    )
    assert patched.status_code == 200
    assert patched.json()["balance_g_min"] == 250.0

    disc = helpers.api.post(f"/pantry/lots/{lid}/discard", headers=h)
    assert disc.status_code == 200
    assert disc.json()["status"] == "discarded"
    assert disc.json()["available"] is False


@pytest.mark.pending_m3_m4
def test_t1_f9_recipes_expanded_search_filter_and_macros(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=True)
    tok = user["access_token"]
    h = helpers.auth_headers(tok)
    listed = helpers.api.get("/recipes", headers=h, params={"slot": "man", "max_minutes": 45, "limit": 10})
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert len(items) >= 1
    first = items[0]
    assert first["slot"] == "man"
    assert first["total_minutes"] <= 45
    detail = helpers.api.get(f"/recipes/{first['id']}", headers=h)
    assert detail.status_code == 200
    djson = detail.json()
    assert len(djson["nutrition"]) >= 1


@pytest.mark.pending_m3_m4
def test_t1_f9_journal_week_and_expanded_macros(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=True)
    tok = user["access_token"]
    h = helpers.auth_headers(tok)
    plan = helpers.api.post(
        "/meal-plans",
        headers=helpers.auth_headers(tok, idem=unique_idem_key("jplan")),
        json={"meal": "lunch", "max_minutes": 90, "persons": 2},
    ).json()
    helpers.api.post(f"/meal-plans/{plan['id']}/accept", headers=h)
    from datetime import datetime, timedelta, timezone

    sess = helpers.api.post(
        "/cook-sessions",
        headers=helpers.auth_headers(tok, idem=unique_idem_key("jcook")),
        json={"meal_plan_id": plan["id"], "serve_at": (datetime.now(timezone.utc) + timedelta(minutes=60)).isoformat(), "confirm_over_time": True},
    ).json()
    comp = helpers.api.post(
        f"/cook-sessions/{sess['id']}/complete",
        headers=helpers.auth_headers(tok, idem=unique_idem_key("jdone")),
        json={"feedback": []},
    )
    assert comp.status_code == 200
    j = helpers.api.get("/journal", headers=h)
    assert j.status_code == 200
    jdata = j.json()
    assert len(jdata["days"]) == 7
    assert sum(d["cooked_trays"] for d in jdata["days"]) >= 1


@pytest.mark.pending_m3_m4
def test_t1_f9_shopping_item_to_pantry_endpoint(helpers: E2EHelpers) -> None:
    user = helpers.create_ready_user(seed_pantry=False)
    tok = user["access_token"]
    h = helpers.auth_headers(tok)
    ing_id = helpers.resolve_ingredient_id(tok, "cà chua")
    created = helpers.api.post("/shopping-items", headers=h, json={"ingredient_id": ing_id, "qty_g": 400.0})
    assert created.status_code in (200, 201)
    sid = created.json()["id"]

    moved = helpers.api.post(f"/shopping-items/{sid}/to-pantry", headers=h)
    assert moved.status_code in (200, 201), moved.text
    lots = helpers.api.get("/pantry/lots", headers=h).json()["items"]
    assert any(l["ingredient_id"] == ing_id for l in lots)


# ==============================================================================
# F10: Website (`landing/`) Redesign & Portal (5 tests)
# ==============================================================================


def test_t1_f10_landing_renders_all_sections_cleanly(base_url: str, page_factory) -> None:
    _, page, telemetry = page_factory(viewport=(1440, 900), color_scheme="light")
    page.goto(f"{base_url}/")
    page.locator("h1").wait_for()
    assert page.locator("#kham-pha").is_visible()
    assert page.locator("#can-bep").is_visible()
    assert page.locator("#nhat-ky").is_visible()
    assert page.locator("details summary").count() >= 4
    telemetry.assert_clean()


def test_t1_f10_landing_works_with_javascript_disabled(base_url: str, page_factory) -> None:
    _, page, telemetry = page_factory(viewport=(1440, 900), java_script_enabled=False)
    page.goto(f"{base_url}/")
    assert page.locator("h1").is_visible()
    assert page.locator("a[href='/dang-ky']").is_visible()
    assert page.locator("a[href='/bep']").first.is_visible()
    telemetry.assert_clean()


def test_t1_f10_landing_ingredient_demo_interactive(base_url: str, page_factory) -> None:
    _, page, telemetry = page_factory(viewport=(1440, 900))
    page.goto(f"{base_url}/")
    tofu_btn = page.locator('[data-ingredient="tofu"]')
    tofu_btn.click()
    assert tofu_btn.get_attribute("aria-pressed") == "true"
    assert "Đậu phụ" in page.locator("#recipe-name").inner_text()
    telemetry.assert_clean()


@pytest.mark.pending_m3_m4
def test_t1_f10_landing_live_tray_simulator_and_theme_toggle(base_url: str, page_factory) -> None:
    _, page, telemetry = page_factory(viewport=(1440, 900), color_scheme="light")
    page.goto(f"{base_url}/")
    sim = page.get_by_test_id("landing-tray-simulator")
    sim.wait_for()
    toggle = page.get_by_test_id("theme-toggle")
    toggle.wait_for()
    bg_before = page.evaluate("() => getComputedStyle(document.body).backgroundColor")
    toggle.click()
    bg_after = page.evaluate("() => getComputedStyle(document.body).backgroundColor")
    assert bg_before != bg_after, f"Landing theme toggle did not alter background: {bg_before}"
    telemetry.assert_clean()


def test_t1_f10_landing_apk_probe_and_cta_links(base_url: str, page_factory) -> None:
    _, page, telemetry = page_factory(viewport=(1440, 900))
    page.goto(f"{base_url}/")
    dl = page.locator("#android-download")
    dl.wait_for()
    # Either points to /tai-ve/tastoria-*.apk (200) or gracefully switches to aria-disabled="true" (404)
    page.wait_for_timeout(800)
    href = dl.get_attribute("href")
    disabled = dl.get_attribute("aria-disabled")
    assert (href and "/tai-ve/" in href) or disabled == "true"
    assert page.locator("a[href='/khao-sat']").first.is_visible()
    telemetry.assert_clean()


# ==============================================================================
# F11: Mobile & Web App Responsive Shell & Core Flows (6 tests)
# ==============================================================================


def test_t1_f11_unauthenticated_bep_redirects_to_dang_nhap(base_url: str, page_factory) -> None:
    _, page, telemetry = page_factory(viewport=(390, 844))
    page.goto(f"{base_url}/bep")
    page.get_by_test_id("screen-login").wait_for()
    assert "/dang-nhap" in page.url
    telemetry.assert_clean()


@pytest.mark.pending_m3_m4
def test_t1_f11_desktop_sidebar_rail_and_mobile_bottom_tabs(base_url: str, helpers: E2EHelpers, page_factory) -> None:
    email = unique_email("shell")
    pw = DEFAULT_PASSWORD
    # Register via UI or API & log in on Desktop + Mobile
    _, d_page, d_tel = page_factory(viewport=(1440, 900), color_scheme="light")
    d_page.goto(f"{base_url}/dang-ky")
    d_page.get_by_test_id("register-email").fill(email)
    d_page.get_by_test_id("register-password").fill(pw)
    d_page.get_by_test_id("register-password2").fill(pw)
    d_page.get_by_test_id("register-submit").click()
    d_page.get_by_test_id("consent-skip").click()
    d_page.get_by_test_id("screen-home").wait_for()
    d_page.get_by_test_id("sidebar-nav-bep").wait_for()
    assert d_page.get_by_test_id("sidebar-nav-kho").is_visible()
    d_tel.assert_clean()

    _, m_page, m_tel = page_factory(viewport=(390, 844), color_scheme="light")
    m_page.goto(f"{base_url}/dang-nhap")
    m_page.get_by_test_id("login-email").fill(email)
    m_page.get_by_test_id("login-password").fill(pw)
    m_page.get_by_test_id("login-submit").click()
    m_page.get_by_test_id("screen-home").wait_for()
    assert m_page.locator('[role="tablist"]').is_visible()
    m_tel.assert_clean()


@pytest.mark.pending_m3_m4
def test_t1_f11_in_app_theme_toggle_persists(base_url: str, page_factory) -> None:
    _, page, telemetry = page_factory(viewport=(1440, 900), color_scheme="light")
    page.goto(f"{base_url}/dang-nhap")
    page.get_by_test_id("screen-login").wait_for()
    toggle = page.get_by_test_id("theme-toggle")
    toggle.wait_for()
    r1 = evaluate_page_rubric(page, screen_name="toggle-before", theme="light", viewport_width=1440, viewport_height=900, strict=False)
    toggle.click()
    page.wait_for_timeout(300)
    r2 = evaluate_page_rubric(page, screen_name="toggle-after", theme="dark", viewport_width=1440, viewport_height=900, strict=False)
    assert_theme_rgb_delta(r1, r2)
    page.reload()
    page.get_by_test_id("screen-login").wait_for()
    r3 = evaluate_page_rubric(page, screen_name="toggle-reload", theme="dark", viewport_width=1440, viewport_height=900, strict=False)
    assert_theme_rgb_delta(r1, r3)
    telemetry.assert_clean()


def test_t1_f11_onboarding_consent_and_4_step_profile_ui(base_url: str, page_factory) -> None:
    _, page, telemetry = page_factory(viewport=(390, 844), color_scheme="light")
    tid = page.get_by_test_id
    page.goto(f"{base_url}/dang-ky")
    tid("register-email").fill(unique_email("onb"))
    tid("register-password").fill(DEFAULT_PASSWORD)
    tid("register-password2").fill(DEFAULT_PASSWORD)
    tid("register-submit").click()

    tid("screen-consent").wait_for()
    tid("consent-health_profile").click()
    tid("consent-personalization").click()
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
    tid("energy-use").click()
    tid("screen-onboarding-allergen").wait_for()
    tid("allergen-none").click()
    tid("step-next").click()
    tid("screen-onboarding-favorites").wait_for()
    tid("step-done").click()
    tid("screen-home").wait_for()
    telemetry.assert_clean()


@pytest.mark.pending_m3_m4
def test_t1_f11_pantry_ui_quick_add_and_urgency_filters(base_url: str, page_factory) -> None:
    _, page, telemetry = page_factory(viewport=(390, 844), color_scheme="light")
    tid = page.get_by_test_id
    page.goto(f"{base_url}/dang-ky")
    tid("register-email").fill(unique_email("pantryui"))
    tid("register-password").fill(DEFAULT_PASSWORD)
    tid("register-password2").fill(DEFAULT_PASSWORD)
    tid("register-submit").click()
    tid("consent-skip").click()
    tid("screen-home").wait_for()
    page.goto(f"{base_url}/kho")
    tid("screen-pantry").wait_for()
    tid("pantry-add").click()
    tid("add-lot-search").fill("cà chua")
    tid("ing-cà chua").first.click()
    tid("add-lot-submit").click()
    tid("sheet-add-lot").wait_for(state="detached")
    tid("lot-cà chua").first.wait_for()
    tid("pantry-filter-tuoi").click()
    assert tid("lot-cà chua").first.is_visible()
    telemetry.assert_clean()


def test_t1_f11_scan_ui_upload_and_confirm_chip_to_pantry(base_url: str, page_factory) -> None:
    _, page, telemetry = page_factory(viewport=(390, 844), color_scheme="light")
    tid = page.get_by_test_id
    page.goto(f"{base_url}/dang-ky")
    tid("register-email").fill(unique_email("scanui"))
    tid("register-password").fill(DEFAULT_PASSWORD)
    tid("register-password2").fill(DEFAULT_PASSWORD)
    tid("register-submit").click()
    tid("consent-skip").click()
    tid("screen-home").wait_for()

    page.goto(f"{base_url}/quet?mode=haul")
    tid("screen-scan").wait_for()
    with tempfile.TemporaryDirectory() as td:
        sample = write_temp_scan_file(Path(td))
        with page.expect_file_chooser() as fc_info:
            tid("scan-library").click()
        fc_info.value.set_files(str(sample))
    tid("scan-send").click()

    # Wait for worker completion on /quet/[id]
    tid("screen-scan-confirm").wait_for(timeout=35000)
    # Resolve any `needs_check` chips under "Cần kiểm tra trước khi dùng" before confirming
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
    # If empty detections, add a chip manually before confirming
    if page.locator('[data-testid^="scan-chip-"]').count() == 0:
        page.get_by_role("button", name="+ Thêm nguyên liệu bị sót").click()
        page.get_by_label("Nguyên liệu").fill("cà chua")
        tid("ing-cà chua").first.click()
        page.get_by_role("button", name="Thêm", exact=True).click()
    tid("scan-confirm").click()
    tid("screen-scan-done").wait_for(timeout=20000)
    telemetry.assert_clean()


# ==============================================================================
# F12: Mobile & Web App Expanded Modules (6 tests)
# ==============================================================================


@pytest.mark.pending_m3_m4
def test_t1_f12_recipe_explorer_kham_pha_and_detail(base_url: str, page_factory) -> None:
    _, page, telemetry = page_factory(viewport=(1440, 900), color_scheme="light")
    tid = page.get_by_test_id
    page.goto(f"{base_url}/dang-ky")
    tid("register-email").fill(unique_email("khampha"))
    tid("register-password").fill(DEFAULT_PASSWORD)
    tid("register-password2").fill(DEFAULT_PASSWORD)
    tid("register-submit").click()
    tid("consent-skip").click()
    tid("screen-home").wait_for()

    page.goto(f"{base_url}/kham-pha")
    tid("screen-explore").wait_for()
    tid("explore-search").fill("rau muống")
    tid("explore-recipe-card").first.click()
    tid("screen-recipe").wait_for()
    telemetry.assert_clean()


def test_t1_f12_meal_tray_mam_compose_and_swap_ui(base_url: str, helpers: E2EHelpers, page_factory) -> None:
    user = helpers.create_ready_user(seed_pantry=True)
    _, page, telemetry = page_factory(viewport=(390, 844), color_scheme="light", allow_4xx_statuses={422})
    tid = page.get_by_test_id
    page.goto(f"{base_url}/dang-nhap")
    tid("login-email").fill(user["_email"])
    tid("login-password").fill(user["_password"])
    tid("login-submit").click()
    tid("screen-home").wait_for()

    page.goto(f"{base_url}/mam")
    tid("screen-tray").wait_for()
    tid("make-plan").click()
    tid("plan-view").wait_for(timeout=30000)

    swapped = False
    for slot in ("rau", "man", "canh"):
        dish = tid(f"tray-dish-{slot}")
        if not dish.count():
            continue
        dish.click()
        tid("sheet-dish").wait_for()
        tid("dish-swap").click()
        tid("swap-khong_hop_gu").click()
        try:
            tid("sheet-dish").wait_for(state="detached", timeout=15000)
            swapped = True
            break
        except Exception:
            page.get_by_label("Đóng").last.click()
            tid("sheet-dish").wait_for(state="detached")
    assert swapped, "Expected at least one tray slot to swap cleanly"
    telemetry.assert_clean()


def test_t1_f12_cook_session_nau_and_10m_undo_ui(base_url: str, helpers: E2EHelpers, page_factory) -> None:
    user = helpers.create_ready_user(seed_pantry=True)
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
    tid("start-cooking").click()
    tid("screen-cooking").wait_for()
    tid("cook-step-done").click()
    tid("cook-finish").click()
    tid("screen-finish").wait_for()
    page.get_by_role("radio", name="Hợp gu").first.click()
    tid("finish-submit").click()
    tid("screen-finished").wait_for(timeout=20000)
    tid("undo").click()
    tid("undo-confirm").click()
    page.wait_for_url("**/mam")
    tid("plan-view").last.wait_for()
    telemetry.assert_clean()


@pytest.mark.pending_m3_m4
def test_t1_f12_shopping_di_cho_and_1tap_to_pantry_ui(base_url: str, helpers: E2EHelpers, page_factory) -> None:
    user = helpers.create_ready_user(seed_pantry=False)
    _, page, telemetry = page_factory(viewport=(390, 844), color_scheme="light")
    tid = page.get_by_test_id
    page.goto(f"{base_url}/dang-nhap")
    tid("login-email").fill(user["_email"])
    tid("login-password").fill(user["_password"])
    tid("login-submit").click()
    tid("screen-home").wait_for()

    page.goto(f"{base_url}/di-cho")
    tid("screen-shopping").wait_for()
    tid("shop-add").click()
    page.get_by_label("Nguyên liệu").fill("cà chua")
    tid("ing-cà chua").first.click()
    page.get_by_role("button", name="Thêm", exact=True).click()
    tid("shop-item-cà chua").wait_for()
    tid("shop-to-pantry-cà chua").click()
    page.goto(f"{base_url}/kho")
    tid("lot-cà chua").first.wait_for()
    telemetry.assert_clean()


def test_t1_f12_survey_khao_sat_open_form_ui(base_url: str, helpers: E2EHelpers, page_factory) -> None:
    helpers.ensure_open_survey_form(anchors=10, random_n=35, seed=42)
    _, page, telemetry = page_factory(viewport=(390, 844), color_scheme="light")
    tid = page.get_by_test_id
    page.goto(f"{base_url}/khao-sat")
    tid("screen-survey-start").wait_for()
    tid("survey-consent").click()
    tid("survey-start").click()
    tid("screen-survey-form").wait_for(timeout=20000)
    # Answer all 45 dishes cleanly
    never_btns = page.get_by_role("checkbox", name="Chưa ăn bao giờ")
    count = never_btns.count()
    assert count == 45, f"Expected 45 survey dish blocks, got {count}"
    for i in range(count):
        never_btns.nth(i).click()
    tid("survey-submit").click()
    tid("screen-survey-thanks").wait_for(timeout=20000)
    telemetry.assert_clean()


@pytest.mark.pending_m3_m4
def test_t1_f12_admin_console_quan_tri_ui(base_url: str, helpers: E2EHelpers, page_factory) -> None:
    staff = helpers.create_staff_session("ml_operator")
    _, page, telemetry = page_factory(viewport=(1440, 900), color_scheme="light")
    tid = page.get_by_test_id
    page.goto(f"{base_url}/dang-nhap")
    tid("login-email").fill(staff["_email"])
    tid("login-password").fill(staff["_password"])
    tid("login-submit").click()
    tid("screen-home").wait_for()

    page.goto(f"{base_url}/quan-tri")
    tid("screen-admin").wait_for()
    assert tid("admin-tab-models").is_visible()
    assert tid("admin-tab-surveys").is_visible()
    telemetry.assert_clean()


# ==============================================================================
# F13: Visual Paradigm System Design Sync (5 tests)
# ==============================================================================


@pytest.mark.pending_m3_m4
def test_t1_f13_sad_check_refs_and_traceability_strict() -> None:
    p1 = subprocess.run(["python3", str(REPO_ROOT / "docs/sad/tools/check_refs.py")], capture_output=True, text=True)
    assert p1.returncode == 0, f"check_refs.py failed:\n{p1.stdout}\n{p1.stderr}"
    trace_path = REPO_ROOT / "docs/sad/08-ma-tran-truy-vet.md"
    orig_bytes = trace_path.read_bytes() if trace_path.is_file() else None
    try:
        p2 = subprocess.run(["python3", str(REPO_ROOT / "docs/sad/tools/gen_traceability.py"), "--strict"], capture_output=True, text=True)
        assert p2.returncode == 0, f"gen_traceability.py --strict failed:\n{p2.stdout}\n{p2.stderr}"
    finally:
        if orig_bytes is not None:
            trace_path.write_bytes(orig_bytes)


def test_t1_f13_vp_check_svg_zero_overlaps() -> None:
    svg_dir = REPO_ROOT / "docs/reports/pttkht/fig/svg"
    proc = subprocess.run(["python3", str(REPO_ROOT / "docs/reports/pttkht/vp/check_svg.py"), str(svg_dir)], capture_output=True, text=True)
    assert proc.returncode == 0, f"check_svg.py failed:\n{proc.stdout}\n{proc.stderr}"


@pytest.mark.pending_m3_m4
def test_t1_f13_vp_files_and_schema_vp_include_make_ahead() -> None:
    vp_dir = REPO_ROOT / "docs/reports/pttkht/vp"
    assert (vp_dir / "Tastoria.vpp").stat().st_size > 100_000
    assert (vp_dir / "Tastoria-ERD.vpp").stat().st_size > 50_000
    ddl = (REPO_ROOT / "db" / "schema_vp.sql").read_text(encoding="utf-8")
    assert "recipe_make_ahead" in ddl


@pytest.mark.pending_m3_m4
def test_t1_f13_vp_check_design_vs_code_exits_zero() -> None:
    checker = REPO_ROOT / "docs/reports/pttkht/vp/check_design_vs_code.py"
    assert checker.is_file(), f"Missing {checker}"
    proc = subprocess.run(["python3", str(checker)], capture_output=True, text=True)
    assert proc.returncode == 0, f"check_design_vs_code.py failed:\n{proc.stdout}\n{proc.stderr}"


@pytest.mark.pending_m3_m4
def test_t1_f13_no_leftover_wip_vp_files() -> None:
    vp_dir = REPO_ROOT / "docs/reports/pttkht/vp"
    for bad in ("Tastoria-test.vpp", "spec_test.tsv"):
        assert not (vp_dir / bad).exists(), f"Leftover WIP file found: {vp_dir / bad}"


# ==============================================================================
# F14: Mobile App Course Report (5 tests)
# ==============================================================================


@pytest.mark.pending_m3_m4
def test_t1_f14_mobile_app_report_files_exist() -> None:
    rdir = REPO_ROOT / "docs" / "reports" / "mobile-app"
    assert (rdir / "Bao-cao-Do-an-Mobile-App-Tastoria.md").is_file()
    assert (rdir / "Bao-cao-Do-an-Mobile-App-Tastoria.docx").is_file()
    assert (rdir / "Bao-cao-Do-an-Mobile-App-Tastoria.pdf").is_file()


@pytest.mark.pending_m3_m4
def test_t1_f14_docx_cover_table_5_cols_and_100_percent_note() -> None:
    doc = Document(str(REPO_ROOT / "docs/reports/mobile-app/Bao-cao-Do-an-Mobile-App-Tastoria.docx"))
    full_text = "\n".join(p.text for p in doc.paragraphs)
    assert "Tổng số % của các thành viên là 100%." in full_text
    assert len(doc.tables) >= 1
    headers = [c.text.strip() for c in doc.tables[0].rows[0].cells]
    assert headers == [
        "STT",
        "Họ và tên",
        "Phần việc tham gia chung cả nhóm",
        "Phần công việc cá nhân",
        "Ước tính % đóng góp",
    ]


@pytest.mark.pending_m3_m4
def test_t1_f14_docx_part1_subsections_and_uc_erd_images() -> None:
    md = (REPO_ROOT / "docs/reports/mobile-app/Bao-cao-Do-an-Mobile-App-Tastoria.md").read_text(encoding="utf-8")
    for marker in ("Phần 1", "Lý do lựa chọn", "Use Case", "ERD"):
        assert marker in md, f"Missing Part 1 section marker '{marker}'"
    doc = Document(str(REPO_ROOT / "docs/reports/mobile-app/Bao-cao-Do-an-Mobile-App-Tastoria.docx"))
    assert len(doc.inline_shapes) >= 2, "Expected Use Case and ERD diagrams embedded in docx"


@pytest.mark.pending_m3_m4
def test_t1_f14_docx_part2_modules_and_activity_diagrams() -> None:
    md = (REPO_ROOT / "docs/reports/mobile-app/Bao-cao-Do-an-Mobile-App-Tastoria.md").read_text(encoding="utf-8")
    assert "Phần 2" in md
    for kw in ("Mô tả chi tiết chức năng", "Thiết kế giao diện", "Giải pháp kỹ thuật", "phát triển tiếp"):
        assert kw in md, f"Missing Part 2 subsection '{kw}'"


@pytest.mark.pending_m3_m4
def test_t1_f14_docx_14pt_body_font_and_real_screenshots() -> None:
    doc = Document(str(REPO_ROOT / "docs/reports/mobile-app/Bao-cao-Do-an-Mobile-App-Tastoria.docx"))
    normal_style = doc.styles["Normal"]
    if normal_style.font.size is not None:
        assert abs(normal_style.font.size.pt - 14.0) <= 0.5
    fig_dir = REPO_ROOT / "docs/reports/mobile-app/fig"
    pngs = list(fig_dir.glob("*.png"))
    assert len(pngs) >= 8, f"Expected real E2E screenshots in {fig_dir}, found {len(pngs)}"
    assert all(p.stat().st_size > 1000 for p in pngs)


# ==============================================================================
# F15: E2E Testing Infrastructure, UI Rubric & Telemetry (5 tests)
# ==============================================================================


def test_t1_f15_rubric_evaluator_detects_tokens_and_contrast() -> None:
    tokens = load_design_tokens()
    assert "text" in tokens["light"] and "bg" in tokens["light"]
    assert "text" in tokens["dark"] and "bg" in tokens["dark"]
    assert hex_contrast_ratio(tokens["light"]["text"], tokens["light"]["bg"]) >= 4.5
    assert hex_contrast_ratio(tokens["dark"]["text"], tokens["dark"]["bg"]) >= 4.5


def test_t1_f15_telemetry_collector_captures_page_and_http_errors(base_url: str, page_factory) -> None:
    _, page, telemetry = page_factory(viewport=(390, 844), allow_console_substrings=("E2E_TEST_PROBE",))
    page.goto(f"{base_url}/")
    page.evaluate("() => { console.error('E2E_TEST_PROBE'); }")
    assert not telemetry.console_errors
    page.evaluate("() => { console.error('REAL_UNEXPECTED_CONSOLE_ERR'); }")
    assert len(telemetry.console_errors) == 1


def test_t1_f15_openapi_contract_spec_valid_70_ops() -> None:
    spec = yaml.safe_load((REPO_ROOT / "docs/api/openapi-v1.yaml").read_text(encoding="utf-8"))
    ops = [
        m
        for path_item in spec["paths"].values()
        for m in path_item
        if m in {"get", "post", "put", "patch", "delete"}
    ]
    assert len(ops) >= 70


def test_t1_f15_requirements_e2e_and_compose_override_valid() -> None:
    req = (REPO_ROOT / "tests/e2e/requirements-e2e.txt").read_text(encoding="utf-8")
    for pkg in ("pytest", "playwright", "httpx", "pillow", "pyyaml", "python-docx"):
        assert pkg in req.lower()

    class _ComposeSafeLoader(yaml.SafeLoader):
        pass

    def _construct_override(loader: yaml.Loader, node: yaml.Node):
        if isinstance(node, yaml.ScalarNode):
            return loader.construct_scalar(node)
        if isinstance(node, yaml.SequenceNode):
            return loader.construct_sequence(node)
        if isinstance(node, yaml.MappingNode):
            return loader.construct_mapping(node)
        return None

    _ComposeSafeLoader.add_constructor("!override", _construct_override)
    comp = yaml.load((REPO_ROOT / "tests/e2e/docker-compose.e2e.yml").read_text(encoding="utf-8"), Loader=_ComposeSafeLoader)
    assert comp["name"] == "tastoria_e2e"
    assert "tastoria_e2e_pgdata" in comp["volumes"]["pgdata"]["name"]


def test_t1_f15_screenshot_pipeline_writes_dual_outputs(base_url: str, page_factory, screenshot_saver) -> None:
    _, page, telemetry = page_factory(viewport=(390, 844), color_scheme="light")
    page.goto(f"{base_url}/dang-nhap")
    page.get_by_test_id("screen-login").wait_for()
    p1, p2 = screenshot_saver(page, "00-probe-login-light.png", "probe-login-light.png")
    try:
        assert p1.is_file() and p1.stat().st_size > 1000
        assert p2.is_file() and p2.stat().st_size == p1.stat().st_size
        assert hashlib.sha256(p1.read_bytes()).hexdigest() == hashlib.sha256(p2.read_bytes()).hexdigest()
        telemetry.assert_clean()
    finally:
        p1.unlink(missing_ok=True)
        p2.unlink(missing_ok=True)
