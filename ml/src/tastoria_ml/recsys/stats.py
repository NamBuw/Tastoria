"""Paired comparisons used across the ML report.

- `paired_bootstrap(a, b)`: per-unit differences d = a − b (unit = user, scenario, query); B resamples of units
  with replacement; 95 % percentile CI of mean(d); two-sided p from the bootstrap distribution shifted to the null
  (p = P(|mean* − mean(d)| ≥ |mean(d)|)), floored at 1/(B+1).
- `holm(p)`: Holm–Bonferroni adjusted p-values (step-down, monotone).
- `wilcoxon(a, b)` and `mcnemar(a, b)` wrap SciPy (exact binomial McNemar on discordant pairs).
"""

from __future__ import annotations

import numpy as np
from scipy import stats as st


def paired_bootstrap(a: np.ndarray, b: np.ndarray, n_boot: int = 2000, seed: int = 0) -> dict[str, float]:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if a.shape != b.shape:
        raise ValueError("paired arrays must have the same shape")
    d = a - b
    d = d[~np.isnan(d)]
    n = len(d)
    if n == 0:
        return {"diff": float("nan"), "lo": float("nan"), "hi": float("nan"), "p": float("nan"), "n": 0}
    rng = np.random.default_rng(seed)
    means = np.empty(n_boot)
    for b0 in range(0, n_boot, 200):
        idx = rng.integers(0, n, size=(min(200, n_boot - b0), n))
        means[b0 : b0 + len(idx)] = d[idx].mean(axis=1)
    obs = d.mean()
    p = (np.sum(np.abs(means - obs) >= abs(obs)) + 1) / (n_boot + 1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return {"diff": float(obs), "lo": float(lo), "hi": float(hi), "p": float(min(1.0, p)), "n": int(n)}


def holm(p: list[float] | np.ndarray) -> np.ndarray:
    p = np.asarray(p, dtype=float)
    m = len(p)
    order = np.argsort(p)
    adj = np.empty(m)
    run = 0.0
    for rank, idx in enumerate(order):
        run = max(run, (m - rank) * p[idx])
        adj[idx] = min(1.0, run)
    return adj


def wilcoxon(a: np.ndarray, b: np.ndarray) -> dict[str, float]:
    d = np.asarray(a, float) - np.asarray(b, float)
    d = d[~np.isnan(d)]
    if np.all(d == 0) or len(d) == 0:
        return {"stat": float("nan"), "p": 1.0, "n_nonzero": 0}
    r = st.wilcoxon(d, zero_method="wilcox", alternative="two-sided")
    return {"stat": float(r.statistic), "p": float(r.pvalue), "n_nonzero": int((d != 0).sum())}


def mcnemar(a: np.ndarray, b: np.ndarray) -> dict[str, float]:
    """a, b boolean per unit. Exact two-sided binomial test on the discordant pairs."""
    a = np.asarray(a, bool)
    b = np.asarray(b, bool)
    n01 = int((~a & b).sum())
    n10 = int((a & ~b).sum())
    n = n01 + n10
    p = 1.0 if n == 0 else float(st.binomtest(n10, n, 0.5).pvalue)
    return {"a_only": n10, "b_only": n01, "p": p}


def mean_ci(x: np.ndarray, n_boot: int = 2000, seed: int = 0) -> tuple[float, float, float]:
    """Mean and 95 % bootstrap percentile CI over units."""
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(x), size=(n_boot, len(x)))
    m = x[idx].mean(axis=1)
    lo, hi = np.percentile(m, [2.5, 97.5])
    return float(x.mean()), float(lo), float(hi)
