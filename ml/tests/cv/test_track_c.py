"""Pure-CPU unit tests for Track C data cleaning pipeline (F6)."""

from __future__ import annotations

import builtins
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from tastoria_ml.cv.track_c_filter import (
    EXPECTED_COUNTABLE_19,
    border_metrics,
    has_black_corners,
    is_tiny_box,
    is_whole_basket_countable,
    run_track_c,
    stage1_filter_record,
)


def _save_solid(path: Path, size: tuple[int, int] = (256, 256), color: tuple[int, int, int] = (120, 140, 90)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", size, color)
    # Add texture in center so border_std isn't always 0 unless intended
    draw = ImageDraw.Draw(im)
    draw.rectangle([40, 40, size[0] - 40, size[1] - 40], fill=(180, 60, 50))
    im.save(path, "JPEG", quality=95)
    return path


def test_track_c_module_has_no_heavy_top_level_imports(monkeypatch) -> None:
    real_import = builtins.__import__

    def _blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
        top = name.split(".")[0]
        if top in {"torch", "torchvision", "transformers", "cv2"}:
            raise ImportError(f"Blocked heavy import: {name}")
        return real_import(name, globals, locals, fromlist, level)

    sys.modules.pop("tastoria_ml.cv.track_c_filter", None)
    monkeypatch.setattr(builtins, "__import__", _blocked_import)
    mod = __import__("tastoria_ml.cv.track_c_filter", fromlist=["stage1_filter_record"])
    assert hasattr(mod, "stage1_filter_record")
    assert hasattr(mod, "run_track_c")


def test_has_black_corners_and_border_metrics(tmp_path: Path) -> None:
    # Normal textured image -> no black corners
    im = Image.new("RGB", (100, 100), (120, 130, 110))
    assert not has_black_corners(im)

    # Top-left 8x8 black triangle -> detected
    arr = np.full((100, 100, 3), 150, dtype=np.uint8)
    arr[:10, :10] = 0
    im_bc = Image.fromarray(arr, mode="RGB")
    assert has_black_corners(im_bc)

    # White background produce image -> white_frac >= 0.85, border_std < 10
    im_white = Image.new("RGB", (200, 200), (255, 255, 255))
    ImageDraw.Draw(im_white).ellipse([50, 50, 150, 150], fill=(200, 30, 30))
    b_std, w_frac = border_metrics(im_white)
    assert b_std < 10.0
    assert w_frac >= 0.85


def test_stage1_explicit_defect_purges_and_bap_cai_retention(tmp_path: Path) -> None:
    img = _save_solid(tmp_path / "img.jpg", (640, 640))

    # 1. rf_tofu_oo dropped 100%
    r_tofu = stage1_filter_record(
        {"source": "rf_tofu_oo", "id": "tofu_oo/1", "path": img, "width": 640, "height": 640, "boxes": [{"cls": "dau_phu", "bbox": [50, 50, 100, 100]}]}
    )
    assert not r_tofu["keep"] and r_tofu["reason"] == "rf_tofu_oo_purged"

    # 2. rf_water_spinach rau_muong dropped
    r_ws = stage1_filter_record(
        {"source": "rf_water_spinach", "id": "ws/1", "path": img, "width": 640, "height": 640, "boxes": [{"cls": "rau_muong", "bbox": [50, 50, 200, 200]}]}
    )
    assert not r_ws["keep"] and r_ws["reason"] == "single_leaf_rau_muong_purged"

    # 3. rf_nhan_dien_rau: rau_muong dropped, bap_cai kept!
    r_ndr = stage1_filter_record(
        {
            "source": "rf_nhan_dien_rau",
            "id": "ndr/1",
            "path": img,
            "width": 640,
            "height": 640,
            "boxes": [
                {"cls": "rau_muong", "bbox": [50, 50, 200, 200]},
                {"cls": "bap_cai", "bbox": [250, 250, 150, 150]},
            ],
        }
    )
    assert r_ndr["keep"]
    assert [b["cls"] for b in r_ndr["boxes"]] == ["bap_cai"]

    # 4. rf_robo1 0-box hard_neg dropped
    r_r1_neg = stage1_filter_record(
        {"source": "rf_robo1", "id": "robo1/neg", "path": img, "width": 640, "height": 640, "boxes": [], "is_neg": True}
    )
    assert not r_r1_neg["keep"] and r_r1_neg["reason"] == "rf_robo1_hard_neg_purged"

    # 5. lvis_v1_neg banned tokens dropped, clean OOD kept
    r_lvis_bad = stage1_filter_record(
        {"source": "lvis_v1_neg", "id": "neg/1", "path": img, "ood_labels": ["pizza"], "boxes": [], "is_neg": True}
    )
    assert not r_lvis_bad["keep"] and r_lvis_bad["reason"] == "lvis_v1_neg_banned_token"

    r_lvis_ok = stage1_filter_record(
        {"source": "lvis_v1_neg", "id": "neg/2", "path": img, "ood_labels": ["apple"], "boxes": [], "is_neg": True}
    )
    assert r_lvis_ok["keep"]


def test_stage1_group_of_countable_whole_basket_tiny_and_exif(tmp_path: Path) -> None:
    img = _save_solid(tmp_path / "good.jpg", (640, 640))

    # 1. OpenImages countable group_of stripped; image dropped if 0 boxes remain (never converted to 0-box neg!)
    r_oi_all_gof = stage1_filter_record(
        {
            "source": "openimages_v7",
            "split": "train",
            "id": "train/abc",
            "path": img,
            "boxes": [{"cls": "ca_chua", "xc": 0.5, "yc": 0.5, "w": 0.4, "h": 0.4, "group_of": True}],
        }
    )
    assert not r_oi_all_gof["keep"] and r_oi_all_gof["reason"] == "group_of_countable_purged"

    # Uncountable group_of (nam) preserved alongside normal countable (ca_chua)
    r_oi_mixed = stage1_filter_record(
        {
            "source": "openimages_v7",
            "split": "train",
            "id": "train/mix",
            "path": img,
            "boxes": [
                {"cls": "ca_chua", "xc": 0.3, "yc": 0.3, "w": 0.2, "h": 0.2, "group_of": True},
                {"cls": "nam", "xc": 0.7, "yc": 0.7, "w": 0.3, "h": 0.3, "group_of": True},
            ],
        }
    )
    assert r_oi_mixed["keep"]
    assert len(r_oi_mixed["boxes"]) == 1 and r_oi_mixed["boxes"][0]["cls"] == "nam"

    # 2. Whole-basket countable boxes: v3det >= 0.92, single-box SINGLE_BOX_BASKET_SOURCES >= 0.94,
    #    while preserving tight single-item produce close-ups in rf_* sources!
    assert is_whole_basket_countable("dau_phu", 0.93, 0.93, "v3det", 2, EXPECTED_COUNTABLE_19)
    assert not is_whole_basket_countable("rau_muong", 0.95, 0.95, "v3det", 1, EXPECTED_COUNTABLE_19)
    assert is_whole_basket_countable("ca_chua", 0.95, 0.95, "mendeley_bd", 1, EXPECTED_COUNTABLE_19)
    assert not is_whole_basket_countable("ca_chua", 0.95, 0.95, "mendeley_bd", 2, EXPECTED_COUNTABLE_19)
    assert not is_whole_basket_countable("ca_rot", 0.96, 1.00, "rf_food_start", 1, EXPECTED_COUNTABLE_19)
    assert not is_whole_basket_countable("bap_cai", 0.99, 0.98, "rf_nhan_dien_rau", 1, EXPECTED_COUNTABLE_19)
    assert not is_whole_basket_countable("bap_cai", 0.97, 0.98, "rf_robo1", 1, EXPECTED_COUNTABLE_19)

    # 3. Tiny box gate on v3det/rf_* vs rf_aicook (24x24 on 640x640 -> min_side=24 >= 16, area=0.0014 >= 0.001)
    assert is_tiny_box(12.0, 40.0, 640, 640)
    assert not is_tiny_box(24.0, 24.0, 640, 640)

    r_aicook = stage1_filter_record(
        {
            "source": "rf_aicook",
            "split": "train",
            "id": "aicook/1",
            "path": img,
            "width": 640,
            "height": 640,
            "boxes": [{"cls": "trung", "bbox": [100, 100, 24, 24]}],
        }
    )
    assert r_aicook["keep"] and len(r_aicook["boxes"]) == 1

    # 4. Non-unit EXIF orientation rejected
    exif_img = tmp_path / "exif6.jpg"
    im = Image.new("RGB", (64, 64), (100, 120, 80))
    ex = Image.Exif()
    ex[0x0112] = 6
    im.save(exif_img, "JPEG", exif=ex.tobytes())
    r_ex = stage1_filter_record({"source": "dfv16", "id": "df/1", "path": exif_img, "boxes": [], "is_neg": True})
    assert not r_ex["keep"] and r_ex["reason"] == "exif_non_unit"


def test_stage2_mocked_sequential_unload_routing_and_manifest(tmp_path: Path) -> None:
    events: list[str] = []

    class _MockScreener:
        backend_name = "mock-siglip2"

        def score_scene_batch(self, images, prompts):
            events.append(f"screener_scene:{len(images)}")
            out = []
            for idx in range(len(images)):
                if idx == 0:
                    # High-confidence cooked meal -> auto-reject
                    out.append({"raw_grocery": 0.05, "cooked_meal": 0.90, "infographic_text": 0.02, "single_lab_leaf": 0.01, "outdoor_vine": 0.02})
                elif idx == 1:
                    # Borderline -> route to VLM
                    out.append({"raw_grocery": 0.48, "cooked_meal": 0.42, "infographic_text": 0.05, "single_lab_leaf": 0.02, "outdoor_vine": 0.03})
                else:
                    # High-confidence raw -> auto-accept
                    out.append({"raw_grocery": 0.92, "cooked_meal": 0.03, "infographic_text": 0.02, "single_lab_leaf": 0.01, "outdoor_vine": 0.02})
            return out

        def score_pair_batch(self, images, pos_prompts, neg_prompts):
            events.append(f"screener_pairs:{len(images)}")
            out = []
            for p in pos_prompts:
                if "graphic poster" in p or "stock photograph" in p:
                    out.append(0.001)
                elif "prepared restaurant dish" in p:
                    out.append(0.10)
                else:
                    out.append(0.92)
            return out

        def unload(self):
            events.append("screener_unload")

    class _MockVLM:
        backend_name = "mock-vintern"

        def ask_yes_no_batch(self, items):
            events.append(f"vlm_ask:{len(items)}")
            # Answer Yes (cooked) for is_cooked, False for is_watermark / other checks
            return ["cooked" in q.lower() or "fried" in q.lower() for _, q in items]

        def unload(self):
            events.append("vlm_unload")

    img0 = _save_solid(tmp_path / "cooked.jpg")
    img1 = _save_solid(tmp_path / "borderline.jpg")
    img2 = _save_solid(tmp_path / "raw_bread.jpg")
    img3 = _save_solid(tmp_path / "tofu_oo.jpg")

    recs = [
        {"source": "v3det", "id": "train/1", "split": "train", "path": img0, "width": 256, "height": 256, "boxes": [{"cls": "thit_bo", "bbox": [30, 30, 120, 120]}]},
        {"source": "rf_viet_hoang", "id": "vh/2", "split": "train", "path": img1, "width": 256, "height": 256, "boxes": [{"cls": "thit_lon", "bbox": [30, 30, 120, 120]}]},
        {"source": "rf_viet_hoang", "id": "vh/3", "split": "train", "path": img2, "width": 256, "height": 256, "boxes": [{"cls": "banh_mi", "bbox": [30, 30, 120, 120]}]},
        {"source": "rf_tofu_oo", "id": "tofu/4", "split": "train", "path": img3, "width": 256, "height": 256, "boxes": [{"cls": "dau_phu", "bbox": [30, 30, 120, 120]}]},
    ]

    out_dir = tmp_path / "yolo_v4_out"
    res = run_track_c(recs, screener=_MockScreener(), vlm=_MockVLM(), dry_run=False, out_dir=out_dir)

    # Sequential GPU invariant: screener MUST unload before VLM runs!
    vlm_idx = next(i for i, e in enumerate(events) if e.startswith("vlm_ask:"))
    assert events.index("screener_unload") < vlm_idx
    assert events[-1] == "vlm_unload"

    decs = res["decisions"]
    assert decs["v3det|train/1"]["keep"] is False
    assert decs["rf_viet_hoang|vh/2"]["keep"] is False
    assert decs["rf_viet_hoang|vh/3"]["keep"] is True
    assert decs["rf_tofu_oo|tofu/4"]["keep"] is False

    # Every Stage 2 decision logs text_graphic and watermark scores
    for k in ("v3det|train/1", "rf_viet_hoang|vh/2", "rf_viet_hoang|vh/3"):
        sc = decs[k]["stage2a_scores"]
        assert "text_graphic" in sc and "watermark" in sc

    manifest = json.loads((out_dir / "cleaning_manifest.json").read_text(encoding="utf-8"))
    assert manifest["quarantined_sources"]["rf_tofu_oo"]["kept"] == 0
    assert manifest["quarantined_sources"]["v3det"]["quarantined"] == 1
    assert manifest["quarantined_sources"]["rf_viet_hoang"]["quarantined"] == 1
    assert "hf_" not in json.dumps(manifest)


def test_stage2_no_crop_bypass_no_packaged_bypass_lvis_and_floor_safety(tmp_path: Path) -> None:
    """Verify cooked crop bypass fix, packaged savory check, lvis_v1 Stage 2, and s1_boxes floor safety."""

    class _BypassScreener:
        backend_name = "mock-siglip2"

        def score_scene_batch(self, images, prompts):
            # idx 0 (v3det high cooked), idx 1 (lvis_v1 cooked tofu), idx 2 (rf_viet_hoang sua_chua cooked wings)
            # idx 3 (rf_nhan_dien_rau mixed rau_muong+bap_cai -> test floor uses s1_boxes not orig_boxes)
            return [
                {"raw_grocery": 0.02, "cooked_meal": 0.97, "infographic_text": 0.0, "single_lab_leaf": 0.0, "outdoor_vine": 0.0},
                {"raw_grocery": 0.05, "cooked_meal": 0.88, "infographic_text": 0.0, "single_lab_leaf": 0.0, "outdoor_vine": 0.0},
                {"raw_grocery": 0.04, "cooked_meal": 0.92, "infographic_text": 0.0, "single_lab_leaf": 0.0, "outdoor_vine": 0.0},
                {"raw_grocery": 0.55, "cooked_meal": 0.10, "infographic_text": 0.0, "single_lab_leaf": 0.0, "outdoor_vine": 0.0},
            ]

        def score_pair_batch(self, images, pos_prompts, neg_prompts):
            out = []
            for p in pos_prompts:
                if "graphic poster" in p or "stock photograph" in p:
                    out.append(0.01)
                elif "prepared restaurant dish" in p:
                    out.append(0.05)
                elif "sealed packaged" in p:
                    # Cooked chicken wings labeled sua_chua fail packaged_ok
                    out.append(0.05)
                elif "clean natural photograph" in p or "clean photograph" in p:
                    out.append(0.95)
                elif "raw uncooked" in p or "fresh" in p or "close-up" in p:
                    # High crop_raw=0.90 to prove mean_crop_raw >= 0.85 can NO LONGER bypass cooked_meal >= 0.80!
                    out.append(0.90)
                else:
                    out.append(0.90)
            return out

        def unload(self):
            pass

    class _MockVLM:
        backend_name = "mock-vintern"

        def ask_yes_no_batch(self, items):
            # Force Stage 2B rejection on idx 3 via is_vine or is_cooked? No, return True ONLY for watermark
            # Wait: test floor rescue when idx 3 is rejected by Stage 2B for vine (not in forbidden floor list)
            return ["growing hanging" in q for _, q in items]

        def unload(self):
            pass

    img = _save_solid(tmp_path / "x.jpg", (640, 640))
    recs = [
        {"source": "v3det", "id": "val/cooked_crop_hi", "split": "val", "path": img, "width": 640, "height": 640, "boxes": [{"cls": "gia_do", "bbox": [50, 50, 120, 120]}]},
        {"source": "lvis_v1", "id": "train/cooked_tofu", "split": "train", "path": img, "width": 640, "height": 640, "boxes": [{"cls": "dau_phu", "bbox": [50, 50, 120, 120]}]},
        {"source": "rf_viet_hoang", "id": "vh/wings_yogurt", "split": "train", "path": img, "width": 640, "height": 640, "boxes": [{"cls": "sua_chua", "bbox": [50, 50, 120, 120]}]},
        {
            "source": "rf_nhan_dien_rau",
            "id": "ndr/mixed",
            "split": "train",
            "path": img,
            "width": 640,
            "height": 640,
            "boxes": [
                {"cls": "rau_muong", "bbox": [10, 10, 80, 80]},
                {"cls": "bap_cai", "bbox": [100, 100, 200, 200]},
            ],
        },
    ]

    res = run_track_c(recs, screener=_BypassScreener(), vlm=_MockVLM(), dry_run=True, out_dir=tmp_path)
    decs = res["decisions"]
    assert decs["v3det|val/cooked_crop_hi"]["keep"] is False
    assert decs["v3det|val/cooked_crop_hi"]["reason"] == "v3det_stage2a_cooked_meal"
    assert decs["lvis_v1|train/cooked_tofu"]["keep"] is False
    assert decs["lvis_v1|train/cooked_tofu"]["reason"] == "lvis_v1_stage2a_cooked_meal"
    assert decs["rf_viet_hoang|vh/wings_yogurt"]["keep"] is False
    assert decs["rf_viet_hoang|vh/wings_yogurt"]["reason"] == "rf_viet_hoang_stage2a_cooked_packaged"
    # Even if rescued_class_floor were ever triggered, Stage-1-purged rau_muong is never in kept_boxes
    assert all(b["cls"] != "rau_muong" for b in decs["rf_nhan_dien_rau|ndr/mixed"]["kept_boxes"])


def test_stage2_watermark_and_v3det_semantic_rejection(tmp_path: Path) -> None:
    """Verify Stage 2B watermark check, v3det muop sponge check, and v3det refrigerator kitchen check."""

    class _MockScreener:
        backend_name = "mock-siglip2"

        def score_scene_batch(self, images, prompts):
            return [
                {"raw_grocery": 0.90, "cooked_meal": 0.03, "infographic_text": 0.01, "single_lab_leaf": 0.01, "outdoor_vine": 0.01}
                for _ in images
            ]

        def score_pair_batch(self, images, pos_prompts, neg_prompts):
            out = []
            for p in pos_prompts:
                if "graphic poster" in p:
                    out.append(0.01)
                elif "stock photograph" in p:
                    out.append(0.10)
                elif "prepared restaurant dish" in p:
                    out.append(0.05)
                else:
                    out.append(0.85)
            return out

        def unload(self):
            pass

    class _MockVLM:
        backend_name = "mock-vintern"

        def ask_yes_no_batch(self, items):
            ans = []
            for im, q in items:
                if "watermark" in q.lower():
                    # Only img_wm (red pixel) has watermark
                    ans.append(im.getpixel((0, 0))[0] > 180)
                elif "bath loofah" in q.lower():
                    ans.append(True)  # reject bath sponge muop
                elif "refrigerator" in q.lower():
                    ans.append(False)  # reject non-kitchen v3det neg
                else:
                    ans.append(False)
            return ans

        def unload(self):
            pass

    img_wm = _save_solid(tmp_path / "wm.jpg", (640, 640), color=(220, 40, 40))
    img_sp = _save_solid(tmp_path / "sp.jpg", (640, 640), color=(40, 140, 40))
    recs = [
        {"source": "rf_robo1", "id": "robo1/wm", "split": "train", "path": img_wm, "width": 640, "height": 640, "boxes": [{"cls": "thit_lon", "bbox": [50, 50, 200, 200]}]},
        {"source": "v3det", "id": "train/sponge", "split": "train", "path": img_sp, "width": 640, "height": 640, "boxes": [{"cls": "muop", "bbox": [50, 50, 200, 200]}]},
        {"source": "v3det", "id": "train/wedding", "split": "train", "path": img_sp, "width": 640, "height": 640, "boxes": [], "is_neg": True},
    ]
    res = run_track_c(recs, screener=_MockScreener(), vlm=_MockVLM(), dry_run=True, out_dir=tmp_path)
    decs = res["decisions"]
    assert decs["rf_robo1|robo1/wm"]["keep"] is False
    assert decs["rf_robo1|robo1/wm"]["reason"] == "rf_robo1_stage2b_watermark"
    assert decs["v3det|train/sponge"]["keep"] is False
    assert decs["v3det|train/sponge"]["reason"] == "v3det_stage2b_bath_sponge"
    assert decs["v3det|train/wedding"]["keep"] is False
    assert decs["v3det|train/wedding"]["reason"] == "v3det_stage2b_non_kitchen"


def test_stage2_closes_cooked_margin_only_packaged_bypass_xuc_xich_and_floor_guard(tmp_path: Path) -> None:
    """Verify M2 Iter 3 fixes: 0.68..0.80 cooked reject, prepared_dish, only_packaged bypass, xuc_xich pizza, floor guard."""
    vlm_questions_seen: list[tuple[str, str]] = []

    class _Iter3Screener:
        backend_name = "mock-siglip2"

        def score_scene_batch(self, images, prompts):
            # 0: non-pkg 0.72 cooked / 0.28 raw -> Stage 2A reject (raw < 0.35)
            # 1: non-pkg 0.62 cooked / 0.25 raw -> Stage 2A reject (cooked - raw >= 0.35)
            # 2: non-pkg 0.25 cooked / 0.75 raw (prepared_dish=0.78 -> Stage 2A prepared_dish)
            # 3: only_packaged banh_mi with cooked=0.88, pkg_ok=0.92 -> MUST NOT bypass is_savory_cooked!
            # 4: only_packaged xuc_xich pizza with cooked=0.45, pkg_ok=0.95 -> MUST route to VLM & reject!
            # 5: only_packaged xuc_xich raw/pkg sausage with cooked=0.05, pkg_ok=0.95 -> MUST stay kept!
            # 6: single thit_bo record with cooked=0.80, raw=0.50 -> MUST NOT be rescued by class floor!
            return [
                {"raw_grocery": 0.28, "cooked_meal": 0.72, "infographic_text": 0.0, "single_lab_leaf": 0.0, "outdoor_vine": 0.0},
                {"raw_grocery": 0.25, "cooked_meal": 0.62, "infographic_text": 0.13, "single_lab_leaf": 0.0, "outdoor_vine": 0.0},
                {"raw_grocery": 0.45, "cooked_meal": 0.25, "infographic_text": 0.0, "single_lab_leaf": 0.0, "outdoor_vine": 0.0},
                {"raw_grocery": 0.12, "cooked_meal": 0.88, "infographic_text": 0.0, "single_lab_leaf": 0.0, "outdoor_vine": 0.0},
                {"raw_grocery": 0.55, "cooked_meal": 0.45, "infographic_text": 0.0, "single_lab_leaf": 0.0, "outdoor_vine": 0.0},
                {"raw_grocery": 0.95, "cooked_meal": 0.05, "infographic_text": 0.0, "single_lab_leaf": 0.0, "outdoor_vine": 0.0},
                {"raw_grocery": 0.50, "cooked_meal": 0.80, "infographic_text": 0.0, "single_lab_leaf": 0.0, "outdoor_vine": 0.0},
            ]

        def score_pair_batch(self, images, pos_prompts, neg_prompts):
            out = []
            for im, p in zip(images, pos_prompts):
                r = im.getpixel((0, 0))[0]
                if "graphic poster" in p or "stock photograph" in p:
                    out.append(0.01)
                elif "prepared restaurant dish" in p:
                    # Only img_sashimi (r == 180) scores high on prepared_dish
                    out.append(0.78 if r == 180 else 0.05)
                elif "sealed packaged" in p or "raw uncooked sausages" in p:
                    out.append(0.95)
                elif "clean natural photograph" in p or "clean photograph" in p:
                    out.append(0.95)
                else:
                    out.append(0.90)
            return out

        def unload(self):
            pass

    class _Iter3VLM:
        backend_name = "mock-vintern"

        def ask_yes_no_batch(self, items):
            ans = []
            for im, q in items:
                r = im.getpixel((0, 0))[0]
                vlm_questions_seen.append((str(r), q))
                if r == 200 and "savory" in q.lower():
                    ans.append(True)  # reject banh_mi savory charcuterie even though pkg_ok=0.92
                elif r == 210 and "pizza" in q.lower():
                    ans.append(True)  # reject pepperoni pizza xuc_xich
                else:
                    ans.append(False)
            return ans

        def unload(self):
            pass

    img_std = _save_solid(tmp_path / "std.jpg", (640, 640), color=(120, 140, 90))
    img_sash = _save_solid(tmp_path / "sash.jpg", (640, 640), color=(180, 140, 90))
    img_bm = _save_solid(tmp_path / "bm.jpg", (640, 640), color=(200, 140, 90))
    img_piz = _save_solid(tmp_path / "piz.jpg", (640, 640), color=(210, 140, 90))
    img_raw_xuc = _save_solid(tmp_path / "raw_xuc.jpg", (640, 640), color=(220, 140, 90))

    recs = [
        {"source": "lvis_v1", "id": "train/ck72", "split": "train", "path": img_std, "width": 640, "height": 640, "boxes": [{"cls": "ca_chua", "bbox": [40, 40, 100, 100]}]},
        {"source": "lvis_v1", "id": "train/margin37", "split": "train", "path": img_std, "width": 640, "height": 640, "boxes": [{"cls": "ca_chua", "bbox": [40, 40, 100, 100]}]},
        {"source": "rf_viet_hoang", "id": "vh/sashimi", "split": "train", "path": img_sash, "width": 640, "height": 640, "boxes": [{"cls": "ca", "bbox": [40, 40, 100, 100]}]},
        {"source": "lvis_v1", "id": "train/bm_pkg92", "split": "train", "path": img_bm, "width": 640, "height": 640, "boxes": [{"cls": "banh_mi", "bbox": [40, 40, 100, 100]}]},
        {"source": "lvis_v1", "id": "val/piz_xuc", "split": "heldout", "path": img_piz, "width": 640, "height": 640, "boxes": [{"cls": "xuc_xich", "bbox": [40, 40, 100, 100]}]},
        {"source": "lvis_v1", "id": "train/raw_xuc", "split": "train", "path": img_raw_xuc, "width": 640, "height": 640, "boxes": [{"cls": "xuc_xich", "bbox": [40, 40, 100, 100]}]},
        {"source": "lvis_v1", "id": "train/floor_bo", "split": "train", "path": img_std, "width": 640, "height": 640, "boxes": [{"cls": "thit_bo", "bbox": [40, 40, 100, 100]}]},
    ]

    res = run_track_c(recs, screener=_Iter3Screener(), vlm=_Iter3VLM(), dry_run=True, out_dir=tmp_path)
    decs = res["decisions"]
    assert decs["lvis_v1|train/ck72"]["keep"] is False
    assert decs["lvis_v1|train/ck72"]["reason"] == "lvis_v1_stage2a_cooked_meal"
    assert decs["lvis_v1|train/margin37"]["keep"] is False
    assert decs["lvis_v1|train/margin37"]["reason"] == "lvis_v1_stage2a_cooked_meal"
    assert decs["rf_viet_hoang|vh/sashimi"]["keep"] is False
    assert decs["rf_viet_hoang|vh/sashimi"]["reason"] == "rf_viet_hoang_stage2a_prepared_dish"
    assert decs["lvis_v1|train/bm_pkg92"]["keep"] is False
    assert decs["lvis_v1|train/bm_pkg92"]["reason"] == "lvis_v1_stage2b_cooked_packaged"
    assert decs["lvis_v1|val/piz_xuc"]["keep"] is False
    assert decs["lvis_v1|val/piz_xuc"]["reason"] == "lvis_v1_stage2b_cooked_packaged"
    assert decs["lvis_v1|train/raw_xuc"]["keep"] is True
    # Floor safeguard MUST NOT rescue cooked=0.80, raw=0.50 even when thit_bo count == 0!
    assert decs["lvis_v1|train/floor_bo"]["keep"] is False
    assert res["manifest"]["rescued_class_floor"] == []


def test_stage1_lvis_cocat_exclusion_split_vlm_prompts_and_vine_floor_refusal(tmp_path: Path) -> None:
    """Verify M2 Iter 4 fixes: LVIS co-cat JSON exclusion, split binary VLM prompts, wm>=0.08, and vine/crop_mismatch floor block."""
    ann_dir = tmp_path / "lvis_ann"
    ann_dir.mkdir(parents=True, exist_ok=True)
    (ann_dir / "lvis_v1_val.json").write_text(
        json.dumps(
            {
                "categories": [
                    {"id": 1, "name": "tomato"},
                    {"id": 2, "name": "pizza"},
                    {"id": 3, "name": "sausage"},
                ],
                "annotations": [
                    {"image_id": 1001, "category_id": 1},
                    {"image_id": 1001, "category_id": 2},
                    {"image_id": 1002, "category_id": 3},
                ],
            }
        ),
        encoding="utf-8",
    )

    img = _save_solid(tmp_path / "cocat.jpg", (640, 640))
    r_pizza = stage1_filter_record(
        {
            "source": "lvis_v1",
            "id": "val/1001",
            "original_id": "val/1001",
            "split": "heldout",
            "path": img,
            "width": 640,
            "height": 640,
            "boxes": [{"cls": "ca_chua", "bbox": [30, 30, 100, 100]}],
        },
        lvis_ann_dir=ann_dir,
    )
    assert not r_pizza["keep"] and r_pizza["reason"] == "lvis_v1_banned_cocat"

    r_clean_xuc = stage1_filter_record(
        {
            "source": "lvis_v1",
            "id": "val/1002",
            "original_id": "val/1002",
            "split": "heldout",
            "path": img,
            "width": 640,
            "height": 640,
            "boxes": [{"cls": "xuc_xich", "bbox": [30, 30, 100, 100]}],
        },
        lvis_ann_dir=ann_dir,
    )
    assert r_clean_xuc["keep"]

    # Stage 2 split binary VLM prompts + wm>=0.08 on rf_viet_hoang + vine/crop_mismatch floor refusal
    seen_prompts: dict[int, list[str]] = {}

    class _Iter4Screener:
        backend_name = "mock-siglip2"

        def score_scene_batch(self, images, prompts):
            # 0: lvis_v1 sup_lo aquarium (cooked=0.45, sc_clean=0.66 < 0.75) -> routes is_underwater_or_aquarium
            # 1: lvis_v1 only_packaged banh_mi hotdog (cooked=0.75, pkg_ok=0.95) -> routes split is_pizza_or_hotdog + is_savory_cooked
            # 2: rf_viet_hoang thit_lon (raw=0.95, cooked=0.02, wm=0.084 >= 0.08) -> routes is_watermark
            # 3: v3det muop (outdoor_vine=0.75, raw=0.20) -> Stage 2A outdoor_vine reject, MUST NOT be floor-rescued!
            # 4: v3det gia_do (min_crop_sem=0.15 < 0.22) -> Stage 2A crop_mismatch reject, MUST NOT be floor-rescued!
            return [
                {"raw_grocery": 0.40, "cooked_meal": 0.45, "infographic_text": 0.0, "single_lab_leaf": 0.0, "outdoor_vine": 0.0},
                {"raw_grocery": 0.20, "cooked_meal": 0.75, "infographic_text": 0.0, "single_lab_leaf": 0.0, "outdoor_vine": 0.0},
                {"raw_grocery": 0.95, "cooked_meal": 0.02, "infographic_text": 0.0, "single_lab_leaf": 0.0, "outdoor_vine": 0.0},
                {"raw_grocery": 0.20, "cooked_meal": 0.02, "infographic_text": 0.0, "single_lab_leaf": 0.0, "outdoor_vine": 0.75},
                {"raw_grocery": 0.60, "cooked_meal": 0.02, "infographic_text": 0.0, "single_lab_leaf": 0.0, "outdoor_vine": 0.0},
            ]

        def score_pair_batch(self, images, pos_prompts, neg_prompts):
            out = []
            for im, p in zip(images, pos_prompts):
                r = im.getpixel((0, 0))[0]
                if "graphic poster" in p:
                    out.append(0.001)
                elif "stock photograph" in p:
                    out.append(0.084 if r == 140 else 0.01)
                elif "prepared restaurant dish" in p:
                    out.append(0.05)
                elif "sealed packaged" in p:
                    out.append(0.95)
                elif "clean natural photograph" in p or "clean photograph" in p:
                    out.append(0.66 if r == 110 else 0.92)
                elif "raw white mung bean sprouts" in p:
                    out.append(0.15)  # triggers stage2a_crop_mismatch on gia_do
                else:
                    out.append(0.90)
            return out

        def unload(self):
            pass

    class _Iter4VLM:
        backend_name = "mock-vintern"

        def ask_yes_no_batch(self, items):
            ans = []
            for im, q in items:
                r = im.getpixel((0, 0))[0]
                seen_prompts.setdefault(r, []).append(q)
                # Verify no 8-clause compound prompt is ever emitted
                assert "sushi, or sashimi" not in q
                if r == 110 and "aquarium" in q.lower():
                    ans.append(True)
                elif r == 130 and "hotdog in a bun" in q.lower():
                    ans.append(True)
                elif r == 140 and "watermark" in q.lower():
                    ans.append(True)
                else:
                    ans.append(False)
            return ans

        def unload(self):
            pass

    img_aqua = _save_solid(tmp_path / "aqua.jpg", (640, 640), color=(110, 140, 90))
    img_hd = _save_solid(tmp_path / "hd.jpg", (640, 640), color=(130, 140, 90))
    img_wm = _save_solid(tmp_path / "wm84.jpg", (640, 640), color=(140, 140, 90))
    img_vine = _save_solid(tmp_path / "vine.jpg", (640, 640), color=(150, 140, 90))
    img_crop = _save_solid(tmp_path / "crop.jpg", (640, 640), color=(160, 140, 90))

    recs = [
        {"source": "lvis_v1", "id": "val/aqua", "split": "heldout", "path": img_aqua, "width": 640, "height": 640, "boxes": [{"cls": "sup_lo", "bbox": [30, 30, 100, 100]}]},
        {"source": "lvis_v1", "id": "val/hotdog_pkg", "split": "heldout", "path": img_hd, "width": 640, "height": 640, "boxes": [{"cls": "banh_mi", "bbox": [30, 30, 100, 100]}]},
        {"source": "rf_viet_hoang", "id": "vh/wm84", "split": "train", "path": img_wm, "width": 640, "height": 640, "boxes": [{"cls": "thit_lon", "bbox": [30, 30, 100, 100]}]},
        {"source": "v3det", "id": "train/vine_muop", "split": "train", "path": img_vine, "width": 640, "height": 640, "boxes": [{"cls": "muop", "bbox": [30, 30, 100, 100]}]},
        {"source": "v3det", "id": "train/crop_giado", "split": "train", "path": img_crop, "width": 640, "height": 640, "boxes": [{"cls": "gia_do", "bbox": [30, 30, 100, 100]}]},
    ]
    res = run_track_c(recs, screener=_Iter4Screener(), vlm=_Iter4VLM(), dry_run=True, out_dir=tmp_path)
    decs = res["decisions"]
    assert decs["lvis_v1|val/aqua"]["keep"] is False
    assert decs["lvis_v1|val/aqua"]["reason"] == "lvis_v1_stage2b_off_topic"
    assert decs["lvis_v1|val/hotdog_pkg"]["keep"] is False
    assert decs["lvis_v1|val/hotdog_pkg"]["reason"] == "lvis_v1_stage2b_cooked_packaged"
    assert decs["rf_viet_hoang|vh/wm84"]["keep"] is False
    assert decs["rf_viet_hoang|vh/wm84"]["reason"] == "rf_viet_hoang_stage2b_watermark"
    # Both vine and crop_mismatch MUST NOT be rescued even when muop and gia_do have 0 kept boxes!
    assert decs["v3det|train/vine_muop"]["keep"] is False
    assert decs["v3det|train/vine_muop"]["reason"] == "v3det_stage2a_outdoor_vine"
    assert decs["v3det|train/crop_giado"]["keep"] is False
    assert decs["v3det|train/crop_giado"]["reason"] == "v3det_stage2a_crop_mismatch"
    assert res["manifest"]["rescued_class_floor"] == []
    # Verify split pizza/hotdog prompt was sent on non-packaged sup_lo as well as packaged banh_mi
    assert any("pizza or a hotdog" in q.lower() for q in seen_prompts.get(110, []))
