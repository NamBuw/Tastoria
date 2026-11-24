"""Tier 3: Cross-feature combinations, raw-fridge vs cooked-meal isolation, and scan->pantry->journal flows."""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml
from kb_helpers import API, accept, add_lot, cook, key, plan, q, stock_for, user
from PIL import Image

from tastoria.modules.catalog.bundle import load_bundle
from tastoria.modules.catalog.nutrition import compute
from tastoria.modules.scan import worker as job

pytestmark = pytest.mark.tier3

REPO_ROOT = Path(__file__).resolve().parents[3]
KB_DIR = REPO_ROOT / "data/kb"
PROCESSED_DIR = REPO_ROOT / "data/processed"
FOOD_ASSETS_DIR = REPO_ROOT / "app/assets/food"

BASELINE_CLEAN_COOKED_DISHES = (
    "bun-dau.webp",
    "bun-thit-nuong.webp",
    "caramel-pork.webp",
    "caramel-trout.webp",
    "seabass-ginger.webp",
    "silken-tofu.webp",
    "vietnamese-table.webp",
)

MAN, RAU, CANH = "Ba chỉ chiên nước mắm", "Bí ngòi xào tỏi", "Canh rau ngót thịt băm"


def test_pure_kb_nutrition_to_meal_calorie_consistency(e2e_cfg, meal_calorie_probe: dict | None) -> None:
    b = load_bundle(KB_DIR, PROCESSED_DIR)
    nut = compute(b, PROCESSED_DIR)

    rice_json = json.loads((PROCESSED_DIR / "kb/rice_bowl.json").read_text(encoding="utf-8"))
    assert float(rice_json["energy_kcal"]) == pytest.approx(nut.rice_bowl_kcal, abs=0.2)

    nin_doc = yaml.safe_load((KB_DIR / "validation/nin_dishes.yaml").read_text(encoding="utf-8"))
    for entry in nin_doc["dishes"]:
        slug = entry.get("kb_slug")
        if slug:
            assert slug in b.recipes, f"nin_dishes.yaml kb_slug {slug!r} missing from KB recipes"

    with (PROCESSED_DIR / "kb/recipe_nutrition.csv").open(newline="", encoding="utf-8") as f:
        csv_rows = {r["slug"]: float(r["kcal_per_serving"]) for r in csv.DictReader(f)}
    for slug in list(b.recipes)[:25]:
        assert abs(csv_rows[slug] - nut.per_serving[slug]["energy_kcal"]) < 10.0

    if meal_calorie_probe is not None:
        svc = meal_calorie_probe["service"]
        deps = meal_calorie_probe["deps"]
        kb_vals = [svc.estimate_meal_calories(deps, dish_slug="bo-kho", portion=p).estimated_kcal for p in ("nho", "vua", "lon")]
        assert kb_vals[0] < kb_vals[1] < kb_vals[2]
        assert kb_vals[1] == pytest.approx(csv_rows["bo-kho"], abs=0.2)
        if meal_calorie_probe["has_onnx"] or e2e_cfg.strict:
            pho_bytes = (FOOD_ASSETS_DIR / "pho.webp").read_bytes()
            vis_vals = [
                svc.estimate_meal_calories(deps, image_bytes=pho_bytes, portion=p).estimated_kcal
                for p in ("nho", "vua", "lon")
            ]
            assert vis_vals[0] < vis_vals[1] < vis_vals[2]
    else:
        assert not e2e_cfg.strict


def test_raw_fridge_vs_cooked_meal_detector_suppression(e2e_cfg, e2e_detector) -> None:
    all_cooked = sorted(FOOD_ASSETS_DIR.glob("*.webp"))
    assert len(all_cooked) == 15

    if e2e_cfg.strict:
        total_boxes = 0
        for p in all_cooked:
            with Image.open(p) as im:
                boxes = e2e_detector.detector.detect(im.convert("RGB"))
            total_boxes += len(boxes)
        assert total_boxes <= 1, f"Strict raw-vs-cooked isolation failed: {total_boxes} false boxes on 15 cooked dishes"
    else:
        for fname in BASELINE_CLEAN_COOKED_DISHES:
            p = FOOD_ASSETS_DIR / fname
            assert p.is_file()
            with Image.open(p) as im:
                boxes = e2e_detector.detector.detect(im.convert("RGB"))
            assert boxes == [], f"Unexpected raw boxes on clean baseline cooked dish {fname}: {boxes}"


@pytest.mark.integration
def test_multi_photo_fridge_scan_to_pantry_aggregation(
    kb_client, kb_db, e2e_worker_ctx, e2e_detector, real_produce_images: list[Path]
) -> None:
    h = user(kb_client)
    # Pick a produce image that yields >= 1 real detection with active model
    chosen = None
    for p in real_produce_images:
        with Image.open(p) as im:
            if e2e_detector.detector.detect(im.convert("RGB")):
                chosen = p
                break
    assert chosen is not None
    raw_bytes = chosen.read_bytes()

    # Upload 2 identical photos on same shelf (shelf_groups=['1','1'])
    files = [("images", (f"p{i}.jpg", raw_bytes, "image/jpeg")) for i in range(2)]
    r_same = kb_client.post(
        f"{API}/scans",
        data={"mode": "fridge", "shelf_groups": ["1", "1"]},
        files=files,
        headers=h | key(),
    )
    assert r_same.status_code == 202, r_same.text
    sid_same = r_same.json()["id"]
    assert job.run_job(e2e_worker_ctx, __import__("uuid").UUID(sid_same)) == "done"
    scan_same = kb_client.get(f"{API}/scans/{sid_same}", headers=h).json()
    assert len(scan_same["items"]) > 0
    assert q(kb_db, "SELECT count(*) FROM pantry_lots").scalar() == 0

    # Same 2 photos marked as different shelves (shelf_groups=['1','2']) -> countable counts double
    r_diff = kb_client.post(
        f"{API}/scans",
        data={"mode": "fridge", "shelf_groups": ["1", "2"]},
        files=files,
        headers=h | key(),
    )
    assert r_diff.status_code == 202, r_diff.text
    sid_diff = r_diff.json()["id"]
    assert job.run_job(e2e_worker_ctx, __import__("uuid").UUID(sid_diff)) == "done"
    scan_diff = kb_client.get(f"{API}/scans/{sid_diff}", headers=h).json()

    same_countable = {i["ingredient_id"]: i["model_count"] for i in scan_same["items"] if i["model_count"] is not None}
    diff_countable = {i["ingredient_id"]: i["model_count"] for i in scan_diff["items"] if i["model_count"] is not None}
    for ing_id, cnt in same_countable.items():
        assert diff_countable[ing_id] == cnt * 2

    # Uncountable items require qty_level before confirm
    uncountable_ids = [i["id"] for i in scan_same["items"] if i["final_count"] is None and i["qty_level"] is None]
    if uncountable_ids:
        conf_err = kb_client.post(f"{API}/scans/{sid_same}/confirm", headers=h)
        assert conf_err.status_code == 422 and conf_err.json()["code"] == "qty_level_required"
        assert q(kb_db, "SELECT count(*) FROM pantry_lots").scalar() == 0
        for item_id in uncountable_ids:
            pr = kb_client.patch(
                f"{API}/scans/{sid_same}/items/{item_id}",
                json={"qty_level": "vua"},
                headers=h | {"Content-Type": "application/merge-patch+json"},
            )
            assert pr.status_code == 200, pr.text

    c1 = kb_client.post(f"{API}/scans/{sid_same}/confirm", headers=h)
    c2 = kb_client.post(f"{API}/scans/{sid_same}/confirm", headers=h)
    assert c1.status_code == c2.status_code == 200
    assert c1.json() == c2.json()
    assert q(kb_db, "SELECT count(*) FROM pantry_lots").scalar() == len(scan_same["items"])


@pytest.mark.integration
def test_cooked_meal_scan_upload_pre_confirm_leaves_pantry_untouched(kb_client, kb_db, e2e_worker_ctx) -> None:
    h = user(kb_client)
    buf = io.BytesIO()
    with Image.open(FOOD_ASSETS_DIR / "pho.webp") as im:
        im.convert("RGB").save(buf, "JPEG", quality=90)
    r = kb_client.post(
        f"{API}/scans",
        data={"mode": "fridge"},
        files=[("images", ("pho.jpg", buf.getvalue(), "image/jpeg"))],
        headers=h | key(),
    )
    assert r.status_code == 202, r.text
    sid = r.json()["id"]
    assert job.run_job(e2e_worker_ctx, __import__("uuid").UUID(sid)) == "done"
    assert q(kb_db, "SELECT count(*) FROM pantry_lots").scalar() == 0
    d = kb_client.post(f"{API}/scans/{sid}/discard", headers=h)
    assert d.status_code == 200 and d.json()["status"] == "discarded"
    assert q(kb_db, "SELECT count(*) FROM pantry_lots").scalar() == 0


@pytest.mark.integration
def test_kb_nutrition_to_journal_calibrated_flow(kb_client, kb_db) -> None:
    h = user(kb_client, "health_profile")
    kb_client.put(f"{API}/me/energy-target", json={"kcal_target": 2000, "kcal_source": "user"}, headers=h)
    stock_for(kb_client, h, kb_db, MAN, RAU, CANH)
    add_lot(kb_client, h, kb_db, "tỏi", 100)
    p = accept(kb_client, h, plan(kb_client, h)["id"])
    s = cook(kb_client, h, p["id"])
    comp = kb_client.post(f"{API}/cook-sessions/{s['id']}/complete", headers=h | key())
    assert comp.status_code == 200, comp.text

    tz = q(kb_db, "SELECT timezone FROM user_settings").scalar()
    local_day = datetime.fromisoformat(comp.json()["cook_session"]["completed_at"]).astimezone(ZoneInfo(tz)).date()
    y, w, _ = local_day.isocalendar()
    wk = kb_client.get(f"{API}/journal", params={"week": f"{y}-W{w:02d}"}, headers=h).json()
    assert wk["kcal_range_status"] == "calibrated"
    day = next(d for d in wk["days"] if d["date"] == local_day.isoformat())
    expected_kcal = sum(i["kcal_per_person"] for i in p["items"]) + p["rice_bowls_per_person"] * 173.2
    assert day["kcal_per_person"] == pytest.approx(expected_kcal, abs=0.4)
    assert wk["macros"]["protein_g"] > 0 and wk["macros"]["carbs_g"] > 0
