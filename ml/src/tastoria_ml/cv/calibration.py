"""Pure NumPy/SciPy probability calibration, cluster bootstrap, and M3 abstention mapping.

Contains zero ``torch``, ``cv2``, or ``sklearn`` imports so it runs identically in both
``.venv`` (CPU tests / statistical analysis) and ``ml/runs/venv-cv`` (GPU training / ONNX).
"""

from __future__ import annotations

import math
from typing import Callable, Sequence

import numpy as np
from scipy import optimize
from scipy.special import log_softmax

from tastoria_ml import stats as mstats

DEFAULT_THRESHOLDS = (0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95)
URGENCY_WEIGHTS_4 = np.array([0.25, 0.65, 0.90, 1.20], dtype=np.float64)
TEMP_MIN = 1e-3
TEMP_MAX = 50.0


def _validate_logits_y(logits: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    z = np.asarray(logits, dtype=np.float64)
    y_arr = np.asarray(y, dtype=np.int64)
    if z.ndim != 2 or z.shape[0] < 1 or z.shape[1] < 2:
        raise ValueError(f"logits must be 2D (N>=1, C>=2), got {z.shape}")
    if y_arr.ndim != 1 or len(y_arr) != z.shape[0]:
        raise ValueError(f"y shape {y_arr.shape} does not match logits rows {z.shape[0]}")
    if not np.all(np.isfinite(z)):
        raise ValueError("logits contain non-finite values")
    if np.any((y_arr < 0) | (y_arr >= z.shape[1])):
        raise ValueError(f"y values must lie in [0, {z.shape[1] - 1}]")
    return z, y_arr


def softmax(logits: np.ndarray) -> np.ndarray:
    """Numerically stable softmax using float64 log-sum-exp."""
    z = np.asarray(logits, dtype=np.float64)
    if z.ndim not in (1, 2):
        raise ValueError(f"logits must be 1D or 2D, got ndim={z.ndim}")
    lsm = log_softmax(z, axis=-1)
    probs = np.exp(lsm)
    probs /= np.sum(probs, axis=-1, keepdims=True)
    return probs


def nll_from_logits(logits: np.ndarray, y: np.ndarray) -> float:
    """Cross-entropy negative log-likelihood from raw or calibrated logits."""
    z, y_arr = _validate_logits_y(logits, y)
    lsm = log_softmax(z, axis=1)
    return float(-np.mean(lsm[np.arange(len(y_arr)), y_arr]))


def fit_temperature(logits: np.ndarray, y: np.ndarray) -> float:
    """Fit scalar temperature T in [1e-3, 50.0] via L-BFGS-B minimizing cross-entropy NLL."""
    z, y_arr = _validate_logits_y(logits, y)
    n = len(y_arr)
    idx_rows = np.arange(n)
    bounds = [(math.log(TEMP_MIN), math.log(TEMP_MAX))]

    def obj_and_grad(params: np.ndarray) -> tuple[float, np.ndarray]:
        log_t = float(params[0])
        temp = math.exp(log_t)
        scaled = z / temp
        lsm = log_softmax(scaled, axis=1)
        loss = float(-np.mean(lsm[idx_rows, y_arr]))
        probs = np.exp(lsm)
        grad_log_t = float(np.mean(scaled[idx_rows, y_arr] - np.sum(probs * scaled, axis=1)))
        return loss, np.array([grad_log_t], dtype=np.float64)

    res = optimize.minimize(
        obj_and_grad,
        x0=np.array([0.0], dtype=np.float64),
        method="L-BFGS-B",
        jac=True,
        bounds=bounds,
        options={"ftol": 1e-12, "gtol": 1e-10, "maxiter": 500},
    )
    temp = math.exp(float(res.x[0]))
    return float(np.clip(temp, TEMP_MIN, TEMP_MAX))


def apply_temperature(logits: np.ndarray, T: float) -> np.ndarray:
    """Divide logits by positive temperature scalar T."""
    t_val = float(T)
    if not math.isfinite(t_val) or t_val <= 0.0:
        raise ValueError(f"temperature T must be finite and > 0, got {T}")
    return np.asarray(logits, dtype=np.float64) / t_val


def fit_vector_scaling(
    logits: np.ndarray,
    y: np.ndarray,
    l2: float = 1e-4,
) -> tuple[np.ndarray, np.ndarray]:
    """Fit diagonal vector scaling (w * logits + b, w > 0) with L2 regularization on (w-1) and b."""
    z, y_arr = _validate_logits_y(logits, y)
    n, c = z.shape
    y_oh = np.zeros((n, c), dtype=np.float64)
    y_oh[np.arange(n), y_arr] = 1.0
    l2_val = float(l2)
    if l2_val < 0.0:
        raise ValueError("l2 must be >= 0")

    bounds = [(math.log(TEMP_MIN), math.log(TEMP_MAX))] * c + [(-50.0, 50.0)] * c
    x0 = np.zeros(2 * c, dtype=np.float64)

    def obj_and_grad(params: np.ndarray) -> tuple[float, np.ndarray]:
        log_w = params[:c]
        b = params[c:]
        w = np.exp(log_w)
        scaled = z * w[None, :] + b[None, :]
        lsm = log_softmax(scaled, axis=1)
        nll = float(-np.mean(np.sum(y_oh * lsm, axis=1)))
        reg = l2_val * float(np.sum((w - 1.0) ** 2) + np.sum(b**2))

        probs = np.exp(lsm)
        diff = (probs - y_oh) / float(n)
        grad_w = np.sum(diff * z, axis=0) + 2.0 * l2_val * (w - 1.0)
        grad_log_w = grad_w * w
        grad_b = np.sum(diff, axis=0) + 2.0 * l2_val * b
        return nll + reg, np.concatenate([grad_log_w, grad_b])

    res = optimize.minimize(
        obj_and_grad,
        x0=x0,
        method="L-BFGS-B",
        jac=True,
        bounds=bounds,
        options={"ftol": 1e-12, "gtol": 1e-9, "maxiter": 1000},
    )
    w_hat = np.exp(res.x[:c]).astype(np.float64)
    b_hat = res.x[c:].astype(np.float64)
    return w_hat, b_hat


def apply_vector_scaling(logits: np.ndarray, w: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Apply diagonal vector scaling z * w + b."""
    z = np.asarray(logits, dtype=np.float64)
    w_arr = np.asarray(w, dtype=np.float64)
    b_arr = np.asarray(b, dtype=np.float64)
    return z * w_arr + b_arr


def fit_platt_matrix(
    logits: np.ndarray,
    y: np.ndarray,
    l2: float = 1e-3,
) -> tuple[np.ndarray, np.ndarray]:
    """Fit full matrix scaling (logits @ W.T + b) with L2 regularization toward (I, 0)."""
    z, y_arr = _validate_logits_y(logits, y)
    n, c = z.shape
    y_oh = np.zeros((n, c), dtype=np.float64)
    y_oh[np.arange(n), y_arr] = 1.0
    eye = np.eye(c, dtype=np.float64)
    l2_val = float(l2)
    if l2_val < 0.0:
        raise ValueError("l2 must be >= 0")

    x0 = np.concatenate([eye.ravel(), np.zeros(c, dtype=np.float64)])

    def obj_and_grad(params: np.ndarray) -> tuple[float, np.ndarray]:
        w_mat = params[: c * c].reshape(c, c)
        b = params[c * c :]
        scaled = z @ w_mat.T + b[None, :]
        lsm = log_softmax(scaled, axis=1)
        nll = float(-np.mean(np.sum(y_oh * lsm, axis=1)))
        reg = l2_val * float(np.sum((w_mat - eye) ** 2) + np.sum(b**2))

        probs = np.exp(lsm)
        diff = (probs - y_oh) / float(n)
        grad_w = diff.T @ z + 2.0 * l2_val * (w_mat - eye)
        grad_b = np.sum(diff, axis=0) + 2.0 * l2_val * b
        return nll + reg, np.concatenate([grad_w.ravel(), grad_b])

    res = optimize.minimize(
        obj_and_grad,
        x0=x0,
        method="L-BFGS-B",
        jac=True,
        options={"ftol": 1e-12, "gtol": 1e-9, "maxiter": 1000},
    )
    w_hat = res.x[: c * c].reshape(c, c).astype(np.float64)
    b_hat = res.x[c * c :].astype(np.float64)
    return w_hat, b_hat


def apply_platt_matrix(logits: np.ndarray, W: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Apply full matrix scaling logits @ W.T + b."""
    z = np.asarray(logits, dtype=np.float64)
    w_mat = np.asarray(W, dtype=np.float64)
    b_arr = np.asarray(b, dtype=np.float64)
    return z @ w_mat.T + b_arr


def fit_and_apply_fold_calibration(
    cal_logits_per_fold: Sequence[np.ndarray],
    cal_y_per_fold: Sequence[np.ndarray],
    test_logits_per_fold: Sequence[np.ndarray],
    test_indices_per_fold: Sequence[np.ndarray],
    n_samples: int | None = None,
    method: str = "temperature",
    l2: float | None = None,
) -> dict:
    """Strictly fit calibration on each fold's cal_k logits and apply to that fold's te_k logits."""
    n_folds = len(test_indices_per_fold)
    if not (len(cal_logits_per_fold) == len(cal_y_per_fold) == len(test_logits_per_fold) == n_folds):
        raise ValueError("All per-fold sequences must have the same length")
    if n_folds == 0:
        raise ValueError("Must supply at least one fold")

    te_concat = np.concatenate([np.asarray(idx, dtype=np.int64) for idx in test_indices_per_fold])
    if n_samples is None:
        n_samples = int(te_concat.max()) + 1 if len(te_concat) else 0
    if len(te_concat) != len(np.unique(te_concat)):
        raise ValueError("Duplicate indices detected across test_indices_per_fold")
    if len(te_concat) != n_samples or set(te_concat.tolist()) != set(range(n_samples)):
        raise ValueError("test_indices_per_fold must form a disjoint partition of 0..n_samples-1")

    n_classes = int(np.asarray(test_logits_per_fold[0]).shape[1])
    cal_oof_logits = np.empty((n_samples, n_classes), dtype=np.float64)
    fold_params: list[dict] = []

    for k in range(n_folds):
        z_cal = np.asarray(cal_logits_per_fold[k], dtype=np.float64)
        y_cal = np.asarray(cal_y_per_fold[k], dtype=np.int64)
        z_te = np.asarray(test_logits_per_fold[k], dtype=np.float64)
        te_idx = np.asarray(test_indices_per_fold[k], dtype=np.int64)
        if z_te.shape[0] != len(te_idx):
            raise ValueError(f"Fold {k}: test logits rows {z_te.shape[0]} != test indices {len(te_idx)}")

        if method == "temperature":
            temp = fit_temperature(z_cal, y_cal)
            z_out = apply_temperature(z_te, temp)
            fold_params.append({"fold": k, "temperature": float(temp), "n_cal": int(len(y_cal)), "n_test": int(len(te_idx))})
        elif method == "vector":
            reg = 1e-4 if l2 is None else float(l2)
            w, b = fit_vector_scaling(z_cal, y_cal, l2=reg)
            z_out = apply_vector_scaling(z_te, w, b)
            fold_params.append({
                "fold": k,
                "w": w.tolist(),
                "b": b.tolist(),
                "l2": reg,
                "n_cal": int(len(y_cal)),
                "n_test": int(len(te_idx)),
            })
        elif method == "platt":
            reg = 1e-3 if l2 is None else float(l2)
            w_mat, b = fit_platt_matrix(z_cal, y_cal, l2=reg)
            z_out = apply_platt_matrix(z_te, w_mat, b)
            fold_params.append({
                "fold": k,
                "W": w_mat.tolist(),
                "b": b.tolist(),
                "l2": reg,
                "n_cal": int(len(y_cal)),
                "n_test": int(len(te_idx)),
            })
        else:
            raise ValueError(f"Unsupported calibration method: {method!r}")

        cal_oof_logits[te_idx] = z_out

    return {
        "method": method,
        "cal_logits": cal_oof_logits,
        "cal_probs": softmax(cal_oof_logits),
        "fold_params": fold_params,
    }


def nested_oof_calibrate(
    raw_logits: np.ndarray,
    y: np.ndarray,
    fit_cal_pairs: Sequence,
    test_indices_per_fold: Sequence[np.ndarray],
    method: str = "temperature",
    l2: float | None = None,
) -> dict:
    """Nested OOF calibration supporting either per-fold ``(cal_logits, cal_y)`` or index pairs.

    ``fit_cal_pairs`` may be a sequence of:
      1. ``(cal_logits_k, cal_y_k)`` where ``cal_logits_k`` is a 2D float array of shape ``(M, C)``,
      2. ``(fit_idx_k, cal_idx_k)`` of 1D integer index arrays into ``raw_logits`` and ``y``, or
      3. ``cal_idx_k`` (1D integer index array into ``raw_logits`` and ``y``).
    """
    z_raw, y_arr = _validate_logits_y(raw_logits, y)
    n_samples = z_raw.shape[0]
    n_folds = len(test_indices_per_fold)
    if len(fit_cal_pairs) != n_folds:
        raise ValueError("fit_cal_pairs and test_indices_per_fold must have equal length")

    cal_logits_list: list[np.ndarray] = []
    cal_y_list: list[np.ndarray] = []
    test_logits_list: list[np.ndarray] = []

    for k in range(n_folds):
        te_idx = np.asarray(test_indices_per_fold[k], dtype=np.int64)
        te_set = set(te_idx.tolist())
        item = fit_cal_pairs[k]

        if isinstance(item, tuple) and len(item) == 2 and np.asarray(item[0]).ndim == 2:
            cal_z_k = np.asarray(item[0], dtype=np.float64)
            cal_y_k = np.asarray(item[1], dtype=np.int64)
        else:
            if isinstance(item, tuple) and len(item) == 2:
                fit_idx = np.asarray(item[0], dtype=np.int64)
                cal_idx = np.asarray(item[1], dtype=np.int64)
                if not set(fit_idx.tolist()).isdisjoint(cal_idx.tolist()):
                    raise ValueError(f"Fold {k}: fit_idx overlaps cal_idx")
                if not set(fit_idx.tolist()).isdisjoint(te_set):
                    raise ValueError(f"Fold {k}: fit_idx overlaps te_idx")
            else:
                cal_idx = np.asarray(item, dtype=np.int64)
            if not set(cal_idx.tolist()).isdisjoint(te_set):
                raise ValueError(f"Fold {k}: cal_idx overlaps te_idx (leakage!)")
            cal_z_k = z_raw[cal_idx]
            cal_y_k = y_arr[cal_idx]

        cal_logits_list.append(cal_z_k)
        cal_y_list.append(cal_y_k)
        test_logits_list.append(z_raw[te_idx])

    return fit_and_apply_fold_calibration(
        cal_logits_per_fold=cal_logits_list,
        cal_y_per_fold=cal_y_list,
        test_logits_per_fold=test_logits_list,
        test_indices_per_fold=test_indices_per_fold,
        n_samples=n_samples,
        method=method,
        l2=l2,
    )


def _confusion_matrix_np(y_true: np.ndarray, y_pred: np.ndarray, n_classes: int = 3) -> np.ndarray:
    y_t = np.asarray(y_true, dtype=np.int64)
    y_p = np.asarray(y_pred, dtype=np.int64)
    if len(y_t) == 0:
        return np.zeros((n_classes, n_classes), dtype=np.int64)
    flat = y_t * n_classes + y_p
    return np.bincount(flat, minlength=n_classes * n_classes).reshape(n_classes, n_classes)


def _macro_f1_from_cm(cm: np.ndarray) -> float:
    tp = np.diag(cm).astype(np.float64)
    fp = cm.sum(axis=0).astype(np.float64) - tp
    fn = cm.sum(axis=1).astype(np.float64) - tp
    denom = 2.0 * tp + fp + fn
    f1 = np.where(denom > 0.0, 2.0 * tp / np.where(denom > 0.0, denom, 1.0), 0.0)
    return float(np.mean(f1))


def _qwk_from_cm(cm: np.ndarray) -> float:
    n_classes = cm.shape[0]
    total = float(cm.sum())
    if total <= 0.0 or n_classes < 2:
        return 0.0
    hist_t = cm.sum(axis=1).astype(np.float64)
    hist_p = cm.sum(axis=0).astype(np.float64)
    expected = np.outer(hist_t, hist_p) / total
    idx = np.arange(n_classes, dtype=np.float64)
    weights = ((idx[:, None] - idx[None, :]) ** 2) / float((n_classes - 1) ** 2)
    num = float(np.sum(weights * cm))
    den = float(np.sum(weights * expected))
    if den <= 0.0:
        return 0.0
    return float(1.0 - num / den)


def macro_f1(y_true: np.ndarray, y_pred: np.ndarray, n_classes: int = 3) -> float:
    """Pure NumPy macro-averaged F1 across classes ``0..n_classes-1``."""
    return _macro_f1_from_cm(_confusion_matrix_np(y_true, y_pred, n_classes=n_classes))


def qwk(y_true: np.ndarray, y_pred: np.ndarray, n_classes: int = 3) -> float:
    """Pure NumPy Quadratic Weighted Kappa across ordinal classes ``0..n_classes-1``."""
    return _qwk_from_cm(_confusion_matrix_np(y_true, y_pred, n_classes=n_classes))


def accuracy(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Classification accuracy."""
    y_t = np.asarray(y_true, dtype=np.int64)
    y_p = np.asarray(y_pred, dtype=np.int64)
    return float(np.mean(y_t == y_p)) if len(y_t) else float("nan")


def mae_level(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Mean absolute ordinal level error."""
    y_t = np.asarray(y_true, dtype=np.float64)
    y_p = np.asarray(y_pred, dtype=np.float64)
    return float(np.mean(np.abs(y_t - y_p))) if len(y_t) else float("nan")


def cluster_bootstrap_single(
    y_true: np.ndarray,
    pred_or_probs: np.ndarray,
    clusters: np.ndarray,
    metric_fn: Callable[[np.ndarray, np.ndarray], float],
    n_boot: int = 2000,
    seed: int = 0,
) -> dict[str, float | int]:
    """Single-arm cluster-level bootstrap for non-linear corpus metrics (Macro-F1, QWK, ECE)."""
    if n_boot <= 0:
        raise ValueError("n_boot must be positive")
    y_arr = np.asarray(y_true)
    p_arr = np.asarray(pred_or_probs)
    cl_arr = np.asarray(clusters)
    if len(y_arr) != len(p_arr) or len(y_arr) != len(cl_arr):
        raise ValueError("y_true, pred_or_probs, and clusters must have matching length")
    n = int(len(y_arr))
    if n == 0:
        return {"point": float("nan"), "lo": float("nan"), "hi": float("nan"), "sd_boot": float("nan"), "n": 0, "n_clusters": 0, "n_boot": n_boot}

    obs = float(metric_fn(y_arr, p_arr))
    _, inv = np.unique(cl_arr, return_inverse=True)
    k = int(inv.max()) + 1
    if k < 2:
        return {"point": obs, "lo": obs, "hi": obs, "sd_boot": float("nan"), "n": n, "n_clusters": k, "n_boot": n_boot}

    members = [np.where(inv == i)[0] for i in range(k)]
    rng = np.random.default_rng(seed)
    vals = np.empty(n_boot, dtype=np.float64)
    for b in range(n_boot):
        c_idx = rng.integers(0, k, size=k)
        idx = np.concatenate([members[i] for i in c_idx])
        vals[b] = float(metric_fn(y_arr[idx], p_arr[idx]))

    valid = vals[np.isfinite(vals)]
    if len(valid) == 0:
        lo, hi, sd = float("nan"), float("nan"), float("nan")
    else:
        lo, hi = (float(v) for v in np.percentile(valid, [2.5, 97.5]))
        sd = float(np.std(valid, ddof=1)) if len(valid) > 1 else 0.0
    return {
        "point": obs,
        "lo": lo,
        "hi": hi,
        "sd_boot": sd,
        "n": n,
        "n_clusters": k,
        "n_boot": int(n_boot),
    }


def cluster_bootstrap_metric(
    y_true: np.ndarray,
    pred_or_probs_a: np.ndarray,
    pred_or_probs_b: np.ndarray,
    clusters: np.ndarray,
    metric_fn: Callable[[np.ndarray, np.ndarray], float],
    n_boot: int = 2000,
    seed: int = 0,
) -> dict[str, float | int]:
    """Paired cluster-level bootstrap comparing ``metric_fn(a) - metric_fn(b)`` across ``clusters``."""
    if n_boot <= 0:
        raise ValueError("n_boot must be positive")
    y_arr = np.asarray(y_true)
    a_arr = np.asarray(pred_or_probs_a)
    b_arr = np.asarray(pred_or_probs_b)
    cl_arr = np.asarray(clusters)
    if not (len(y_arr) == len(a_arr) == len(b_arr) == len(cl_arr)):
        raise ValueError("All arrays must have matching leading dimension")
    n = int(len(y_arr))
    if n == 0:
        return {
            "obs_a": float("nan"),
            "obs_b": float("nan"),
            "diff": float("nan"),
            "lo": float("nan"),
            "hi": float("nan"),
            "p": float("nan"),
            "n": 0,
            "n_clusters": 0,
            "n_boot": int(n_boot),
        }

    obs_a = float(metric_fn(y_arr, a_arr))
    obs_b = float(metric_fn(y_arr, b_arr))
    obs_diff = obs_a - obs_b

    _, inv = np.unique(cl_arr, return_inverse=True)
    k = int(inv.max()) + 1
    if n < 2 or k < 2:
        return {
            "obs_a": obs_a,
            "obs_b": obs_b,
            "diff": obs_diff,
            "lo": obs_diff,
            "hi": obs_diff,
            "p": float("nan"),
            "n": n,
            "n_clusters": k,
            "n_boot": int(n_boot),
        }

    members = [np.where(inv == i)[0] for i in range(k)]
    rng = np.random.default_rng(seed)
    boot_diffs = np.empty(n_boot, dtype=np.float64)
    for b in range(n_boot):
        c_idx = rng.integers(0, k, size=k)
        idx = np.concatenate([members[i] for i in c_idx])
        boot_diffs[b] = float(metric_fn(y_arr[idx], a_arr[idx])) - float(metric_fn(y_arr[idx], b_arr[idx]))

    valid = boot_diffs[np.isfinite(boot_diffs)]
    if len(valid) == 0:
        return {
            "obs_a": obs_a,
            "obs_b": obs_b,
            "diff": obs_diff,
            "lo": float("nan"),
            "hi": float("nan"),
            "p": float("nan"),
            "n": n,
            "n_clusters": k,
            "n_boot": int(n_boot),
        }

    lo, hi = (float(v) for v in np.percentile(valid, [2.5, 97.5]))
    p_val = min(1.0, (float(np.sum(np.abs(valid - obs_diff) >= abs(obs_diff))) + 1.0) / (len(valid) + 1.0))
    return {
        "obs_a": obs_a,
        "obs_b": obs_b,
        "diff": obs_diff,
        "lo": lo,
        "hi": hi,
        "p": float(p_val),
        "n": n,
        "n_clusters": k,
        "n_boot": int(n_boot),
    }


def map_to_four_class_probs(probs3: np.ndarray, tau: float) -> np.ndarray:
    """Map calibrated 3-class probs ``(tuoi, dung_som, dung_ngay)`` to 4-class backend schema with ``kiem_tra``.

    Implements the M3 Hard Abstention Gate:
      - ``if max(q) < tau -> (0.0, 0.0, 0.0, 1.0)``
      - ``else -> (q0 / s, q1 / s, q2 / s, 0.0)``
    """
    tau_val = float(tau)
    if not (0.0 <= tau_val <= 1.0):
        raise ValueError(f"tau must lie in [0, 1], got {tau}")
    q = np.asarray(probs3, dtype=np.float64)
    squeeze = False
    if q.ndim == 1:
        if q.shape[0] != 3:
            raise ValueError(f"Expected 3-class probabilities, got shape {q.shape}")
        q = q[None, :]
        squeeze = True
    elif q.ndim != 2 or q.shape[1] != 3:
        raise ValueError(f"Expected shape (N, 3) or (3,), got {q.shape}")

    q = np.clip(q, 0.0, 1.0)
    sums = np.sum(q, axis=1, keepdims=True)
    q_norm = np.where(sums > 0.0, q / np.where(sums > 0.0, sums, 1.0), np.full_like(q, 1.0 / 3.0))
    max_q = np.max(q_norm, axis=1)
    abstain = max_q < tau_val

    out = np.zeros((len(q_norm), 4), dtype=np.float64)
    out[~abstain, :3] = q_norm[~abstain]
    out[abstain, 3] = 1.0
    return out[0] if squeeze else out


def compute_u_img(probs4: np.ndarray) -> np.ndarray:
    """Compute backend urgency score ``u_img`` from 4-class probabilities."""
    p = np.asarray(probs4, dtype=np.float64)
    return p @ URGENCY_WEIGHTS_4


def _confidence_scores(probs3: np.ndarray, score_type: str) -> np.ndarray:
    p = np.clip(np.asarray(probs3, dtype=np.float64), 0.0, 1.0)
    sums = np.sum(p, axis=1, keepdims=True)
    p = np.where(sums > 0.0, p / np.where(sums > 0.0, sums, 1.0), 1.0 / p.shape[1])
    if score_type == "max_prob":
        return np.max(p, axis=1)
    if score_type == "entropy":
        p_clip = np.clip(p, 1e-12, 1.0)
        ent = -np.sum(p_clip * np.log(p_clip), axis=1) / math.log(p.shape[1])
        return np.clip(1.0 - ent, 0.0, 1.0)
    raise ValueError(f"score_type must be 'max_prob' or 'entropy', got {score_type!r}")


def _selective_stratum_curve(
    probs3: np.ndarray,
    y: np.ndarray,
    clusters: np.ndarray,
    thresholds: Sequence[float],
    score_type: str,
    n_boot: int,
    seed: int,
) -> dict:
    p = np.asarray(probs3, dtype=np.float64)
    y_arr = np.asarray(y, dtype=np.int64)
    cl_arr = np.asarray(clusters)
    n = int(len(y_arr))
    n_classes = int(p.shape[1])
    scores = _confidence_scores(p, score_type)
    y_hat = np.argmax(p, axis=1)
    err = (y_hat != y_arr).astype(np.float64)
    sev = (np.abs(y_hat - y_arr) == 2).astype(np.float64)

    _, inv = np.unique(cl_arr, return_inverse=True)
    k = int(inv.max()) + 1
    rng = np.random.default_rng(seed)
    boot_c_idx = rng.integers(0, k, size=(n_boot, k)) if k >= 2 else None

    c_tot_cnt = np.bincount(inv, minlength=k).astype(np.float64)
    c_tot_err = np.bincount(inv, weights=err, minlength=k).astype(np.float64)
    full_err = float(err.mean())
    if boot_c_idx is not None:
        boot_tot_cnt = c_tot_cnt[boot_c_idx].sum(axis=1)
        boot_full_err = c_tot_err[boot_c_idx].sum(axis=1) / boot_tot_cnt
    else:
        boot_tot_cnt = None
        boot_full_err = None

    points: list[dict] = []
    raw_pvals: list[float] = []

    # Precompute cluster-level confusion matrices for each tau cleanly via bincount
    for tau in thresholds:
        tau_f = float(tau)
        acc_mask = scores >= tau_f
        n_acc = int(acc_mask.sum())
        cov = float(n_acc / n) if n > 0 else float("nan")
        abst = 1.0 - cov if math.isfinite(cov) else float("nan")

        if n_acc == 0:
            points.append({
                "tau": tau_f,
                "n_total": n,
                "n_accepted": 0,
                "coverage": 0.0,
                "coverage_ci95": [0.0, 0.0],
                "abstention_rate": 1.0,
                "selective_error": float("nan"),
                "selective_error_ci95": [float("nan"), float("nan")],
                "severe_error_rate": float("nan"),
                "severe_error_rate_ci95": [float("nan"), float("nan")],
                "selective_macro_f1": float("nan"),
                "selective_macro_f1_ci95": [float("nan"), float("nan")],
                "selective_qwk": float("nan"),
                "selective_qwk_ci95": [float("nan"), float("nan")],
                "error_diff_vs_full": float("nan"),
                "error_diff_ci95": [float("nan"), float("nan")],
                "p_error_vs_full": float("nan"),
            })
            raw_pvals.append(float("nan"))
            continue

        sel_err = float(err[acc_mask].mean())
        sel_sev = float(sev[acc_mask].mean())
        cm_obs = _confusion_matrix_np(y_arr[acc_mask], y_hat[acc_mask], n_classes=n_classes)
        sel_f1 = _macro_f1_from_cm(cm_obs)
        sel_qwk = _qwk_from_cm(cm_obs)
        err_diff = sel_err - full_err

        if boot_c_idx is not None:
            c_acc_cnt = np.bincount(inv[acc_mask], minlength=k).astype(np.float64)
            c_acc_err = np.bincount(inv[acc_mask], weights=err[acc_mask], minlength=k).astype(np.float64)
            c_acc_sev = np.bincount(inv[acc_mask], weights=sev[acc_mask], minlength=k).astype(np.float64)

            # Cluster-level confusion matrices shape (k, C*C)
            flat_acc = y_arr[acc_mask] * n_classes + y_hat[acc_mask]
            c_cm = np.zeros((k, n_classes * n_classes), dtype=np.int64)
            np.add.at(c_cm, (inv[acc_mask], flat_acc), 1)

            b_acc_cnt = c_acc_cnt[boot_c_idx].sum(axis=1)
            b_cov = b_acc_cnt / boot_tot_cnt
            cov_ci = [float(v) for v in np.percentile(b_cov, [2.5, 97.5])]

            valid_b = b_acc_cnt > 0
            b_err = np.where(valid_b, c_acc_err[boot_c_idx].sum(axis=1) / np.where(valid_b, b_acc_cnt, 1.0), np.nan)
            b_sev = np.where(valid_b, c_acc_sev[boot_c_idx].sum(axis=1) / np.where(valid_b, b_acc_cnt, 1.0), np.nan)
            b_diff = b_err - boot_full_err

            valid_err = b_err[np.isfinite(b_err)]
            err_ci = [float(v) for v in np.percentile(valid_err, [2.5, 97.5])] if len(valid_err) else [float("nan"), float("nan")]
            valid_sev = b_sev[np.isfinite(b_sev)]
            sev_ci = [float(v) for v in np.percentile(valid_sev, [2.5, 97.5])] if len(valid_sev) else [float("nan"), float("nan")]
            valid_diff = b_diff[np.isfinite(b_diff)]
            if len(valid_diff):
                diff_ci = [float(v) for v in np.percentile(valid_diff, [2.5, 97.5])]
                p_err = min(1.0, (float(np.sum(np.abs(valid_diff - err_diff) >= abs(err_diff))) + 1.0) / (len(valid_diff) + 1.0))
            else:
                diff_ci = [float("nan"), float("nan")]
                p_err = float("nan")

            b_cm = c_cm[boot_c_idx].sum(axis=1).reshape(n_boot, n_classes, n_classes)
            b_f1 = np.array([_macro_f1_from_cm(b_cm[i]) for i in range(n_boot)], dtype=np.float64)
            b_qwk = np.array([_qwk_from_cm(b_cm[i]) for i in range(n_boot)], dtype=np.float64)
            f1_ci = [float(v) for v in np.percentile(b_f1, [2.5, 97.5])]
            qwk_ci = [float(v) for v in np.percentile(b_qwk, [2.5, 97.5])]
        else:
            cov_ci = [cov, cov]
            err_ci = [sel_err, sel_err]
            sev_ci = [sel_sev, sel_sev]
            diff_ci = [err_diff, err_diff]
            f1_ci = [sel_f1, sel_f1]
            qwk_ci = [sel_qwk, sel_qwk]
            p_err = float("nan")

        raw_pvals.append(float(p_err))
        points.append({
            "tau": tau_f,
            "n_total": n,
            "n_accepted": n_acc,
            "coverage": cov,
            "coverage_ci95": cov_ci,
            "abstention_rate": abst,
            "selective_error": sel_err,
            "selective_error_ci95": err_ci,
            "severe_error_rate": sel_sev,
            "severe_error_rate_ci95": sev_ci,
            "selective_macro_f1": sel_f1,
            "selective_macro_f1_ci95": f1_ci,
            "selective_qwk": sel_qwk,
            "selective_qwk_ci95": qwk_ci,
            "error_diff_vs_full": err_diff,
            "error_diff_ci95": diff_ci,
            "p_error_vs_full": float(p_err),
        })

    q_vals = mstats.bh_fdr(raw_pvals)
    for pt, q_val in zip(points, q_vals, strict=True):
        pt["q_bh_error_vs_full"] = float(q_val) if math.isfinite(float(q_val)) else float("nan")

    # AURC over valid points (anchor at coverage=0 -> risk=0 if needed, or trapezoid over observed points)
    def _aurc_from_pts(covs: np.ndarray, risks: np.ndarray) -> float:
        ok = np.isfinite(covs) & np.isfinite(risks) & (covs > 0.0)
        if not np.any(ok):
            return float("nan")
        c_v = covs[ok]
        r_v = risks[ok]
        order = np.argsort(c_v)
        c_s = np.r_[0.0, c_v[order]]
        r_s = np.r_[0.0, r_v[order]]
        _trapz = getattr(np, "trapezoid", None) or getattr(np, "trapz")
        return float(_trapz(r_s, c_s))

    obs_covs = np.array([pt["coverage"] for pt in points], dtype=np.float64)
    obs_risks = np.array([pt["selective_error"] for pt in points], dtype=np.float64)
    aurc_obs = _aurc_from_pts(obs_covs, obs_risks)

    if boot_c_idx is not None:
        b_covs = np.empty((n_boot, len(thresholds)), dtype=np.float64)
        b_risks = np.empty((n_boot, len(thresholds)), dtype=np.float64)
        for j, tau in enumerate(thresholds):
            acc_mask = scores >= float(tau)
            c_acc_cnt = np.bincount(inv[acc_mask], minlength=k).astype(np.float64) if np.any(acc_mask) else np.zeros(k)
            c_acc_err = np.bincount(inv[acc_mask], weights=err[acc_mask], minlength=k).astype(np.float64) if np.any(acc_mask) else np.zeros(k)
            b_cnt = c_acc_cnt[boot_c_idx].sum(axis=1)
            b_covs[:, j] = b_cnt / boot_tot_cnt
            valid_b = b_cnt > 0
            b_risks[:, j] = np.where(valid_b, c_acc_err[boot_c_idx].sum(axis=1) / np.where(valid_b, b_cnt, 1.0), np.nan)
        b_aurc = np.array([_aurc_from_pts(b_covs[i], b_risks[i]) for i in range(n_boot)], dtype=np.float64)
        valid_aurc = b_aurc[np.isfinite(b_aurc)]
        aurc_ci = [float(v) for v in np.percentile(valid_aurc, [2.5, 97.5])] if len(valid_aurc) else [float("nan"), float("nan")]
    else:
        aurc_ci = [aurc_obs, aurc_obs]

    return {
        "score_type": score_type,
        "n_samples": n,
        "n_clusters": k,
        "full_error": full_err,
        "full_severe_error": float(sev.mean()) if n > 0 else float("nan"),
        "aurc": aurc_obs,
        "aurc_ci95": aurc_ci,
        "points": points,
    }


def selective_abstention_curve(
    probs3: np.ndarray,
    y: np.ndarray,
    clusters: np.ndarray,
    thresholds: Sequence[float] | None = None,
    score_type: str = "max_prob",
    n_boot: int = 2000,
    seed: int = 0,
    dataset_labels: np.ndarray | None = None,
) -> dict:
    """Sweep confidence thresholds ``tau`` mapping low-confidence samples to ``kiem_tra``.

    Computes coverage, abstention rate, selective error rate, severe 2-level error rate,
    selective Macro-F1, selective QWK, AURC with cluster-bootstrap 95% CIs, and ``bh_fdr``
    adjusted p-values across operating points (overall + optional dataset stratification).
    """
    p = np.asarray(probs3, dtype=np.float64)
    y_arr = np.asarray(y, dtype=np.int64)
    cl_arr = np.asarray(clusters)
    if p.ndim != 2 or len(p) != len(y_arr) or len(p) != len(cl_arr):
        raise ValueError("probs3, y, and clusters must have matching leading dimension")
    thresh = list(DEFAULT_THRESHOLDS if thresholds is None else thresholds)
    if len(thresh) == 0:
        raise ValueError("thresholds must be non-empty")

    overall = _selective_stratum_curve(p, y_arr, cl_arr, thresh, score_type=score_type, n_boot=n_boot, seed=seed)
    out = {
        "analysis_intent": "exploratory",
        "score_type": score_type,
        "thresholds": [float(t) for t in thresh],
        "overall": overall,
        "by_dataset": {},
    }
    if dataset_labels is not None:
        ds_arr = np.asarray(dataset_labels)
        if len(ds_arr) != len(y_arr):
            raise ValueError("dataset_labels must have same length as y")
        for idx_ds, ds in enumerate(sorted(set(ds_arr.tolist()))):
            mask = ds_arr == ds
            out["by_dataset"][str(ds)] = _selective_stratum_curve(
                p[mask],
                y_arr[mask],
                cl_arr[mask],
                thresh,
                score_type=score_type,
                n_boot=n_boot,
                seed=seed + 100 + idx_ds,
            )
    return out
