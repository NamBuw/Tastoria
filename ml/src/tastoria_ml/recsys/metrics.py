"""Ranking metrics.

Top-N on the full catalog (Food.com): for user u with held-out positives T_u and the top-K list L_u (already-seen
items removed, no sampled negatives — Krichene & Rendle 2020):
    HR@K     = 1[|L_u ∩ T_u| > 0]
    Recall@K = |L_u ∩ T_u| / |T_u|
    NDCG@K   = Σ_{j ≤ K} 1[L_u[j] ∈ T_u] / log2(j + 1)  /  Σ_{j ≤ min(K, |T_u|)} 1 / log2(j + 1)

Graded (survey): items of one user with true grades y (1–5), predicted scores s:
    NDCG@K with gain = y − 1 (a dish rated 1 adds nothing; review ml#1), ideal = gains sorted descending
    AUC_u = fraction of pairs (a, b) with y_a > y_b ranked s_a > s_b (ties in s count ½); pairs with y_a = y_b skipped
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import scipy.sparse as sp


def _discount(k: int) -> np.ndarray:
    return 1.0 / np.log2(np.arange(2, k + 2))


def topk_metrics(
    score_fn: Callable[[np.ndarray], np.ndarray],
    targets: dict[int, np.ndarray],
    seen: sp.csr_matrix,
    k: int = 10,
    batch: int = 1024,
    allowed: np.ndarray | None = None,
    return_top: bool = False,
) -> dict[str, np.ndarray]:
    """Per-user HR/Recall/NDCG@k. `score_fn(users)` → dense (len(users), n_items) scores.

    Items seen by the user before the cutoff get −inf. `allowed` (bool per item) restricts the catalog (models that
    cannot score some items, e.g. EASE on a capped catalog); targets outside it simply cannot be hit."""
    users = np.array(sorted(targets), dtype=np.int64)
    disc = _discount(k)
    hr = np.zeros(len(users))
    rec = np.zeros(len(users))
    ndcg = np.zeros(len(users))
    tops = np.zeros((len(users), k), dtype=np.int64) if return_top else None
    for b0 in range(0, len(users), batch):
        ub = users[b0 : b0 + batch]
        s = np.asarray(score_fn(ub), dtype=np.float32).copy()
        sub = seen[ub]
        rows = np.repeat(np.arange(len(ub)), np.diff(sub.indptr))
        s[rows, sub.indices] = -np.inf
        if allowed is not None:
            s[:, ~allowed] = -np.inf
        top = np.argpartition(-s, k, axis=1)[:, :k]
        order = np.argsort(-np.take_along_axis(s, top, axis=1), axis=1, kind="stable")
        top = np.take_along_axis(top, order, axis=1)
        if tops is not None:
            tops[b0 : b0 + len(ub)] = top
        for r, u in enumerate(ub):
            t = targets[int(u)]
            hits = np.isin(top[r], t)
            n_hit = hits.sum()
            j = b0 + r
            hr[j] = float(n_hit > 0)
            rec[j] = n_hit / len(t)
            ndcg[j] = (hits * disc).sum() / disc[: min(k, len(t))].sum()
    out = {"users": users, "hr": hr, "recall": rec, "ndcg": ndcg}
    if tops is not None:
        out["top"] = tops
    return out


def summarize(m: dict[str, np.ndarray], k: int = 10) -> dict[str, float]:
    return {f"{key}@{k}": float(np.mean(m[key])) for key in ("hr", "recall", "ndcg")} | {"n_users": int(len(m["users"]))}


def ndcg_graded(y: np.ndarray, s: np.ndarray, k: int = 5) -> float:
    """Graded NDCG@k with gain = y − 1; NaN when every gain is 0 (nothing to rank)."""
    y = np.asarray(y, dtype=float)
    s = np.asarray(s, dtype=float)
    gain = y - 1.0
    kk = min(k, len(y))
    disc = _discount(kk)
    ideal = (np.sort(gain)[::-1][:kk] * disc).sum()
    if ideal <= 0:
        return float("nan")
    order = _tie_random_order(s)[:kk]
    return float((gain[order] * disc).sum() / ideal)


def _tie_random_order(s: np.ndarray) -> np.ndarray:
    """Descending order of s with ties broken by a fixed random permutation (seed 0): a model that cannot separate
    items (all scores equal) gets a random-ranking NDCG instead of one favoured by the item order."""
    tie = np.random.default_rng(0).random(len(s))
    return np.lexsort((tie, -s))


def auc_pairs(y: np.ndarray, s: np.ndarray) -> float:
    """Per-user pairwise accuracy over pairs with different grades; NaN without such pairs."""
    y = np.asarray(y, dtype=float)
    s = np.asarray(s, dtype=float)
    dy = y[:, None] - y[None, :]
    ds = s[:, None] - s[None, :]
    mask = dy > 0
    n = mask.sum()
    if n == 0:
        return float("nan")
    return float(((ds > 0) & mask).sum() + 0.5 * ((ds == 0) & mask).sum()) / n
