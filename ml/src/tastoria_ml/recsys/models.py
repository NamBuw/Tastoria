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


def make(name: str, **params: object):
    return {
        "MostPop": MostPop,
        "ItemKNN": ItemKNN,
        "EASE": EASE,
        "BPR-MF (NumPy)": BPRNumpy,
        "BPR (implicit)": ImplicitBPR,
        "ALS (implicit)": ALS,
        "LightFM WARP": LightFMWarp,
    }[name](**params)
