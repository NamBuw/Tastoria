"""Taste ranking ŝ(u, r) and its per-user, per-slot percentile ŝ' (design v2 §6.1, "Phục vụ").

`Ranker` is the plug point for the trained models of the ML report (biased MF, LightFM, LambdaMART exported to NumPy
and registered in mlops). Until one is deployed, `BaselineRanker` serves BR-CONSENT-03's fallback for everyone:

    ŝ = 0.5 · popularity_r + 0.5 · content_r (+ 0.25 · own_r with a personalization consent)

  * popularity_r — shrunk item average of the interactions of all consenting users:
                   (positive + k·½) / (positive + negative + k), k = 5; positive = liked + cooked,
                   negative = disliked + swapped as "không hợp gu" (BR-SWAP-01);
  * content_r    — cosine between the recipe vector and the mean vector of the user's 5 favourite dishes
                   (features: main/side non-staple ingredients, cooking method, tags; design v2 §6.1 bậc 3);
  * own_r        — the user's own signal on the recipe in [−1, 1], read only with a current consent (FR-15-17).

ŝ carries taste only: no stock, urgency or energy signal (those live in the composer objective).
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from tastoria.modules.catalog.schemas import RecipeView
from tastoria.modules.events.schemas import RecipeSignal

SHRINK_K = 5.0


@dataclass(frozen=True)
class RankContext:
    user_id: uuid.UUID
    favorites: Sequence[RecipeView]
    popularity: dict[uuid.UUID, RecipeSignal] = field(default_factory=dict)
    personal: dict[uuid.UUID, RecipeSignal] | None = None  # None without a personalization consent


class Ranker(Protocol):
    version_id: uuid.UUID | None  # model_versions.id of the deployed ranker; None for the baseline

    def score(self, ctx: RankContext, recipes: Sequence[RecipeView]) -> dict[uuid.UUID, float]: ...


def features(r: RecipeView) -> dict[str, float]:
    f = {f"ing:{ln.ingredient.id}": 1.0 for ln in r.lines if ln.role != "seasoning" and not ln.ingredient.is_staple}
    f[f"method:{r.method_code}"] = 1.0
    f.update({f"tag:{t}": 0.5 for t in r.tag_codes})
    return f


def _cos(a: dict[str, float], b: dict[str, float]) -> float:
    dot = sum(v * b.get(k, 0.0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def _profile(favs: Iterable[RecipeView]) -> dict[str, float]:
    favs = list(favs)
    acc: dict[str, float] = {}
    for r in favs:
        for k, v in features(r).items():
            acc[k] = acc.get(k, 0.0) + v / len(favs)
    return acc


def _shrunk(sig: RecipeSignal | None) -> float:
    pos, neg = (sig.positive, sig.negative) if sig else (0, 0)
    return (pos + SHRINK_K * 0.5) / (pos + neg + SHRINK_K)


class BaselineRanker:
    version_id: uuid.UUID | None = None

    def score(self, ctx: RankContext, recipes: Sequence[RecipeView]) -> dict[uuid.UUID, float]:
        prof = _profile(ctx.favorites)
        out = {}
        for r in recipes:
            s = 0.5 * _shrunk(ctx.popularity.get(r.id)) + 0.5 * _cos(features(r), prof)
            if ctx.personal is not None and (sig := ctx.personal.get(r.id)) is not None:
                total = sig.positive + sig.negative
                s += 0.25 * (sig.positive - sig.negative) / total if total else 0.0
            out[r.id] = s
        return out


class NumpyRanker:
    """Learned hybrid factor + BPR + content + popularity ranker loaded from `model.npz` (allow_pickle=False)."""

    def __init__(
        self,
        *,
        version_id: uuid.UUID,
        recipe_names: np.ndarray,
        recipe_slots: np.ndarray,
        feature_names: np.ndarray,
        X_content: np.ndarray,
        item_prior: np.ndarray,
        mf_mu: float,
        mf_lam: float,
        mf_bi: np.ndarray,
        mf_Q: np.ndarray,
        bpr_b: np.ndarray,
        bpr_Q: np.ndarray,
        norm_stats: np.ndarray,
        hybrid_weights: np.ndarray,
        serving: dict[str, Any] | None = None,
    ) -> None:
        self.version_id: uuid.UUID | None = version_id
        self.X_content = np.asarray(X_content, dtype=np.float32)
        self.item_prior = np.asarray(item_prior, dtype=np.float64)
        self.mf_mu = float(mf_mu)
        self.mf_lam = float(mf_lam)
        self.mf_bi = np.asarray(mf_bi, dtype=np.float64)
        self.mf_Q = np.asarray(mf_Q, dtype=np.float64)
        self.bpr_b = np.asarray(bpr_b, dtype=np.float64)
        self.bpr_Q = np.asarray(bpr_Q, dtype=np.float64)
        self.norm_stats = np.asarray(norm_stats, dtype=np.float64).ravel()
        self.hybrid_weights = np.asarray(hybrid_weights, dtype=np.float64).ravel()

        names = [str(x) for x in recipe_names]
        slots = [str(x) for x in recipe_slots]
        self._slot_name_to_idx: dict[tuple[str, str], int] = {
            (n, s): i for i, (n, s) in enumerate(zip(names, slots, strict=True))
        }
        self._name_to_idx: dict[str, int] = {n: i for i, n in enumerate(names)}
        self._feat_to_idx: dict[str, int] = {str(f): i for i, f in enumerate(feature_names)}
        self.n_features = len(self._feat_to_idx)

        serving = serving or {}
        live = serving.get("live_signal_blending") or {}
        self.pop_w = float(live.get("popularity_weight", 0.0))
        self.pers_w = float(live.get("personal_weight", 0.25))
        self.shrink_k = float(live.get("shrink_k", SHRINK_K))
        inf = serving.get("inference") or {}
        self.fold_in_target = float(inf.get("mf_fold_in_target_rating", 5.0))
        self.fold_in_min_lam = float(inf.get("mf_fold_in_min_lam", 1e-3))

    def _recipe_index(self, r: RecipeView) -> int | None:
        idx = self._slot_name_to_idx.get((r.name_vi, r.slot))
        if idx is not None:
            return idx
        return self._name_to_idx.get(r.name_vi)

    def _featurize(self, r: RecipeView) -> np.ndarray:
        vec = np.zeros(self.n_features, dtype=np.float32)
        for ln in r.lines:
            if ln.role != "seasoning" and not ln.ingredient.is_staple:
                idx = self._feat_to_idx.get(f"ing:{ln.ingredient.name_vi}")
                if idx is not None:
                    vec[idx] = 1.0
        midx = self._feat_to_idx.get(f"method:{r.method_code}")
        if midx is not None:
            vec[midx] = 1.0
        for t in r.tag_codes:
            tidx = self._feat_to_idx.get(f"tag:{t}")
            if tidx is not None:
                vec[tidx] = 0.5
        return vec

    def _fold_in(self, favorites: Sequence[RecipeView]) -> tuple[float, np.ndarray, np.ndarray, np.ndarray]:
        fav_indices = [idx for f in favorites if (idx := self._recipe_index(f)) is not None]
        k = self.mf_Q.shape[1]
        if fav_indices:
            Q_sub = self.mf_Q[fav_indices]
            A = np.column_stack([np.ones(len(fav_indices), dtype=np.float64), Q_sub])
            y = self.fold_in_target - self.mf_mu - self.mf_bi[fav_indices]
            reg = max(self.mf_lam, self.fold_in_min_lam) * len(fav_indices) * np.eye(k + 1, dtype=np.float64)
            sol = np.linalg.solve(A.T @ A + reg, A.T @ y)
            bu_mf = float(sol[0])
            pu_mf = sol[1:]
            pu_bpr = self.bpr_Q[fav_indices].mean(axis=0)
        else:
            bu_mf = 0.0
            pu_mf = np.zeros(k, dtype=np.float64)
            pu_bpr = np.zeros(self.bpr_Q.shape[1], dtype=np.float64)

        if favorites:
            prof = np.mean(
                [
                    self.X_content[idx] if (idx := self._recipe_index(f)) is not None else self._featurize(f)
                    for f in favorites
                ],
                axis=0,
            ).astype(np.float32)
        else:
            prof = np.zeros(self.n_features, dtype=np.float32)
        return bu_mf, pu_mf, pu_bpr, prof

    def score(self, ctx: RankContext, recipes: Sequence[RecipeView]) -> dict[uuid.UUID, float]:
        if not recipes:
            return {}
        bu_mf, pu_mf, pu_bpr, fav_prof = self._fold_in(ctx.favorites)
        prof_norm = float(np.linalg.norm(fav_prof))
        n = len(recipes)
        s_mf = np.empty(n, dtype=np.float64)
        s_bpr = np.empty(n, dtype=np.float64)
        s_pop = np.empty(n, dtype=np.float64)
        X_cand = np.empty((n, self.n_features), dtype=np.float32)
        for i, r in enumerate(recipes):
            idx = self._recipe_index(r)
            if idx is not None:
                s_mf[i] = self.mf_mu + bu_mf + self.mf_bi[idx] + float(self.mf_Q[idx] @ pu_mf)
                s_bpr[i] = float(self.bpr_b[idx] + self.bpr_Q[idx] @ pu_bpr)
                s_pop[i] = float(self.item_prior[idx])
                X_cand[i] = self.X_content[idx]
            else:
                s_mf[i] = self.mf_mu + bu_mf
                s_bpr[i] = 0.0
                s_pop[i] = self.mf_mu
                X_cand[i] = self._featurize(r)

        if prof_norm > 0:
            cand_norms = np.linalg.norm(X_cand, axis=1)
            dots = X_cand @ fav_prof
            s_cnt = np.where(cand_norms > 0, dots / np.maximum(cand_norms * prof_norm, 1e-12), 0.0).astype(np.float64)
        else:
            s_cnt = np.zeros(n, dtype=np.float64)

        mf_mu, mf_sd, bpr_mu, bpr_sd, cnt_mu, cnt_sd, pop_mu, pop_sd = self.norm_stats
        z_mf = (s_mf - mf_mu) / mf_sd
        z_bpr = (s_bpr - bpr_mu) / bpr_sd
        z_cnt = (s_cnt - cnt_mu) / cnt_sd
        z_pop = (s_pop - pop_mu) / pop_sd
        w_mf, w_bpr, w_cnt, w_pop = self.hybrid_weights
        base = w_mf * z_mf + w_bpr * z_bpr + w_cnt * z_cnt + w_pop * z_pop

        out: dict[uuid.UUID, float] = {}
        for i, r in enumerate(recipes):
            s = float(base[i])
            if self.pop_w != 0.0:
                sig_p = ctx.popularity.get(r.id)
                pos, neg = (sig_p.positive, sig_p.negative) if sig_p else (0, 0)
                s += self.pop_w * ((pos + self.shrink_k * 0.5) / (pos + neg + self.shrink_k))
            if ctx.personal is not None and self.pers_w != 0.0:
                sig = ctx.personal.get(r.id)
                if sig is not None:
                    total = sig.positive + sig.negative
                    if total:
                        s += self.pers_w * (sig.positive - sig.negative) / total
            out[r.id] = s
        return out


def load_ranker(npz_path: Path, *, version_id: uuid.UUID, serving: dict[str, Any] | None = None) -> NumpyRanker:
    with np.load(npz_path, allow_pickle=False) as z:
        return NumpyRanker(
            version_id=version_id,
            recipe_names=z["recipe_names"],
            recipe_slots=z["recipe_slots"],
            feature_names=z["feature_names"],
            X_content=z["X_content"],
            item_prior=z["item_prior"],
            mf_mu=float(np.asarray(z["mf_mu"]).item()),
            mf_lam=float(np.asarray(z["mf_lam"]).item()),
            mf_bi=z["mf_bi"],
            mf_Q=z["mf_Q"],
            bpr_b=z["bpr_b"],
            bpr_Q=z["bpr_Q"],
            norm_stats=z["norm_stats"],
            hybrid_weights=z["hybrid_weights"],
            serving=serving,
        )


def percentiles(scores: dict[uuid.UUID, float]) -> dict[uuid.UUID, float]:
    """ŝ' ∈ [0, 1]: rank of each score among the given ones (ties share their mean rank); one item → 1."""
    if not scores:
        return {}
    if len(scores) == 1:
        return {k: 1.0 for k in scores}
    ordered = sorted(scores.items(), key=lambda kv: kv[1])
    out: dict[uuid.UUID, float] = {}
    i = 0
    n = len(ordered)
    while i < n:
        j = i
        while j + 1 < n and ordered[j + 1][1] == ordered[i][1]:
            j += 1
        rank = (i + j) / 2 / (n - 1)
        for k in range(i, j + 1):
            out[ordered[k][0]] = rank
        i = j + 1
    return out
