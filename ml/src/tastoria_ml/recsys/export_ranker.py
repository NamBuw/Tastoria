"""Deterministic pure-NumPy Learned Ranker export and inference (`deploy/models/ranker/`).

Training uses `kb_catalog` + `survey.simulate` (or an exported real survey) to fit `HybridFactorRanker`
(`BiasedMF` + `BPRPairs` + `ContentFav` + `ShrunkMean`) and exports `model.npz` (`allow_pickle=False`),
`serving.json`, `metrics.json`, and `version` for `tastoria mlops register ranker`.

Runtime inference (`ExportedNumpyRanker`) depends ONLY on `numpy` and the Python standard library so
`tastoria-backend` can serve it without `scipy`, `pandas`, or `lightgbm`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[4]
DEFAULT_DEPLOY_DIR = REPO / "deploy" / "models" / "ranker"
RANKER_VERSION = "ranker_hybrid_v1"
SIMULATION_NOTICE = (
    "MÔ PHỎNG — huấn luyện trên survey_sim (seed=20261018), chỉ kiểm đường ống và hợp đồng phục vụ, "
    "không đại diện thị hiếu thật của người Việt."
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def kb_publishability_audit(kb_dir: Path | None = None) -> dict[str, Any]:
    """Audit `180` KB recipes vs `171` publishable DB recipes using the exact catalog importer rules.

    Rule (`backend/src/tastoria/modules/catalog/bundle.py:586-601`, FR-25-08 / FR-25-12):
    A recipe is `published` iff `len(sources) >= 2` AND every non-seasoning, non-optional ingredient
    has `comp_source.source is not None`.
    """
    from tastoria_ml.kb.recipes import load_proposed, load_recipes
    from tastoria_ml.kb.validate import load_kb

    root = Path(kb_dir) if kb_dir is not None else (REPO / "data" / "kb")
    kb, errs = load_kb(root)
    if kb is None:
        raise ValueError(f"KB load failed: {errs}")
    ings = {i.name_vi: i for i in kb.ingredients.ingredients}
    proposed, perrs = load_proposed(root)
    if perrs:
        raise ValueError(f"KB proposed ingredients failed: {perrs}")
    for p in proposed:
        ings.setdefault(p.name_vi, p)
    rep = load_recipes(root)
    if rep.errors:
        raise ValueError(f"KB recipes failed: {rep.errors}")

    recipes = sorted(rep.recipes.values(), key=lambda r: (r.slot, r.slug))
    publishable_by_slug: dict[str, bool] = {}
    draft_recipes: list[dict[str, Any]] = []
    by_slot_total: dict[str, int] = {}
    by_slot_pub: dict[str, int] = {}

    for rec in recipes:
        by_slot_total[rec.slot] = by_slot_total.get(rec.slot, 0) + 1
        reasons: list[str] = []
        if len(rec.sources) < 2:
            reasons.append(f"sources={len(rec.sources)} (< 2)")
        unmapped = [
            it.name
            for it in rec.ingredients
            if it.name in ings and ings[it.name].comp_source.source is None and it.role != "seasoning" and not it.optional
        ]
        if unmapped:
            reasons.append(f"unmapped_comp_source: {', '.join(unmapped)}")
        is_pub = len(reasons) == 0
        publishable_by_slug[rec.slug] = is_pub
        if is_pub:
            by_slot_pub[rec.slot] = by_slot_pub.get(rec.slot, 0) + 1
        else:
            draft_recipes.append(
                {
                    "slug": rec.slug,
                    "name_vi": rec.name_vi,
                    "slot": rec.slot,
                    "n_sources": len(rec.sources),
                    "unmapped_ingredients": unmapped,
                    "reasons": reasons,
                }
            )

    return {
        "n_kb_total": len(recipes),
        "n_publishable": sum(1 for v in publishable_by_slug.values() if v),
        "n_draft": len(draft_recipes),
        "by_slot_total": dict(sorted(by_slot_total.items())),
        "by_slot_publishable": dict(sorted(by_slot_pub.items())),
        "publishable_by_slug": publishable_by_slug,
        "draft_recipes": draft_recipes,
    }


def _cosine_matrix_vec(mat: np.ndarray, vec: np.ndarray) -> np.ndarray:
    na = np.linalg.norm(mat, axis=1)
    nb = float(np.linalg.norm(vec))
    out = np.zeros(len(mat), dtype=np.float64)
    ok = (na > 0.0) & (nb > 0.0)
    if np.any(ok):
        out[ok] = (mat[ok] @ vec) / (na[ok] * nb)
    return out


def _signal_pos_neg(sig: Any) -> tuple[int, int]:
    if sig is None:
        return 0, 0
    if isinstance(sig, dict):
        return int(sig.get("positive", 0)), int(sig.get("negative", 0))
    return int(getattr(sig, "positive", 0)), int(getattr(sig, "negative", 0))


@dataclass
class ExportedNumpyRanker:
    """Pure-NumPy Ranker loaded from `deploy/models/ranker/{model.npz,serving.json}`."""

    serving: dict[str, Any]
    recipe_names: list[str]
    recipe_slots: list[str]
    recipe_slugs: list[str]
    publishable: np.ndarray
    feature_names: list[str]
    X_content: np.ndarray
    item_prior: np.ndarray
    mf_mu: float
    mf_lam: float
    mf_bi: np.ndarray
    mf_Q: np.ndarray
    bpr_b: np.ndarray
    bpr_Q: np.ndarray
    norm_stats: np.ndarray  # [mf_mu, mf_sd, bpr_mu, bpr_sd, cnt_mu, cnt_sd, pop_mu, pop_sd]
    hybrid_weights: np.ndarray  # [w_mf, w_bpr, w_cnt, w_pop]

    def __post_init__(self) -> None:
        self._name_to_idx: dict[str, int] = {n: i for i, n in enumerate(self.recipe_names)}
        self._slot_name_to_idx: dict[tuple[str, str], int] = {
            (n, s): i for i, (n, s) in enumerate(zip(self.recipe_names, self.recipe_slots, strict=True))
        }
        self._slug_to_idx: dict[str, int] = {s: i for i, s in enumerate(self.recipe_slugs)}
        self._feat_to_col: dict[str, int] = {f: j for j, f in enumerate(self.feature_names)}

    @classmethod
    def load(cls, model_dir: Path | str = DEFAULT_DEPLOY_DIR, verify_sha256: bool = True) -> ExportedNumpyRanker:
        mdir = Path(model_dir)
        serving_path = mdir / "serving.json"
        if not serving_path.exists():
            raise FileNotFoundError(f"serving.json not found in {mdir}")
        serving = json.loads(serving_path.read_text(encoding="utf-8"))
        npz_path = mdir / serving.get("artifact_file", "model.npz")
        if not npz_path.exists():
            raise FileNotFoundError(f"artifact not found: {npz_path}")
        if verify_sha256:
            expected = serving["artifact_sha256"]
            actual = sha256_file(npz_path)
            if actual != expected:
                raise ValueError(f"SHA-256 mismatch for {npz_path}: expected {expected}, got {actual}")

        with np.load(npz_path, allow_pickle=False) as z:
            return cls(
                serving=serving,
                recipe_names=[str(x) for x in z["recipe_names"]],
                recipe_slots=[str(x) for x in z["recipe_slots"]],
                recipe_slugs=[str(x) for x in z["recipe_slugs"]],
                publishable=np.asarray(z["publishable"], dtype=np.uint8),
                feature_names=[str(x) for x in z["feature_names"]],
                X_content=np.asarray(z["X_content"], dtype=np.float64),
                item_prior=np.asarray(z["item_prior"], dtype=np.float64),
                mf_mu=float(z["mf_mu"]),
                mf_lam=float(z["mf_lam"]),
                mf_bi=np.asarray(z["mf_bi"], dtype=np.float64),
                mf_Q=np.asarray(z["mf_Q"], dtype=np.float64),
                bpr_b=np.asarray(z["bpr_b"], dtype=np.float64),
                bpr_Q=np.asarray(z["bpr_Q"], dtype=np.float64),
                norm_stats=np.asarray(z["norm_stats"], dtype=np.float64),
                hybrid_weights=np.asarray(z["hybrid_weights"], dtype=np.float64),
            )

    def resolve_index(self, item: Any) -> int | None:
        if isinstance(item, (int, np.integer)):
            idx = int(item)
            return idx if 0 <= idx < len(self.recipe_names) else None
        if isinstance(item, str):
            if item in self._name_to_idx:
                return self._name_to_idx[item]
            if item in self._slug_to_idx:
                return self._slug_to_idx[item]
            return None
        if isinstance(item, dict):
            name_vi = item.get("name_vi")
            slot = item.get("slot")
            slug = item.get("slug")
        else:
            name_vi = getattr(item, "name_vi", None)
            slot = getattr(item, "slot", None)
            slug = getattr(item, "slug", None)
        if name_vi is not None and slot is not None and (name_vi, slot) in self._slot_name_to_idx:
            return self._slot_name_to_idx[(name_vi, slot)]
        if name_vi is not None and name_vi in self._name_to_idx:
            return self._name_to_idx[name_vi]
        if slug is not None and slug in self._slug_to_idx:
            return self._slug_to_idx[slug]
        return None

    def featurize(self, item: Any) -> np.ndarray:
        idx = self.resolve_index(item)
        if idx is not None and not (isinstance(item, dict) and "features" in item):
            return self.X_content[idx].copy()

        vec = np.zeros(len(self.feature_names), dtype=np.float64)
        if isinstance(item, dict) and "features" in item:
            for k, v in item["features"].items():
                if k in self._feat_to_col:
                    vec[self._feat_to_col[k]] = float(v)
            return vec

        # Duck-typed RecipeView (backend) or KB Recipe
        if isinstance(item, dict):
            method = item.get("method_code") or item.get("method")
            tags = item.get("tag_codes") or item.get("tags") or []
            lines = item.get("lines") or item.get("ingredients") or []
        else:
            method = getattr(item, "method_code", None) or getattr(item, "method", None)
            tags = getattr(item, "tag_codes", None)
            if tags is None:
                tags = getattr(item, "tags", []) or []
            lines = getattr(item, "lines", None)
            if lines is None:
                lines = getattr(item, "ingredients", []) or []

        if method:
            mk = f"method:{method}"
            if mk in self._feat_to_col:
                vec[self._feat_to_col[mk]] = 1.0
        for t in tags:
            tk = f"tag:{t}"
            if tk in self._feat_to_col:
                vec[self._feat_to_col[tk]] = 0.5
        for ln in lines:
            if isinstance(ln, dict):
                role = ln.get("role")
                ing_obj = ln.get("ingredient")
                if isinstance(ing_obj, dict):
                    ing_name = ing_obj.get("name_vi")
                    is_staple = bool(ing_obj.get("is_staple", False))
                else:
                    ing_name = ln.get("name") or ln.get("name_vi")
                    is_staple = bool(ln.get("is_staple", False))
            else:
                role = getattr(ln, "role", None)
                ing_obj = getattr(ln, "ingredient", None)
                if ing_obj is not None:
                    ing_name = getattr(ing_obj, "name_vi", None)
                    is_staple = bool(getattr(ing_obj, "is_staple", False))
                else:
                    ing_name = getattr(ln, "name", None) or getattr(ln, "name_vi", None)
                    is_staple = bool(getattr(ln, "is_staple", False))
            if ing_name and role != "seasoning" and not is_staple:
                ik = f"ing:{ing_name}"
                if ik in self._feat_to_col:
                    vec[self._feat_to_col[ik]] = 1.0
        return vec

    def fold_in_user(self, favorites: Sequence[Any]) -> tuple[np.ndarray, float, np.ndarray, np.ndarray]:
        fav_idx = [i for f in favorites if (i := self.resolve_index(f)) is not None]
        d_mf = self.mf_Q.shape[1]
        if fav_idx:
            fi = np.asarray(fav_idx, dtype=np.int64)
            A = np.hstack([np.ones((len(fi), 1), dtype=np.float64), self.mf_Q[fi]])
            y = 5.0 - self.mf_mu - self.mf_bi[fi]
            reg = max(self.mf_lam, 1e-3) * len(fi) * np.eye(d_mf + 1, dtype=np.float64)
            sol = np.linalg.solve(A.T @ A + reg, A.T @ y)
            bu_mf = float(sol[0])
            pu_mf = sol[1:]
            pu_bpr = self.bpr_Q[fi].mean(axis=0)
        else:
            bu_mf = 0.0
            pu_mf = np.zeros(d_mf, dtype=np.float64)
            pu_bpr = np.zeros(self.bpr_Q.shape[1], dtype=np.float64)

        if favorites:
            fav_vecs = np.vstack([self.featurize(f) for f in favorites])
            fav_prof = fav_vecs.mean(axis=0)
        else:
            fav_prof = np.zeros(len(self.feature_names), dtype=np.float64)
        return pu_mf, bu_mf, pu_bpr, fav_prof

    def score_indices(self, fav_indices: Sequence[int], item_indices: Sequence[int]) -> np.ndarray:
        """Exact vectorized score over known KB indices (matches HybridFactorRanker user_cold fold-in)."""
        return self.score(list(fav_indices), list(item_indices))

    def score(
        self,
        favorites: Sequence[Any],
        candidates: Sequence[Any],
        popularity: dict[Any, Any] | None = None,
        personal: dict[Any, Any] | None = None,
        popularity_weight: float | None = None,
        personal_weight: float | None = None,
    ) -> np.ndarray:
        if len(candidates) == 0:
            return np.zeros(0, dtype=np.float64)
        pu_mf, bu_mf, pu_bpr, fav_prof = self.fold_in_user(favorites)

        n = len(candidates)
        s_mf = np.empty(n, dtype=np.float64)
        s_bpr = np.empty(n, dtype=np.float64)
        s_pop = np.empty(n, dtype=np.float64)
        X_cand = np.empty((n, len(self.feature_names)), dtype=np.float64)

        for k, cand in enumerate(candidates):
            idx = self.resolve_index(cand)
            if idx is not None:
                s_mf[k] = self.mf_mu + bu_mf + self.mf_bi[idx] + float(self.mf_Q[idx] @ pu_mf)
                s_bpr[k] = self.bpr_b[idx] + float(self.bpr_Q[idx] @ pu_bpr)
                s_pop[k] = self.item_prior[idx]
                X_cand[k] = self.X_content[idx]
            else:
                # Unseen item fallback: user bias + global mean + live content features
                s_mf[k] = self.mf_mu + bu_mf
                s_bpr[k] = 0.0
                s_pop[k] = self.mf_mu
                X_cand[k] = self.featurize(cand)

        s_cnt = _cosine_matrix_vec(X_cand, fav_prof)

        mf_mu, mf_sd, bpr_mu, bpr_sd, cnt_mu, cnt_sd, pop_mu, pop_sd = self.norm_stats
        w_mf, w_bpr, w_cnt, w_pop = self.hybrid_weights
        base = (
            w_mf * ((s_mf - mf_mu) / mf_sd)
            + w_bpr * ((s_bpr - bpr_mu) / bpr_sd)
            + w_cnt * ((s_cnt - cnt_mu) / cnt_sd)
            + w_pop * ((s_pop - pop_mu) / pop_sd)
        )

        blend_cfg = self.serving.get("live_signal_blending", {})
        pop_w = float(blend_cfg.get("popularity_weight", 0.0) if popularity_weight is None else popularity_weight)
        pers_w = float(blend_cfg.get("personal_weight", 0.25) if personal_weight is None else personal_weight)
        shrink_k = float(blend_cfg.get("shrink_k", 5.0))

        if popularity is not None and pop_w != 0.0:
            pop_adj = np.empty(n, dtype=np.float64)
            for k, cand in enumerate(candidates):
                key = getattr(cand, "id", cand if not isinstance(cand, dict) else cand.get("id"))
                pos, neg = _signal_pos_neg(popularity.get(key))
                pop_adj[k] = (pos + shrink_k * 0.5) / (pos + neg + shrink_k)
            base = base + pop_w * pop_adj

        if personal is not None and pers_w != 0.0:
            pers_adj = np.zeros(n, dtype=np.float64)
            for k, cand in enumerate(candidates):
                key = getattr(cand, "id", cand if not isinstance(cand, dict) else cand.get("id"))
                sig = personal.get(key)
                if sig is not None:
                    pos, neg = _signal_pos_neg(sig)
                    tot = pos + neg
                    if tot > 0:
                        pers_adj[k] = (pos - neg) / tot
            base = base + pers_w * pers_adj

        if not np.isfinite(base).all():
            raise ValueError("ExportedNumpyRanker produced non-finite scores")
        return base

    def score_map(
        self,
        favorites: Sequence[Any],
        candidates: Sequence[Any],
        popularity: dict[Any, Any] | None = None,
        personal: dict[Any, Any] | None = None,
    ) -> dict[Any, float]:
        vals = self.score(favorites, candidates, popularity=popularity, personal=personal)
        out: dict[Any, float] = {}
        for cand, val in zip(candidates, vals, strict=True):
            key = getattr(cand, "id", cand if not isinstance(cand, dict) else cand.get("id", cand.get("name_vi")))
            if key is None:
                key = getattr(cand, "name_vi", cand)
            out[key] = float(val)
        return out


def _select_hybrid_weights_cv(sd, seed: int) -> tuple[dict[str, float], dict[str, float]]:
    """Select HybridFactorRanker blend weights via 3-fold CV across warm + user_cold on `sd`."""
    from tastoria_ml.recsys import metrics, survey

    best_params: dict[str, float] | None = None
    best_score = -np.inf
    cv_summary: dict[str, float] = {}
    rng_w = np.random.default_rng(seed)
    rng_u = np.random.default_rng(seed + 1)
    rows = sd.ratings.reset_index(drop=True)
    f_warm = survey._assign_folds(sd, "warm", rows, 3, rng_w)
    f_ucold = survey._assign_folds(sd, "user_cold", rows, 3, rng_u)

    for params in survey.HybridFactorRanker.grid:
        vals_w, vals_u = [], []
        for k in range(3):
            tr_w, te_w = rows[f_warm != k], rows[f_warm == k]
            m_w = survey.HybridFactorRanker(seed=seed + k, **params).fit(
                survey._fold_obj(sd, tr_w, "warm", np.unique(te_w.user))
            )
            r_w = survey._score_users(m_w, te_w, sd.cat.slots)
            vals_w.append(float(np.nanmean([x["ndcg@5"] for x in r_w.values()])))

            tr_u, te_u = rows[f_ucold != k], rows[f_ucold == k]
            m_u = survey.HybridFactorRanker(seed=seed + 10 + k, **params).fit(
                survey._fold_obj(sd, tr_u, "user_cold", np.unique(te_u.user))
            )
            r_u = survey._score_users(m_u, te_u, sd.cat.slots)
            vals_u.append(float(np.nanmean([x["ndcg@5"] for x in r_u.values()])))

        sc = 0.5 * float(np.mean(vals_w)) + 0.5 * float(np.mean(vals_u))
        if sc > best_score:
            best_score = sc
            best_params = dict(params)
            cv_summary = {
                "cv3_warm_ndcg@5": float(np.mean(vals_w)),
                "cv3_user_cold_ndcg@5": float(np.mean(vals_u)),
                "cv3_combined_ndcg@5": sc,
            }
    assert best_params is not None
    return best_params, cv_summary


def train_and_export(
    output_dir: Path | str = DEFAULT_DEPLOY_DIR,
    seed: int = 20261018,
    weights: tuple[float, float, float, float] | None = None,
    cv_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Train HybridFactorRanker on full KB + simulated survey (`seed`) and export `deploy/models/ranker/`."""
    from tastoria_ml.recsys import kb_catalog, survey

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cat = kb_catalog.load()
    sd = survey.simulate(cat, seed=seed)
    kb_audit = kb_publishability_audit()

    if weights is None:
        best_params, sel_cv = _select_hybrid_weights_cv(sd, seed=seed)
    else:
        best_params = {
            "w_mf": float(weights[0]),
            "w_bpr": float(weights[1]),
            "w_cnt": float(weights[2]),
            "w_pop": float(weights[3]),
        }
        sel_cv = {}

    full_fold = survey.Fold(sd.ratings, sd.favorites, sd.n_users, sd.n_items, cat)
    model = survey.HybridFactorRanker(seed=seed, **best_params).fit(full_fold)

    pub_mask = np.array([1 if kb_audit["publishable_by_slug"].get(r.slug, False) else 0 for r in cat.recipes], dtype=np.uint8)
    norm_stats = np.array(
        [
            model.mf_mu,
            model.mf_sd,
            model.bpr_mu,
            model.bpr_sd,
            model.cnt_mu,
            model.cnt_sd,
            model.pop_mu,
            model.pop_sd,
        ],
        dtype=np.float64,
    )
    hybrid_weights = np.array(model.weights(), dtype=np.float32)

    npz_path = out_dir / "model.npz"
    np.savez(
        npz_path,
        schema_version=np.array(["ranker.npz.v1"]),
        model_type=np.array(["hybrid_factor_ranker"]),
        recipe_names=np.array([r.name_vi for r in cat.recipes]),
        recipe_slots=np.array([r.slot for r in cat.recipes]),
        recipe_slugs=np.array([r.slug for r in cat.recipes]),
        publishable=pub_mask,
        feature_names=np.array(cat.feature_names),
        X_content=cat.X.astype(np.float32),
        item_prior=model.pop.s.astype(np.float32),
        mf_mu=np.array(model.mf.mu, dtype=np.float64),
        mf_lam=np.array(model.mf.lam, dtype=np.float64),
        mf_bi=model.mf.bi.astype(np.float32),
        mf_Q=model.mf.Q.astype(np.float32),
        bpr_b=model.bpr.b.astype(np.float32),
        bpr_Q=model.bpr.Q.astype(np.float32),
        norm_stats=norm_stats,
        hybrid_weights=hybrid_weights,
        seed=np.array(seed, dtype=np.int64),
    )

    # Verify strict allow_pickle=False & zero object dtypes
    with np.load(npz_path, allow_pickle=False) as check_z:
        for k in check_z.files:
            if check_z[k].dtype == object:
                raise AssertionError(f"object dtype forbidden in {npz_path}: key={k}")

    art_sha = sha256_file(npz_path)

    metrics_payload: dict[str, Any] = {
        "SIMULATED": True,
        "simulation_notice": SIMULATION_NOTICE,
        "version": RANKER_VERSION,
        "model_type": "hybrid_factor_ranker",
        "weights": {
            "w_mf": float(hybrid_weights[0]),
            "w_bpr": float(hybrid_weights[1]),
            "w_cnt": float(hybrid_weights[2]),
            "w_pop": float(hybrid_weights[3]),
        },
        "selection_cv": sel_cv,
        "cv_metrics": cv_metrics or {},
        "kb_alignment": {
            "n_kb_total": kb_audit["n_kb_total"],
            "n_publishable": kb_audit["n_publishable"],
            "n_draft": kb_audit["n_draft"],
        },
    }

    serving_payload: dict[str, Any] = {
        "schema_version": "ranker.serving.v1",
        "name": "ranker",
        "version": RANKER_VERSION,
        "model_type": "hybrid_factor_ranker",
        "artifact_file": "model.npz",
        "artifact_sha256": art_sha,
        "SIMULATED": True,
        "simulation_notice": SIMULATION_NOTICE,
        "training_data": {
            "source": "survey_sim",
            "seed": seed,
            "n_users": sd.n_users,
            "n_ratings": int(len(sd.ratings)),
            "n_never_eaten": int(len(sd.never)),
            "n_kb_recipes": kb_audit["n_kb_total"],
            "n_published_db_recipes": kb_audit["n_publishable"],
            "n_draft_db_recipes": kb_audit["n_draft"],
        },
        "recipe_identity": {
            "primary_key": "name_vi",
            "secondary_key": "slot",
            "slots": ["man", "rau", "canh"],
        },
        "feature_schema": {
            "content_prefixes": {
                "ing:": {"weight": 1.0, "exclude_roles": ["seasoning"], "exclude_staples": True},
                "method:": {"weight": 1.0},
                "tag:": {"weight": 0.5},
            },
            "n_content_features": len(cat.feature_names),
            "feature_names_in_npz": "feature_names",
        },
        "inference": {
            "allow_pickle": False,
            "mf_fold_in_target_rating": 5.0,
            "mf_fold_in_min_lam": 0.001,
            "unseen_item_fallback": "content_plus_global_mean",
            "percentile_per_slot": True,
        },
        "live_signal_blending": {
            "popularity_weight": 0.0,
            "personal_weight": 0.25,
            "shrink_k": 5.0,
            "consent_purpose": "personalization",
        },
        "metrics": metrics_payload,
    }

    (out_dir / "serving.json").write_text(json.dumps(serving_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "metrics.json").write_text(json.dumps(metrics_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "version").write_text(f"{RANKER_VERSION}\n", encoding="utf-8")

    # Verify loaded ExportedNumpyRanker parity with HybridFactorRanker cold-user fold-in
    loaded = ExportedNumpyRanker.load(out_dir, verify_sha256=True)
    fav0 = sd.favorites[0]
    model.mf.P[0], model.mf.bu[0] = model.mf._fold_in(fav0)
    model.bpr.P[0] = model.bpr.Q[fav0].mean(0) if len(fav0) else 0.0
    all_items = np.arange(sd.n_items)
    expected_scores = model.score(0, all_items)
    actual_scores = loaded.score_indices(fav0.tolist(), all_items.tolist())
    max_abs_diff = float(np.max(np.abs(expected_scores - actual_scores)))
    if not math.isfinite(max_abs_diff) or max_abs_diff > 1e-4:
        raise AssertionError(f"ExportedNumpyRanker parity check failed: max_abs_diff={max_abs_diff}")

    return {
        "output_dir": str(out_dir),
        "artifact_sha256": art_sha,
        "version": RANKER_VERSION,
        "weights": metrics_payload["weights"],
        "parity_max_abs_diff": max_abs_diff,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Train and export deterministic pure-NumPy Learned Ranker.")
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_DEPLOY_DIR)
    ap.add_argument("--seed", type=int, default=20261018)
    args = ap.parse_args(argv)
    res = train_and_export(output_dir=args.out_dir, seed=args.seed)
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
