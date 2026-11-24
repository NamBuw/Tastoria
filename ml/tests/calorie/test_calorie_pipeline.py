"""Unit & artifact verification tests for tastoria_ml.calorie (F10)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import onnxruntime as ort
import pandas as pd
import pytest
from PIL import Image

from tastoria_ml.calorie import INPUT_SIZE, PHYSICAL_UPPER_BOUNDS, PORTION_MULTIPLIERS, TARGET_COLS
from tastoria_ml.calorie.baselines import ConstantBaseline, KBDishLookup
from tastoria_ml.calorie.dataset import check_split_integrity, decode_jpeg_letterbox, letterbox_rgb
from tastoria_ml.calorie.eval import compute_all_target_metrics, compute_target_metrics, paired_bootstrap_mae
from tastoria_ml.calorie.export_onnx import benchmark_onnx_cpu

REPO = Path(__file__).resolve().parents[3]
DEPLOY_DIR = REPO / "deploy" / "models" / "meal_calorie"


def test_split_group_isolation_rejects_leakage() -> None:
    clean_df = pd.DataFrame(
        [
            {"dish_id": "d1", "split": "train", "group": "g1", "test_clean": False, "kcal": 200.0, "n_items": 2},
            {"dish_id": "d2", "split": "val", "group": "g2", "test_clean": False, "kcal": 250.0, "n_items": 3},
            {"dish_id": "d3", "split": "test", "group": "g3", "test_clean": True, "kcal": 180.0, "n_items": 2},
            {"dish_id": "d4", "split": "test", "group": "g1", "test_clean": False, "kcal": 0.0, "n_items": 0},
        ]
    )
    rep = check_split_integrity(clean_df)
    assert rep.test_clean_count == 1
    assert rep.test_clean_group_overlap_train == 0
    assert rep.test_clean_group_overlap_val == 0
    assert rep.anomalies.empty_plate_dish_ids == ("d4",)

    leaky_df = clean_df.copy()
    leaky_df.loc[leaky_df["dish_id"] == "d3", "group"] = "g1"
    with pytest.raises(ValueError, match="Split leakage detected"):
        check_split_integrity(leaky_df)


def test_constant_baseline_and_kb_portion_scaling() -> None:
    y = np.array(
        [
            [100.0, 100.0, 5.0, 10.0, 5.0],
            [200.0, 200.0, 10.0, 20.0, 10.0],
            [300.0, 300.0, 15.0, 30.0, 15.0],
        ],
        dtype=np.float32,
    )
    cb = ConstantBaseline.fit(y)
    np.testing.assert_allclose(cb.median_vec, [200.0, 200.0, 10.0, 20.0, 10.0])
    np.testing.assert_allclose(cb.predict_median(2)[1], [200.0, 200.0, 10.0, 20.0, 10.0])

    kb = KBDishLookup.from_repo(REPO)
    assert len(kb.by_slug) == 569
    assert kb.calibrated is True

    est_vua = kb.estimate(slug="thit-kho-tau", portion="vua")
    est_nho = kb.estimate(slug="thit-kho-tau", portion="nho")
    est_lon = kb.estimate(slug="thit-kho-tau", portion="lon")
    assert est_vua is not None and est_nho is not None and est_lon is not None
    assert est_nho.estimated_kcal == pytest.approx(round(est_vua.estimated_kcal * PORTION_MULTIPLIERS["nho"], 1), abs=0.2)
    assert est_lon.estimated_kcal == pytest.approx(round(est_vua.estimated_kcal * PORTION_MULTIPLIERS["lon"], 1), abs=0.2)
    assert est_vua.kcal_low < est_vua.estimated_kcal < est_vua.kcal_high

    # Diacritic-insensitive Vietnamese name lookup
    by_name = kb.estimate(dish_name="thit kho tau", portion="vua")
    assert by_name is not None and by_name.slug == "thit-kho-tau"

    assert kb.estimate(slug="mon-khong-co", portion="vua") is None
    with pytest.raises(ValueError, match="Unsupported portion"):
        kb.estimate(slug="thit-kho-tau", portion="khong_lo")


def test_metrics_math_and_paired_bootstrap() -> None:
    yt = np.array([0.0, 100.0, 200.0, 400.0], dtype=np.float64)
    yp = np.array([10.0, 110.0, 180.0, 440.0], dtype=np.float64)
    # errors: 10, 10, -20, 40 -> abs: 10, 10, 20, 40 -> mae=20
    m = compute_target_metrics(yt, yp, mape_min_true=50.0)
    assert m["mae"] == pytest.approx(20.0)
    assert m["rmse"] == pytest.approx(np.sqrt((100 + 100 + 400 + 1600) / 4))
    assert m["mape_n"] == 3  # excludes 0.0
    assert m["mape_ge_thresh"] == pytest.approx((0.10 + 0.10 + 0.10) / 3.0)
    assert m["within_20pct_ge_thresh"] == pytest.approx(1.0)
    assert 0.9 < float(m["r2"]) < 1.0

    yt2 = np.column_stack([yt, yt, yt / 10, yt / 10, yt / 10])
    yp2 = np.column_stack([yp, yp, yp / 10, yp / 10, yp / 10])
    all_m = compute_all_target_metrics(yt2, yp2)
    assert tuple(all_m.keys()) == TARGET_COLS

    pb = np.array([200.0, 200.0, 200.0, 200.0], dtype=np.float64)
    boot = paired_bootstrap_mae(yt, yp, pb, n_boot=500, seed=42)
    assert boot["delta_mae"] < 0
    assert boot["mae_model"] < boot["mae_baseline"]


def test_letterbox_rgb_preserves_shape_and_dtype() -> None:
    img = Image.new("RGB", (640, 480), (200, 100, 50))
    arr = letterbox_rgb(img)
    assert arr.shape == (INPUT_SIZE, INPUT_SIZE, 3)
    assert arr.dtype == np.uint8

    import io
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    arr2 = decode_jpeg_letterbox(buf.getvalue())
    assert arr2.shape == (INPUT_SIZE, INPUT_SIZE, 3)


def test_deployed_meal_calorie_artifact_integrity_and_latency() -> None:
    onnx_path = DEPLOY_DIR / "model.onnx"
    serving_path = DEPLOY_DIR / "serving.json"
    metrics_path = DEPLOY_DIR / "metrics.json"
    if not onnx_path.exists():
        pytest.skip("deploy/models/meal_calorie/model.onnx not exported yet")

    serving = json.loads(serving_path.read_text(encoding="utf-8"))
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))

    assert serving["schema_version"] == "meal_calorie.serving.v1"
    assert serving["portion_multipliers"] == PORTION_MULTIPLIERS
    assert "domain_shift_note" in serving and len(serving["domain_shift_note"]) > 20

    actual_sha = hashlib.sha256(onnx_path.read_bytes()).hexdigest()
    assert serving["artifact_sha256"] == actual_sha

    so = ort.SessionOptions()
    so.intra_op_num_threads = 2
    so.inter_op_num_threads = 1
    so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    so.add_session_config_entry("session.intra_op.allow_spinning", "0")
    sess = ort.InferenceSession(str(onnx_path), so, providers=["CPUExecutionProvider"])
    x = np.full((2, 3, INPUT_SIZE, INPUT_SIZE), 128.0, dtype=np.float32)
    out = sess.run(None, {sess.get_inputs()[0].name: x})[0]
    assert out.shape[0] == 2 and out.shape[1] in (5, 7)
    assert np.all(out >= 0.0)

    lat = benchmark_onnx_cpu(onnx_path, n_warmup=5, n_runs=50)
    assert lat["p95_ms"] <= 50.0, lat

    # Honest falsification check: beats constant median baseline on Nutrition5k test & test_clean
    assert metrics["splits"]["test"]["model"]["kcal"]["mae"] < metrics["splits"]["test"]["baseline_median"]["kcal"]["mae"]
    assert metrics["splits"]["test_clean"]["model"]["kcal"]["mae"] < metrics["splits"]["test_clean"]["baseline_median"]["kcal"]["mae"]


def test_physical_upper_bounds_and_kb_short_substring_guard() -> None:
    assert PHYSICAL_UPPER_BOUNDS == (3500.0, 3000.0, 250.0, 400.0, 250.0)
    kb = KBDishLookup.from_repo(REPO)
    assert kb.lookup(dish_name="a") is None
    assert kb.lookup(dish_name="ga") is None
    assert kb.lookup(dish_name="thit kho tau") is not None


def test_with_norm_calorie_wrapper_clamps_bounds() -> None:
    torch = pytest.importorskip("torch")
    from tastoria_ml.calorie.model import WithNormCalorieWrapper

    class _DummyNet(torch.nn.Module):
        def __init__(self, out_vec: list[float]) -> None:
            super().__init__()
            self.register_buffer("out", torch.tensor([out_vec], dtype=torch.float32))

        def forward(self, x_norm: torch.Tensor) -> torch.Tensor:
            return self.out.expand(x_norm.shape[0], -1)

    mean = np.zeros(5, dtype=np.float32)
    std = np.ones(5, dtype=np.float32)

    hi_wrap = WithNormCalorieWrapper(_DummyNet([1e6, 1e6, 1e6, 1e6, 1e6]), mean, std).eval()
    lo_wrap = WithNormCalorieWrapper(_DummyNet([-1e5, -10.0, -5.0, -1.0, -999.0]), mean, std).eval()

    x = torch.zeros(2, 3, INPUT_SIZE, INPUT_SIZE, dtype=torch.float32)
    with torch.no_grad():
        hi = hi_wrap(x).numpy()
        lo = lo_wrap(x).numpy()
    np.testing.assert_allclose(hi[0], PHYSICAL_UPPER_BOUNDS)
    np.testing.assert_allclose(lo[0], [0.0, 0.0, 0.0, 0.0, 0.0])
