"""Unit tests for M2 blind held-out VN & multi-domain evaluation harness (G-16)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from tastoria_ml.calorie.eval_blind_vn import (
    compute_excluded_mmfood_urls,
    format_ablation_markdown,
    is_atwater_consistent,
    parse_portion_grams,
    sample_unseen_mmfood_candidates,
    summarize_calorie_predictions,
)


def test_parse_portion_grams_and_atwater_filter() -> None:
    assert parse_portion_grams('["rice 150g", "chicken 120g"]') == 270.0
    assert parse_portion_grams('["soup 0.4 kg"]') == 400.0
    assert parse_portion_grams('["candy 10g"]') is None  # below 30g floor
    assert parse_portion_grams("not-json") is None

    assert is_atwater_consistent(300.0, 20.0, 30.0, 11.0) is True  # 4*20+4*30+9*11 = 299
    assert is_atwater_consistent(900.0, 10.0, 10.0, 5.0) is False  # 125 vs 900


def test_mmfood_unseen_sampling_zero_overlap(tmp_path: Path) -> None:
    csv_path = tmp_path / "mm.csv"
    rows = []
    for i in range(40):
        rows.append(
            {
                "image_url": f"https://example.com/img_{i}.jpg",
                "dish_name": "pho" if i == 0 else f"dish_{i}",
                "food_prob": "0.96",
                "food_type": "Homemade food",
                "nutritional_profile": json.dumps(
                    {"calories_kcal": 300.0 + i, "protein_g": 20.0, "carbohydrate_g": 32.0, "fat_g": 10.0}
                ),
                "portion_size": '["meal 300g"]',
            }
        )
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    excl = compute_excluded_mmfood_urls(csv_path, max_v3=10, max_v4=15, seed=20261017)
    assert "https://example.com/img_0.jpg" in excl
    assert len(excl) >= 15

    unseen = sample_unseen_mmfood_candidates(csv_path, excluded_urls=excl, target_n=20, seed=99)
    unseen_urls = {c["image_url"] for c in unseen}
    assert unseen_urls.isdisjoint(excl)
    assert len(unseen) == 40 - len(excl)


def test_ablation_summary_and_markdown_formatting() -> None:
    s = summarize_calorie_predictions([200.0, 400.0], [210.0, 380.0], [180.0, 340.0], [240.0, 440.0])
    assert s["n"] == 2
    assert s["mae"] == 15.0
    assert s["within_20pct"] == 100.0
    assert s["ci_coverage_pct"] == 100.0

    md = format_ablation_markdown(
        {
            "sota_jobs": {"task_4790": {"status": "REJECTED"}},
            "splits": {
                "mmfood_100k_unseen": {
                    "n_samples": 2,
                    "disambiguation_rate_pct": 50.0,
                    "e2e_cpu_p95_ms": 140.0,
                    "arms": {"m2_fusion": s},
                }
            },
        }
    )
    assert "mmfood_100k_unseen" in md
    assert "REJECTED" in md


def test_vn_home_dishes_taxonomy_and_gating_markdown() -> None:
    from tastoria_ml.calorie.dish_taxonomy import BY_ID

    for did in ("rau_cai_xao", "trung_xao_ca_chua", "ca_hap_xi_dau"):
        assert BY_ID[did].category == "vn"

    md = format_ablation_markdown(
        {
            "sota_jobs": {},
            "highres_mobile_3024x4032_ms": {
                "jpeg_bytes": 500000,
                "sanitize_p50_ms": 15.0,
                "dish_cls_p50_ms": 115.0,
                "e2e_p50_ms": 170.0,
                "e2e_p95_ms": 190.0,
            },
            "classifier_gating": {
                "verdict": "KEEP_V3_REJECT_V4",
                "hoagmin_v3_top1": 94.4,
                "hoagmin_v4_top1": 94.4,
                "vn103_v3_top1": 92.0,
                "vn103_v4_top1": 90.8,
                "vn103_v3_macro_f1": 0.7064,
                "vn103_v4_macro_f1": 0.6731,
                "v3_cpu": {"p50_ms": 117.0, "p95_ms": 149.0},
                "v4_cpu": {"p50_ms": 111.0, "p95_ms": 130.0},
            },
            "splits": {},
        }
    )
    assert "KEEP_V3_REJECT_V4" in md
    assert "3024x4032" in md


def test_mmfood_exclusion_matches_v3_and_ingest_substrings(tmp_path: Path) -> None:
    csv_path = tmp_path / "mm_sub.csv"
    rows = [
        # Matched ONLY by ingest_dishes_v3 substring rules (not MMFOOD_EXACT)
        {
            "image_url": "https://example.com/sub_fish.jpg",
            "dish_name": "Steamed Fish with Rice and Vegetables",
            "food_prob": "0.95",
            "food_type": "Homemade food",
            "nutritional_profile": json.dumps({"calories_kcal": 400.0, "protein_g": 30.0, "carbohydrate_g": 45.0, "fat_g": 10.0}),
            "portion_size": '["meal 350g"]',
        },
        {
            "image_url": "https://example.com/sub_egg.jpg",
            "dish_name": "Tomato Scrambled Egg Bowl",
            "food_prob": "0.95",
            "food_type": "Restaurant food",
            "nutritional_profile": json.dumps({"calories_kcal": 280.0, "protein_g": 14.0, "carbohydrate_g": 12.0, "fat_g": 18.0}),
            "portion_size": '["meal 240g"]',
        },
        # Excluded ONLY by train_v3_portion (no Atwater filter -> large Atwater mismatch!)
        {
            "image_url": "https://example.com/v3_only_atw.jpg",
            "dish_name": "Unmatched Special Dish",
            "food_prob": "0.95",
            "food_type": "Homemade food",
            "nutritional_profile": json.dumps({"calories_kcal": 900.0, "protein_g": 5.0, "carbohydrate_g": 10.0, "fat_g": 5.0}),
            "portion_size": '["meal 300g"]',
        },
        # Clean unseen candidate
        {
            "image_url": "https://example.com/clean_unseen.jpg",
            "dish_name": "Grilled Zucchini Platter",
            "food_prob": "0.95",
            "food_type": "Homemade food",
            "nutritional_profile": json.dumps({"calories_kcal": 220.0, "protein_g": 8.0, "carbohydrate_g": 20.0, "fat_g": 12.0}),
            "portion_size": '["meal 260g"]',
        },
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    excl_sub = compute_excluded_mmfood_urls(csv_path, max_v3=0, max_v4=0, seed=20261017)
    assert "https://example.com/sub_fish.jpg" in excl_sub
    assert "https://example.com/sub_egg.jpg" in excl_sub
    assert "https://example.com/clean_unseen.jpg" not in excl_sub

    # Also verify train_v3_portion keeps & excludes Atwater-mismatched rows (not filtered by v4)
    excl_v3 = compute_excluded_mmfood_urls(csv_path, max_v3=10, max_v4=10, seed=20261017)
    assert "https://example.com/v3_only_atw.jpg" in excl_v3

    unseen = sample_unseen_mmfood_candidates(csv_path, excluded_urls=excl_sub, target_n=10, seed=99)
    assert [u["image_url"] for u in unseen] == ["https://example.com/clean_unseen.jpg"]

    # Proxy eval label check on hoagmin_vn_valid & vn103_validation
    md = format_ablation_markdown(
        {
            "sota_jobs": {},
            "splits": {
                "hoagmin_vn_valid": {
                    "n_samples": 10,
                    "disambiguation_rate_pct": 5.0,
                    "e2e_cpu_p95_ms": 150.0,
                    "arms": {"m2_fusion": {"n": 10, "mae": 10.0, "rmse": 15.0, "mape_pct": 2.5, "within_20pct": 98.0, "ci_coverage_pct": 99.0}},
                },
                "vn103_validation": {
                    "n_samples": 10,
                    "disambiguation_rate_pct": 5.0,
                    "e2e_cpu_p95_ms": 150.0,
                    "arms": {"m2_fusion": {"n": 10, "mae": 10.0, "rmse": 15.0, "mape_pct": 2.5, "within_20pct": 98.0, "ci_coverage_pct": 99.0}},
                },
            },
        }
    )
    assert md.count("Classifier-to-KB Proxy Eval") >= 2
    assert "kb.estimate_recognized" in md


def test_real_mmfood_csv_zero_leakage_if_cached() -> None:
    import random as _random

    mm_csvs = list((Path.home() / ".cache/huggingface/hub/datasets--Humanbased-AI--MM-Food-100K/snapshots").glob("*/MM-Food-100K.csv"))
    if not mm_csvs:
        return
    mm_csv = mm_csvs[0]
    excl = compute_excluded_mmfood_urls(mm_csv)
    unseen = sample_unseen_mmfood_candidates(mm_csv, excluded_urls=excl, target_n=160, seed=992026)
    unseen_urls = {c["image_url"] for c in unseen}

    # Independently reconstruct train_v3_portion exact 4500 URLs and check 0 overlap
    v3_urls: list[str] = []
    with mm_csv.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                if float(row.get("food_prob") or 0) < 0.90:
                    continue
                if row.get("food_type") not in ("Homemade food", "Restaurant food"):
                    continue
                npf = json.loads(row["nutritional_profile"])
                kcal = float(npf["calories_kcal"])
                _ = float(npf["protein_g"]), float(npf["carbohydrate_g"]), float(npf["fat_g"])
                grams = parse_portion_grams(row["portion_size"])
                if grams is None or not (30.0 <= kcal <= 2500.0):
                    continue
                v3_urls.append(str(row["image_url"]).strip())
            except Exception:
                continue
    rng = _random.Random(20261017)
    rng.shuffle(v3_urls)
    assert unseen_urls.isdisjoint(set(v3_urls[:4500]))
