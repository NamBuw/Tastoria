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
