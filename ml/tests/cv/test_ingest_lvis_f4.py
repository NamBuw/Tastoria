from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from tastoria_ml.cv import lvis


def test_lvis_neg_clean_excludes_pizza_dining_and_ranks_commercial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "lvis_v1"
    ann = root / "ann"
    ann.mkdir(parents=True)
    monkeypatch.setattr(lvis, "ROOT", root)
    monkeypatch.setattr(lvis, "ANN", ann)
    monkeypatch.setattr(lvis, "IMAGES", root / "images")
    monkeypatch.setattr(lvis, "NEG_CLEAN_IMAGES", root / "images_neg_clean")
    monkeypatch.setattr(lvis, "NEG_CLEAN_ANN", root / "annotations_neg.json")

    fake_train = {
        "licenses": [
            {"id": 1, "name": "Attribution License"},
            {"id": 2, "name": "Attribution-NonCommercial License"},
        ],
        "categories": [
            {"id": 1, "name": "apple"},
            {"id": 2, "name": "pizza"},
            {"id": 3, "name": "tomato"},
            {"id": 4, "name": "onion"},
            {"id": 5, "name": "plate"},
        ],
        "images": [
            {"id": 101, "coco_url": "https://ex/101.jpg", "license": 1, "width": 640, "height": 480, "neg_category_ids": [3], "not_exhaustive_category_ids": []},
            {"id": 102, "coco_url": "https://ex/102.jpg", "license": 2, "width": 640, "height": 480, "neg_category_ids": [3], "not_exhaustive_category_ids": []},
            {"id": 103, "coco_url": "https://ex/103.jpg", "license": 1, "width": 640, "height": 480, "neg_category_ids": [], "not_exhaustive_category_ids": []},
            {"id": 104, "coco_url": "https://ex/104.jpg", "license": 1, "width": 640, "height": 480, "neg_category_ids": [], "not_exhaustive_category_ids": []},
            {"id": 105, "coco_url": "https://ex/105.jpg", "license": 1, "width": 640, "height": 480, "neg_category_ids": [], "not_exhaustive_category_ids": []},
            {"id": 106, "coco_url": "https://ex/106.jpg", "license": 1, "width": 640, "height": 480, "neg_category_ids": [], "not_exhaustive_category_ids": [3]},
        ],
        "annotations": [
            {"id": 1, "image_id": 101, "category_id": 1, "bbox": [10, 10, 50, 50]},  # clean comm apple
            {"id": 2, "image_id": 102, "category_id": 1, "bbox": [10, 10, 50, 50]},  # clean NC apple
            {"id": 3, "image_id": 103, "category_id": 1, "bbox": [10, 10, 50, 50]},
            {"id": 4, "image_id": 103, "category_id": 2, "bbox": [20, 20, 80, 80]},  # apple + pizza -> drop
            {"id": 5, "image_id": 104, "category_id": 1, "bbox": [10, 10, 50, 50]},
            {"id": 6, "image_id": 104, "category_id": 5, "bbox": [20, 20, 80, 80]},  # apple + plate -> drop
            {"id": 7, "image_id": 105, "category_id": 4, "bbox": [10, 10, 50, 50]},  # onion not in clean list -> drop
            {"id": 8, "image_id": 106, "category_id": 1, "bbox": [10, 10, 50, 50]},  # not_exhaustive tomato -> drop
        ],
    }
    train_json = ann / "lvis_v1_train.json"
    train_json.write_text(json.dumps(fake_train), encoding="utf-8")
    monkeypatch.setattr(lvis, "_download_resized", lambda url, dst: (dst.parent.mkdir(parents=True, exist_ok=True), Image.new("RGB", (640, 480)).save(dst), (640, 480))[2])

    summary = lvis.fetch_neg_clean(target_total=1, workers=1, train_json=train_json)
    assert summary["schema_version"] == "m1_v1"
    assert summary["images"] == 1
    assert summary["commercial_ok_images"] == 1

    recs = lvis.neg_records()
    assert len(recs) == 1
    assert recs[0]["coco_id"] == 101
    assert recs[0]["is_commercial_ok"] is True
    assert recs[0]["is_neg"] is True
    assert recs[0]["ood_labels"] == ["apple"]


def test_lvis_neg_clean_excludes_prawn_saucer_and_prunes_stale_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert "prawn" in lvis.COOKED_OR_DINING_EXCL
    assert "saucer" in lvis.COOKED_OR_DINING_EXCL
    assert "toaster_oven" in lvis.COOKED_OR_DINING_EXCL
    assert "food_processor" in lvis.COOKED_OR_DINING_EXCL

    root = tmp_path / "lvis_v1"
    ann = root / "ann"
    neg_dir = root / "images_neg_clean"
    ann.mkdir(parents=True)
    neg_dir.mkdir(parents=True)
    stale_jpg = neg_dir / "000000428113.jpg"
    Image.new("RGB", (64, 64)).save(stale_jpg)

    monkeypatch.setattr(lvis, "ROOT", root)
    monkeypatch.setattr(lvis, "ANN", ann)
    monkeypatch.setattr(lvis, "IMAGES", root / "images")
    monkeypatch.setattr(lvis, "NEG_CLEAN_IMAGES", neg_dir)
    monkeypatch.setattr(lvis, "NEG_CLEAN_ANN", root / "annotations_neg.json")

    fake_train = {
        "licenses": [{"id": 1, "name": "Attribution License"}],
        "categories": [
            {"id": 1, "name": "orange_(fruit)"},
            {"id": 2, "name": "prawn"},
            {"id": 3, "name": "saucer"},
        ],
        "images": [
            {"id": 428113, "coco_url": "https://ex/428113.jpg", "license": 1, "width": 640, "height": 480, "neg_category_ids": [], "not_exhaustive_category_ids": []},
            {"id": 500001, "coco_url": "https://ex/500001.jpg", "license": 1, "width": 640, "height": 480, "neg_category_ids": [], "not_exhaustive_category_ids": []},
            {"id": 500002, "coco_url": "https://ex/500002.jpg", "license": 1, "width": 640, "height": 480, "neg_category_ids": [], "not_exhaustive_category_ids": []},
        ],
        "annotations": [
            {"id": 1, "image_id": 428113, "category_id": 1, "bbox": [10, 10, 40, 40]},
            {"id": 2, "image_id": 428113, "category_id": 2, "bbox": [50, 50, 60, 60]},  # prawn -> exclude
            {"id": 3, "image_id": 500001, "category_id": 1, "bbox": [10, 10, 40, 40]},
            {"id": 4, "image_id": 500001, "category_id": 3, "bbox": [20, 20, 80, 80]},  # saucer -> exclude
            {"id": 5, "image_id": 500002, "category_id": 1, "bbox": [10, 10, 40, 40]},  # clean
        ],
    }
    train_json = ann / "lvis_v1_train.json"
    train_json.write_text(json.dumps(fake_train), encoding="utf-8")
    monkeypatch.setattr(lvis, "_download_resized", lambda url, dst: (dst.parent.mkdir(parents=True, exist_ok=True), Image.new("RGB", (640, 480)).save(dst), (640, 480))[2])

    summary = lvis.fetch_neg_clean(target_total=5, workers=1, force=True, train_json=train_json)
    assert summary["images"] == 1
    assert [r["coco_id"] for r in lvis.neg_records()] == [500002]
    assert not stale_jpg.exists()
    assert [p.name for p in neg_dir.iterdir()] == ["000000500002.jpg"]


def test_lvis_prawn_audit_and_allowlist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "lvis_v1"
    ann = root / "ann"
    ann.mkdir(parents=True)
    monkeypatch.setattr(lvis, "ROOT", root)
    monkeypatch.setattr(lvis, "ANN", ann)
    monkeypatch.setattr(lvis, "PRAWN_AUDIT_DIR", root / "prawn_audit")
    monkeypatch.setattr(lvis, "PRAWN_AUDIT_JSON", root / "prawn_audit.json")

    fake_train = {
        "licenses": [
            {"id": 1, "name": "Attribution License"},
            {"id": 2, "name": "Attribution-NonCommercial License"},
        ],
        "categories": [
            {"id": 10, "name": "prawn"},
            {"id": 11, "name": "plate"},
            {"id": 12, "name": "carrot"},
        ],
        "images": [
            {"id": 201, "coco_url": "https://ex/201.jpg", "license": 1, "width": 640, "height": 480, "not_exhaustive_category_ids": []},
            {"id": 202, "coco_url": "https://ex/202.jpg", "license": 1, "width": 640, "height": 480, "not_exhaustive_category_ids": []},
            {"id": 203, "coco_url": "https://ex/203.jpg", "license": 1, "width": 640, "height": 480, "not_exhaustive_category_ids": [10]},
            {"id": 204, "coco_url": "https://ex/204.jpg", "license": 2, "width": 640, "height": 480, "not_exhaustive_category_ids": []},
        ],
        "annotations": [
            {"id": 1, "image_id": 201, "category_id": 10, "bbox": [20, 30, 100, 60]},  # clean comm
            {"id": 2, "image_id": 201, "category_id": 12, "bbox": [10, 10, 40, 40]},
            {"id": 3, "image_id": 202, "category_id": 10, "bbox": [20, 30, 100, 60]},
            {"id": 4, "image_id": 202, "category_id": 11, "bbox": [0, 0, 400, 400]},  # plate -> drop
            {"id": 5, "image_id": 203, "category_id": 10, "bbox": [20, 30, 100, 60]},  # not_exhaustive -> drop
            {"id": 6, "image_id": 204, "category_id": 10, "bbox": [20, 30, 100, 60]},  # clean NC
        ],
    }
    train_json = ann / "lvis_v1_train.json"
    train_json.write_text(json.dumps(fake_train), encoding="utf-8")
    monkeypatch.setattr(lvis, "_download_resized", lambda url, dst: (dst.parent.mkdir(parents=True, exist_ok=True), Image.new("RGB", (640, 480)).save(dst), (640, 480))[2])

    summary = lvis.audit_prawn(workers=1, include_nc=True, train_json=train_json, val_json=ann / "missing.json")
    assert summary["images"] == 2
    assert summary["stats_by_split"]["train"] == {
        "total": 4,
        "exhaustive": 3,
        "non_tableware": 2,
        "commercial_ok_non_tableware": 1,
    }

    sheet = lvis.prawn_contact_sheet(tmp_path / "prawn_sheet.jpg", cols=2, rows=2, tile_size=256)
    assert sheet.exists() and sheet.stat().st_size > 1000

    monkeypatch.setattr(lvis, "RAW_PRAWN_ALLOWLIST", ())
    assert lvis.prawn_records() == []
    monkeypatch.setattr(lvis, "RAW_PRAWN_ALLOWLIST", (201, 204))
    assert [r["coco_id"] for r in lvis.prawn_records(commercial_only=True)] == [201]
    assert [r["coco_id"] for r in lvis.prawn_records(commercial_only=False)] == [201, 204]
