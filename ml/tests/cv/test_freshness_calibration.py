"""Unit tests for M1.2b produce freshness calibration, zero-leakage splits, and M3 contracts."""

from __future__ import annotations

import ast
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tastoria_ml import stats as mstats
from tastoria_ml.cv import calibration as cal
from tastoria_ml.cv import freshness_study as fs
from tastoria_ml.cv.classes import REPO
from tastoria_ml.cv.freshness import MANIFEST, WORK


def test_calibration_module_has_no_heavy_imports():
    src = Path(cal.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint({"torch", "torchvision", "cv2", "sklearn", "onnx", "onnxruntime"})


def test_fit_temperature_recovers_scale_and_improves_calibration():
    rng = np.random.default_rng(42)
    n = 6000
    true_scale = 2.5
    z_true = rng.normal(0.0, 1.2, size=(n, 3))
    p_true = cal.softmax(z_true)
    y = np.array([rng.choice(3, p=row) for row in p_true], dtype=np.int64)
    z_overconf = z_true * true_scale

    z_tr, y_tr = z_overconf[:3000], y[:3000]
    z_te, y_te = z_overconf[3000:], y[3000:]

    t_hat = cal.fit_temperature(z_tr, y_tr)
    assert t_hat == pytest.approx(true_scale, abs=0.25)

    p_uncal = cal.softmax(z_te)
    p_cal = cal.softmax(cal.apply_temperature(z_te, t_hat))
    m_uncal = mstats.calibration_metrics(y_te, p_uncal, n_bins=10)
    m_cal = mstats.calibration_metrics(y_te, p_cal, n_bins=10)
    assert m_cal["nll"] < m_uncal["nll"]
    assert m_cal["ece"] < m_uncal["ece"]
    assert m_cal["brier"] < m_uncal["brier"]
    # Temperature scaling preserves argmax
    assert np.array_equal(np.argmax(p_uncal, axis=1), np.argmax(p_cal, axis=1))


def test_fit_vector_and_platt_scaling_improve_miscalibrated_logits():
    rng = np.random.default_rng(123)
    n = 4000
    z_true = rng.normal(0.0, 1.0, size=(n, 3))
    p_true = cal.softmax(z_true)
    y = np.array([rng.choice(3, p=row) for row in p_true], dtype=np.int64)

    # Inject per-class miscalibration (diagonal scale + class bias)
    w_true = np.array([2.2, 0.7, 1.8])
    b_true = np.array([0.6, -0.8, 0.3])
    z_bad = (z_true - b_true[None, :]) / w_true[None, :]

    z_tr, y_tr = z_bad[:2000], y[:2000]
    z_te, y_te = z_bad[2000:], y[2000:]

    p_raw = cal.softmax(z_te)
    m_raw = mstats.calibration_metrics(y_te, p_raw, n_bins=10)

    w_hat, bv_hat = cal.fit_vector_scaling(z_tr, y_tr, l2=1e-4)
    p_vec = cal.softmax(cal.apply_vector_scaling(z_te, w_hat, bv_hat))
    m_vec = mstats.calibration_metrics(y_te, p_vec, n_bins=10)
    assert m_vec["nll"] < m_raw["nll"]
    assert m_vec["ece"] < m_raw["ece"]

    w_mat, bm_hat = cal.fit_platt_matrix(z_tr, y_tr, l2=1e-3)
    p_platt = cal.softmax(cal.apply_platt_matrix(z_te, w_mat, bm_hat))
    m_platt = mstats.calibration_metrics(y_te, p_platt, n_bins=10)
    assert m_platt["nll"] < m_raw["nll"]
    assert m_platt["ece"] < m_raw["ece"]


def test_nested_oof_calibrate_disjoint_and_rejects_leakage():
    rng = np.random.default_rng(7)
    n = 500
    z_true = rng.normal(0.0, 1.0, size=(n, 3))
    p_true = cal.softmax(z_true)
    y = np.array([rng.choice(3, p=row) for row in p_true], dtype=np.int64)
    z_raw = z_true * 3.0

    folds_idx = [np.arange(k * 100, (k + 1) * 100) for k in range(5)]
    fit_cal_pairs = []
    for k in range(5):
        rem = np.concatenate([folds_idx[j] for j in range(5) if j != k])
        cal_k = rem[:80]
        fit_k = rem[80:]
        fit_cal_pairs.append((fit_k, cal_k))

    res = cal.nested_oof_calibrate(z_raw, y, fit_cal_pairs, folds_idx, method="temperature")
    assert res["cal_probs"].shape == (n, 3)
    assert np.allclose(res["cal_probs"].sum(axis=1), 1.0)
    assert len(res["fold_params"]) == 5
    for fp in res["fold_params"]:
        assert 2.0 < fp["temperature"] < 4.5

    m_raw = mstats.calibration_metrics(y, cal.softmax(z_raw), n_bins=10)
    m_cal = mstats.calibration_metrics(y, res["cal_probs"], n_bins=10)
    assert m_cal["nll"] < m_raw["nll"]
    assert m_cal["ece"] < m_raw["ece"]

    # Overlapping cal_idx and te_idx must raise
    bad_pairs = [(fit_cal_pairs[k][0], folds_idx[k][:10]) for k in range(5)]
    with pytest.raises(ValueError, match="overlaps te_idx"):
        cal.nested_oof_calibrate(z_raw, y, bad_pairs, folds_idx, method="temperature")


def test_zero_leakage_splitter_synthetic_disjoint_groups():
    rng = np.random.default_rng(9)
    n_groups = 70
    rows = []
    for g in range(n_groups):
        ds = "agrifreshnet" if g < 40 else "local_spinach_leaf"
        prod = "tomato" if g < 40 else "water_spinach"
        lbl = ["tuoi", "dung_som", "dung_ngay"][g % 3] if ds == "agrifreshnet" else ["tuoi", "dung_ngay"][g % 2]
        for _ in range(3):
            rows.append({"dataset": ds, "produce": prod, "label3": lbl, "lot": f"grp_{g}"})
    df = pd.DataFrame(rows)
    groups = df["lot"].values

    for seed in (0, 1, 2):
        splits = fs.make_zero_leakage_splits(df, groups, seed=seed)
        assert len(splits) == 5
        te_all = []
        for fit_k, cal_k, te_k in splits:
            assert set(groups[fit_k]).isdisjoint(groups[cal_k])
            assert set(groups[fit_k]).isdisjoint(groups[te_k])
            assert set(groups[cal_k]).isdisjoint(groups[te_k])
            assert len(fit_k) + len(cal_k) + len(te_k) == len(df)
            te_all.append(te_k)
        te_cat = np.concatenate(te_all)
        assert len(te_cat) == len(df) and len(np.unique(te_cat)) == len(df)


@pytest.mark.skipif(
    not (MANIFEST.exists() and (WORK / "phash_d8_pairs.npy").exists()),
    reason="freshness manifest or phash_d8_pairs.npy not available",
)
def test_zero_leakage_splitter_real_d8dedup4_groups():
    df, groups = fs._load_table_and_groups("d8dedup4")
    assert len(df) == 9182
    assert len(np.unique(groups)) == 2366

    for seed in fs.SEEDS:
        splits = fs.make_zero_leakage_splits(df, groups, seed=seed)
        assert len(splits) == fs.N_FOLDS
        te_all = []
        for fit_k, cal_k, te_k in splits:
            g_fit = set(groups[fit_k].tolist())
            g_cal = set(groups[cal_k].tolist())
            g_te = set(groups[te_k].tolist())
            assert g_fit.isdisjoint(g_cal)
            assert g_fit.isdisjoint(g_te)
            assert g_cal.isdisjoint(g_te)
            assert len(fit_k) + len(cal_k) + len(te_k) == len(df)
            te_all.append(te_k)
        te_cat = np.concatenate(te_all)
        assert len(te_cat) == len(df) and len(np.unique(te_cat)) == len(df)


def test_cluster_bootstrap_metric_and_single_invariants():
    rng = np.random.default_rng(11)
    n_clusters = 40
    cl_size = 8
    clusters = np.repeat(np.arange(n_clusters), cl_size)
    y = rng.integers(0, 3, size=n_clusters * cl_size)
    pred_a = y.copy()
    pred_b = y.copy()
    flip = rng.random(len(y)) < 0.25
    pred_b[flip] = (pred_b[flip] + 1) % 3

    n_boot = 300
    single = cal.cluster_bootstrap_single(y, pred_b, clusters, lambda yt, yp: cal.macro_f1(yt, yp, 3), n_boot=n_boot, seed=0)
    assert single["n_clusters"] == n_clusters
    assert single["lo"] <= single["point"] <= single["hi"]

    paired = cal.cluster_bootstrap_metric(
        y, pred_a, pred_b, clusters, lambda yt, yp: cal.macro_f1(yt, yp, 3), n_boot=n_boot, seed=0
    )
    assert paired["n_clusters"] == n_clusters
    assert paired["diff"] == pytest.approx(paired["obs_a"] - paired["obs_b"])
    assert paired["lo"] <= paired["diff"] <= paired["hi"]
    assert (1.0 / (n_boot + 1)) <= paired["p"] <= 1.0

    # Compare linear accuracy cluster bootstrap against stats.paired_bootstrap
    acc_a = (pred_a == y).astype(float)
    acc_b = (pred_b == y).astype(float)
    ref = mstats.paired_bootstrap(acc_a, acc_b, n_boot=n_boot, seed=0, clusters=clusters)
    acc_cb = cal.cluster_bootstrap_metric(
        y, pred_a, pred_b, clusters, lambda yt, yp: cal.accuracy(yt, yp), n_boot=n_boot, seed=0
    )
    assert acc_cb["diff"] == pytest.approx(ref["diff"])
    assert acc_cb["n_clusters"] == ref["n_clusters"]
    assert acc_cb["p"] == pytest.approx(ref["p"], abs=0.05)


def test_map_to_four_class_probs_and_selective_abstention_invariants():
    probs3 = np.array([
        [0.80, 0.15, 0.05],  # accepted at tau=0.60
        [0.45, 0.35, 0.20],  # abstained at tau=0.60
        [0.05, 0.10, 0.85],  # accepted at tau=0.60
        [0.34, 0.33, 0.33],  # abstained at tau=0.60
    ])
    probs4 = cal.map_to_four_class_probs(probs3, tau=0.60)
    assert probs4.shape == (4, 4)
    assert np.allclose(probs4.sum(axis=1), 1.0)
    u = cal.compute_u_img(probs4)

    # Row 1 & 3 abstained -> exact (0, 0, 0, 1), u_img = 1.2 > 1.0
    assert np.allclose(probs4[1], [0.0, 0.0, 0.0, 1.0])
    assert np.allclose(probs4[3], [0.0, 0.0, 0.0, 1.0])
    assert u[1] > 1.0 and u[3] > 1.0

    # Row 0 & 2 accepted -> p_kiem_tra == 0, u_img <= 1.0, max(probs4) >= 0.60
    assert probs4[0, 3] == 0.0 and probs4[2, 3] == 0.0
    assert u[0] <= 1.0 and u[2] <= 1.0
    assert np.max(probs4[0]) >= 0.60 and np.max(probs4[2]) >= 0.60

    # Selective abstention curve invariants
    rng = np.random.default_rng(5)
    n_cl = 30
    clusters = np.repeat(np.arange(n_cl), 10)
    z = rng.normal(0.0, 1.5, size=(n_cl * 10, 3))
    p = cal.softmax(z)
    y = np.array([rng.choice(3, p=row) for row in p], dtype=np.int64)
    ds = np.array(["agrifreshnet"] * 150 + ["local_spinach_leaf"] * 150)

    curve = cal.selective_abstention_curve(
        p, y, clusters, thresholds=[0.4, 0.6, 0.8], score_type="max_prob", n_boot=200, seed=0, dataset_labels=ds
    )
    pts = curve["overall"]["points"]
    covs = [pt["coverage"] for pt in pts]
    assert covs[0] >= covs[1] >= covs[2]
    assert math.isfinite(curve["overall"]["aurc"]) and curve["overall"]["aurc"] >= 0.0
    assert set(curve["by_dataset"].keys()) == {"agrifreshnet", "local_spinach_leaf"}
    for pt in pts:
        if math.isfinite(pt["q_bh_error_vs_full"]):
            assert 0.0 <= pt["q_bh_error_vs_full"] <= 1.0

    curve_ent = cal.selective_abstention_curve(
        p, y, clusters, thresholds=[0.2, 0.5, 0.8], score_type="entropy", n_boot=200, seed=1
    )
    ent_covs = [pt["coverage"] for pt in curve_ent["overall"]["points"]]
    assert ent_covs[0] >= ent_covs[1] >= ent_covs[2]


def test_freshness_serving_artifacts_if_staged():
    fresh_dir = REPO / "deploy" / "models" / "freshness"
    onnx_path = fresh_dir / "model.onnx"
    serving_path = fresh_dir / "serving.json"
    if not onnx_path.exists() or not serving_path.exists():
        pytest.skip("freshness serving artifacts not staged yet (Phase 2)")

    serving = json.loads(serving_path.read_text(encoding="utf-8"))
    assert serving["schema_version"] == "freshness.serving.v1"
    assert serving["classes"] == ["tuoi", "dung_som", "dung_ngay"]
    assert serving["backend_classes"] == ["tuoi", "dung_som", "dung_ngay", "kiem_tra"]
    assert serving["input"]["grabcut_required"] is False
    assert serving["input"]["imgsz"] == 224
    assert float(serving["abstention"]["tau"]) >= 0.60
    assert serving["sha256"] == hashlib.sha256(onnx_path.read_bytes()).hexdigest()

    ort = pytest.importorskip("onnxruntime")
    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    assert tuple(sess.get_inputs()[0].shape[1:]) == (3, 224, 224)
    dummy = np.full((2, 3, 224, 224), 128.0, dtype=np.float32)
    probs, logits = sess.run(["probs", "logits"], {"image": dummy})
    assert probs.shape == (2, 3)
    assert logits.shape == (2, 3)
    assert np.allclose(probs.sum(axis=1), 1.0, atol=1e-5)
