"""Shared statistical inference, assumption checks, effect sizes, multiplicity, and calibration helpers.

Uses only NumPy and SciPy (`scipy.stats`) so all functions work identically in both
`.venv` (RecSys/Substitution/Composer) and `ml/runs/venv-cv` (CV/Calibration).
"""

from __future__ import annotations

import math

import numpy as np
from scipy import stats as st

__all__ = [
    "bh_fdr",
    "calibration_metrics",
    "check_paired_assumptions",
    "cliffs_delta",
    "cohens_dz",
    "holm",
    "mcnemar",
    "mean_ci",
    "paired_bootstrap",
    "wilcoxon",
]


def _wilson_ci(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    """Wilson score confidence interval for a single proportion k / n."""
    if n <= 0:
        return float("nan"), float("nan")
    p = k / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / denom
    half = (z * math.sqrt((p * (1.0 - p) + z2 / (4.0 * n)) / n)) / denom
    return max(0.0, center - half), min(1.0, center + half)


def paired_bootstrap(
    a: np.ndarray | list[float],
    b: np.ndarray | list[float],
    n_boot: int = 2000,
    seed: int = 0,
    clusters: np.ndarray | list | None = None,
) -> dict[str, float | int]:
    """Paired bootstrap of per-unit differences ``d = a - b`` (or cluster-level resampling).

    Preserves keys ``diff, lo, hi, p, n`` and adds ``sd_diff``, ``cohen_dz``, and
    ``n_clusters`` (when ``clusters`` is provided).
    """
    a_arr = np.asarray(a, dtype=float)
    b_arr = np.asarray(b, dtype=float)
    if a_arr.shape != b_arr.shape:
        raise ValueError("paired arrays must have the same shape")
    if n_boot <= 0:
        raise ValueError("n_boot must be positive")

    d = a_arr - b_arr
    valid = ~np.isnan(d)

    if clusters is not None:
        cl_arr = np.asarray(clusters)
        if cl_arr.shape != a_arr.shape:
            raise ValueError("clusters must have the same shape as paired arrays")
        d = d[valid]
        cl_valid = cl_arr[valid]
        n = int(len(d))
        if n == 0:
            return {
                "diff": float("nan"),
                "lo": float("nan"),
                "hi": float("nan"),
                "p": float("nan"),
                "n": 0,
                "sd_diff": float("nan"),
                "cohen_dz": float("nan"),
                "n_clusters": 0,
            }
        uniq, inv = np.unique(cl_valid, return_inverse=True)
        k = int(len(uniq))
        obs = float(d.mean())
        if n < 2 or k < 2:
            return {
                "diff": obs,
                "lo": obs,
                "hi": obs,
                "p": float("nan"),
                "n": n,
                "sd_diff": float("nan"),
                "cohen_dz": float("nan"),
                "n_clusters": k,
            }
        c_sum = np.bincount(inv, weights=d, minlength=k).astype(float)
        c_cnt = np.bincount(inv, minlength=k).astype(float)

        rng = np.random.default_rng(seed)
        means = np.empty(n_boot, dtype=float)
        for b0 in range(0, n_boot, 200):
            chunk = min(200, n_boot - b0)
            idx = rng.integers(0, k, size=(chunk, k))
            means[b0 : b0 + chunk] = c_sum[idx].sum(axis=1) / c_cnt[idx].sum(axis=1)

        sd_diff = float(d.std(ddof=1))
        cohen_dz_val = float(obs / sd_diff) if sd_diff > 0.0 else (0.0 if obs == 0.0 else float("nan"))
        p = (np.sum(np.abs(means - obs) >= abs(obs)) + 1) / (n_boot + 1)
        lo, hi = np.percentile(means, [2.5, 97.5])
        return {
            "diff": obs,
            "lo": float(lo),
            "hi": float(hi),
            "p": float(min(1.0, p)),
            "n": n,
            "sd_diff": sd_diff,
            "cohen_dz": cohen_dz_val,
            "n_clusters": k,
        }

    d = d[valid]
    n = int(len(d))
    if n == 0:
        return {
            "diff": float("nan"),
            "lo": float("nan"),
            "hi": float("nan"),
            "p": float("nan"),
            "n": 0,
            "sd_diff": float("nan"),
            "cohen_dz": float("nan"),
        }
    obs = float(d.mean())
    if n < 2:
        return {
            "diff": obs,
            "lo": obs,
            "hi": obs,
            "p": float("nan"),
            "n": n,
            "sd_diff": float("nan"),
            "cohen_dz": float("nan"),
        }

    rng = np.random.default_rng(seed)
    means = np.empty(n_boot, dtype=float)
    for b0 in range(0, n_boot, 200):
        idx = rng.integers(0, n, size=(min(200, n_boot - b0), n))
        means[b0 : b0 + len(idx)] = d[idx].mean(axis=1)
    sd_diff = float(d.std(ddof=1))
    cohen_dz_val = float(obs / sd_diff) if sd_diff > 0.0 else (0.0 if obs == 0.0 else float("nan"))
    p = (np.sum(np.abs(means - obs) >= abs(obs)) + 1) / (n_boot + 1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return {
        "diff": obs,
        "lo": float(lo),
        "hi": float(hi),
        "p": float(min(1.0, p)),
        "n": n,
        "sd_diff": sd_diff,
        "cohen_dz": cohen_dz_val,
    }


def mean_ci(
    x: np.ndarray | list[float],
    n_boot: int = 2000,
    seed: int = 0,
    clusters: np.ndarray | list | None = None,
    alpha: float = 0.05,
) -> tuple[float, float, float]:
    """Mean and (1 - alpha) bootstrap percentile CI over units (or clusters)."""
    if not (0.0 < alpha < 1.0):
        raise ValueError("alpha must be in (0, 1)")
    if n_boot <= 0:
        raise ValueError("n_boot must be positive")

    x_arr = np.asarray(x, dtype=float)
    valid = ~np.isnan(x_arr)
    lo_q = 100.0 * (alpha / 2.0)
    hi_q = 100.0 * (1.0 - alpha / 2.0)

    if clusters is not None:
        cl_arr = np.asarray(clusters)
        if cl_arr.shape != x_arr.shape:
            raise ValueError("clusters must have the same shape as x")
        x_valid = x_arr[valid]
        cl_valid = cl_arr[valid]
        if len(x_valid) == 0:
            return float("nan"), float("nan"), float("nan")
        uniq, inv = np.unique(cl_valid, return_inverse=True)
        k = int(len(uniq))
        c_sum = np.bincount(inv, weights=x_valid, minlength=k).astype(float)
        c_cnt = np.bincount(inv, minlength=k).astype(float)
        rng = np.random.default_rng(seed)
        m = np.empty(n_boot, dtype=float)
        for b0 in range(0, n_boot, 500):
            chunk = min(500, n_boot - b0)
            idx = rng.integers(0, k, size=(chunk, k))
            m[b0 : b0 + chunk] = c_sum[idx].sum(axis=1) / c_cnt[idx].sum(axis=1)
        lo, hi = np.percentile(m, [lo_q, hi_q])
        return float(x_valid.mean()), float(lo), float(hi)

    x_valid = x_arr[valid]
    n = len(x_valid)
    if n == 0:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    m = np.empty(n_boot, dtype=float)
    for b0 in range(0, n_boot, 500):
        chunk = min(500, n_boot - b0)
        idx = rng.integers(0, n, size=(chunk, n))
        m[b0 : b0 + chunk] = x_valid[idx].mean(axis=1)
    lo, hi = np.percentile(m, [lo_q, hi_q])
    return float(x_valid.mean()), float(lo), float(hi)


def wilcoxon(a: np.ndarray | list[float], b: np.ndarray | list[float]) -> dict[str, float | int | tuple[float, float]]:
    """Two-sided Wilcoxon signed-rank test with rank-biserial correlation and Hodges-Lehmann shift."""
    a_arr = np.asarray(a, dtype=float)
    b_arr = np.asarray(b, dtype=float)
    if a_arr.shape != b_arr.shape:
        raise ValueError("paired arrays must have the same shape")
    d = a_arr - b_arr
    d = d[~np.isnan(d)]
    if len(d) == 0:
        return {
            "stat": float("nan"),
            "p": 1.0,
            "n_nonzero": 0,
            "rank_biserial": float("nan"),
            "hodges_lehmann": float("nan"),
            "hl_ci95": (float("nan"), float("nan")),
        }
    d_nz = d[d != 0.0]
    n_nz = int(len(d_nz))
    if n_nz == 0:
        return {
            "stat": float("nan"),
            "p": 1.0,
            "n_nonzero": 0,
            "rank_biserial": 0.0,
            "hodges_lehmann": 0.0,
            "hl_ci95": (0.0, 0.0),
        }

    r = st.wilcoxon(d, zero_method="wilcox", alternative="two-sided")
    ranks = st.rankdata(np.abs(d_nz))
    w_plus = float(ranks[d_nz > 0.0].sum())
    w_minus = float(ranks[d_nz < 0.0].sum())
    rank_biserial = float((w_plus - w_minus) / (w_plus + w_minus))

    if n_nz <= 1500:
        iu0, iu1 = np.triu_indices(n_nz)
        walsh = np.sort(0.5 * (d_nz[iu0] + d_nz[iu1]))
        hl = float(np.median(walsh))
        m = len(walsh)
        if n_nz >= 6:
            sigma_w = math.sqrt(n_nz * (n_nz + 1) * (2 * n_nz + 1) / 24.0)
            k_idx = max(0, min(m - 1, int(math.floor(m / 2.0 - 1.959963984540054 * sigma_w))))
            hl_ci = (float(walsh[k_idx]), float(walsh[m - 1 - k_idx]))
        else:
            hl_ci = (float(walsh[0]), float(walsh[-1]))
    else:
        rng = np.random.default_rng(0)
        n_pairs = 100_000
        u = rng.integers(0, n_nz, size=n_pairs)
        v = rng.integers(0, n_nz, size=n_pairs)
        i_idx = np.minimum(u, v)
        j_idx = np.maximum(u, v)
        hl = float(np.median(0.5 * (d_nz[i_idx] + d_nz[j_idx])))

        n_boot_hl = 500
        n_boot_pairs = 4000
        meds = np.empty(n_boot_hl, dtype=float)
        for b0 in range(0, n_boot_hl, 50):
            chunk = min(50, n_boot_hl - b0)
            samp = d_nz[rng.integers(0, n_nz, size=(chunk, n_nz))]
            pu = rng.integers(0, n_nz, size=(chunk, n_boot_pairs))
            pv = rng.integers(0, n_nz, size=(chunk, n_boot_pairs))
            rows = np.arange(chunk)[:, None]
            walsh_b = 0.5 * (samp[rows, pu] + samp[rows, pv])
            meds[b0 : b0 + chunk] = np.median(walsh_b, axis=1)
        lo, hi = np.percentile(meds, [2.5, 97.5])
        hl_ci = (float(lo), float(hi))

    return {
        "stat": float(r.statistic),
        "p": float(r.pvalue),
        "n_nonzero": n_nz,
        "rank_biserial": rank_biserial,
        "hodges_lehmann": hl,
        "hl_ci95": hl_ci,
    }


def mcnemar(
    a: np.ndarray | list[bool] | list[int],
    b: np.ndarray | list[bool] | list[int],
) -> dict[str, float | int | tuple[float, float]]:
    """Exact two-sided McNemar test with discordant odds ratio (Haldane +0.5 guard) and Newcombe risk diff CI."""
    a_raw = np.asarray(a)
    b_raw = np.asarray(b)
    if a_raw.shape != b_raw.shape:
        raise ValueError("paired boolean arrays must have the same shape")
    a_num = np.asarray(a_raw, dtype=float)
    b_num = np.asarray(b_raw, dtype=float)
    valid = np.isfinite(a_num) & np.isfinite(b_num)
    a_arr = a_num[valid].astype(bool)
    b_arr = b_num[valid].astype(bool)
    n_total = int(a_arr.size)
    n11 = int((a_arr & b_arr).sum())
    n01 = int((~a_arr & b_arr).sum())
    n10 = int((a_arr & ~b_arr).sum())
    n00 = int((~a_arr & ~b_arr).sum())
    n_disc = n01 + n10
    p = 1.0 if n_disc == 0 else float(st.binomtest(n10, n_disc, 0.5).pvalue)

    if n_total == 0:
        return {
            "a_only": 0,
            "b_only": 0,
            "p": 1.0,
            "n": 0,
            "risk_diff": float("nan"),
            "risk_diff_ci95": (float("nan"), float("nan")),
            "odds_ratio": float("nan"),
        }

    # Newcombe Method 10 paired risk-difference 95% CI
    k1 = n11 + n10
    k2 = n11 + n01
    p1 = k1 / n_total
    p2 = k2 / n_total
    rd = p1 - p2
    l1, u1 = _wilson_ci(k1, n_total)
    l2, u2 = _wilson_ci(k2, n_total)

    # Paired correlation phi (Tango / Newcombe correction)
    denom_prod = k1 * (n_total - k1) * k2 * (n_total - k2)
    if denom_prod <= 0:
        phi = 0.0
    else:
        num = n11 * n00 - n10 * n01
        if num > 0:
            num = max(0.0, num - n_total / 2.0)
        phi = max(-1.0, min(1.0, num / math.sqrt(denom_prod)))

    d1_lo = (p1 - l1) ** 2 - 2.0 * phi * (p1 - l1) * (u2 - p2) + (u2 - p2) ** 2
    d1_hi = (u1 - p1) ** 2 - 2.0 * phi * (u1 - p1) * (p2 - l2) + (p2 - l2) ** 2
    ci_lo = max(-1.0, rd - math.sqrt(max(0.0, d1_lo)))
    ci_hi = min(1.0, rd + math.sqrt(max(0.0, d1_hi)))

    if n10 == 0 or n01 == 0:
        odds_ratio = (n10 + 0.5) / (n01 + 0.5)
    else:
        odds_ratio = n10 / n01

    return {
        "a_only": n10,
        "b_only": n01,
        "p": p,
        "n": n_total,
        "risk_diff": float(rd),
        "risk_diff_ci95": (float(ci_lo), float(ci_hi)),
        "odds_ratio": float(odds_ratio),
    }


def holm(p: list[float] | np.ndarray) -> np.ndarray:
    """Holm-Bonferroni step-down adjusted p-values (controls FWER)."""
    p_arr = np.asarray(p, dtype=float)
    if p_arr.size == 0:
        return np.empty_like(p_arr, dtype=float)
    finite = np.isfinite(p_arr)
    if np.any((p_arr[finite] < 0.0) | (p_arr[finite] > 1.0)):
        raise ValueError("p-values must lie in [0.0, 1.0]")
    out = np.full(p_arr.shape, np.nan, dtype=float)
    m_valid = int(np.sum(finite))
    if m_valid == 0:
        return out
    p_valid = p_arr[finite]
    order = np.argsort(p_valid)
    adj_valid = np.empty(m_valid, dtype=float)
    run = 0.0
    for rank, idx in enumerate(order):
        run = max(run, (m_valid - rank) * p_valid[idx])
        adj_valid[idx] = min(1.0, max(0.0, run))
    out[finite] = adj_valid
    return out


def bh_fdr(p: list[float] | np.ndarray) -> np.ndarray:
    """Benjamini-Hochberg step-up FDR adjusted p-values."""
    p_arr = np.asarray(p, dtype=float)
    if p_arr.size == 0:
        return np.empty_like(p_arr, dtype=float)
    finite = np.isfinite(p_arr)
    if np.any((p_arr[finite] < 0.0) | (p_arr[finite] > 1.0)):
        raise ValueError("p-values must lie in [0.0, 1.0]")
    out = np.full(p_arr.shape, np.nan, dtype=float)
    m_valid = int(np.sum(finite))
    if m_valid == 0:
        return out
    p_valid = p_arr[finite]
    order = np.argsort(p_valid)
    sorted_p = p_valid[order]
    ranks = np.arange(1, m_valid + 1, dtype=float)
    scaled = sorted_p * m_valid / ranks
    monotone = np.minimum.accumulate(scaled[::-1])[::-1]
    adj_valid = np.empty(m_valid, dtype=float)
    adj_valid[order] = np.clip(monotone, 0.0, 1.0)
    out[finite] = adj_valid
    return out


def check_paired_assumptions(a: np.ndarray | list[float], b: np.ndarray | list[float]) -> dict[str, float | int | bool | str]:
    """Diagnostic summary on paired within-unit differences ``d = a - b``."""
    a_arr = np.asarray(a, dtype=float)
    b_arr = np.asarray(b, dtype=float)
    if a_arr.shape != b_arr.shape:
        raise ValueError("paired arrays must have the same shape")
    d = a_arr - b_arr
    d = d[~np.isnan(d)]
    n = int(len(d))
    if n == 0:
        return {
            "n": 0,
            "n_nonzero": 0,
            "frac_zero": float("nan"),
            "normality_p": float("nan"),
            "skewness": float("nan"),
            "excess_kurtosis": float("nan"),
            "symmetry_flag": False,
            "recommended_test": "insufficient_data",
        }

    n_nonzero = int((d != 0.0).sum())
    frac_zero = float((n - n_nonzero) / n)

    if np.ptp(d) == 0.0:
        return {
            "n": n,
            "n_nonzero": n_nonzero,
            "frac_zero": frac_zero,
            "normality_p": float("nan"),
            "skewness": 0.0,
            "excess_kurtosis": 0.0,
            "symmetry_flag": True,
            "recommended_test": "no_variation",
        }

    if 3 <= n <= 5000:
        normality_p = float(st.shapiro(d).pvalue)
    elif n > 5000:
        normality_p = float(st.normaltest(d).pvalue)
    else:
        normality_p = float("nan")

    if n >= 3:
        skewness = float(st.skew(d, bias=False))
        excess_kurtosis = float(st.kurtosis(d, fisher=True, bias=False)) if n >= 4 else 0.0
    else:
        skewness = 0.0
        excess_kurtosis = 0.0

    symmetry_flag = bool(abs(skewness) <= 1.0)
    if n < 6:
        rec = "paired_bootstrap"
    elif not symmetry_flag or frac_zero > 0.5:
        rec = "paired_bootstrap"
    elif math.isfinite(normality_p) and normality_p >= 0.05 and abs(excess_kurtosis) <= 2.0:
        rec = "paired_t_or_bootstrap"
    else:
        rec = "wilcoxon_or_paired_bootstrap"

    return {
        "n": n,
        "n_nonzero": n_nonzero,
        "frac_zero": frac_zero,
        "normality_p": normality_p,
        "skewness": skewness,
        "excess_kurtosis": excess_kurtosis,
        "symmetry_flag": symmetry_flag,
        "recommended_test": rec,
    }


def cohens_dz(
    a: np.ndarray | list[float],
    b: np.ndarray | list[float],
    n_boot: int = 2000,
    seed: int = 0,
) -> dict[str, float | int]:
    """Paired Cohen's ``d_z = mean(d) / sd(d)``, Hedges' ``g_z``, and 95% bootstrap CI."""
    a_arr = np.asarray(a, dtype=float)
    b_arr = np.asarray(b, dtype=float)
    if a_arr.shape != b_arr.shape:
        raise ValueError("paired arrays must have the same shape")
    if n_boot <= 0:
        raise ValueError("n_boot must be positive")
    d = a_arr - b_arr
    d = d[~np.isnan(d)]
    n = int(len(d))
    if n < 2:
        return {"d_z": float("nan"), "hedges_gz": float("nan"), "lo": float("nan"), "hi": float("nan"), "n": n}

    obs_mean = float(d.mean())
    obs_sd = float(d.std(ddof=1))
    if obs_sd == 0.0:
        return {
            "d_z": 0.0 if obs_mean == 0.0 else float("nan"),
            "hedges_gz": (0.0 if (obs_mean == 0.0 and n >= 3) else float("nan")),
            "lo": float("nan"),
            "hi": float("nan"),
            "n": n,
        }

    dz = obs_mean / obs_sd
    if n < 3:
        gz = float("nan")
    else:
        df = n - 1
        j_corr = 1.0 - 3.0 / (4.0 * df - 1.0)
        gz = dz * j_corr

    rng = np.random.default_rng(seed)
    boot_dz = np.empty(n_boot, dtype=float)
    for b0 in range(0, n_boot, 200):
        chunk = min(200, n_boot - b0)
        idx = rng.integers(0, n, size=(chunk, n))
        samp = d[idx]
        m = samp.mean(axis=1)
        s = samp.std(axis=1, ddof=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            vals = np.where(s > 0.0, m / s, np.where(m == 0.0, 0.0, np.nan))
        boot_dz[b0 : b0 + chunk] = vals
    valid_boot = boot_dz[np.isfinite(boot_dz)]
    if len(valid_boot) == 0:
        lo, hi = float("nan"), float("nan")
    else:
        lo, hi = (float(v) for v in np.percentile(valid_boot, [2.5, 97.5]))
    return {"d_z": float(dz), "hedges_gz": float(gz), "lo": lo, "hi": hi, "n": n}


def cliffs_delta(x: np.ndarray | list[float], y: np.ndarray | list[float]) -> float:
    """Unpaired non-parametric Cliff's delta in [-1, 1] using O((nx + ny) log ny) rank search."""
    x_arr = np.asarray(x, dtype=float)
    y_arr = np.asarray(y, dtype=float)
    x_arr = x_arr[~np.isnan(x_arr)]
    y_arr = y_arr[~np.isnan(y_arr)]
    if len(x_arr) == 0 or len(y_arr) == 0:
        return float("nan")
    y_sorted = np.sort(y_arr)
    less = np.searchsorted(y_sorted, x_arr, side="left")
    le = np.searchsorted(y_sorted, x_arr, side="right")
    greater = len(y_sorted) - le
    return float((less.sum() - greater.sum()) / (len(x_arr) * len(y_arr)))


def calibration_metrics(
    y_true: np.ndarray | list[int],
    probs: np.ndarray | list[float],
    n_bins: int = 10,
) -> dict[str, float | int | np.ndarray]:
    """Compute ECE (uniform), adaptive ECE (equal-mass), multiclass Brier, NLL, and bin arrays."""
    if n_bins < 1:
        raise ValueError("n_bins must be >= 1")
    y_raw = np.asarray(y_true, dtype=float)
    p_arr = np.asarray(probs, dtype=float)
    if p_arr.ndim == 1:
        p_arr = np.stack([1.0 - p_arr, p_arr], axis=1)
    if y_raw.ndim != 1 or p_arr.ndim != 2 or len(y_raw) != len(p_arr):
        raise ValueError("y_true and probs must have matching leading dimension")

    valid = np.isfinite(y_raw) & np.all(np.isfinite(p_arr), axis=1)
    y_valid_f = y_raw[valid]
    p_arr = p_arr[valid]
    n = int(len(y_valid_f))
    n_classes = p_arr.shape[1]
    if n == 0:
        edges = np.linspace(0.0, 1.0, n_bins + 1)
        return {
            "ece": float("nan"),
            "ece_adaptive": float("nan"),
            "brier": float("nan"),
            "nll": float("nan"),
            "n": 0,
            "n_bins": n_bins,
            "bin_edges": edges,
            "bin_counts": np.zeros(n_bins, dtype=int),
            "bin_conf": np.full(n_bins, np.nan),
            "bin_acc": np.full(n_bins, np.nan),
        }

    if np.any(y_valid_f != np.floor(y_valid_f)):
        raise ValueError("y_true labels must be integer class indices")
    y_arr = y_valid_f.astype(int)
    if np.any((y_arr < 0) | (y_arr >= n_classes)):
        raise ValueError("y_true labels out of range for probs shape")

    if np.any((p_arr < -1e-9) | (p_arr > 1.0 + 1e-9)):
        raise ValueError("probs must lie in [0.0, 1.0]")
    p_arr = np.clip(p_arr, 0.0, 1.0)

    p_clip = np.clip(p_arr, 1e-12, 1.0)
    nll = float(-np.mean(np.log(p_clip[np.arange(n), y_arr])))

    y_onehot = np.zeros_like(p_arr)
    y_onehot[np.arange(n), y_arr] = 1.0
    brier = float(np.mean(np.sum((p_arr - y_onehot) ** 2, axis=1)))

    conf = np.max(p_arr, axis=1)
    acc = (np.argmax(p_arr, axis=1) == y_arr).astype(float)

    edges = np.linspace(0.0, 1.0, n_bins + 1)
    bin_counts = np.zeros(n_bins, dtype=int)
    bin_conf = np.full(n_bins, np.nan)
    bin_acc = np.full(n_bins, np.nan)
    ece = 0.0
    for b in range(n_bins):
        lo_e, hi_e = edges[b], edges[b + 1]
        if b == n_bins - 1:
            mask = (conf >= lo_e) & (conf <= hi_e)
        else:
            mask = (conf >= lo_e) & (conf < hi_e)
        cnt = int(mask.sum())
        bin_counts[b] = cnt
        if cnt > 0:
            c_mean = float(conf[mask].mean())
            a_mean = float(acc[mask].mean())
            bin_conf[b] = c_mean
            bin_acc[b] = a_mean
            ece += (cnt / n) * abs(a_mean - c_mean)

    q_edges = np.quantile(conf, np.linspace(0.0, 1.0, n_bins + 1))
    a_edges = np.unique(q_edges)
    m_a = len(a_edges) - 1
    if m_a < 1:
        ece_adaptive = abs(float(acc.mean()) - float(conf.mean()))
    else:
        ece_adaptive = 0.0
        for b in range(m_a):
            if b == 0:
                mask_a = conf < a_edges[1] if m_a > 1 else np.ones(n, dtype=bool)
            elif b == m_a - 1:
                mask_a = conf >= a_edges[m_a - 1]
            else:
                mask_a = (conf >= a_edges[b]) & (conf < a_edges[b + 1])
            cnt_a = int(mask_a.sum())
            if cnt_a > 0:
                ece_adaptive += (cnt_a / n) * abs(float(acc[mask_a].mean()) - float(conf[mask_a].mean()))

    return {
        "ece": float(ece),
        "ece_adaptive": float(ece_adaptive),
        "brier": brier,
        "nll": nll,
        "n": n,
        "n_bins": n_bins,
        "bin_edges": edges,
        "bin_counts": bin_counts,
        "bin_conf": bin_conf,
        "bin_acc": bin_acc,
    }
