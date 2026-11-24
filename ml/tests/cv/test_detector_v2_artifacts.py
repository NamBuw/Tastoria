import hashlib
import json

import numpy as np
import pytest

from tastoria_ml.cv import onnx_latency as ol
from tastoria_ml.cv.build_yolo_v2 import all_class_rows
from tastoria_ml.cv.classes import REPO


def test_onnx_latency_shape_check_and_summary():
    ol._check_output_shape((1, 34, 8400), "raw", expected_nc=30)
    ol._check_output_shape((1, 300, 6), "e2e")
    with pytest.raises(ValueError):
        ol._check_output_shape((1, 300, 6), "raw", expected_nc=30)
    with pytest.raises(ValueError):
        ol._check_output_shape((1, 17, 8400), "raw", expected_nc=30)
    with pytest.raises(ValueError):
        ol._check_output_shape((1, 34, 8400), "e2e")

    summ = ol._latency_summary(np.array([0.01, 0.02, 0.03, 0.04]))
    assert summ["p50"] == pytest.approx(25.0)
    assert summ["p95"] >= summ["p50"]
    assert summ["p99"] >= summ["p95"]


def test_detector_v2_artifacts_if_staged():
    det_dir = REPO / "deploy" / "models" / "detector_v2"
    onnx_path = det_dir / "model.onnx"
    serving_path = det_dir / "serving.json"
    if not onnx_path.exists() or not serving_path.exists():
        pytest.skip("detector_v2 artifacts not staged yet")

    serving = json.loads(serving_path.read_text(encoding="utf-8"))
    assert 0.0 < float(serving["conf"]) < 1.0
    assert 0.0 < float(serving["iou"]) < 1.0
    assert int(serving["imgsz"]) == 640

    digest = hashlib.sha256(onnx_path.read_bytes()).hexdigest()
    assert serving["sha256"] == digest

    classes = serving["classes"]
    assert isinstance(classes, list) and len(classes) == 30
    valid_ids = {r["id"] for r in all_class_rows()}
    assert set(classes) <= valid_ids
    assert serving["onnx_output_shape"] == [1, 34, 8400]
    assert "c1" in serving["latency_ms"] and "val" in serving["metrics"]

    ort = pytest.importorskip("onnxruntime")
    import ast

    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    assert tuple(sess.get_inputs()[0].shape) == (1, 3, 640, 640)
    assert tuple(sess.get_outputs()[0].shape) == (1, 34, 8400)
    meta = sess.get_modelmeta().custom_metadata_map
    names = ast.literal_eval(meta["names"])
    assert [names[i] for i in range(30)] == classes
    assert meta.get("end2end") == "False"
