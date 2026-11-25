"""Unit tests for plate_detector D-FINE decoding and conditional multi-dish wiring."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from tastoria.modules.meal_calorie.dish_classifier import DishCandidate, DishClassification
from tastoria.modules.meal_calorie.estimator import ArtifactIntegrityError, VisualPrediction
from tastoria.modules.meal_calorie.kb_lookup import KBDishCatalog
from tastoria.modules.meal_calorie.plate_detector import PlateDetector, decode_dfine, load_plate_detector
from tastoria.modules.meal_calorie.service import MealCalorieDeps, estimate_meal_calories

from unit.test_meal_calorie import REPO_ROOT, _ld, _node, _value_info, _vi, _write_synthetic_bundle
from unit.test_meal_calorie_dish_classifier import _tensor_proto_float, _write_synthetic_classifier_bundle


def _textured_webp_bytes() -> bytes:
    w, h = 320, 240
    xs = np.linspace(40, 220, w, dtype=np.uint8)[None, :]
    ys = np.linspace(30, 200, h, dtype=np.uint8)[:, None]
    rgb = np.stack(
        [np.broadcast_to(xs, (h, w)), np.broadcast_to(ys, (h, w)), np.broadcast_to(((xs + ys) // 2).astype(np.uint8), (h, w))],
        axis=-1,
    )
    buf = io.BytesIO()
    Image.fromarray(rgb, mode="RGB").save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def test_decode_dfine_sigmoid_nms_and_clamp() -> None:
    logits = np.full((1, 5, 3), -10.0, dtype=np.float32)
    boxes = np.zeros((1, 5, 4), dtype=np.float32)
    # Query 0: dish_plate confident (p ~ 0.95), overlapping Query 1 (p ~ 0.88) -> Query 1 suppressed by NMS
    logits[0, 0, 0] = 3.0
    boxes[0, 0] = [0.25, 0.50, 0.40, 0.40]
    logits[0, 1, 0] = 2.0
    boxes[0, 1] = [0.26, 0.50, 0.40, 0.40]
    # Query 2: bowl near edge (needs clamp to [0, 1])
    logits[0, 2, 1] = 2.5
    boxes[0, 2] = [0.90, 0.90, 0.40, 0.40]
    # Query 3: below threshold
    logits[0, 3, 2] = -2.0
    boxes[0, 3] = [0.5, 0.5, 0.2, 0.2]

    plates = decode_dfine(logits, boxes, conf_threshold=0.35, nms_iou=0.60, max_crops=8)
    assert len(plates) == 2
    assert plates[0].label == "dish_plate"
    assert plates[1].label == "bowl"
    assert plates[1].x2 == 1.0 and plates[1].y2 == 1.0
    assert all(0.0 <= p.x1 < p.x2 <= 1.0 and 0.0 <= p.y1 < p.y2 <= 1.0 for p in plates)


def test_load_plate_detector_checks_sha256_and_synthetic_inference(tmp_path: Path) -> None:
    # Build minimal valid ONNX with two constant outputs via Identity/Add on [1,3,640,640]
    c_logits = np.full((1, 2, 3), -8.0, dtype=np.float32)
    c_logits[0, 0, 1] = 2.2
    c_boxes = np.array([[[0.5, 0.5, 0.4, 0.4], [0.2, 0.2, 0.1, 0.1]]], dtype=np.float32)
    nodes = [
        _node("GlobalAveragePool", ["pixel_values"], ["g"], []),
        _node("Flatten", ["g"], ["f"], []),
        _node("MatMul", ["f", "wz"], ["z"], []),
        _node("Unsqueeze", ["z", "axes1"], ["u"], []),
        _node("Add", ["u", "b_logits"], ["logits"], []),
        _node("Add", ["u", "b_boxes"], ["pred_boxes"], []),
    ]
    inits = [
        _tensor_proto_float("wz", [3, 1], np.zeros((3, 1), dtype=np.float32)),
        _vi(1, 1) + _vi(2, 7) + _ld(8, b"axes1") + _ld(9, np.array([1], dtype="<i8").tobytes()),
        _tensor_proto_float("b_logits", [1, 2, 3], c_logits),
        _tensor_proto_float("b_boxes", [1, 2, 4], c_boxes),
    ]
    graph = (
        b"".join(_ld(1, n) for n in nodes)
        + _ld(2, b"plate_det_test")
        + b"".join(_ld(5, i) for i in inits)
        + _ld(11, _value_info("pixel_values", [1, 3, 640, 640]))
        + _ld(12, _value_info("logits", [1, 2, 3]))
        + _ld(12, _value_info("pred_boxes", [1, 2, 4]))
    )
    onnx_path = tmp_path / "model.onnx"
    onnx_path.write_bytes(_vi(1, 8) + _ld(7, graph) + _ld(8, _ld(1, b"") + _vi(2, 13)))
    sha = hashlib.sha256(onnx_path.read_bytes()).hexdigest()
    serving = {
        "schema_version": "plate_detector.serving.v1",
        "artifact_file": "model.onnx",
        "artifact_sha256": sha,
        "labels": {"0": "dish_plate", "1": "bowl", "2": "drink_cup"},
        "conf_threshold": 0.35,
        "nms_iou": 0.60,
        "max_crops": 8,
    }
    (tmp_path / "serving.json").write_text(json.dumps(serving), encoding="utf-8")

    det = load_plate_detector(tmp_path, verify_sha256=True)
    plates, lat = det.detect(Image.new("RGB", (320, 240), (90, 90, 90)))
    assert lat >= 0.0 and len(plates) == 1 and plates[0].label == "bowl"

    (tmp_path / "serving.json").write_text(json.dumps({**serving, "artifact_sha256": "deadbeef"}), encoding="utf-8")
    with pytest.raises(ArtifactIntegrityError):
        load_plate_detector(tmp_path, verify_sha256=True)


def test_estimate_meal_calories_runs_plate_detector_only_when_multidish(tmp_path: Path) -> None:
    cal_dir = _write_synthetic_bundle(tmp_path / "meal_calorie")
    cls_dir = _write_synthetic_classifier_bundle(tmp_path / "dish_classifier")
    kb = KBDishCatalog.from_dirs(REPO_ROOT / "data" / "kb", REPO_ROOT / "data" / "processed" / "kb")
    img_bytes = _textured_webp_bytes()

    class _FixedEst:
        domain_shift_note = None

        def __init__(self, multi_score: float) -> None:
            self.multi_score = multi_score

        def predict(self, _img):  # noqa: ANN001
            return VisualPrediction(
                kcal=320.0, mass_g=280.0, fat_g=10.0, carb_g=40.0, protein_g=16.0,
                latency_ms=3.0, multi_dish_score=self.multi_score,
            )

    class _FixedCls:
        def predict(self, _img, top_k=3):  # noqa: ANN001
            return DishClassification(
                top_k=[DishCandidate("pho", "Phở", "Pho", 0.90, None, "man")],
                top1_id="pho", top1_name_vi="Phở", top1_confidence=0.90,
                confident=True, conf_threshold=0.42, latency_ms=2.0,
            )

    calls = {"n": 0}

    class _MockPlateDetector:
        def detect(self, _img):  # noqa: ANN001
            calls["n"] += 1
            from tastoria.modules.meal_calorie.plate_detector import DetectedPlate
            return [
                DetectedPlate("bowl", 0.88, 0.05, 0.10, 0.45, 0.55),
                DetectedPlate("dish_plate", 0.81, 0.50, 0.20, 0.92, 0.80),
            ], 64.0

    deps_single = MealCalorieDeps(
        model_dir=cal_dir, kb_dir=REPO_ROOT / "data" / "kb", kb_processed_dir=REPO_ROOT / "data" / "processed" / "kb",
        dish_classifier_model_dir=cls_dir, estimator=_FixedEst(0.15), dish_classifier=_FixedCls(),
        plate_detector=_MockPlateDetector(), kb_catalog=kb,
    )  # type: ignore[arg-type]
    out_single = estimate_meal_calories(deps_single, image_bytes=img_bytes)
    assert calls["n"] == 0 and out_single.detected_plates == []

    deps_multi = MealCalorieDeps(
        model_dir=cal_dir, kb_dir=REPO_ROOT / "data" / "kb", kb_processed_dir=REPO_ROOT / "data" / "processed" / "kb",
        dish_classifier_model_dir=cls_dir, estimator=_FixedEst(0.75), dish_classifier=_FixedCls(),
        plate_detector=_MockPlateDetector(), kb_catalog=kb,
    )  # type: ignore[arg-type]
    out_multi = estimate_meal_calories(deps_multi, image_bytes=img_bytes)
    assert calls["n"] == 1 and len(out_multi.detected_plates) == 2
    assert "2 đĩa/bát" in (out_multi.domain_shift_note or "")


def test_real_plate_detector_on_vietnamese_table_if_present() -> None:
    p_dir = REPO_ROOT / "deploy" / "models" / "plate_detector"
    img_path = REPO_ROOT / "app" / "assets" / "food" / "vietnamese-table.webp"
    if not ((p_dir / "model.onnx").is_file() and img_path.is_file()):
        pytest.skip("plate_detector artifact not staged")
    det = load_plate_detector(p_dir, verify_sha256=True)
    plates, lat = det.detect(Image.open(img_path))
    assert isinstance(det, PlateDetector) and lat > 0.0
    assert len(plates) >= 3
