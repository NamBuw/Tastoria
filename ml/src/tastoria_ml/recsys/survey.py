"""Explicit-rating taste ranking for the Vietnamese survey (design v2 §6.1, review ml#1, ml#2, ml#8, ml#9).

Data: the UC24 export of the survey (`tastoria survey export`): ratings.csv (1–5 or never_eaten), favorites.csv
("5 món hay ăn"), recipes.csv (recipe_id → name_vi, slot) — mapped to data/kb dishes by (name_vi, slot).
"never_eaten" answers are not ratings: they are left out of every ranking metric and kept as a familiarity signal.

Models (all score dishes for one user; ŝ carries taste only):
  ShrunkMean   s_i = (Σ_u r_ui + k·μ) / (n_i + k)                                            (bậc 1, the baseline)
  Bias         r̂ = μ + b_u + b_i, ridge by alternating means (λ_u, λ_i); ranks by b_i            (bậc 2)
  ContentFav   cos(x_i, mean of x_f over the user's 5 favourites)                                (bậc 3)
  BiasedMF     r̂ = μ + b_u + b_i + p_uᵀq_i, SGD on squared error + λ(‖p‖² + ‖q‖² + b²)          (bậc 4a)
  BPRPairs     ŝ = b_i + p_uᵀq_i, −Σ ln σ(ŝ_ua − ŝ_ub) + λ‖Θ‖² over pairs with r_ua > r_ub          (bậc 4b)
  LightFMLog   LightFM logistic loss, label +1 (r ≥ 4), −1 (r ≤ 2), 3 dropped; user features = identity +
               the 5 favourites; item features = identity + content                               (bậc 5)
  LambdaMART   LightGBM lambdarank, query = user, label = r − 1 (linear gain), features: content, slot, favourite
               match, leave-one-out item mean and count, MF score produced out of fold                 (bậc 6)
Cold users (user-cold scenario) are seen only through their favourites: MF folds them in by ridge on the
favourites taken as 5-star ratings, BPR uses the centroid of the favourites' item factors, LightFM uses the
favourite features only. Cold items get no identity parameters (MF/BPR: 0 → ties), content where the model has it.

Evaluation: three scenarios × 5 outer folds × 5 seeds; hyper-parameters chosen in an inner 3-fold CV of the same
kind inside each outer training set (nested CV by user):
  warm       each user's ratings split into 5 folds
  item_cold  dishes split into 5 folds (stratified by slot): test = ratings of the held 20 % of dishes
  user_cold  respondents split into 5 folds: test users contribute only their favourites to training
Per user and fold: graded NDCG@5 (gain r − 1) and pairwise AUC over that user's test dishes, overall and within each
slot. Primary comparison: "best personalised" (the personalised model with the best inner score, chosen per outer
fold) vs ShrunkMean; the other models vs ShrunkMean with Holm correction; paired bootstrap by user.

`simulate` builds a SIMULATED survey from a stated latent model. It only tests the pipeline; it is not a result.
"""

from __future__ import annotations

import csv
import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.sparse as sp

from tastoria_ml.recsys import kb_catalog, metrics, stats
from tastoria_ml.recsys.kb_catalog import Catalog

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")


# ===================================================================================================== data


@dataclass
class SurveyData:
    ratings: pd.DataFrame  # user, item, rating (1–5)
    never: pd.DataFrame  # user, item (never eaten)
    favorites: dict[int, np.ndarray]
    n_users: int
    cat: Catalog
    simulated: bool
    meta: dict = field(default_factory=dict)

    @property
    def n_items(self) -> int:
        return len(self.cat.recipes)


def load_export(export_dir: Path, cat: Catalog | None = None) -> SurveyData:
    """Read a `tastoria survey export` directory. Unknown dishes (not in data/kb) are reported and dropped."""
    export_dir = Path(export_dir)
    cat = cat or kb_catalog.load()
    by_name = cat.by_name()
    rid2item, unmapped = {}, []
    with open(export_dir / "recipes.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (row["name_vi"], row["slot"])
            if key in by_name:
                rid2item[row["recipe_id"]] = by_name[key]
            else:
                unmapped.append(row["name_vi"])
    users: dict[str, int] = {}
    with open(export_dir / "respondents.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            users.setdefault(row["respondent_id"], len(users))
    rat, nev = [], []
    with open(export_dir / "ratings.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["respondent_id"] not in users or row["recipe_id"] not in rid2item:
                continue
            u, i = users[row["respondent_id"]], rid2item[row["recipe_id"]]
            if row["never_eaten"] == "true" or row["rating"] == "":
                nev.append((u, i))
            else:
                rat.append((u, i, float(row["rating"])))
    favs: dict[int, list[int]] = {}
    with open(export_dir / "favorites.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["respondent_id"] in users and row["recipe_id"] in rid2item:
                favs.setdefault(users[row["respondent_id"]], []).append(rid2item[row["recipe_id"]])
    manifest = json.loads((export_dir / "manifest.json").read_text(encoding="utf-8"))
    return SurveyData(
        pd.DataFrame(rat, columns=["user", "item", "rating"]),
        pd.DataFrame(nev, columns=["user", "item"]),
        {u: np.array(sorted(v)) for u, v in favs.items()},
        len(users),
        cat,
        simulated=False,
        meta={"export": str(export_dir), "manifest": manifest, "unmapped_recipes": unmapped},
    )


SIM_DEFAULTS = dict(
    n_users=90,
    n_anchor=10,
    n_random=35,
    dim=6,
    quality_sd=0.5,
    user_bias_sd=0.4,
    taste_scale=1.0,
    content_share=0.6,
    noise_sd=0.6,
    thresholds=(-1.4, -0.6, 0.2, 1.0),
    familiarity_mean=1.8,
    familiarity_sd=1.0,
    n_fav=5,
)


def simulate(cat: Catalog, seed: int = 20261018, **kw: object) -> SurveyData:
    """SIMULATED survey (pipeline test only). Latent model, all draws from `seed`:

        x̃_i   = content vector of dish i, standardised per column
        v_i   = √c · W x̃_i / ‖W x̃_i‖_rms + √(1 − c) · ε_i,  W ~ N(0, 1), ε_i ~ N(0, I_d)   (c = content_share)
        a_i ~ N(0, quality_sd²) dish quality,  b_u ~ N(0, user_bias_sd²),  θ_u ~ N(0, I_d)
        z_ui  = a_i + b_u + taste_scale · θ_uᵀ v_i / √d + e_ui,  e_ui ~ N(0, noise_sd²)
        r_ui  = 1 + #{k : z_ui > t_k}, t = thresholds
        never_eaten_ui ~ Bernoulli(σ(−(f_i + g_u))), f_i ~ N(familiarity_mean, familiarity_sd²), g_u ~ N(0, 0.5²)
        favourites_u = top-n_fav of z_ui + Gumbel(0, 0.5) among dishes the user has eaten (whole catalog)
        form_u = n_anchor common dishes + n_random dishes drawn per slot in proportion to slot size, least-shown first
    """
    p = {**SIM_DEFAULTS, **kw}
    rng = np.random.default_rng(seed)
    n_i = len(cat.recipes)
    X = cat.X
    Xs = (X - X.mean(0)) / np.where(X.std(0) > 0, X.std(0), 1.0)
    d = int(p["dim"])
    W = rng.standard_normal((X.shape[1], d))
    vc = Xs @ W
    vc /= np.sqrt((vc**2).mean())
    c = float(p["content_share"])
    V = np.sqrt(c) * vc + np.sqrt(1 - c) * rng.standard_normal((n_i, d))
    a = rng.normal(0, p["quality_sd"], n_i)
    n_u = int(p["n_users"])
    bu = rng.normal(0, p["user_bias_sd"], n_u)
    th = rng.standard_normal((n_u, d))
    z = a[None, :] + bu[:, None] + p["taste_scale"] * (th @ V.T) / np.sqrt(d) + rng.normal(0, p["noise_sd"], (n_u, n_i))
    t = np.array(p["thresholds"])
    r = 1 + (z[:, :, None] > t[None, None, :]).sum(-1)
    fam = rng.normal(p["familiarity_mean"], p["familiarity_sd"], n_i)
    g = rng.normal(0, 0.5, n_u)
    never = rng.random((n_u, n_i)) < 1 / (1 + np.exp(fam[None, :] + g[:, None]))
    slots = cat.slots
    slot_names = sorted(set(slots))
    share = {s: (slots == s).sum() / n_i for s in slot_names}
    n_anchor = int(p["n_anchor"])
    alloc = _largest_remainder(n_anchor, share)
    anchors = []
    for s in slot_names:
        anchors += list(rng.choice(np.flatnonzero(slots == s), size=alloc[s], replace=False))
    anchors = np.array(sorted(anchors))
    shown = np.zeros(n_i, int)
    n_rand = int(p["n_random"])
    alloc_r = {s: int(np.floor(n_rand * share[s])) for s in slot_names}  # leftover slots drawn per respondent
    rows_r, rows_n, favs = [], [], {}
    for u in range(n_u):
        left = n_rand - sum(alloc_r.values())
        extra = rng.permutation(slot_names)[:left]
        items = list(anchors)
        for s in slot_names:
            k = alloc_r[s] + int(s in extra)
            pool = np.setdiff1d(np.flatnonzero(slots == s), anchors)
            pool = rng.permutation(pool)
            pool = pool[np.argsort(shown[pool], kind="stable")][:k]
            shown[pool] += 1
            items += list(pool)
        for i in items:
            (rows_n if never[u, i] else rows_r).append((u, int(i)) if never[u, i] else (u, int(i), float(r[u, i])))
        eaten = np.flatnonzero(~never[u])
        noisy = z[u, eaten] + rng.gumbel(0, 0.5, len(eaten))
        favs[u] = np.sort(eaten[np.argsort(-noisy)[: int(p["n_fav"])]])
    meta = {
        "SIMULATION": "dữ liệu MÔ PHỎNG từ mô hình ẩn nêu trong docstring simulate(); chỉ kiểm đường ống, không phải kết quả",
        "seed": seed,
        "params": {k: (list(v) if isinstance(v, tuple) else v) for k, v in p.items()},
        "true_rating_hist": {str(k): int((r == k).sum()) for k in range(1, 6)},
    }
    return SurveyData(
        pd.DataFrame(rows_r, columns=["user", "item", "rating"]),
        pd.DataFrame(rows_n, columns=["user", "item"]),
        favs,
        n_u,
        cat,
        simulated=True,
        meta=meta,
    )


def _largest_remainder(n: int, share: dict[str, float]) -> dict[str, int]:
    base = {k: int(np.floor(n * v)) for k, v in share.items()}
    left = n - sum(base.values())
    for k in sorted(share, key=lambda k: -(n * share[k] - base[k]))[:left]:
        base[k] += 1
    return base


# ===================================================================================================== models


@dataclass
class Fold:
    train: pd.DataFrame  # user, item, rating
    favorites: dict[int, np.ndarray]
    n_users: int
    n_items: int
    cat: Catalog
    cold_users: frozenset[int] = frozenset()  # users with no training ratings (only favourites are visible)


class SurveyModel:
    name = "base"
    personalised = True
    grid: list[dict] = [{}]

    def __init__(self, seed: int = 0, **params: object) -> None:
        self.seed = seed
        self.params = params

    def fit(self, f: Fold) -> SurveyModel:
        raise NotImplementedError

    def score(self, user: int, items: np.ndarray) -> np.ndarray:
        raise NotImplementedError


class ShrunkMean(SurveyModel):
    name = "ShrunkMean"
    personalised = False
    grid = [{"k": k} for k in (1.0, 3.0, 10.0)]

    def fit(self, f: Fold) -> ShrunkMean:
        k = float(self.params.get("k", 3.0))
        mu = f.train.rating.mean()
        s = np.zeros(f.n_items)
        n = np.zeros(f.n_items)
        np.add.at(s, f.train.item.to_numpy(), f.train.rating.to_numpy())
        np.add.at(n, f.train.item.to_numpy(), 1)
        self.s = (s + k * mu) / (n + k)
        return self

    def score(self, user: int, items: np.ndarray) -> np.ndarray:
        return self.s[items]


def _biases(tr: pd.DataFrame, n_u: int, n_i: int, lam_u: float, lam_i: float, iters: int = 10):
    u, i, r = tr.user.to_numpy(), tr.item.to_numpy(), tr.rating.to_numpy(float)
    mu = r.mean()
    bu, bi = np.zeros(n_u), np.zeros(n_i)
    nu = np.bincount(u, minlength=n_u)
    ni = np.bincount(i, minlength=n_i)
    for _ in range(iters):
        bi = np.bincount(i, r - mu - bu[u], minlength=n_i) / (lam_i + ni)
        bu = np.bincount(u, r - mu - bi[i], minlength=n_u) / (lam_u + nu)
    return mu, bu, bi


class Bias(SurveyModel):
    name = "Bias u+i"
    personalised = False  # within one user the ranking is by b_i (debiased item effect)
    grid = [{"lam": lam} for lam in (1.0, 5.0, 15.0)]

    def fit(self, f: Fold) -> Bias:
        lam = float(self.params.get("lam", 5.0))
        self.mu, self.bu, self.bi = _biases(f.train, f.n_users, f.n_items, lam, lam)
        return self

    def score(self, user: int, items: np.ndarray) -> np.ndarray:
        return self.bi[items]


class ContentFav(SurveyModel):
    name = "Content (5 món hay ăn)"
    grid = [{}]

    def fit(self, f: Fold) -> ContentFav:
        self.X = f.cat.X
        self.favs = f.favorites
        return self

    def score(self, user: int, items: np.ndarray) -> np.ndarray:
        fav = self.favs.get(user)
        if fav is None or len(fav) == 0:
            return np.zeros(len(items))
        return kb_catalog.cosine_rows(self.X[items], self.X[fav].mean(0))


class BiasedMF(SurveyModel):
    name = "Biased MF"
    grid = [{"dim": d, "lam": lam} for d in (4, 8) for lam in (0.02, 0.1)]

    def fit(self, f: Fold) -> BiasedMF:
        d = int(self.params.get("dim", 8))
        lam = float(self.params.get("lam", 0.05))
        lr = float(self.params.get("lr", 0.02))
        epochs = int(self.params.get("epochs", 80))
        rng = np.random.default_rng(self.seed)
        u, i, r = f.train.user.to_numpy(), f.train.item.to_numpy(), f.train.rating.to_numpy(float)
        self.mu = r.mean()
        P = rng.normal(0, 0.1, (f.n_users, d))
        Q = rng.normal(0, 0.1, (f.n_items, d))
        bu, bi = np.zeros(f.n_users), np.zeros(f.n_items)
        n = len(r)
        for _ in range(epochs):
            for b in np.array_split(rng.permutation(n), max(1, n // 128)):
                uu, ii = u[b], i[b]
                e = r[b] - (self.mu + bu[uu] + bi[ii] + np.einsum("bd,bd->b", P[uu], Q[ii]))
                pu, qi = P[uu].copy(), Q[ii].copy()
                np.add.at(bu, uu, lr * (e - lam * bu[uu]))
                np.add.at(bi, ii, lr * (e - lam * bi[ii]))
                np.add.at(P, uu, lr * (e[:, None] * qi - lam * pu))
                np.add.at(Q, ii, lr * (e[:, None] * pu - lam * qi))
        seen_i = np.bincount(i, minlength=f.n_items) > 0
        Q[~seen_i] = 0.0  # cold dishes: no identity parameters
        bi[~seen_i] = 0.0
        self.P, self.Q, self.bu, self.bi, self.lam = P, Q, bu, bi, lam
        for cu in f.cold_users:
            self.P[cu], self.bu[cu] = self._fold_in(f.favorites.get(cu, np.zeros(0, int)))
        return self

    def _fold_in(self, fav: np.ndarray) -> tuple[np.ndarray, float]:
        """Ridge on the favourites taken as 5-star ratings: min Σ (5 − μ − b_f − b_u − p·q_f)² + λ(‖p‖² + b_u²)."""
        d = self.Q.shape[1]
        if len(fav) == 0:
            return np.zeros(d), 0.0
        A = np.hstack([np.ones((len(fav), 1)), self.Q[fav]])
        y = 5.0 - self.mu - self.bi[fav]
        sol = np.linalg.solve(A.T @ A + max(self.lam, 1e-3) * len(fav) * np.eye(d + 1), A.T @ y)
        return sol[1:], float(sol[0])

    def score(self, user: int, items: np.ndarray) -> np.ndarray:
        return self.mu + self.bu[user] + self.bi[items] + self.Q[items] @ self.P[user]


class BPRPairs(SurveyModel):
    name = "BPR (cặp chênh điểm)"
    grid = [{"dim": d, "lam": lam} for d in (4, 8) for lam in (0.01, 0.1)]

    def fit(self, f: Fold) -> BPRPairs:
        d = int(self.params.get("dim", 8))
        lam = float(self.params.get("lam", 0.01))
        lr = float(self.params.get("lr", 0.05))
        epochs = int(self.params.get("epochs", 60))
        rng = np.random.default_rng(self.seed)
        pairs = []
        for uu, g in f.train.groupby("user"):
            it, rt = g.item.to_numpy(), g.rating.to_numpy()
            hi, lo = np.nonzero(rt[:, None] > rt[None, :])
            pairs.append(np.stack([np.full(len(hi), uu), it[hi], it[lo]], 1))
        pairs = np.concatenate(pairs) if pairs else np.zeros((0, 3), int)
        P = rng.normal(0, 0.1, (f.n_users, d))
        Q = rng.normal(0, 0.1, (f.n_items, d))
        b = np.zeros(f.n_items)
        n = len(pairs)
        for _ in range(epochs):
            for bt in np.array_split(rng.permutation(n), max(1, n // 256)):
                uu, ia, ib = pairs[bt, 0], pairs[bt, 1], pairs[bt, 2]
                pu, qa, qb = P[uu].copy(), Q[ia].copy(), Q[ib].copy()
                x = b[ia] - b[ib] + np.einsum("bd,bd->b", pu, qa - qb)
                g = 0.5 * (1 + np.tanh(-0.5 * x))  # σ(−x)
                np.add.at(P, uu, lr * (g[:, None] * (qa - qb) - 2 * lam * pu))
                np.add.at(Q, ia, lr * (g[:, None] * pu - 2 * lam * qa))
                np.add.at(Q, ib, lr * (-g[:, None] * pu - 2 * lam * qb))
                np.add.at(b, ia, lr * (g - 2 * lam * b[ia]))
                np.add.at(b, ib, lr * (-g - 2 * lam * b[ib]))
        seen_i = np.bincount(f.train.item.to_numpy(), minlength=f.n_items) > 0
        Q[~seen_i] = 0.0
        b[~seen_i] = 0.0
        for cu in f.cold_users:
            fav = f.favorites.get(cu, np.zeros(0, int))
            P[cu] = Q[fav].mean(0) if len(fav) else 0.0
        self.P, self.Q, self.b = P, Q, b
        return self

    def score(self, user: int, items: np.ndarray) -> np.ndarray:
        return self.b[items] + self.Q[items] @ self.P[user]


def _row_norm(m: sp.csr_matrix) -> sp.csr_matrix:
    s = np.asarray(m.sum(axis=1)).ravel()
    return (sp.diags(1.0 / np.where(s > 0, s, 1.0)) @ m).tocsr().astype(np.float32)


class LightFMLogistic(SurveyModel):
    name = "LightFM logistic ±1"
    grid = [{"dim": d, "epochs": e} for d in (8, 16) for e in (20, 60)]

    def fit(self, f: Fold) -> LightFMLogistic:
        from lightfm import LightFM

        d = int(self.params.get("dim", 16))
        epochs = int(self.params.get("epochs", 30))
        tr = f.train[(f.train.rating >= 4) | (f.train.rating <= 2)]
        y = np.where(tr.rating >= 4, 1.0, -1.0).astype(np.float32)
        inter = sp.coo_matrix((y, (tr.user, tr.item)), shape=(f.n_users, f.n_items))
        n_u, n_i = f.n_users, f.n_items
        fav_rows, fav_cols = [], []
        for uu, items in f.favorites.items():
            fav_rows += [uu] * len(items)
            fav_cols += list(items)
        favm = sp.csr_matrix((np.ones(len(fav_rows), np.float32), (fav_rows, fav_cols)), shape=(n_u, n_i))
        ident_u = sp.identity(n_u, format="csr", dtype=np.float32)
        cold_mask = np.zeros(n_u, np.float32)
        cold_mask[list(f.cold_users)] = 1.0
        ident_u_warm = sp.diags(1 - cold_mask) @ ident_u
        self.uf = _row_norm(sp.hstack([ident_u_warm, favm], format="csr"))
        seen_i = (np.bincount(f.train.item.to_numpy(), minlength=n_i) > 0).astype(np.float32)
        Xc = sp.csr_matrix(f.cat.X.astype(np.float32))
        self.itf = _row_norm(sp.hstack([sp.diags(seen_i) @ sp.identity(n_i, format="csr", dtype=np.float32), Xc], format="csr"))
        m = LightFM(no_components=d, loss="logistic", learning_rate=0.05, random_state=self.seed)
        m.fit(inter, user_features=self.uf, item_features=self.itf, epochs=epochs, num_threads=1)
        _, self.U = m.get_user_representations(self.uf)
        self.ib, self.V = m.get_item_representations(self.itf)
        return self

    def score(self, user: int, items: np.ndarray) -> np.ndarray:
        return self.V[items] @ self.U[user] + self.ib[items]


class LambdaMART(SurveyModel):
    name = "LambdaMART"
    grid = [{"num_leaves": nl, "n_estimators": ne} for nl in (7, 15) for ne in (100, 300)]

    def _features(self, users: np.ndarray, items: np.ndarray, mf_scores: np.ndarray, loo_mean: np.ndarray, loo_n: np.ndarray) -> np.ndarray:
        cat = self.cat
        fav_cos = np.array([self._favcos(u)[i] for u, i in zip(users, items, strict=True)])
        slot_oh = (cat.slots[items][:, None] == np.array(["man", "rau", "canh"])[None, :]).astype(float)
        return np.hstack([cat.X[items], slot_oh, fav_cos[:, None], loo_mean[:, None], loo_n[:, None], mf_scores[:, None]])

    def _favcos(self, u: int) -> np.ndarray:
        if u not in self._fav_cache:
            fav = self.favs.get(u)
            self._fav_cache[u] = kb_catalog.cosine_rows(self.cat.X, self.cat.X[fav].mean(0)) if fav is not None and len(fav) else np.zeros(len(self.cat.X))
        return self._fav_cache[u]

    def fit(self, f: Fold) -> LambdaMART:
        import lightgbm as lgb

        self.cat, self.favs, self._fav_cache = f.cat, f.favorites, {}
        tr = f.train.sort_values(["user", "item"]).reset_index(drop=True)
        rng = np.random.default_rng(self.seed)
        # out-of-fold MF score for the training rows (3 folds within each user's ratings)
        oof = np.zeros(len(tr))
        fold = np.zeros(len(tr), int)
        for _, idx in tr.groupby("user").indices.items():
            fold[idx] = rng.permutation(np.arange(len(idx)) % 3)
        mf_params = {"dim": 8, "lam": 0.05}
        for k in range(3):
            inner = Fold(tr[fold != k], f.favorites, f.n_users, f.n_items, f.cat)
            mf = BiasedMF(seed=self.seed, **mf_params).fit(inner)
            rows = np.flatnonzero(fold == k)
            oof[rows] = mf.mu + mf.bu[tr.user.to_numpy()[rows]] + mf.bi[tr.item.to_numpy()[rows]] + np.einsum(
                "bd,bd->b", mf.P[tr.user.to_numpy()[rows]], mf.Q[tr.item.to_numpy()[rows]]
            )
        self.mf = BiasedMF(seed=self.seed, **mf_params).fit(f)
        # leave-one-out item mean / count for training rows; full mean for scoring
        s = np.bincount(tr.item, tr.rating, minlength=f.n_items)
        n = np.bincount(tr.item, minlength=f.n_items).astype(float)
        mu = tr.rating.mean()
        it, r = tr.item.to_numpy(), tr.rating.to_numpy(float)
        loo_mean = (s[it] - r + 3 * mu) / (n[it] - 1 + 3)
        self.item_mean = (s + 3 * mu) / (n + 3)
        self.item_n = n
        Xf = self._features(tr.user.to_numpy(), it, oof, loo_mean, n[it] - 1)
        group = tr.groupby("user", sort=True).size().to_numpy()
        self.model = lgb.LGBMRanker(
            objective="lambdarank",
            n_estimators=int(self.params.get("n_estimators", 200)),
            num_leaves=int(self.params.get("num_leaves", 15)),
            learning_rate=0.05,
            min_child_samples=20,
            label_gain=[0, 1, 2, 3, 4],
            lambdarank_truncation_level=10,
            random_state=self.seed,
            n_jobs=1,
            verbose=-1,
        )
        self.model.fit(Xf, (tr.rating.to_numpy() - 1).astype(int), group=group)
        return self

    def score(self, user: int, items: np.ndarray) -> np.ndarray:
        mf = self.mf.score(user, items)
        Xf = self._features(np.full(len(items), user), items, mf, self.item_mean[items], self.item_n[items])
        return self.model.predict(Xf)


MODELS: list[type[SurveyModel]] = [ShrunkMean, Bias, ContentFav, BiasedMF, BPRPairs, LightFMLogistic, LambdaMART]
BEST = "Best personalised (chọn trong CV trong)"


# ===================================================================================================== evaluation


def _assign_folds(sd: SurveyData, scenario: str, rows: pd.DataFrame, k: int, rng: np.random.Generator) -> np.ndarray:
    """Fold id of each row of `rows` (user, item, rating) for the scenario."""
    if scenario == "warm":
        fold = np.zeros(len(rows), int)
        for _, idx in rows.groupby("user").indices.items():
            fold[idx] = rng.permutation(np.arange(len(idx)) % k)
        return fold
    if scenario == "item_cold":
        items = np.unique(rows.item)
        f_item = {}
        for s in ("man", "rau", "canh"):
            its = rng.permutation(items[sd.cat.slots[items] == s])
            for j, it in enumerate(its):
                f_item[it] = j % k
        return rows.item.map(f_item).to_numpy()
    if scenario == "user_cold":
        users = rng.permutation(np.unique(rows.user))
        f_user = {u: j % k for j, u in enumerate(users)}
        return rows.user.map(f_user).to_numpy()
    raise ValueError(scenario)


def _score_users(model: SurveyModel, test: pd.DataFrame, slots: np.ndarray) -> dict[int, dict[str, float]]:
    out = {}
    for u, g in test.groupby("user"):
        items, y = g.item.to_numpy(), g.rating.to_numpy(float)
        s = model.score(int(u), items)
        rec = {"ndcg@5": metrics.ndcg_graded(y, s, 5), "auc": metrics.auc_pairs(y, s)}
        for sl in ("man", "rau", "canh"):
            m = slots[items] == sl
            rec[f"ndcg@5_{sl}"] = metrics.ndcg_graded(y[m], s[m], 5) if m.sum() >= 2 else float("nan")
        out[int(u)] = rec
    return out


def _fold_obj(sd: SurveyData, train: pd.DataFrame, scenario: str, test_users: np.ndarray) -> Fold:
    cold = frozenset(int(u) for u in test_users) if scenario == "user_cold" else frozenset()
    return Fold(train, sd.favorites, sd.n_users, sd.n_items, sd.cat, cold)


def _inner_select(sd: SurveyData, train: pd.DataFrame, scenario: str, cls: type[SurveyModel], seed: int, k_inner: int = 3):
    rng = np.random.default_rng(10_000 + seed)
    fold = _assign_folds(sd, scenario, train, k_inner, rng)
    best, best_score = None, -np.inf
    for params in cls.grid:
        vals = []
        for k in range(k_inner):
            tr, te = train[fold != k], train[fold == k]
            m = cls(seed=seed, **params).fit(_fold_obj(sd, tr, scenario, np.unique(te.user)))
            r = _score_users(m, te, sd.cat.slots)
            vals.append(np.nanmean([x["ndcg@5"] for x in r.values()]))
        sc = float(np.mean(vals))
        if sc > best_score:
            best, best_score = params, sc
    return best, best_score


def run_scenario(sd: SurveyData, scenario: str, seed: int, k_outer: int = 5, models: list | None = None,
                 log: Callable[[str], None] | None = None) -> dict:
    """One repetition (seed) of the nested CV for one scenario. Returns per-user metrics per model."""
    models = models or MODELS
    rng = np.random.default_rng(seed)
    rows = sd.ratings.reset_index(drop=True)
    fold = _assign_folds(sd, scenario, rows, k_outer, rng)
    per_model: dict[str, dict[int, list[dict]]] = {}
    chosen: dict[str, list] = {}
    for k in range(k_outer):
        tr, te = rows[fold != k], rows[fold == k]
        inner_scores = {}
        fitted = {}
        for cls in models:
            params, sc = _inner_select(sd, tr, scenario, cls, seed * 100 + k)
            m = cls(seed=seed * 100 + k, **params).fit(_fold_obj(sd, tr, scenario, np.unique(te.user)))
            res = _score_users(m, te, sd.cat.slots)
            for u, rec in res.items():
                per_model.setdefault(cls.name, {}).setdefault(u, []).append(rec)
            chosen.setdefault(cls.name, []).append({"fold": k, "params": params, "inner_ndcg@5": sc})
            inner_scores[cls.name] = sc
            fitted[cls.name] = res
        pers = [c.name for c in models if c.personalised]
        if pers:
            pick = max(pers, key=lambda n: inner_scores[n])
            for u, rec in fitted[pick].items():
                per_model.setdefault(BEST, {}).setdefault(u, []).append(rec)
            chosen.setdefault(BEST, []).append({"fold": k, "model": pick})
        if log:
            log(f"{scenario} seed={seed} fold={k} done")
    # average a user's folds (warm: a user appears in every fold; cold scenarios: once)
    agg = {
        name: {u: {key: float(np.nanmean([r[key] for r in recs])) if any(not np.isnan(r[key]) for r in recs) else float("nan")
                   for key in recs[0]} for u, recs in users.items()}
        for name, users in per_model.items()
    }
    return {"scenario": scenario, "seed": seed, "per_user": agg, "chosen": chosen}


def summarise(runs: list[dict], baseline: str = "ShrunkMean") -> dict:
    """Mean ± sd over seeds of the user-mean metrics; per-user (seed-averaged) paired bootstrap vs the baseline."""
    names = list(runs[0]["per_user"])
    keys = list(next(iter(runs[0]["per_user"][names[0]].values())))
    out = {"models": {}, "comparisons": {}}
    for name in names:
        per_seed = {key: [float(np.nanmean([r[key] for r in run["per_user"][name].values()])) for run in runs] for key in keys}
        out["models"][name] = {key: {"mean": float(np.mean(v)), "sd": float(np.std(v, ddof=1)) if len(v) > 1 else 0.0} for key, v in per_seed.items()}
    users = sorted(set.intersection(*[set(run["per_user"][baseline]) for run in runs]))

    def user_mean(name, key):
        return np.array([np.nanmean([run["per_user"][name].get(u, {}).get(key, np.nan) for run in runs]) for u in users])

    for key in ("ndcg@5", "auc"):
        base = user_mean(baseline, key)
        comp = {}
        for name in names:
            if name == baseline:
                continue
            comp[name] = stats.paired_bootstrap(user_mean(name, key), base, n_boot=5000, seed=7)
        others = [n for n in comp if n != BEST]
        adj = stats.holm([comp[n]["p"] for n in others]) if others else []
        for n, a in zip(others, adj, strict=True):
            comp[n]["p_holm"] = float(a)
        if BEST in comp:
            comp[BEST]["role"] = "primary comparison (not in the Holm family)"
        out["comparisons"][key] = comp
    out["n_users"] = len(users)
    return out


# ===================================================================================================== CLI

OUT = kb_catalog.REPO / "data" / "processed" / "recsys"
SCENARIOS = ("warm", "item_cold", "user_cold")


def _job(args: tuple) -> dict:
    source, scenario, seed = args
    sd = load_export(Path(source)) if source != "simulate" else simulate(kb_catalog.load())
    return run_scenario(sd, scenario, seed)


def run(source: str = "simulate", seeds: tuple[int, ...] = (0, 1, 2, 3, 4), workers: int = 8) -> dict:
    """source = 'simulate' or a survey export directory. Writes survey_<sim|real>.json under data/processed/recsys."""
    from concurrent.futures import ProcessPoolExecutor

    sd = load_export(Path(source)) if source != "simulate" else simulate(kb_catalog.load())
    jobs = [(source, sc, s) for sc in SCENARIOS for s in seeds]
    with ProcessPoolExecutor(max_workers=workers) as ex:
        runs = list(ex.map(_job, jobs))
    out = {
        "SIMULATED": sd.simulated,
        "label": "MÔ PHỎNG — chỉ kiểm đường ống, không phải kết quả" if sd.simulated else "dữ liệu khảo sát thật",
        "data": {
            "n_users": sd.n_users,
            "n_items": sd.n_items,
            "n_ratings": int(len(sd.ratings)),
            "n_never_eaten": int(len(sd.never)),
            "rating_hist": {str(int(k)): int(v) for k, v in sd.ratings.rating.value_counts().sort_index().items()},
            "ratings_per_user_mean": float(sd.ratings.groupby("user").size().mean()),
            **sd.meta,
        },
        "seeds": list(seeds),
        "scenarios": {},
    }
    for sc in SCENARIOS:
        rs = [r for r in runs if r["scenario"] == sc]
        out["scenarios"][sc] = summarise(rs) | {"chosen": {r["seed"]: r["chosen"] for r in rs}}
    name = "survey_sim.json" if sd.simulated else "survey_real.json"
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(out, indent=1, ensure_ascii=False, default=float) + "\n", encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Survey taste-ranking nested CV")
    ap.add_argument("source", nargs="?", default="simulate", help="'simulate' or a `tastoria survey export` directory")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args(argv)
    out = run(a.source, workers=a.workers)
    for sc, res in out["scenarios"].items():
        print(sc)
        for n, v in res["models"].items():
            print(f"  {n:45s} NDCG@5 {v['ndcg@5']['mean']:.3f}±{v['ndcg@5']['sd']:.3f}  AUC {v['auc']['mean']:.3f}±{v['auc']['sd']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
