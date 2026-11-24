"""Unit tests for shared statistical helpers in ``tastoria_ml.stats`` and ``recsys.stats`` shim."""

from __future__ import annotations

import math

import numpy as np
import pytest

from tastoria_ml import stats
from tastoria_ml.recsys import stats as recsys_stats


def test_recsys_shim_exports_same_objects():
    for name in (
        "paired_bootstrap",
        "mean_ci",
        "wilcoxon",
        "mcnemar",
        "holm",
        "bh_fdr",
        "check_paired_assumptions",
        "cohens_dz",
        "cliffs_delta",
        "calibration_metrics",
    ):
        assert getattr(recsys_stats, name) is getattr(stats, name)


def test_paired_bootstrap_standard_and_empty():
    rng = np.random.default_rng(42)
    b = rng.normal(0.0, 1.0, 400)
    a = b + 0.4
    res = stats.paired_bootstrap(a, b, n_boot=1000, seed=0)
    assert res["n"] == 400
    assert res["diff"] == pytest.approx(0.4, abs=1e-12)
    assert res["lo"] <= res["diff"] <= res["hi"]
    assert res["p"] < 0.01
    assert res["sd_diff"] == pytest.approx(0.0, abs=1e-12)

    empty = stats.paired_bootstrap([np.nan], [1.0])
    assert empty["n"] == 0
    assert math.isnan(empty["diff"]) and math.isnan(empty["p"])


def test_paired_bootstrap_clusters_widens_ci_under_intraclass_correlation():
    rng = np.random.default_rng(7)
    n_clusters = 25
    cluster_size = 20
    cluster_effects = rng.normal(0.2, 0.8, n_clusters)
    clusters = np.repeat(np.arange(n_clusters), cluster_size)
    d = np.repeat(cluster_effects, cluster_size) + rng.normal(0.0, 0.05, n_clusters * cluster_size)
    b = np.zeros_like(d)

    naive = stats.paired_bootstrap(d, b, n_boot=1000, seed=1)
    clustered = stats.paired_bootstrap(d, b, n_boot=1000, seed=1, clusters=clusters)
    assert clustered["n_clusters"] == n_clusters
    assert clustered["n"] == n_clusters * cluster_size
    assert clustered["diff"] == pytest.approx(naive["diff"])
    assert (clustered["hi"] - clustered["lo"]) > 2.0 * (naive["hi"] - naive["lo"])


def test_mean_ci_handles_empty_and_clusters():
    m, lo, hi = stats.mean_ci([np.nan, np.nan])
    assert math.isnan(m) and math.isnan(lo) and math.isnan(hi)

    vals = np.array([1.0, 1.0, 1.0, 5.0, 5.0, 5.0])
    cl = np.array([0, 0, 0, 1, 1, 1])
    mean_v, lo_v, hi_v = stats.mean_ci(vals, n_boot=500, seed=0, clusters=cl, alpha=0.05)
    assert mean_v == pytest.approx(3.0)
    assert 1.0 <= lo_v <= 3.0 <= hi_v <= 5.0


def test_wilcoxon_effect_sizes_and_degenerate_cases():
    a = np.array([2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0])
    b = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0])
    res = stats.wilcoxon(a, b)
    assert res["n_nonzero"] == 8
    assert res["rank_biserial"] == pytest.approx(1.0)
    assert res["p"] < 0.02
    lo, hi = res["hl_ci95"]
    assert lo <= res["hodges_lehmann"] <= hi

    zero = stats.wilcoxon([1.0, 2.0], [1.0, 2.0])
    assert zero["n_nonzero"] == 0 and zero["p"] == 1.0 and zero["rank_biserial"] == 0.0


def test_mcnemar_haldane_or_and_newcombe_ci():
    a = np.array([True, True, True, False, True, False])
    b = np.array([False, False, True, False, True, False])
    res = stats.mcnemar(a, b)
    assert res["a_only"] == 2 and res["b_only"] == 0 and res["n"] == 6
    assert res["odds_ratio"] == pytest.approx((2 + 0.5) / (0 + 0.5))
    assert res["risk_diff"] == pytest.approx(2.0 / 6.0)
    lo, hi = res["risk_diff_ci95"]
    assert -1.0 <= lo <= res["risk_diff"] <= hi <= 1.0


def test_holm_and_bh_fdr():
    p = np.array([0.01, 0.04, 0.03, 0.20])
    h = stats.holm(p)
    fdr = stats.bh_fdr(p)
    assert np.allclose(h, [0.04, 0.09, 0.09, 0.20])
    assert np.allclose(fdr, [0.04, 0.0533333333, 0.0533333333, 0.20])
    assert np.all(fdr <= h + 1e-12)
    assert stats.holm([]).size == 0 and stats.bh_fdr([]).size == 0


def test_check_paired_assumptions_diagnostics():
    rng = np.random.default_rng(10)
    a = rng.normal(0.0, 1.0, 100)
    b = np.zeros(100)
    norm_diag = stats.check_paired_assumptions(a, b)
    assert norm_diag["n"] == 100 and norm_diag["n_nonzero"] == 100
    assert norm_diag["symmetry_flag"] is True

    skewed = np.exp(rng.normal(0.0, 1.5, 100))
    skew_diag = stats.check_paired_assumptions(skewed, b)
    assert skew_diag["skewness"] > 1.0
    assert skew_diag["symmetry_flag"] is False
    assert skew_diag["recommended_test"] == "paired_bootstrap"


def test_cohens_dz_and_cliffs_delta():
    rng = np.random.default_rng(3)
    b = rng.normal(0.0, 1.0, 80)
    a = b + rng.normal(0.5, 1.0, 80)
    eff = stats.cohens_dz(a, b, n_boot=500, seed=0)
    assert eff["n"] == 80
    assert eff["lo"] <= eff["d_z"] <= eff["hi"]
    assert abs(eff["hedges_gz"]) < abs(eff["d_z"])

    assert stats.cliffs_delta([10.0, 20.0], [1.0, 2.0]) == pytest.approx(1.0)
    assert stats.cliffs_delta([1.0, 2.0], [10.0, 20.0]) == pytest.approx(-1.0)
    assert stats.cliffs_delta([1.0, 5.0], [1.0, 5.0]) == pytest.approx(0.0)


def test_calibration_metrics_perfect_vs_overconfident():
    y = np.array([0, 1, 2, 0, 1, 2])
    perfect = np.eye(3)[y]
    m_perf = stats.calibration_metrics(y, perfect, n_bins=5)
    assert m_perf["ece"] == pytest.approx(0.0)
    assert m_perf["ece_adaptive"] == pytest.approx(0.0)
    assert m_perf["brier"] == pytest.approx(0.0)
    assert m_perf["nll"] < 1e-10

    overconf = np.array([
        [0.99, 0.005, 0.005],
        [0.99, 0.005, 0.005],  # wrong
        [0.005, 0.005, 0.99],
        [0.005, 0.99, 0.005],  # wrong
        [0.005, 0.99, 0.005],
        [0.005, 0.005, 0.99],
    ])
    m_bad = stats.calibration_metrics(y, overconf, n_bins=5)
    assert m_bad["ece"] > 0.3
    assert m_bad["ece_adaptive"] > 0.3
    assert m_bad["brier"] > 0.5
    assert m_bad["nll"] > 1.5
    assert m_bad["bin_counts"].sum() == 6


def test_paired_bootstrap_degenerate_single_unit_or_cluster_returns_nan_p():
    single = stats.paired_bootstrap([0.5], [0.0], n_boot=500)
    assert single["n"] == 1
    assert single["diff"] == pytest.approx(0.5)
    assert math.isnan(single["p"])
    assert math.isnan(single["sd_diff"])
    assert math.isnan(single["cohen_dz"])

    one_cluster = stats.paired_bootstrap([0.5, 0.6, 0.7], [0.0, 0.0, 0.0], n_boot=500, clusters=[0, 0, 0])
    assert one_cluster["n"] == 3 and one_cluster["n_clusters"] == 1
    assert math.isnan(one_cluster["p"])
    assert math.isnan(one_cluster["sd_diff"])
    assert math.isnan(one_cluster["cohen_dz"])


def test_wilcoxon_large_n_nonzero_with_zero_inflation_is_continuous():
    a_ones = np.concatenate([np.zeros(8000), np.ones(2000)])
    b_zeros = np.zeros(10000)
    res_ones = stats.wilcoxon(a_ones, b_zeros)
    assert res_ones["n_nonzero"] == 2000
    assert res_ones["hodges_lehmann"] == pytest.approx(1.0)
    assert res_ones["hl_ci95"] == pytest.approx((1.0, 1.0))

    d_pos = np.random.default_rng(7).exponential(2.0, 1501)
    w_1500 = stats.wilcoxon(np.r_[d_pos[:1500], np.zeros(1600)], np.zeros(3100))
    w_1501 = stats.wilcoxon(np.r_[d_pos[:1501], np.zeros(1600)], np.zeros(3101))
    assert w_1500["n_nonzero"] == 1500 and w_1501["n_nonzero"] == 1501
    assert abs(w_1500["hodges_lehmann"] - w_1501["hodges_lehmann"]) < 0.2
    assert w_1501["hl_ci95"][0] <= w_1501["hodges_lehmann"] <= w_1501["hl_ci95"][1]


def test_mcnemar_filters_nonfinite_paired_rows():
    res = stats.mcnemar([np.nan, 0.0, 1.0, np.inf], [0.0, 0.0, 1.0, 0.0])
    assert res["n"] == 2
    assert res["a_only"] == 0 and res["b_only"] == 0
    assert res["p"] == pytest.approx(1.0)


def test_holm_and_bh_fdr_nan_preservation_and_range_validation():
    p = np.array([0.01, np.nan, 0.04])
    h = stats.holm(p)
    bh = stats.bh_fdr(p)
    assert h[0] == pytest.approx(0.02) and math.isnan(h[1]) and h[2] == pytest.approx(0.04)
    assert bh[0] == pytest.approx(0.02) and math.isnan(bh[1]) and bh[2] == pytest.approx(0.04)

    all_nan = stats.holm([np.nan, np.nan])
    assert all_nan.shape == (2,) and np.all(np.isnan(all_nan))
    all_nan_bh = stats.bh_fdr([np.nan, np.nan])
    assert all_nan_bh.shape == (2,) and np.all(np.isnan(all_nan_bh))

    with pytest.raises(ValueError):
        stats.holm([-0.05, 0.2])
    with pytest.raises(ValueError):
        stats.bh_fdr([0.1, 1.2])


def test_cohens_dz_n_lt_3_and_heavy_ties():
    res2 = stats.cohens_dz([10.0, 10.2], [0.0, 0.0], n_boot=200, seed=0)
    assert res2["n"] == 2
    assert math.isfinite(res2["d_z"])
    assert math.isnan(res2["hedges_gz"])

    ties = stats.cohens_dz([1.0, 1.0, 1.0, 1.0, 10.0], [0.0] * 5, n_boot=500, seed=0)
    assert ties["n"] == 5
    assert math.isfinite(ties["d_z"]) and math.isfinite(ties["hedges_gz"])


def test_calibration_metrics_tied_adaptive_ece_permutation_invariant_and_nan():
    y = np.array([0] * 50 + [1] * 50)
    p = np.tile([0.3, 0.7], (100, 1))
    m1 = stats.calibration_metrics(y, p, n_bins=10)
    assert m1["ece"] == pytest.approx(0.20)
    assert m1["ece_adaptive"] == pytest.approx(0.20)

    perm = np.random.default_rng(123).permutation(100)
    m2 = stats.calibration_metrics(y[perm], p[perm], n_bins=10)
    assert m2["ece_adaptive"] == pytest.approx(0.20)

    # Partial ties + non-tied values remain permutation-invariant
    rng = np.random.default_rng(9)
    p_mix = np.vstack([p[:40], np.column_stack([1 - np.linspace(0.55, 0.95, 60), np.linspace(0.55, 0.95, 60)])])
    y_mix = rng.integers(0, 2, size=100)
    perm_mix = rng.permutation(100)
    assert stats.calibration_metrics(y_mix, p_mix, n_bins=10)["ece_adaptive"] == pytest.approx(
        stats.calibration_metrics(y_mix[perm_mix], p_mix[perm_mix], n_bins=10)["ece_adaptive"]
    )

    # Paired NaN row filtering keeps same n across all 4 metrics
    p_nan = np.array([[0.8, 0.2], [np.nan, 0.5], [0.3, 0.7]])
    y_nan = np.array([0, 1, 1], dtype=float)
    m_nan = stats.calibration_metrics(y_nan, p_nan, n_bins=5)
    m_clean = stats.calibration_metrics([0, 1], [[0.8, 0.2], [0.3, 0.7]], n_bins=5)
    assert m_nan["n"] == 2
    assert m_nan["ece"] == pytest.approx(m_clean["ece"])
    assert m_nan["ece_adaptive"] == pytest.approx(m_clean["ece_adaptive"])
    assert m_nan["brier"] == pytest.approx(m_clean["brier"])
    assert m_nan["nll"] == pytest.approx(m_clean["nll"])

    # Out-of-range probabilities raise ValueError
    with pytest.raises(ValueError):
        stats.calibration_metrics([0, 1], [[1.2, 0.2], [0.1, 1.5]], n_bins=5)
