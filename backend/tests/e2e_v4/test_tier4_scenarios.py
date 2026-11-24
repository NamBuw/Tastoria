"""Tier 4: Real-world scenarios S3 (c1/c5 latency SLA), S4 (full user journey), S5 (Vietnamese meal calorie)."""

from __future__ import annotations

import io
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pytest
import yaml
from kb_helpers import API, accept, cook, key, plan, q, stock_for, user
from PIL import Image

from tastoria.modules.catalog.bundle import load_bundle
from tastoria.modules.catalog.nutrition import compute
from tastoria.modules.scan import worker as job
from tastoria.modules.scan.images import sanitize

pytestmark = pytest.mark.tier4

REPO_ROOT = Path(__file__).resolve().parents[3]
KB_DIR = REPO_ROOT / "data/kb"
PROCESSED_DIR = REPO_ROOT / "data/processed"
FOOD_ASSETS_DIR = REPO_ROOT / "app/assets/food"

MAN, RAU, CANH = "Ba chỉ chiên nước mắm", "Bí ngòi xào tỏi", "Canh rau ngót thịt băm"


@pytest.mark.parametrize("concurrency", [1, 5])
def test_s3_smart_fridge_scan_latency_sla_c1_and_c5(
    concurrency: int, e2e_cfg, e2e_detector, real_produce_images: list[Path]
) -> None:
    """S3: CPU serving latency SLA (p95 <= 3000 ms) at c=1 and c=5 over real produce & heldout photos."""
    payloads = [p.read_bytes() for p in real_produce_images[:20]]
    n_calls = 20 if concurrency == 1 else 25

    # Warmup
    warm = sanitize(payloads[0])
    with Image.open(io.BytesIO(warm.jpeg)) as im:
        _ = e2e_detector.detector.detect(im)

    def _run_one(idx: int) -> float:
        raw = payloads[idx % len(payloads)]
        t0 = time.perf_counter()
        clean = sanitize(raw)
        with Image.open(io.BytesIO(clean.jpeg)) as im:
            boxes = e2e_detector.detector.detect(im)
        dt = (time.perf_counter() - t0) * 1000.0
        assert all(0.0 <= b.x1 < b.x2 <= 1.0 and 0.0 <= b.y1 < b.y2 <= 1.0 for b in boxes)
        return dt

    if concurrency == 1:
        latencies = [_run_one(i) for i in range(n_calls)]
    else:
        with ThreadPoolExecutor(max_workers=concurrency) as ex:
            latencies = list(ex.map(_run_one, range(n_calls)))

    arr = np.asarray(latencies, dtype=np.float64)
    p50, p95, mx = float(np.percentile(arr, 50)), float(np.percentile(arr, 95)), float(arr.max())
    print(f"[S3 c={concurrency}] n={n_calls} p50={p50:.1f}ms p95={p95:.1f}ms max={mx:.1f}ms")
    assert p95 <= e2e_cfg.latency_sla_ms, f"c={concurrency} p95={p95:.1f} ms > {e2e_cfg.latency_sla_ms} ms"


@pytest.mark.integration
def test_s4_full_user_journey_fridge_scan_exif6_to_pantry_meal_journal(
    kb_client, kb_db, e2e_worker_ctx, e2e_detector, real_produce_images: list[Path]
) -> None:
    """S4: Register -> consents -> EXIF=6 scan -> poll -> chip edit -> confirm -> meal plan -> cook -> journal."""
    h = user(kb_client, "health_profile")
    kb_client.put(f"{API}/me/energy-target", json={"kcal_target": 2000, "kcal_source": "user"}, headers=h)

    # Pick a real produce photo where the detector finds >= 1 item, and wrap it with EXIF=6 + GPS
    chosen = None
    for p in real_produce_images:
        with Image.open(p) as im:
            if e2e_detector.detector.detect(im.convert("RGB")):
                chosen = p
                break
    assert chosen is not None

    with Image.open(chosen) as orig:
        upright_w, upright_h = orig.size
        ex = Image.Exif()
        ex[0x0112] = 6
        ex[0x8825] = {1: "N", 2: (21.0, 1.0, 30.0), 3: "E", 4: (105.0, 51.0, 0.0)}
        buf = io.BytesIO()
        orig.convert("RGB").save(buf, "JPEG", quality=90, exif=ex.tobytes())
        exif6_bytes = buf.getvalue()

    up = kb_client.post(
        f"{API}/scans",
        data={"mode": "fridge"},
        files=[("images", ("fridge.jpg", exif6_bytes, "image/jpeg"))],
        headers=h | key(),
    )
    assert up.status_code == 202, up.text
    sid = up.json()["id"]

    assert job.run_job(e2e_worker_ctx, uuid.UUID(sid)) == "done"
    polled = kb_client.get(f"{API}/scans/{sid}?wait=10", headers=h)
    assert polled.status_code == 200, polled.text
    scan = polled.json()
    assert scan["status"] == "done" and len(scan["items"]) > 0
    # Orientation=6 swaps width and height after exif_transpose
    assert (scan["images"][0]["width"], scan["images"][0]["height"]) == (upright_h, upright_w)

    for it in scan["items"]:
        if it["final_count"] is None and it["qty_level"] is None:
            pr = kb_client.patch(
                f"{API}/scans/{sid}/items/{it['id']}",
                json={"qty_level": "vua"},
                headers=h | {"Content-Type": "application/merge-patch+json"},
            )
            assert pr.status_code == 200, pr.text

    conf = kb_client.post(f"{API}/scans/{sid}/confirm", headers=h)
    assert conf.status_code == 200, conf.text
    lots = kb_client.get(f"{API}/pantry/lots", headers=h).json()["items"]
    assert len(lots) == len(scan["items"])

    # Stock tray ingredients alongside scanned lots, compose meal plan, cook, and inspect calibrated journal
    stock_for(kb_client, h, kb_db, MAN, RAU, CANH)
    p = accept(kb_client, h, plan(kb_client, h)["id"])
    s = cook(kb_client, h, p["id"])
    comp = kb_client.post(f"{API}/cook-sessions/{s['id']}/complete", headers=h | key())
    assert comp.status_code == 200, comp.text

    tz = q(kb_db, "SELECT timezone FROM user_settings").scalar()
    local_day = datetime.fromisoformat(comp.json()["cook_session"]["completed_at"]).astimezone(ZoneInfo(tz)).date()
    y, w, _ = local_day.isocalendar()
    wk = kb_client.get(f"{API}/journal", params={"week": f"{y}-W{w:02d}"}, headers=h).json()
    assert wk["kcal_range_status"] == "calibrated"
    assert len(wk["cooked_history"]) == 1
    day = next(d for d in wk["days"] if d["date"] == local_day.isoformat())
    assert day["cooked_trays"] == 1 and day["kcal_per_person"] > 0 and day["protein_g"] > 0


@pytest.mark.parametrize(
    ("dish_stem", "baseline_clean", "kb_slug"),
    [
        ("pho", False, "bo-kho"),
        ("bun-dau", True, "dau-phu-sot-ca-chua"),
        ("tomato-egg", False, "canh-ca-chua-trung"),
        ("caramel-pork", True, "thit-kho-tau"),
    ],
)
def test_s5_vietnamese_cooked_meal_calorie_and_isolation_workflow(
    dish_stem: str,
    baseline_clean: bool,
    kb_slug: str,
    e2e_cfg,
    e2e_detector,
    meal_calorie_probe: dict | None,
) -> None:
    """S5: Cooked-meal photo workflow across nho/vua/lon + raw-fridge detector isolation."""
    img_path = FOOD_ASSETS_DIR / f"{dish_stem}.webp"
    assert img_path.is_file()
    raw_bytes = img_path.read_bytes()

    cleaned = sanitize(raw_bytes)
    with Image.open(io.BytesIO(cleaned.jpeg)) as im:
        assert not im.getexif()
        raw_boxes = e2e_detector.detector.detect(im)

    if e2e_cfg.strict:
        assert len(raw_boxes) <= 1, (
            f"Strict mode allows at most 1 minor garnish false box on {dish_stem}.webp, got {raw_boxes}"
        )
        assert not any(b.confidence >= 0.75 for b in raw_boxes), (
            f"Strict mode forbids high-confidence false raw detection on {dish_stem}.webp: {raw_boxes}"
        )
    elif baseline_clean:
        assert raw_boxes == [], f"Baseline clean dish {dish_stem}.webp produced false raw boxes: {raw_boxes}"

    # Verify KB cooked-dish nutrition & recipe isolation
    b = load_bundle(KB_DIR, PROCESSED_DIR)
    nut = compute(b, PROCESSED_DIR)
    assert kb_slug in nut.per_serving and nut.per_serving[kb_slug]["energy_kcal"] > 0.0
    vision_ids = {
        str(r["id"])
        for r in (
            lambda d: list(d["classes"]) + list(d.get("proposed_classes") or [])
        )(yaml.safe_load((KB_DIR / "vision_classes.yaml").read_text(encoding="utf-8")))
    }
    assert kb_slug not in vision_ids

    if meal_calorie_probe is not None:
        svc = meal_calorie_probe["service"]
        deps = meal_calorie_probe["deps"]
        kb_kcals = [
            svc.estimate_meal_calories(deps, dish_slug=kb_slug, portion=p).estimated_kcal
            for p in ("nho", "vua", "lon")
        ]
        assert kb_kcals[0] < kb_kcals[1] < kb_kcals[2]

        if meal_calorie_probe["has_onnx"] or e2e_cfg.strict:
            t_runs: list[float] = []
            vis_kcals: list[float] = []
            for portion in ("nho", "vua", "lon"):
                t0 = time.perf_counter()
                res = svc.estimate_meal_calories(deps, image_bytes=raw_bytes, dish_slug=kb_slug, portion=portion)
                t_runs.append((time.perf_counter() - t0) * 1000.0)
                assert res.source == "hybrid"
                assert res.visual_kcal is not None and np.isfinite(res.visual_kcal) and res.visual_kcal > 0.0
                vis_kcals.append(res.visual_kcal)
            assert vis_kcals[0] < vis_kcals[1] < vis_kcals[2]
            assert float(np.percentile(np.asarray(t_runs), 95)) <= 200.0
    else:
        assert not e2e_cfg.strict
