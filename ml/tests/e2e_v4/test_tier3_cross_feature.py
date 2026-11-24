"""Tier 3: Pairwise combinatorial & cross-feature E2E tests (preprocess x aspect x threshold x counting)."""

from __future__ import annotations

import json

import numpy as np
import onnxruntime as ort
import pytest
from PIL import Image

from tastoria.modules.scan.detector import Detector
from tastoria.modules.scan.runner import resolve_class_conf
from tastoria_ml.cv.counting import count_metrics, countable_ids, masked_metrics, pred_counts

pytestmark = pytest.mark.tier3


@pytest.mark.parametrize(
    ("arm", "aspect", "thresh_mode"),
    [
        ("none", "landscape", "global_conf"),
        ("none", "portrait", "per_class_conf"),
        ("none", "square", "agnostic_iou"),
        ("gw", "landscape", "per_class_conf"),
        ("gw", "portrait", "agnostic_iou"),
        ("gw", "square", "global_conf"),
        ("clahe", "landscape", "agnostic_iou"),
        ("clahe", "portrait", "global_conf"),
        ("gw_clahe", "square", "per_class_conf"),
    ],
)
def test_pairwise_preprocess_aspect_threshold_combinations(
    arm: str,
    aspect: str,
    thresh_mode: str,
    e2e_config,
    onnx_session: ort.InferenceSession,
    onnx_names: list[str],
) -> None:
    sizes = {"landscape": (640, 360), "portrait": (360, 640), "square": (480, 480)}
    w, h = sizes[aspect]
    rng = np.random.default_rng(42)
    arr = rng.integers(30, 220, size=(h, w, 3), dtype=np.uint8)
    img = Image.fromarray(arr, mode="RGB")

    serving = json.loads(e2e_config.serving_path.read_text(encoding="utf-8"))
    conf = float(serving["conf"])
    iou = float(serving["iou"])
    class_conf = {0: 1.0, 1: max(0.05, conf * 0.8)} if thresh_mode == "per_class_conf" else None
    agnostic = 0.65 if thresh_mode == "agnostic_iou" else None

    det = Detector(
        onnx_session,
        conf=conf,
        iou=iou,
        preprocess_version=arm,
        agnostic_iou=agnostic,
        class_conf=class_conf,
    )
    boxes_a = det.detect(img)
    boxes_b = det.detect(img)
    assert boxes_a == boxes_b, "Detector.detect must be deterministic across identical runs"
    for b in boxes_a:
        assert 0 <= b.class_index < len(onnx_names)
        assert 0.0 <= b.x1 < b.x2 <= 1.0 and 0.0 <= b.y1 < b.y2 <= 1.0
        if thresh_mode == "per_class_conf" and b.class_index == 0:
            raise AssertionError("Disabled class 0 (class_conf=1.0) should never be emitted")


def test_detector_countable_contract_with_counting_metrics(vision_rows: list[dict]) -> None:
    names = [str(r["id"]) for r in vision_rows]
    c_ids = countable_ids(include_proposed=True)
    assert len(c_ids) == 19
    cols = [i for i, n in enumerate(names) if n in c_ids]
    non_c_cols = [i for i, n in enumerate(names) if n not in c_ids]
    assert len(cols) == 19 and len(non_c_cols) == 18

    idx_trung = names.index("trung")
    idx_thit_lon = names.index("thit_lon")
    idx_ca_chua = names.index("ca_chua")

    # 2 images, 37 classes: countable class trung has exact/near counts; non-countable class thit_lon
    # has huge mismatch that MUST NOT affect countable metrics; image 1 ca_chua is group_of-excluded.
    gt = np.zeros((2, 37), dtype=int)
    gt[0, idx_trung] = 4
    gt[1, idx_trung] = 2
    gt[0, idx_thit_lon] = 10  # uncountable package
    gt[1, idx_ca_chua] = 5  # excluded via group_of

    pred = {
        "img": np.array([0, 0, 0, 0, 1, 0, 1], dtype=int),
        "cls": np.array([idx_trung, idx_trung, idx_trung, idx_trung, idx_trung, idx_thit_lon, idx_ca_chua], dtype=int),
        "scores": np.array([0.9, 0.8, 0.7, 0.6, 0.8, 0.9, 0.9], dtype=float),
    }
    chat = pred_counts(pred, n_images=2, n_classes=37, conf=0.5)
    excluded = np.zeros((2, 37), dtype=bool)
    excluded[1, idx_ca_chua] = True

    m = masked_metrics(gt, chat, excluded, cols)
    assert m["n_pairs"] == 2
    assert m["mae"] == pytest.approx(0.5)  # img0: |4-4|=0, img1: |1-2|=1 -> mean 0.5; thit_lon & ca_chua excluded
    raw_trung = count_metrics(gt[:, idx_trung], chat[:, idx_trung])
    assert raw_trung["exact"] == pytest.approx(0.5)


def test_37_class_map_resolve_class_conf_and_serving_f05(
    e2e_config, onnx_session: ort.InferenceSession, onnx_names: list[str], vision_rows: list[dict]
) -> None:
    full_ids = [str(r["id"]) for r in vision_rows]
    full_map = {i: 100 + i for i in range(len(full_ids))}
    code_by_vid = {100 + i: cid for i, cid in enumerate(full_ids)}

    resolved = resolve_class_conf(
        {"thit_bo": 1.0, "ca_chua": 0.45, "2": 0.60, "nonexistent_cls": 0.5},
        full_map,
        code_by_vid,
    )
    assert resolved == {1: 1.0, 7: 0.45, 2: 0.60}

    # Also test against active model's serving_f05.json if present
    active_map = {i: 200 + i for i in range(len(onnx_names))}
    active_vid = {200 + i: cid for i, cid in enumerate(onnx_names)}
    if e2e_config.serving_f05_path is not None:
        f05 = json.loads(e2e_config.serving_f05_path.read_text(encoding="utf-8"))
        cc = resolve_class_conf(f05.get("class_conf"), active_map, active_vid)
        assert cc is not None
        disabled_indices = {i for i, thr in cc.items() if thr >= 1.0}
        det = Detector(
            onnx_session,
            conf=float(f05["conf"]),
            iou=float(f05["iou"]),
            agnostic_iou=f05.get("agnostic_iou"),
            class_conf=cc,
        )
        boxes = det.detect(Image.new("RGB", (640, 480), (150, 120, 90)))
        assert all(b.class_index not in disabled_indices for b in boxes)
