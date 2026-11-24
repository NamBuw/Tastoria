"""Implicit-feedback top-N rankers. Every model exposes `fit(train)` and `scores(users) -> (len(users), n_items)`.

`train` is the users × items CSR matrix of positives before the cutoff (1 per positive).

BPR-MF (own NumPy implementation) follows the loss of the v1 design §3.4 exactly:
    ŝ_ur = p_uᵀ q_r            (no bias term)
    L_BPR = − Σ_{(u, r, r')} ln σ(ŝ_ur − ŝ_ur') + λ ‖Θ‖²
with r a positive of u and r' an item u has no positive for, sampled uniformly. Optimisation is mini-batch SGD as in
Rendle et al. 2009: each sampled triple contributes its gradient and the λ term is applied to the parameter rows the
triple touches (so λ is "per occurrence", the usual SGD reading of λ‖Θ‖²). Gradient of one triple, x = ŝ_ur − ŝ_ur':
    ∂/∂p_u = −σ(−x)(q_r − q_r') + 2λ p_u,  ∂/∂q_r = −σ(−x) p_u + 2λ q_r,  ∂/∂q_r' = σ(−x) p_u + 2λ q_r'.
"""

from __future__ import annotations

import os
from collections.abc import Callable

import numpy as np
import scipy.sparse as sp

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")  # CPU only (shared GPU)
N_THREADS = int(os.environ.get("TASTORIA_THREADS", "16"))


class MostPop:
    name = "MostPop"
    stochastic = False

    def __init__(self) -> None:
        self.pop: np.ndarray | None = None

    def fit(self, train: sp.csr_matrix, **_: object) -> MostPop:
        self.pop = np.asarray(train.sum(axis=0)).ravel().astype(np.float32)
        return self

    def scores(self, users: np.ndarray) -> np.ndarray:
        return np.broadcast_to(self.pop, (len(users), len(self.pop)))


class Random:
    name = "Random"
    stochastic = True

    def __init__(self, seed: int = 0) -> None:
        self.rng = np.random.default_rng(seed)
        self.n_items = 0

    def fit(self, train: sp.csr_matrix, **_: object) -> Random:
        self.n_items = train.shape[1]
        return self

    def scores(self, users: np.ndarray) -> np.ndarray:
        return self.rng.random((len(users), self.n_items), dtype=np.float32)


class ItemKNN:
    """Item-based kNN (Sarwar et al. 2001): cosine with shrinkage h, sim_ij = c_ij / (√(n_i n_j) + h), keeping the
    k largest neighbours of each item; score_ur = Σ_{j ∈ I_u} sim_jr."""

    name = "ItemKNN"
    stochastic = False

    def __init__(self, k: int = 100, shrink: float = 0.0, chunk: int = 2000) -> None:
        self.k, self.shrink, self.chunk = k, shrink, chunk
        self.train: sp.csr_matrix | None = None
        self.sim: sp.csr_matrix | None = None

    def fit(self, train: sp.csr_matrix, **_: object) -> ItemKNN:
        x = train.tocsr().astype(np.float32)
        n = x.shape[1]
        norms = np.sqrt(np.asarray(x.sum(axis=0)).ravel())
        xt = x.T.tocsr()  # items × users
        rows, cols, vals = [], [], []
        k = min(self.k, n - 1)
        for c0 in range(0, n, self.chunk):
            c1 = min(n, c0 + self.chunk)
            g = (xt[c0:c1] @ x).toarray()  # chunk × n co-counts (symmetric, so row r = column r)
            denom = norms[c0:c1, None] * norms[None, :] + self.shrink
            np.divide(g, denom, out=g, where=denom > 0)
            g[np.arange(c1 - c0), np.arange(c0, c1)] = 0.0
            top = np.argpartition(-g, k, axis=1)[:, :k]  # k neighbours of each item in the chunk
            v = np.take_along_axis(g, top, axis=1)
            keep = v > 0
            # sim[j, r] = similarity of neighbour j to target item r, so score_ur = Σ_{j ∈ I_u} sim[j, r]
            rows.append(top[keep])
            cols.append(np.broadcast_to(np.arange(c0, c1)[:, None], top.shape)[keep])
            vals.append(v[keep])
        self.sim = sp.csr_matrix(
            (np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(n, n), dtype=np.float32
        )
        self.train = train.tocsr().astype(np.float32)
        return self

    def scores(self, users: np.ndarray) -> np.ndarray:
        return (self.train[users] @ self.sim).toarray()


class EASE:
    """EASE^R (Steck 2019), closed form: B = I − P·diag(1/diag(P)), P = (XᵀX + λI)⁻¹, diag(B) = 0.

    The dense inverse is O(n³) in the number of items, so the catalog can be capped to the `max_items` most popular
    training items; items outside the cap get −inf (reported as catalog coverage)."""

    name = "EASE"
    stochastic = False

    def __init__(self, lam: float = 500.0, max_items: int | None = 20000) -> None:
        self.lam, self.max_items = lam, max_items
        self.cat: np.ndarray | None = None
        self.b: np.ndarray | None = None
        self.train: sp.csr_matrix | None = None
        self.n_items = 0

    def fit(self, train: sp.csr_matrix, **_: object) -> EASE:
        from threadpoolctl import threadpool_limits

        self.n_items = train.shape[1]
        pop = np.asarray(train.sum(axis=0)).ravel()
        cat = np.flatnonzero(pop > 0)
        if self.max_items is not None and len(cat) > self.max_items:
            cat = np.sort(cat[np.argsort(-pop[cat], kind="stable")[: self.max_items]])
        self.cat = cat
        with threadpool_limits(N_THREADS):
            x = train[:, cat].astype(np.float32).toarray()  # dense GEMM: far faster than sparse XᵀX here
            g = (x.T @ x).astype(np.float64)
            del x
            g[np.diag_indices_from(g)] += self.lam
            p = np.linalg.inv(g)
            del g
            b = p / (-np.diag(p))
            b[np.diag_indices_from(b)] = 0.0
        self.b = b.astype(np.float32)
        self.train = train[:, cat].tocsr().astype(np.float32)
        return self

    @property
    def allowed(self) -> np.ndarray:
        a = np.zeros(self.n_items, bool)
        a[self.cat] = True
        return a

    def scores(self, users: np.ndarray) -> np.ndarray:
        out = np.full((len(users), self.n_items), -np.inf, dtype=np.float32)
        out[:, self.cat] = self.train[users] @ self.b
        return out


class BPRNumpy:
    """BPR-MF of §3.4 (see module docstring), mini-batch SGD in NumPy, uniform negative sampling."""

    name = "BPR-MF (NumPy)"
    stochastic = True

    def __init__(
        self,
        dim: int = 64,
        lam: float = 1e-4,
        lr: float = 0.05,
        epochs: int = 60,
        batch: int = 2048,
        init_std: float = 0.1,
        seed: int = 0,
    ) -> None:
        self.dim, self.lam, self.lr, self.epochs, self.batch = dim, lam, lr, epochs, batch
        self.init_std, self.seed = init_std, seed
        self.P: np.ndarray | None = None
        self.Q: np.ndarray | None = None
        self.history: list[dict] = []

    def fit(
        self,
        train: sp.csr_matrix,
        callback: Callable[[int, BPRNumpy], float | None] | None = None,
        eval_every: int = 10,
        **_: object,
    ) -> BPRNumpy:
        rng = np.random.default_rng(self.seed)
        n_u, n_i = train.shape
        coo = train.tocoo()
        pu, pi = coo.row.astype(np.int64), coo.col.astype(np.int64)
        keys = np.sort(pu * n_i + pi)
        self.P = (rng.standard_normal((n_u, self.dim)) * self.init_std).astype(np.float32)
        self.Q = (rng.standard_normal((n_i, self.dim)) * self.init_std).astype(np.float32)
        P, Q, lam, lr = self.P, self.Q, self.lam, self.lr
        n = len(pu)
        for ep in range(1, self.epochs + 1):
            perm = rng.permutation(n)
            loss = 0.0
            for b0 in range(0, n, self.batch):
                idx = perm[b0 : b0 + self.batch]
                u, i = pu[idx], pi[idx]
                j = _sample_negatives(rng, u, keys, n_i)
                pu_, qi, qj = P[u], Q[i], Q[j]
                x = np.einsum("bd,bd->b", pu_, qi - qj)
                g = _sigmoid(-x)  # = −∂(ln σ(x))/∂x
                loss += float(np.sum(np.logaddexp(0.0, -x)))
                gu = g[:, None] * (qi - qj) - 2 * lam * pu_
                gi = g[:, None] * pu_ - 2 * lam * qi
                gj = -g[:, None] * pu_ - 2 * lam * qj
                np.add.at(P, u, lr * gu)
                np.add.at(Q, i, lr * gi)
                np.add.at(Q, j, lr * gj)
            rec = {"epoch": ep, "loss": loss / n}
            if callback is not None and (ep % eval_every == 0 or ep == self.epochs):
                rec["val"] = callback(ep, self)
            self.history.append(rec)
        return self

    def scores(self, users: np.ndarray) -> np.ndarray:
        return self.P[users] @ self.Q.T


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 0.5 * (1.0 + np.tanh(0.5 * x))


def _sample_negatives(rng: np.random.Generator, u: np.ndarray, keys: np.ndarray, n_items: int) -> np.ndarray:
    """Uniform items that are not positives of u (rejection sampling against the sorted u·n + i keys)."""
    j = rng.integers(0, n_items, size=len(u))
    for _ in range(20):
        k = u * n_items + j
        pos = np.searchsorted(keys, k)
        bad = (pos < len(keys)) & (keys[np.minimum(pos, len(keys) - 1)] == k)
        if not bad.any():
            break
        j[bad] = rng.integers(0, n_items, size=int(bad.sum()))
    return j


class ImplicitBPR:
    """BPR from the `implicit` library (CPU build), for cross-checking BPRNumpy."""

    name = "BPR (implicit)"
    stochastic = True

    def __init__(self, factors: int = 64, lr: float = 0.05, reg: float = 0.01, iterations: int = 100, seed: int = 0):
        self.kw = dict(factors=factors, learning_rate=lr, regularization=reg, iterations=iterations)
        self.seed = seed
        self.U: np.ndarray | None = None
        self.V: np.ndarray | None = None

    def fit(self, train: sp.csr_matrix, **_: object) -> ImplicitBPR:
        from implicit.cpu.bpr import BayesianPersonalizedRanking

        m = BayesianPersonalizedRanking(**self.kw, random_state=self.seed, num_threads=N_THREADS)
        m.fit(train.tocsr().astype(np.float32), show_progress=False)
        self.U, self.V = np.asarray(m.user_factors), np.asarray(m.item_factors)
        return self

    def scores(self, users: np.ndarray) -> np.ndarray:
        return self.U[users] @ self.V.T


class ALS:
    """Implicit ALS (Hu, Koren, Volinsky 2008) from `implicit`: confidence c = 1 + α·x."""

    name = "ALS (implicit)"
    stochastic = True

    def __init__(self, factors: int = 64, reg: float = 0.1, alpha: float = 10.0, iterations: int = 15, seed: int = 0):
        self.kw = dict(factors=factors, regularization=reg, alpha=alpha, iterations=iterations)
        self.seed = seed
        self.U: np.ndarray | None = None
        self.V: np.ndarray | None = None

    def fit(self, train: sp.csr_matrix, **_: object) -> ALS:
        from implicit.cpu.als import AlternatingLeastSquares

        from threadpoolctl import threadpool_limits

        m = AlternatingLeastSquares(**self.kw, random_state=self.seed, num_threads=N_THREADS)
        with threadpool_limits(1, "blas"):  # implicit's own threads; nested BLAS threads slow it down
            m.fit(train.tocsr().astype(np.float32), show_progress=False)
        self.U, self.V = np.asarray(m.user_factors), np.asarray(m.item_factors)
        return self

    def scores(self, users: np.ndarray) -> np.ndarray:
        return self.U[users] @ self.V.T


class LightFMWarp:
    """LightFM (lightfm-next) with WARP loss and item features (identity + Food.com tags/ingredients)."""

    name = "LightFM WARP"
    stochastic = True

    def __init__(
        self,
        dim: int = 64,
        lr: float = 0.05,
        item_alpha: float = 1e-6,
        epochs: int = 30,
        loss: str = "warp",
        max_sampled: int = 30,
        seed: int = 0,
    ):
        self.dim, self.lr, self.item_alpha, self.epochs = dim, lr, item_alpha, epochs
        self.loss, self.max_sampled, self.seed = loss, max_sampled, seed
        self.U = self.V = self.ib = None

    def fit(
        self,
        train: sp.csr_matrix,
        item_features: sp.csr_matrix | None = None,
        callback: Callable[[int, LightFMWarp], float | None] | None = None,
        eval_every: int = 5,
        **_: object,
    ) -> LightFMWarp:
        from lightfm import LightFM

        m = LightFM(
            no_components=self.dim,
            loss=self.loss,
            learning_rate=self.lr,
            item_alpha=self.item_alpha,
            max_sampled=self.max_sampled,
            random_state=self.seed,
        )
        self.model = m
        self.item_features = item_features
        self.history = []
        coo = train.tocoo()
        done = 0
        while done < self.epochs:
            step = min(eval_every if callback else self.epochs, self.epochs - done)
            m.fit_partial(coo, item_features=item_features, epochs=step, num_threads=N_THREADS)
            done += step
            self._refresh()
            if callback is not None:
                self.history.append({"epoch": done, "val": callback(done, self)})
        return self

    def _refresh(self) -> None:
        _, self.U = self.model.get_user_representations()
        self.ib, self.V = self.model.get_item_representations(self.item_features)

    def item_repr(self, features: sp.csr_matrix) -> tuple[np.ndarray, np.ndarray]:
        return self.model.get_item_representations(features)

    def scores(self, users: np.ndarray) -> np.ndarray:
        return self.U[users] @ self.V.T + self.ib[None, :]


def _zscore_rows(arr: np.ndarray) -> np.ndarray:
    mean = arr.mean(axis=1, keepdims=True)
    std = np.maximum(arr.std(axis=1, keepdims=True), 1e-6)
    return ((arr - mean) / std).astype(np.float32)


class ContentCosine:
    """L2-normalized item-feature cosine similarity between user positive history profile and items."""

    name = "ContentCosine"
    stochastic = False

    def __init__(self) -> None:
        self.Fn: sp.csr_matrix | None = None
        self.prof: sp.csr_matrix | None = None

    def fit(self, train: sp.csr_matrix, item_features: sp.csr_matrix | None = None, **_: object) -> ContentCosine:
        n_items = train.shape[1]
        F = sp.identity(n_items, dtype=np.float32, format="csr") if item_features is None else item_features.tocsr().astype(np.float32)
        fn_norms = np.maximum(np.sqrt(np.asarray(F.multiply(F).sum(axis=1)).ravel()), 1e-12)
        self.Fn = (sp.diags(1.0 / fn_norms).astype(np.float32) @ F).tocsr()
        prof = train.tocsr().astype(np.float32) @ self.Fn
        p_norms = np.maximum(np.sqrt(np.asarray(prof.multiply(prof).sum(axis=1)).ravel()), 1e-12)
        self.prof = (sp.diags(1.0 / p_norms).astype(np.float32) @ prof).tocsr()
        return self

    def scores(self, users: np.ndarray) -> np.ndarray:
        return (self.prof[users] @ self.Fn.T).toarray().astype(np.float32)


class HybridCFContent:
    """Per-user z-score fusion of ALS + ContentCosine + log1p(MostPop) prior."""

    name = "HybridCFContent"
    stochastic = True

    def __init__(
        self,
        weights: tuple[float, float, float] = (0.5, 0.3, 0.2),
        als_params: dict | None = None,
        seed: int = 0,
    ) -> None:
        self.weights = tuple(float(w) for w in weights)
        self.als_params = dict(als_params or {"factors": 32, "reg": 10.0, "alpha": 5.0, "iterations": 15})
        self.seed = int(seed)
        self.cf: ALS | None = None
        self.content: ContentCosine | None = None
        self.pop_z: np.ndarray | None = None

    def fit(self, train: sp.csr_matrix, item_features: sp.csr_matrix | None = None, **_: object) -> HybridCFContent:
        self.cf = ALS(**self.als_params, seed=self.seed).fit(train)
        self.content = ContentCosine().fit(train, item_features=item_features)
        pop = np.log1p(np.asarray(train.sum(axis=0)).ravel().astype(np.float64))
        self.pop_z = ((pop - pop.mean()) / max(float(pop.std()), 1e-6)).astype(np.float32)
        return self

    def component_scores(self, users: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        cf_z = _zscore_rows(self.cf.scores(users))
        cnt_z = _zscore_rows(self.content.scores(users))
        return cf_z, cnt_z, self.pop_z

    def scores(self, users: np.ndarray) -> np.ndarray:
        w_cf, w_cnt, w_pop = self.weights
        cf_z, cnt_z, pop_z = self.component_scores(users)
        return (w_cf * cf_z + w_cnt * cnt_z + w_pop * pop_z[None, :]).astype(np.float32)


class TwoStageLGBMReranker:
    """Two-stage candidate union (MostPop + ALS + ContentCosine top-M) + LGBMRanker(lambdarank).

    Stage-1 features are computed strictly from `train` (pre-cutoff) without future leakage.
    """

    name = "TwoStageLGBMReranker"
    stochastic = True
    FEATURE_NAMES = (
        "s_als_raw",
        "s_als_z",
        "rr_als",
        "s_cnt_raw",
        "s_cnt_z",
        "rr_cnt",
        "log_pop",
        "pop_pct",
        "rr_pop",
        "user_act",
        "item_feat_nnz",
        "als_x_cnt",
        "als_x_pop",
        "cnt_x_pop",
        "in_top_als",
        "in_top_cnt",
        "in_top_pop",
    )

    def __init__(
        self,
        top_m: int = 100,
        als_params: dict | None = None,
        lgb_params: dict | None = None,
        seed: int = 0,
    ) -> None:
        self.top_m = int(top_m)
        self.als_params = dict(als_params or {"factors": 32, "reg": 10.0, "alpha": 5.0, "iterations": 15})
        self.lgb_params = dict(
            lgb_params or {"num_leaves": 15, "n_estimators": 200, "learning_rate": 0.05, "min_child_samples": 30}
        )
        self.seed = int(seed)
        self.als: ALS | None = None
        self.content: ContentCosine | None = None
        self.seen: sp.csr_matrix | None = None
        self.n_items = 0
        self.pop_raw: np.ndarray | None = None
        self.log_pop: np.ndarray | None = None
        self.pop_pct: np.ndarray | None = None
        self.pop_order: np.ndarray | None = None
        self.user_act: np.ndarray | None = None
        self.item_feat_nnz: np.ndarray | None = None
        self.ranker = None

    def fit_stage1(
        self,
        train: sp.csr_matrix,
        seen: sp.csr_matrix | None = None,
        item_features: sp.csr_matrix | None = None,
    ) -> TwoStageLGBMReranker:
        tr = train.tocsr()
        self.n_items = tr.shape[1]
        self.seen = seen.tocsr() if seen is not None else tr
        self.als = ALS(**self.als_params, seed=self.seed).fit(tr)
        self.content = ContentCosine().fit(tr, item_features=item_features)
        pop_raw = np.asarray(tr.sum(axis=0)).ravel().astype(np.float32)
        self.pop_raw = pop_raw
        self.log_pop = np.log1p(pop_raw)
        order = np.argsort(-pop_raw, kind="stable")
        self.pop_order = order
        pct = np.empty_like(pop_raw, dtype=np.float32)
        pct[order] = np.arange(len(pop_raw), dtype=np.float32) / max(1, len(pop_raw) - 1)
        self.pop_pct = pct
        self.user_act = np.log1p(np.diff(tr.indptr).astype(np.float32))
        if item_features is not None:
            self.item_feat_nnz = np.asarray((item_features > 0).sum(axis=1)).ravel().astype(np.float32)
        else:
            self.item_feat_nnz = np.ones(self.n_items, dtype=np.float32)
        return self

    def _top_unseen(self, scores_batch: np.ndarray, seen_batch: sp.csr_matrix, m: int) -> tuple[np.ndarray, np.ndarray]:
        s = scores_batch.copy()
        rows = np.repeat(np.arange(len(s)), np.diff(seen_batch.indptr))
        if len(rows):
            s[rows, seen_batch.indices] = -np.inf
        k = min(m, s.shape[1])
        top = np.argpartition(-s, k - 1, axis=1)[:, :k] if k < s.shape[1] else np.broadcast_to(np.arange(s.shape[1]), s.shape).copy()
        vals = np.take_along_axis(s, top, axis=1)
        order = np.argsort(-vals, axis=1, kind="stable")
        top = np.take_along_axis(top, order, axis=1)
        vals = np.take_along_axis(vals, order, axis=1)
        return top, np.isfinite(vals)

    def _candidates_and_features(
        self, users: np.ndarray, batch: int = 256
    ) -> tuple[list[np.ndarray], np.ndarray, np.ndarray]:
        users = np.asarray(users, dtype=np.int64)
        cands_all: list[np.ndarray] = []
        feats_chunks: list[np.ndarray] = []
        groups: list[int] = []
        m = min(self.top_m, self.n_items)

        for b0 in range(0, len(users), batch):
            ub = users[b0 : b0 + batch]
            s_als = self.als.scores(ub).astype(np.float32)
            s_cnt = self.content.scores(ub).astype(np.float32)
            z_als = _zscore_rows(s_als)
            z_cnt = _zscore_rows(s_cnt)
            seen_b = self.seen[ub]
            top_als, ok_als = self._top_unseen(s_als, seen_b, m)
            top_cnt, ok_cnt = self._top_unseen(s_cnt, seen_b, m)

            for r, u in enumerate(ub):
                seen_u = set(seen_b[r].indices.tolist())
                a_items = top_als[r][ok_als[r]]
                c_items = top_cnt[r][ok_cnt[r]]
                p_items_list = []
                for idx in self.pop_order:
                    ii = int(idx)
                    if ii not in seen_u:
                        p_items_list.append(ii)
                        if len(p_items_list) >= m:
                            break
                p_items = np.asarray(p_items_list, dtype=np.int64)

                cand = np.unique(np.concatenate([a_items, c_items, p_items]))
                if len(cand) == 0:
                    cand = np.arange(min(m, self.n_items), dtype=np.int64)
                cands_all.append(cand)
                groups.append(len(cand))

                a_rank = {int(it): rk for rk, it in enumerate(a_items)}
                c_rank = {int(it): rk for rk, it in enumerate(c_items)}
                p_rank = {int(it): rk for rk, it in enumerate(p_items)}

                rr_a = np.array([1.0 / (1.0 + a_rank[int(it)]) if int(it) in a_rank else 0.0 for it in cand], dtype=np.float32)
                rr_c = np.array([1.0 / (1.0 + c_rank[int(it)]) if int(it) in c_rank else 0.0 for it in cand], dtype=np.float32)
                rr_p = np.array([1.0 / (1.0 + p_rank[int(it)]) if int(it) in p_rank else 0.0 for it in cand], dtype=np.float32)

                in_a = (rr_a > 0).astype(np.float32)
                in_c = (rr_c > 0).astype(np.float32)
                in_p = (rr_p > 0).astype(np.float32)

                sa_r = s_als[r, cand]
                za_r = z_als[r, cand]
                sc_r = s_cnt[r, cand]
                zc_r = z_cnt[r, cand]
                lp = self.log_pop[cand]
                pp = self.pop_pct[cand]
                ua = np.full(len(cand), self.user_act[int(u)], dtype=np.float32)
                fn = self.item_feat_nnz[cand]

                X_u = np.column_stack(
                    [
                        sa_r,
                        za_r,
                        rr_a,
                        sc_r,
                        zc_r,
                        rr_c,
                        lp,
                        pp,
                        rr_p,
                        ua,
                        fn,
                        za_r * zc_r,
                        za_r * lp,
                        zc_r * lp,
                        in_a,
                        in_c,
                        in_p,
                    ]
                ).astype(np.float32)
                feats_chunks.append(X_u)

        X_flat = np.vstack(feats_chunks) if feats_chunks else np.zeros((0, len(self.FEATURE_NAMES)), dtype=np.float32)
        return cands_all, X_flat, np.asarray(groups, dtype=np.int32)

    def build_dataset(
        self,
        train: sp.csr_matrix,
        targets: dict[int, np.ndarray],
        seen: sp.csr_matrix,
        item_features: sp.csr_matrix | None = None,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        self.fit_stage1(train, seen=seen, item_features=item_features)
        users = np.array(sorted(targets), dtype=np.int64)
        cands, X_flat, groups = self._candidates_and_features(users)
        keep_X, keep_y, keep_g, keep_u = [], [], [], []
        offset = 0
        for u, cand, g in zip(users, cands, groups, strict=True):
            y_u = np.isin(cand, targets[int(u)]).astype(np.int32)
            X_u = X_flat[offset : offset + int(g)]
            offset += int(g)
            if y_u.sum() > 0 and len(cand) >= 2:
                keep_X.append(X_u)
                keep_y.append(y_u)
                keep_g.append(int(g))
                keep_u.append(int(u))
        if not keep_X:
            return np.zeros((0, len(self.FEATURE_NAMES)), dtype=np.float32), np.zeros(0, dtype=np.int32), np.zeros(0, dtype=np.int32), np.zeros(0, dtype=np.int64)
        return (
            np.vstack(keep_X),
            np.concatenate(keep_y),
            np.asarray(keep_g, dtype=np.int32),
            np.asarray(keep_u, dtype=np.int64),
        )

    def fit_reranker(self, X: np.ndarray, y: np.ndarray, groups: np.ndarray) -> TwoStageLGBMReranker:
        import lightgbm as lgb

        self.ranker = lgb.LGBMRanker(
            objective="lambdarank",
            label_gain=[0, 1],
            lambdarank_truncation_level=10,
            random_state=self.seed,
            n_jobs=N_THREADS,
            verbose=-1,
            **self.lgb_params,
        )
        self.ranker.fit(X, y, group=groups)
        return self

    def fit(
        self,
        train: sp.csr_matrix,
        item_features: sp.csr_matrix | None = None,
        val_targets: dict[int, np.ndarray] | None = None,
        val_seen: sp.csr_matrix | None = None,
        **_: object,
    ) -> TwoStageLGBMReranker:
        if val_targets is not None:
            X, y, groups, _ = self.build_dataset(
                train, val_targets, seen=val_seen if val_seen is not None else train, item_features=item_features
            )
            self.fit_reranker(X, y, groups)
            return self
        # Standalone internal split fallback (for unit tests)
        rng = np.random.default_rng(self.seed)
        coo = train.tocoo()
        n = len(coo.row)
        hold = rng.random(n) < 0.25
        tr_sub = sp.csr_matrix((np.ones((~hold).sum(), np.float32), (coo.row[~hold], coo.col[~hold])), shape=train.shape)
        tr_sub.sum_duplicates()
        targets: dict[int, list[int]] = {}
        for u, i in zip(coo.row[hold], coo.col[hold], strict=True):
            if tr_sub[u].nnz > 0:
                targets.setdefault(int(u), []).append(int(i))
        tg = {u: np.unique(v) for u, v in targets.items()}
        X, y, groups, _ = self.build_dataset(tr_sub, tg, seen=tr_sub, item_features=item_features)
        self.fit_reranker(X, y, groups)
        self.fit_stage1(train, seen=train, item_features=item_features)
        return self

    def scores(self, users: np.ndarray) -> np.ndarray:
        cands, X_flat, groups = self._candidates_and_features(users)
        preds = self.ranker.predict(X_flat).astype(np.float32) if len(X_flat) else np.zeros(0, dtype=np.float32)
        out = np.full((len(users), self.n_items), -1e6, dtype=np.float32)
        offset = 0
        for row, (cand, g) in enumerate(zip(cands, groups, strict=True)):
            g_int = int(g)
            out[row, cand] = preds[offset : offset + g_int]
            offset += g_int
        return out


class ColdHybrid:
    """Cold-item hybrid blending feature-only LightFM WARP and L2-normalized ContentCosine."""

    name = "ColdHybrid"
    stochastic = True

    def __init__(
        self,
        alpha: float = 0.5,
        lfm_params: dict | None = None,
        seed: int = 0,
    ) -> None:
        self.alpha = float(alpha)
        self.lfm_params = dict(lfm_params or {"dim": 64, "lr": 0.02, "item_alpha": 0.0, "epochs": 12})
        self.seed = int(seed)
        self.lfm: LightFMWarp | None = None
        self.content: ContentCosine | None = None
        self.allowed: np.ndarray | None = None

    def fit(
        self,
        train: sp.csr_matrix,
        item_features: sp.csr_matrix | None = None,
        allowed: np.ndarray | None = None,
        **_: object,
    ) -> ColdHybrid:
        self.allowed = allowed
        self.lfm = LightFMWarp(**self.lfm_params, seed=self.seed).fit(train, item_features=item_features)
        self.content = ContentCosine().fit(train, item_features=item_features)
        return self

    def _norm_allowed(self, arr: np.ndarray) -> np.ndarray:
        if self.allowed is None:
            return _zscore_rows(arr)
        sub = arr[:, self.allowed]
        mean = sub.mean(axis=1, keepdims=True)
        std = np.maximum(sub.std(axis=1, keepdims=True), 1e-6)
        return ((arr - mean) / std).astype(np.float32)

    def component_scores(self, users: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        s_lfm = self._norm_allowed(self.lfm.scores(users).astype(np.float32))
        s_cnt = self._norm_allowed(self.content.scores(users).astype(np.float32))
        return s_lfm, s_cnt

    def scores(self, users: np.ndarray) -> np.ndarray:
        s_lfm, s_cnt = self.component_scores(users)
        return (self.alpha * s_lfm + (1.0 - self.alpha) * s_cnt).astype(np.float32)


def cold_feature_matrix(
    n_items: int,
    item_features_only: sp.csr_matrix,
    feature_names: list[str],
    variant: str,
) -> sp.csr_matrix:
    """Build cold-item feature matrix for Food.com ablations: id_only, tags_only, ing_only, tags_ing."""
    if variant == "id_only":
        return sp.identity(n_items, dtype=np.float32, format="csr")
    if variant == "tags_ing":
        return item_features_only.tocsr().astype(np.float32)
    if variant == "tags_only":
        cols = [j for j, name in enumerate(feature_names) if name.startswith("tag:")]
    elif variant == "ing_only":
        cols = [j for j, name in enumerate(feature_names) if name.startswith("ing:")]
    else:
        raise ValueError(f"unknown cold feature variant: {variant!r}")
    sub = item_features_only[:, cols].tocsr().astype(np.float32)
    deg = np.asarray(sub.sum(axis=1)).ravel()
    scale = np.where(deg > 0, 1.0 / np.maximum(deg, 1e-12), 0.0).astype(np.float32)
    return (sp.diags(scale) @ sub).tocsr()


def make(name: str, **params: object):
    return {
        "Random": Random,
        "MostPop": MostPop,
        "ItemKNN": ItemKNN,
        "EASE": EASE,
        "BPR-MF (NumPy)": BPRNumpy,
        "BPR (implicit)": ImplicitBPR,
        "ALS (implicit)": ALS,
        "LightFM WARP": LightFMWarp,
        "ContentCosine": ContentCosine,
        "HybridCFContent": HybridCFContent,
        "TwoStageLGBMReranker": TwoStageLGBMReranker,
        "ColdHybrid": ColdHybrid,
    }[name](**params)
