import numpy as np
import pytest

from tastoria_ml.cv import p1_study as ps


def test_mde_dz_matches_prereg_formula():
    assert ps._mde_dz(2000) == pytest.approx(2.801585 / np.sqrt(2000), rel=1e-4)
    assert ps._mde_dz(1253) == pytest.approx(2.801585 / np.sqrt(1253), rel=1e-4)


def test_choose_val_conf_guards_zero_gt_class():
    # Class 1 has zero GT boxes in val -> must not crash or pull macro-F1 via division by zero
    gt = [
        (np.array([[0.0, 0.0, 10.0, 10.0]]), np.array([0])),
        (np.array([[20.0, 20.0, 30.0, 30.0]]), np.array([0])),
    ]
    pred = {
        "files": np.array(["a.jpg", "b.jpg"]),
        "hw": np.array([[100, 100], [100, 100]]),
        "img": np.array([0, 0, 1], dtype=np.int32),
        "cls": np.array([0, 0, 0], dtype=np.int16),
        "boxes": np.array([[0, 0, 10, 10], [50, 50, 60, 60], [20, 20, 30, 30]], dtype=np.float32),
        "scores": np.array([0.9, 0.2, 0.85], dtype=np.float32),
        "names": np.array(["covered_cls", "zero_gt_cls"]),
    }
    conf, mf1 = ps._choose_val_conf_from_pred(pred, gt)
    assert 0.2 < conf <= 0.85
    assert mf1 == pytest.approx(1.0)


def test_decode_raw_like_backend_nms_and_letterbox():
    # Synthetic raw output (1, 6, 4) for 2 classes: 2 overlapping boxes for cls 0, 1 box for cls 1
    raw = np.zeros((1, 6, 4), dtype=np.float32)
    # anchor 0: center (320, 320), w=100, h=100, cls0=0.9
    raw[0, :4, 0] = [320.0, 320.0, 100.0, 100.0]
    raw[0, 4, 0] = 0.9
    # anchor 1: overlapping cls0=0.8 -> should be suppressed by NMS (iou=0.7)
    raw[0, :4, 1] = [322.0, 320.0, 100.0, 100.0]
    raw[0, 4, 1] = 0.8
    # anchor 2: cls1=0.7 -> different class, kept
    raw[0, :4, 2] = [320.0, 320.0, 100.0, 100.0]
    raw[0, 5, 2] = 0.7
    # anchor 3: low score -> filtered by conf=0.25
    raw[0, :4, 3] = [100.0, 100.0, 40.0, 40.0]
    raw[0, 4, 3] = 0.1

    lb = (1.0, 0, 0, 640, 640)
    dets = ps._decode_raw_like_backend(raw, lb, conf=0.25, iou=0.7)
    assert [(c, round(s, 2)) for c, s, _ in dets] == [(0, 0.9), (1, 0.7)]
