"""Detector post-processing (letterbox, YOLO26 one-to-many head, NMS) against fixtures and ultralytics' own output.

Fixtures `fixtures/yolo26n_head_{bd,oi}.npz`: the raw head output of the deployed ONNX (yolo26n_640_none) on one
validation image of each public source, after *our* letterbox (anchors with a best score < 0.05 dropped), and the
boxes ultralytics 8.4.173 `predict(conf=0.25, iou=0.7)` returns for the same image (its own letterbox, cv2 resize).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from tastoria.modules.scan.detector import Letterbox, decode, letterbox, nms

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def _iou(a, b) -> float:  # noqa: ANN001
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)


@pytest.mark.parametrize("name", ["bd", "oi"])
def test_decode_matches_ultralytics(name: str) -> None:
    f = np.load(FIX / f"yolo26n_head_{name}.npz")
    s, px, py, w, h = f["letterbox"]
    boxes = decode(f["output"][None], Letterbox(float(s), int(px), int(py), int(w), int(h)), conf=0.25, iou=0.7)
    ref = f["ultralytics"]  # x1 y1 x2 y2 (normalised) conf cls
    assert len(boxes) == len(ref) >= 4
    unmatched = list(range(len(ref)))
    for b in boxes:
        best = max(unmatched, key=lambda j: _iou((b.x1, b.y1, b.x2, b.y2), ref[j][:4]))
        assert int(ref[best][5]) == b.class_index
        assert _iou((b.x1, b.y1, b.x2, b.y2), ref[best][:4]) > 0.9  # letterbox differs (PIL vs cv2 resize)
        assert abs(float(ref[best][4]) - b.confidence) < 0.05
        unmatched.remove(best)
    confs = [b.confidence for b in boxes]
    assert confs == sorted(confs, reverse=True)
    assert all(0 <= b.x1 < b.x2 <= 1 and 0 <= b.y1 < b.y2 <= 1 for b in boxes)


def _head(rows: list[tuple[float, float, float, float, int, float]], n_classes: int = 3) -> np.ndarray:
    out = np.zeros((4 + n_classes, len(rows)), np.float32)
    for i, (cx, cy, w, h, c, sc) in enumerate(rows):
        out[:4, i] = (cx, cy, w, h)
        out[4 + c, i] = sc
    return out[None]


IDENT = Letterbox(1.0, 0, 0, 640, 640)


def test_duplicates_of_one_object_collapse_but_other_classes_survive() -> None:
    out = _head([
        (100, 100, 50, 50, 0, 0.9),
        (102, 101, 50, 52, 0, 0.8),  # same object, same class -> suppressed
        (101, 100, 50, 50, 1, 0.7),  # same place, other class -> kept (class-aware)
        (400, 400, 40, 40, 0, 0.6),
        (300, 300, 40, 40, 2, 0.2),  # below conf
    ])  # fmt: skip
    boxes = decode(out, IDENT, conf=0.25, iou=0.7)
    assert [(b.class_index, round(b.confidence, 2)) for b in boxes] == [(0, 0.9), (1, 0.7), (0, 0.6)]
    assert boxes[0].x1 == pytest.approx(75 / 640) and boxes[0].y2 == pytest.approx(125 / 640)


def test_iou_at_threshold_is_kept() -> None:
    # two 100x100 boxes shifted so IoU = 0.5 exactly-ish: kept at iou=0.7, suppressed at iou=0.3
    a, b = (np.array([0, 0, 100, 100.0]), np.array([33.3333, 0, 133.3333, 100.0]))
    boxes = np.stack([a, b])
    assert list(nms(boxes, np.array([0.9, 0.8]), 0.7)) == [0, 1]
    assert list(nms(boxes, np.array([0.9, 0.8]), 0.3)) == [0]


def test_letterbox_round_trip_maps_back_to_original_pixels() -> None:
    img = Image.new("RGB", (1280, 720), (10, 200, 30))
    x, lb = letterbox(img, 640)
    assert x.shape == (1, 3, 640, 640) and x.dtype == np.float32
    assert (lb.scale, lb.pad_x, lb.pad_y) == (0.5, 0, 140)
    assert x[0, :, 0, 0] == pytest.approx([114 / 255] * 3)  # padding
    # an object at (640, 360) in the original, 200x100 px -> centre (320, 320) in the input, 100x50
    boxes = decode(_head([(320, 320, 100, 50, 2, 0.95)]), lb, conf=0.25, iou=0.7)
    assert len(boxes) == 1
    b = boxes[0]
    assert (b.x1 * 1280, b.y1 * 720, b.x2 * 1280, b.y2 * 720) == pytest.approx((540, 310, 740, 410), abs=1e-3)


def test_boxes_in_the_padding_are_dropped_and_partial_ones_clipped() -> None:
    lb = Letterbox(0.5, 0, 140, 1280, 720)
    out = _head([(320, 60, 100, 40, 0, 0.9), (20, 300, 80, 40, 1, 0.8)])  # first lies in the top padding
    boxes = decode(out, lb, conf=0.25, iou=0.7)
    assert len(boxes) == 1 and boxes[0].class_index == 1 and boxes[0].x1 == 0.0


def test_nothing_above_threshold() -> None:
    assert decode(_head([(100, 100, 10, 10, 0, 0.1)]), IDENT, conf=0.25, iou=0.7) == []


def test_agnostic_iou_suppresses_conflicting_cross_class_box_on_same_object() -> None:
    out = _head([
        (100, 100, 50, 50, 0, 0.85),
        (102, 100, 50, 50, 1, 0.62),  # IoU > 0.65 with box 0, different class
    ])
    kept_default = decode(out, IDENT, conf=0.25, iou=0.45)
    assert [(b.class_index, round(b.confidence, 2)) for b in kept_default] == [(0, 0.85), (1, 0.62)]
    kept_agnostic = decode(out, IDENT, conf=0.25, iou=0.45, agnostic_iou=0.65)
    assert [(b.class_index, round(b.confidence, 2)) for b in kept_agnostic] == [(0, 0.85)]


def test_agnostic_iou_keeps_adjacent_or_nested_different_class_boxes() -> None:
    # Nested small item (20x20 -> area 400) inside large item (100x100 -> area 10000): IoU = 0.04 <= 0.65
    # Adjacent box shifted right: IoU < 0.65
    out = _head([
        (200, 200, 100, 100, 0, 0.90),
        (200, 200, 20, 20, 1, 0.70),  # nested different class
        (230, 200, 100, 100, 2, 0.60),  # shifted IoU = 70*100 / (20000 - 7000) = 0.538 <= 0.65
    ])
    boxes = decode(out, IDENT, conf=0.25, iou=0.45, agnostic_iou=0.65)
    assert [b.class_index for b in boxes] == [0, 1, 2]


def test_class_conf_applies_per_class_threshold_and_disables_dead_class_without_stealing_anchor() -> None:
    # Anchor 0: disabled class 0 (0.85) must not mask enabled class 1 (0.45 >= 0.35)
    # Anchor 1: class 2 (0.50) below per-class threshold 0.60 must be dropped even though fallback conf=0.35
    out = np.zeros((4 + 3, 2), np.float32)
    out[:4, 0] = (100, 100, 40, 40)
    out[4 + 0, 0] = 0.85
    out[4 + 1, 0] = 0.45
    out[:4, 1] = (300, 300, 40, 40)
    out[4 + 2, 1] = 0.50
    boxes = decode(
        out[None],
        IDENT,
        conf=0.35,
        iou=0.45,
        class_conf={0: 1.0, 1: 0.35, 2: 0.60},
    )
    assert [(b.class_index, round(b.confidence, 2)) for b in boxes] == [(1, 0.45)]


def test_resolve_class_conf_maps_codes_and_ignores_unknown() -> None:
    from tastoria.modules.scan.runner import resolve_class_conf

    class_map = {0: 10, 1: 20, 2: 30}
    code_by_vid = {10: "ca_chua", 20: "ca_rot", 30: "thit_bo"}
    raw = {"ca_chua": 0.47, "ca_rot": 0.33, "2": 1.0, "unknown_cls": 0.5}
    resolved = resolve_class_conf(raw, class_map, code_by_vid)
    assert resolved == {0: 0.47, 1: 0.33, 2: 1.0}
    assert resolve_class_conf(None, class_map, code_by_vid) is None
    assert resolve_class_conf({}, class_map, code_by_vid) is None


def test_hysteresis_counting_keeps_secondary_boxes_only_when_presence_confirmed() -> None:
    # Class 0 has 3 eggs: [0.80, 0.70, 0.52]; presence thr=0.55, count thr=0.25 -> keeps all 3!
    # Class 1 has 2 items: [0.40, 0.35]; presence thr=0.50, count thr=0.20 -> dropped completely (0 absent-class FPs!).
    # Class 2 is disabled (class_conf=1.0, score=0.95) at anchor overlapping class 0 -> must not steal anchor!
    out = np.zeros((4 + 3, 5), np.float32)
    out[:4, 0], out[4 + 0, 0], out[4 + 2, 0] = (100, 100, 50, 50), 0.80, 0.95
    out[:4, 1], out[4 + 0, 1] = (200, 100, 50, 50), 0.70
    out[:4, 2], out[4 + 0, 2] = (300, 100, 50, 50), 0.52
    out[:4, 3], out[4 + 1, 3] = (100, 300, 60, 60), 0.40
    out[:4, 4], out[4 + 1, 4] = (250, 300, 60, 60), 0.35
    boxes = decode(
        out[None],
        IDENT,
        conf=0.35,
        iou=0.45,
        class_conf={0: 0.55, 1: 0.50, 2: 1.0},
        class_count_conf={0: 0.25, 1: 0.20, 2: 0.20},
    )
    assert [(b.class_index, round(b.confidence, 2)) for b in boxes] == [(0, 0.80), (0, 0.70), (0, 0.52)]


def test_hysteresis_unconfirmed_class_cannot_agnostic_suppress_confirmed_class() -> None:
    # Unconfirmed class 0 (0.48 < pres 0.50) overlaps confirmed class 1 (0.45 >= pres 0.40) -> class 1 must survive!
    out = np.zeros((4 + 2, 2), np.float32)
    out[:4, 0], out[4 + 0, 0] = (100, 100, 50, 50), 0.48
    out[:4, 1], out[4 + 1, 1] = (101, 100, 50, 50), 0.45
    boxes = decode(
        out[None],
        IDENT,
        conf=0.40,
        iou=0.45,
        agnostic_iou=0.65,
        class_conf={0: 0.50, 1: 0.40},
        class_count_conf={0: 0.25, 1: 0.25},
    )
    assert [(b.class_index, round(b.confidence, 2)) for b in boxes] == [(1, 0.45)]


def test_guarded_zoom_rescue_behavior_on_synthetic_sessions() -> None:
    from tastoria.modules.scan.detector import Detector

    class _FakeInput:
        name = "images"
        shape = [1, 3, 640, 640]

    class _SeqSession:
        def __init__(self, outputs: list[np.ndarray]) -> None:
            self._outputs = outputs
            self.calls = 0

        def get_inputs(self) -> list[_FakeInput]:
            return [_FakeInput()]

        def run(self, *_args: object, **_kwargs: object) -> list[np.ndarray]:
            out = self._outputs[min(self.calls, len(self._outputs) - 1)]
            self.calls += 1
            return [out]

    # Case 1: full frame empty & below full_min -> zoom MUST NOT fire (calls == 1)
    empty_full = np.zeros((1, 4 + 2, 1), dtype=np.float32)
    empty_full[0, :4, 0] = (320, 320, 80, 80)
    empty_full[0, 4, 0] = 0.03
    s_skip = _SeqSession([empty_full])
    det_skip = Detector(
        s_skip,
        conf=0.40,
        iou=0.45,
        zoom_rescue={"enabled": True, "crop_frac": 0.60, "full_min": 0.08, "conf_floor": 0.62},
    )
    assert det_skip.detect(Image.new("RGB", (600, 800), (10, 20, 30))) == []
    assert s_skip.calls == 1

    # Case 2: full frame confirms class 0 at 0.15 (>=0.08), zoom finds valid box + oversized box (filtered!)
    warm_full = np.zeros((1, 4 + 2, 1), dtype=np.float32)
    warm_full[0, :4, 0] = (320, 320, 80, 80)
    warm_full[0, 4 + 0, 0] = 0.15  # class 0 warmed
    warm_full[0, 4 + 1, 0] = 0.02  # class 1 unconfirmed
    zoom_out = np.zeros((1, 4 + 2, 3), dtype=np.float32)
    # Anchor 0: valid centered 200x200 box on class 0 (crop_frac=0.6 on 600x800 -> crop=(360,480), lb scale=640/480=4/3, pad_x=80)
    zoom_out[0, :4, 0] = (320, 320, 160, 160)
    zoom_out[0, 4 + 0, 0] = 0.78
    # Anchor 1: oversized crop-filling box on class 0 -> rejected by max_crop_area=0.85
    zoom_out[0, :4, 1] = (320, 320, 470, 620)
    zoom_out[0, 4 + 0, 1] = 0.90
    # Anchor 2: class 1 strong in zoom but full_max=0.02 < full_min -> rejected!
    zoom_out[0, :4, 2] = (320, 320, 120, 120)
    zoom_out[0, 4 + 1, 2] = 0.85
    s_rescue = _SeqSession([warm_full, zoom_out])
    det_rescue = Detector(
        s_rescue,
        conf=0.40,
        iou=0.45,
        zoom_rescue={"enabled": True, "crop_frac": 0.60, "full_min": 0.08, "conf_floor": 0.62, "max_crop_area": 0.85},
    )
    rescued = det_rescue.detect(Image.new("RGB", (600, 800), (10, 20, 30)))
    assert s_rescue.calls == 2
    assert len(rescued) == 1
    assert rescued[0].class_index == 0 and rescued[0].confidence == pytest.approx(0.78, abs=1e-4)
    assert 0.30 < rescued[0].x1 < 0.45 and 0.55 < rescued[0].x2 < 0.70
