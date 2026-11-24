"""Pure-CPU unit tests for yolo_v4 builder (F7)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import yaml
from PIL import Image

from tastoria_ml.cv.build_yolo_v2 import all_class_rows
from tastoria_ml.cv.build_yolo_v4 import _box_dict_to_yolo, build_from_records
from tastoria_ml.cv.phash import hamming, phash
from tastoria_ml.cv.track_c_filter import EXPECTED_COUNTABLE_19


def _pattern_jpg(path: Path, seed: int, size: tuple[int, int] = (128, 128)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    grid = rng.integers(0, 256, size=(8, 8, 3), dtype=np.uint8)
    w, h = size
    arr = np.repeat(np.repeat(grid, max(1, h // 8), axis=0), max(1, w // 8), axis=1)[:h, :w]
    Image.fromarray(arr, mode="RGB").save(path, "JPEG", quality=92)
    return path


def test_build_yolo_v4_37_classes_purges_group_of_and_phash_dedupe(tmp_path: Path) -> None:
    rows = all_class_rows()
    order = [str(r["id"]) for r in rows]
    assert len(order) == 37

    raw_dir = tmp_path / "raw"
    out_dir = tmp_path / "yolo_v4"

    # Build minimal records covering all 37 classes in train & val, plus test/heldout & defects
    cands: list[dict] = []
    seed = 100

    # Test split: 2 distinct mendeley_bd images + 1 openimages_v7 with countable group_of stripped
    seed += 1
    test_img = _pattern_jpg(raw_dir / "test_1.jpg", seed)
    cands.append(
        {
            "split": "test",
            "source": "mendeley_bd",
            "id": "VID_1/test_1.jpg",
            "original_id": "VID_1/test_1.jpg",
            "path": test_img,
            "width": 128,
            "height": 128,
            "license": "CC BY 4.0",
            "license_flag": "ok",
            "boxes": [{"cls": "ca_chua", "xc": 0.5, "yc": 0.5, "w": 0.3, "h": 0.3, "group_of": False}],
        }
    )

    # Train exact duplicate of test_img (must be dropped by pHash <= 4!)
    dup_train_img = raw_dir / "dup_train.jpg"
    Image.open(test_img).save(dup_train_img, "JPEG", quality=92)
    cands.append(
        {
            "split": "train",
            "source": "dfv16",
            "id": "dfv16/dup",
            "original_id": "dfv16/dup",
            "path": dup_train_img,
            "width": 128,
            "height": 128,
            "license": "CC BY 4.0",
            "license_flag": "ok",
            "boxes": [{"cls": "khoai_tay", "xc": 0.5, "yc": 0.5, "w": 0.3, "h": 0.3}],
        }
    )

    # Heldout: omorros_kitchen (ok) + rpc_checkout (non_commercial)
    seed += 1
    cands.append(
        {
            "split": "heldout",
            "source": "omorros_kitchen",
            "id": "omo_1",
            "original_id": "omo_1",
            "path": _pattern_jpg(raw_dir / "omo_1.jpg", seed),
            "width": 128,
            "height": 128,
            "license": "CC BY 4.0",
            "license_flag": "ok",
            "boxes": [{"cls": "chanh", "bbox": [20, 20, 40, 40]}],
        }
    )
    seed += 1
    cands.append(
        {
            "split": "heldout",
            "source": "rpc_checkout",
            "id": "rpc_1",
            "original_id": "rpc_1",
            "path": _pattern_jpg(raw_dir / "rpc_1.jpg", seed),
            "width": 128,
            "height": 128,
            "license": "CC BY-NC-SA 4.0",
            "license_flag": "non_commercial",
            "boxes": [{"cls": "mi_tom", "bbox": [20, 20, 40, 40]}],
        }
    )

    # Val: 1 valid image
    seed += 1
    cands.append(
        {
            "split": "val",
            "source": "dfv16",
            "id": "df_val_1",
            "original_id": "df_val_1",
            "path": _pattern_jpg(raw_dir / "df_val_1.jpg", seed),
            "width": 128,
            "height": 128,
            "license": "CC BY 4.0",
            "license_flag": "ok",
            "boxes": [{"cls": "ca_chua", "bbox": [20, 20, 40, 40]}],
        }
    )

    # Train: cover all 37 classes cleanly (each in a distinct synthetic texture)
    for idx_c, cid in enumerate(order):
        seed += 17
        src = "v3det" if cid in {"rau_muong", "muop", "gia_do"} else "openimages_v7"
        cands.append(
            {
                "split": "train",
                "source": src,
                "id": f"train_{idx_c}",
                "original_id": f"train_{idx_c}",
                "path": _pattern_jpg(raw_dir / f"c_{idx_c}.jpg", seed),
                "width": 128,
                "height": 128,
                "license": "CC BY 2.0",
                "license_flag": "non_commercial" if src == "v3det" else "ok",
                "boxes": [{"cls": cid, "xc": 0.5, "yc": 0.5, "w": 0.35, "h": 0.35, "group_of": False}],
            }
        )

    # Add defective records that MUST be purged:
    # 1) rf_tofu_oo
    seed += 11
    cands.append(
        {
            "split": "train",
            "source": "rf_tofu_oo",
            "id": "tofu_oo_1",
            "original_id": "tofu_oo_1",
            "path": _pattern_jpg(raw_dir / "tofu_oo.jpg", seed),
            "width": 128,
            "height": 128,
            "boxes": [{"cls": "dau_phu", "bbox": [20, 20, 40, 40]}],
        }
    )
    # 2) rf_robo1 is_hard_neg=1
    seed += 11
    cands.append(
        {
            "split": "train",
            "source": "rf_robo1",
            "id": "robo1_neg",
            "original_id": "robo1_neg",
            "path": _pattern_jpg(raw_dir / "robo1_neg.jpg", seed),
            "width": 128,
            "height": 128,
            "boxes": [],
            "is_neg": True,
        }
    )
    # 3) lvis_v1_neg with pizza
    seed += 11
    cands.append(
        {
            "split": "train",
            "source": "lvis_v1_neg",
            "id": "neg/pizza_99",
            "original_id": "neg/pizza_99",
            "path": _pattern_jpg(raw_dir / "lvis_pizza.jpg", seed),
            "width": 128,
            "height": 128,
            "ood_labels": ["pizza"],
            "boxes": [],
            "is_neg": True,
        }
    )
    # 4) lvis_v1_neg clean apple
    seed += 11
    cands.append(
        {
            "split": "train",
            "source": "lvis_v1_neg",
            "id": "neg/apple_100",
            "original_id": "neg/apple_100",
            "path": _pattern_jpg(raw_dir / "lvis_apple.jpg", seed),
            "width": 128,
            "height": 128,
            "ood_labels": ["apple"],
            "boxes": [],
            "is_neg": True,
        }
    )
    # 5) openimages_v7 with ONLY countable group_of (must be dropped, not converted to 0-box neg!)
    seed += 11
    cands.append(
        {
            "split": "train",
            "source": "openimages_v7",
            "id": "train/gof_only",
            "original_id": "train/gof_only",
            "path": _pattern_jpg(raw_dir / "oi_gof.jpg", seed),
            "width": 128,
            "height": 128,
            "boxes": [{"cls": "trung", "xc": 0.5, "yc": 0.5, "w": 0.4, "h": 0.4, "group_of": True}],
        }
    )
    # 6) v3det whole-basket countable box >= 0.92
    seed += 11
    cands.append(
        {
            "split": "train",
            "source": "v3det",
            "id": "train/basket_1",
            "original_id": "train/basket_1",
            "path": _pattern_jpg(raw_dir / "v3_basket.jpg", seed),
            "width": 128,
            "height": 128,
            "boxes": [{"cls": "dau_phu", "bbox": [2, 2, 124, 124]}],
        }
    )
    # 7) Track C Stage 2 rejected rf_viet_hoang BBQ
    seed += 11
    cands.append(
        {
            "split": "train",
            "source": "rf_viet_hoang",
            "id": "vh/bbq_1",
            "original_id": "vh/bbq_1",
            "path": _pattern_jpg(raw_dir / "vh_bbq.jpg", seed),
            "width": 128,
            "height": 128,
            "boxes": [{"cls": "thit_lon", "bbox": [20, 20, 60, 60]}],
        }
    )

    decisions = {
        "rf_viet_hoang|vh/bbq_1": {"keep": False, "reason": "rf_viet_hoang_stage2b_cooked"},
    }
    sheet_path = tmp_path / "sheet.jpg"
    Image.new("RGB", (64, 64), (10, 20, 30)).save(sheet_path, "JPEG")

    stats = build_from_records(
        cands,
        out_dir=out_dir,
        decisions=decisions,
        contact_sheets=[str(sheet_path)],
        check_pixels=True,
    )

    # Check YAMLs
    for yname in ("dataset.yaml", "data.yaml", "dataset_heldout.yaml"):
        yp = out_dir / yname
        assert yp.is_file()
        ydata = yaml.safe_load(yp.read_text(encoding="utf-8"))
        assert [ydata["names"][i] for i in range(37)] == order

    assert stats["n_classes"] == 37
    assert stats["classes_without_data"] == []

    # Check manifest_v4.csv invariants
    with (out_dir / "manifest_v4.csv").open("r", encoding="utf-8") as f:
        m_rows = list(csv.DictReader(f))

    sources = {r["source"] for r in m_rows}
    assert "rf_tofu_oo" not in sources
    assert "rf_robo1" not in sources
    assert "rf_viet_hoang" not in sources
    assert not any("dup" in r["original_id"] for r in m_rows)
    assert not any("gof_only" in r["original_id"] for r in m_rows)
    assert not any("basket_1" in r["original_id"] for r in m_rows)
    assert not any("pizza" in r["original_id"] for r in m_rows)
    assert any(r["source"] == "lvis_v1_neg" and int(r["is_hard_neg"]) == 1 for r in m_rows)

    train_bg = 0
    for r in m_rows:
        assert int(r["countable_group_of_boxes"]) == 0
        assert int(r["is_hard_neg"]) == int(int(r["n_boxes"]) == 0)
        if r["split"] == "train" and int(r["is_hard_neg"]) == 1:
            train_bg += 1
        gpc = json.loads(r["group_of_per_class"])
        assert not (set(gpc) & EXPECTED_COUNTABLE_19)

    assert train_bg == stats["total_train_bg_images"]

    # Check cross-split pHash leakage == 0
    eval_h = np.array([int(r["phash"], 16) for r in m_rows if r["split"] in {"test", "heldout"}], dtype=np.uint64)
    dev_h = np.array([int(r["phash"], 16) for r in m_rows if r["split"] in {"train", "val"}], dtype=np.uint64)
    for eh in eval_h:
        assert int(hamming(dev_h, eh).min()) > 4

    # Check cleaning_manifest.json schema
    cleaning = json.loads((out_dir / "cleaning_manifest.json").read_text(encoding="utf-8"))
    assert cleaning["quarantined_sources"]["rf_tofu_oo"]["kept"] == 0
    assert cleaning["quarantined_sources"]["v3det"]["quarantined"] >= 1
    assert cleaning["quarantined_sources"]["rf_viet_hoang"]["quarantined"] >= 1
    assert cleaning["quarantined_sources"]["rf_robo1"]["quarantined"] >= 1
    assert any("whole_basket" in k or "group_of" in k for k in cleaning["purged_defects"])
    assert cleaning["contact_sheets"] == [str(sheet_path)]
    assert "rescued_class_floor" in cleaning
    assert "hf_" not in json.dumps(cleaning)


def test_box_dict_to_yolo_respects_normalized_flag() -> None:
    full = {"ca_chua": 7}
    b = _box_dict_to_yolo(
        {"cls": "ca_chua", "bbox": [0.1, 0.2, 0.4, 0.5], "normalized": True},
        full,
        img_w=640,
        img_h=640,
    )
    assert b is not None
    assert abs(b.xc - 0.30) < 1e-6
    assert abs(b.yc - 0.45) < 1e-6
    assert abs(b.w - 0.40) < 1e-6
    assert abs(b.h - 0.50) < 1e-6
