"""Unit tests for 8-class mushroom ingestion, zero-leakage splitting, detector nam threshold, and serving artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from tastoria_ml.cv.ingest_mushroom_sub import (
    CLASSES,
    assign_stratified_group_splits,
    deduplicate_records,
    is_clean_wiki_title,
    merge_near_groups,
    verify_zero_leakage,
)


def test_taxonomy_has_8_fungiclef_classes() -> None:
    assert len(CLASSES) == 8
    assert CLASSES[:6] == (
        "nam-rom",
        "nam-huong-tuoi",
        "nam-kim-cham",
        "nam-dui-ga",
        "nam-so",
        "nam-mo",
    )
    assert CLASSES[6:] == ("other_mushroom", "not_mushroom")


def test_wiki_title_filter_rejects_cooked_for_mushrooms_and_mushrooms_for_negatives() -> None:
    assert is_clean_wiki_title("File:Flammulina_velutipes_enoki_fresh.jpg")
    assert is_clean_wiki_title("File:Volvariella_volvacea_market.webp")
    assert not is_clean_wiki_title("File:Shiitake_noodle_soup.jpg")
    assert not is_clean_wiki_title("File:Agaricus_diagram.svg")
    assert not is_clean_wiki_title("File:Dried_shiitake_mushrooms.jpg")
    assert is_clean_wiki_title("File:Fried_rice_dish.jpg", allow_cooked=True)
    assert not is_clean_wiki_title("File:Shiitake_fried_rice.jpg", allow_cooked=True)


def test_deduplicate_records_drops_same_class_dupes_and_both_cross_class_dupes() -> None:
    h1 = 0x0000000000000000
    h2 = 0x0000000000000003  # hamming 2 from h1
    h3 = 0xFFFFFFFFFFFFFFFF
    h4 = 0xFFFFFFFFFFFFFFFE  # hamming 1 from h3

    recs = [
        {"slug": "nam-so", "phash": str(h1), "group_id": "g1", "source": "wikimedia"},
        {"slug": "nam-so", "phash": str(h2), "group_id": "g2", "source": "inaturalist"},
        {"slug": "nam-rom", "phash": str(h3), "group_id": "g3", "source": "wikimedia"},
        {"slug": "nam-mo", "phash": str(h4), "group_id": "g4", "source": "inaturalist"},
    ]
    kept = deduplicate_records(recs, threshold=4)
    assert len(kept) == 1
    assert kept[0]["slug"] == "nam-so" and kept[0]["group_id"] == "g1"


def test_grouped_split_and_zero_leakage_verification() -> None:
    rng = np.random.default_rng(7)
    recs = []
    for c_idx, slug in enumerate(CLASSES):
        for i in range(15):
            h = int(rng.integers(0, 2**63 - 1, dtype=np.uint64))
            gid = f"obs:{c_idx}:{i // 2}"
            recs.append({"slug": slug, "phash": str(h), "group_id": gid, "source": "inaturalist"})

    grouped = merge_near_groups(recs, merge_hamming=4)
    split = assign_stratified_group_splits(grouped, val_frac=0.15, test_frac=0.15, seed=42)
    leak = verify_zero_leakage(split, threshold=4)
    assert leak["group_overlap"] == 0
    assert leak["cross_split_phash_le_4"] == 0
    assert {"train", "val", "test"} <= {r["split"] for r in split}


def test_leakage_verifier_catches_cross_split_near_duplicate() -> None:
    recs = [
        {"slug": "nam-mo", "phash": "0", "split_group": "g1", "split": "train"},
        {"slug": "nam-mo", "phash": "1", "split_group": "g2", "split": "test"},
    ]
    with pytest.raises(RuntimeError, match="Leakage detected"):
        verify_zero_leakage(recs, threshold=4)


def test_detector_nam_threshold_updated_and_mushroom_artifacts_if_present() -> None:
    repo = Path(__file__).resolve().parents[3]
    det_serving = json.loads((repo / "deploy" / "models" / "detector" / "serving.json").read_text(encoding="utf-8"))
    assert det_serving["class_conf"]["nam"] == 0.42

    mdir = repo / "deploy" / "models" / "mushroom_classifier"
    if not (mdir / "serving.json").is_file():
        pytest.skip("mushroom_classifier artifacts not exported yet")
    serving = json.loads((mdir / "serving.json").read_text(encoding="utf-8"))
    metrics = json.loads((mdir / "metrics.json").read_text(encoding="utf-8"))
    assert serving["schema_version"] == "mushroom_classifier.serving.v1"
    assert serving["n_classes"] == 8
    assert serving["output"]["calibration_applied_in_onnx"] is False
    assert serving["safety"]["culinary_prob_min"] == 0.85
    assert serving["safety"]["other_mushroom_prob_max"] == 0.03
    assert isinstance(serving["safety"]["energy_threshold"], float)
    assert metrics["onnx_parity"]["max_abs_logit_diff"] < 1e-4
    assert metrics["cpu_latency_2threads"]["p95_ms"] < 25.0
