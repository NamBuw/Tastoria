"""Honest evaluation metrics & paired bootstrap comparisons for Meal Calorie models."""

from __future__ import annotations

import numpy as np

from tastoria_ml.calorie import TARGET_COLS


def compute_target_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    *,
    mape_min_true: float = 50.0,
) -> dict[str, float | int]:
    """Compute MAE, RMSE, R^2, MAPE (filtered ``y_true >= mape_min_true``), and Within-20%."""
    yt = np.asarray(y_true, dtype=np.float64)
    yp = np.asarray(y_pred, dtype=np.float64)
    if yt.shape != yp.shape or yt.ndim != 1:
        raise ValueError(f"Expected matching 1D arrays, got {yt.shape} vs {yp.shape}")
    if len(yt) == 0:
        raise ValueError("Cannot compute metrics on empty arrays")

    err = yp - yt
    abs_err = np.abs(err)
    mae = float(abs_err.mean())
    rmse = float(np.sqrt(np.mean(err ** 2)))
    ss_res = float(np.sum(err ** 2))
    ss_tot = float(np.sum((yt - yt.mean()) ** 2))
    r2 = float(1.0 - ss_res / ss_tot) if ss_tot > 0 else 0.0

    mask = yt >= mape_min_true
    if int(mask.sum()) > 0:
        rel_err = abs_err[mask] / yt[mask]
        mape = float(rel_err.mean())
        within_20pct = float((rel_err <= 0.20).mean())
        mape_n = int(mask.sum())
    else:
        mape = float("nan")
        within_20pct = float("nan")
        mape_n = 0

    return {
        "n": int(len(yt)),
        "mae": round(mae, 4),
        "rmse": round(rmse, 4),
        "r2": round(r2, 4),
        "mape_ge_thresh": round(mape, 4) if not np.isnan(mape) else None,
        "within_20pct_ge_thresh": round(within_20pct, 4) if not np.isnan(within_20pct) else None,
        "mape_min_true": float(mape_min_true),
        "mape_n": mape_n,
    }


def compute_all_target_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    *,
    targets: tuple[str, ...] = TARGET_COLS,
) -> dict[str, dict[str, float | int | None]]:
    yt = np.asarray(y_true, dtype=np.float64)
    yp = np.asarray(y_pred, dtype=np.float64)
    if yt.shape != yp.shape or yt.ndim != 2 or yt.shape[1] != len(targets):
        raise ValueError(f"Expected shape (N, {len(targets)}), got {yt.shape} and {yp.shape}")

    thresholds = {"kcal": 50.0, "mass_g": 50.0, "fat_g": 5.0, "carb_g": 5.0, "protein_g": 5.0}
    out: dict[str, dict[str, float | int | None]] = {}
    for j, name in enumerate(targets):
        out[name] = compute_target_metrics(yt[:, j], yp[:, j], mape_min_true=thresholds.get(name, 5.0))
    return out


def paired_bootstrap_mae(
    y_true: np.ndarray,
    pred_model: np.ndarray,
    pred_baseline: np.ndarray,
    *,
    n_boot: int = 2000,
    seed: int = 20261017,
) -> dict[str, float]:
    """Paired bootstrap of ``MAE(model) - MAE(baseline)`` (negative means model is better)."""
    yt = np.asarray(y_true, dtype=np.float64)
    pm = np.asarray(pred_model, dtype=np.float64)
    pb = np.asarray(pred_baseline, dtype=np.float64)
    err_m = np.abs(pm - yt)
    err_b = np.abs(pb - yt)
    diff = err_m - err_b  # negative = model beats baseline
    obs_delta = float(diff.mean())

    rng = np.random.default_rng(seed)
    n = len(diff)
    idx = rng.integers(0, n, size=(n_boot, n))
    boot_deltas = diff[idx].mean(axis=1)
    ci_lo, ci_hi = np.percentile(boot_deltas, [2.5, 97.5])
    # One-sided p-value: fraction of bootstrap samples where model is NOT better (delta >= 0)
    p_non_inferior = float((boot_deltas >= 0.0).mean())
    return {
        "mae_model": round(float(err_m.mean()), 4),
        "mae_baseline": round(float(err_b.mean()), 4),
        "delta_mae": round(obs_delta, 4),
        "ci95_low": round(float(ci_lo), 4),
        "ci95_high": round(float(ci_hi), 4),
        "p_model_worse_or_equal": round(p_non_inferior, 5),
        "n_boot": int(n_boot),
    }
