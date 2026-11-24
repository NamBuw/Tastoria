"""Milestone M1.3a confirmatory and exploratory study runner for Problem 3 (Recommender Systems).

Implements `TASTORIA-ML-PREREG-2026-11-18` (docs/reports/hoc-may/research_protocol.md):
- Never mutates locked baseline files in `data/processed/recsys/`.
- Emits structured JSON/CSV artifacts under `ml/runs/research/p3_recsys/`:
    * `manifest.json`
    * `foodcom_baseline_ref.json` (`analysis_intent="baseline_reproduction"`)
    * `foodcom_confirmatory.json` + `foodcom_confirmatory_pairs.csv` (`analysis_intent="confirmatory"`, H3b)
    * `foodcom_exploratory.json` (`analysis_intent="exploratory"`, Exploratory #5)
    * `kb_db_alignment.json` (`analysis_intent="exploratory"`, Exploratory #5)
    * `survey_confirmatory.json` + `survey_confirmatory_pairs.csv` (`SIMULATED=true`, `analysis_intent="confirmatory"`, H3a)
    * `sanity_controls.json`
    * `summary.json`

Run on `171.226.10.153`:
    CUDA_VISIBLE_DEVICES= OPENBLAS_NUM_THREADS=1 uv run --frozen --package tastoria-ml python -m tastoria_ml.recsys.research
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import platform
import subprocess
import sys
import time
from importlib import metadata
from pathlib import Path
from typing import Any

import numpy as np
import scipy.sparse as sp

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

from tastoria_ml.recsys import data, export_ranker, kb_catalog, metrics, models, stats, survey  # noqa: E402

REPO = data.REPO
PROTOCOL_ID = "TASTORIA-ML-PREREG-2026-11-18"
BASELINE_DIR = REPO / "data" / "processed" / "recsys"
BASELINE_CACHE = BASELINE_DIR / "cache"
OUT_DIR = REPO / "ml" / "runs" / "research" / "p3_recsys"
CACHE_DIR = OUT_DIR / "cache"
SEEDS = (0, 1, 2, 3, 4)
K = 10
Z_MDE_80 = 1.959963984540054 + 0.8416212335729143  # norm.ppf(0.975) + norm.ppf(0.80) = 2.8015852...


def _log(*args: object) -> None:
    print(time.strftime("%H:%M:%S"), "[p3_research]", *args, flush=True)


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=float) + "\n", encoding="utf-8")


def _d_mde(n_eff: int) -> float:
    return float(Z_MDE_80 / math.sqrt(n_eff)) if n_eff > 0 else float("nan")


def descriptives(arr: np.ndarray, floor_val: float = 0.0, ceil_val: float = 1.0) -> dict[str, float | int]:
    arr = np.asarray(arr, dtype=float)
    n_missing = int(np.isnan(arr).sum())
    v = arr[~np.isnan(arr)]
    n = int(len(v))
    if n == 0:
        return {
            "n": 0,
            "n_missing": n_missing,
            "mean": float("nan"),
            "sd": float("nan"),
            "median": float("nan"),
            "iqr": float("nan"),
            "floor_count": 0,
            "ceiling_count": 0,
        }
    q25, med, q75 = np.percentile(v, [25.0, 50.0, 75.0])
    return {
        "n": n,
        "n_missing": n_missing,
        "mean": float(np.mean(v)),
        "sd": float(np.std(v, ddof=1)) if n > 1 else 0.0,
        "median": float(med),
        "iqr": float(q75 - q25),
        "floor_count": int(np.sum(np.isclose(v, floor_val, atol=1e-9))),
        "ceiling_count": int(np.sum(np.isclose(v, ceil_val, atol=1e-9))),
    }


def paired_report(
    a: np.ndarray,
    b: np.ndarray,
    seed: int = 0,
    n_boot: int = 2000,
    binary_a: np.ndarray | None = None,
    binary_b: np.ndarray | None = None,
) -> dict[str, Any]:
    """Complete `tastoria_ml.stats` bundle for paired arrays (no post-hoc observed power)."""
    out: dict[str, Any] = {
        "desc_a": descriptives(a),
        "desc_b": descriptives(b),
        "assumptions": stats.check_paired_assumptions(a, b),
        "paired_bootstrap": stats.paired_bootstrap(a, b, n_boot=n_boot, seed=seed),
        "wilcoxon": stats.wilcoxon(a, b),
        "cohens_dz": stats.cohens_dz(a, b, n_boot=n_boot, seed=seed),
    }
    if binary_a is not None and binary_b is not None:
        out["mcnemar"] = stats.mcnemar(binary_a, binary_b)
    return out


def _baseline_slug(label: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in label).strip("_").lower()


# ----------------------------------------------------------------------------------------------------- 1. Manifest


def build_manifest(out_dir: Path = OUT_DIR) -> dict[str, Any]:
    try:
        commit = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    except OSError:
        commit = ""

    libs: dict[str, str] = {}
    for pkg in (
        "numpy",
        "scipy",
        "pandas",
        "scikit-learn",
        "lightgbm",
        "implicit",
        "lightfm-next",
        "threadpoolctl",
        "pyyaml",
        "pydantic",
    ):
        try:
            libs[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            libs[pkg] = "not_installed"

    sha_targets = {
        "foodcom_interactions_parquet": REPO / "data" / "processed" / "foodcom" / "interactions.parquet",
        "foodcom_recipes_parquet": REPO / "data" / "processed" / "foodcom" / "recipes.parquet",
        "kb_recipe_nutrition_csv": REPO / "data" / "processed" / "kb" / "recipe_nutrition.csv",
        "locked_recsys_manifest": BASELINE_DIR / "manifest.json",
        "locked_recsys_test": BASELINE_DIR / "test.json",
        "locked_recsys_cold": BASELINE_DIR / "cold.json",
        "locked_recsys_survey_sim": BASELINE_DIR / "survey_sim.json",
    }
    dataset_sha256 = {
        k: export_ranker.sha256_file(p) if p.exists() else None for k, p in sha_targets.items()
    }

    kb_audit = export_ranker.kb_publishability_audit()
    obj = {
        "protocol_id": PROTOCOL_ID,
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_commit": commit,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "threads": models.N_THREADS,
        "libraries": libs,
        "seeds": {
            "foodcom_val": 0,
            "foodcom_test": list(SEEDS),
            "survey_sim": 20261018,
            "survey_cv": list(SEEDS),
        },
        "dataset_sha256": dataset_sha256,
        "kb_recipe_counts": {
            "total": kb_audit["n_kb_total"],
            "publishable": kb_audit["n_publishable"],
            "draft": kb_audit["n_draft"],
            "by_slot_total": kb_audit["by_slot_total"],
            "by_slot_publishable": kb_audit["by_slot_publishable"],
            "draft_recipes": kb_audit["draft_recipes"],
        },
        "mde_sensitivity": {
            "observed_power_computed": False,
            "note": "Post-hoc observed power is strictly prohibited; MDE reported at 80% power, two-sided alpha=0.05.",
            "foodcom_warm": {"n_eff": 4834, "alpha": 0.05, "power": 0.80, "d_mde": _d_mde(4834)},
            "foodcom_cold": {"n_eff": 422, "alpha": 0.05, "power": 0.80, "d_mde": _d_mde(422)},
            "vn_survey": {
                "n_eff": 90,
                "alpha": 0.05,
                "power": 0.80,
                "d_mde": _d_mde(90),
                "small_sample_note": "Underpowered for |d_z| < 0.30; interpret via 95% CIs.",
            },
        },
    }
    _write_json(out_dir / "manifest.json", obj)
    return obj


# ----------------------------------------------------------------------------------------------------- 2. Food.com Ctx


class StudyCtx:
    def __init__(self) -> None:
        _log("loading Food.com dataset and item features...")
        self.d = data.load()
        self.F, self.f_names_id = data.item_features(self.d.items, identity=True)
        self.F_only, self.f_names = data.item_features(self.d.items, identity=False)
        self._splits: dict[str, data.Split] = {}

    def split(self, phase: str) -> data.Split:
        if phase not in self._splits:
            self._splits[phase] = self.d.split(phase)
        return self._splits[phase]


def _save_user_cache(
    path: Path,
    users: np.ndarray,
    ndcg: np.ndarray,
    hr: np.ndarray,
    recall: np.ndarray,
    top: np.ndarray | None = None,
    per_seed: list[dict[str, float]] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    kw: dict[str, Any] = {"users": users, "ndcg": ndcg, "hr": hr, "recall": recall}
    if top is not None:
        kw["top"] = top
    if per_seed:
        kw["seed_ndcg"] = np.array([p["ndcg@10"] for p in per_seed], dtype=np.float64)
        kw["seed_hr"] = np.array([p["hr@10"] for p in per_seed], dtype=np.float64)
        kw["seed_recall"] = np.array([p["recall@10"] for p in per_seed], dtype=np.float64)
    np.savez_compressed(path, **kw)


def _seed_stats_from_cache(z: Any) -> tuple[list[dict[str, float]], dict[str, dict[str, float]]]:
    if "seed_ndcg" in z.files:
        sn, sh, sr = z["seed_ndcg"], z["seed_hr"], z["seed_recall"]
        per_seed = [
            {"ndcg@10": float(sn[i]), "hr@10": float(sh[i]), "recall@10": float(sr[i])}
            for i in range(len(sn))
        ]
        agg = {
            "ndcg@10": {"mean": float(np.mean(sn)), "sd": float(np.std(sn, ddof=1)) if len(sn) > 1 else 0.0},
            "hr@10": {"mean": float(np.mean(sh)), "sd": float(np.std(sh, ddof=1)) if len(sh) > 1 else 0.0},
            "recall@10": {"mean": float(np.mean(sr)), "sd": float(np.std(sr, ddof=1)) if len(sr) > 1 else 0.0},
        }
        return per_seed, agg
    agg = {
        "ndcg@10": {"mean": float(z["ndcg"].mean()), "sd": 0.0},
        "hr@10": {"mean": float(z["hr"].mean()), "sd": 0.0},
        "recall@10": {"mean": float(z["recall"].mean()), "sd": 0.0},
    }
    return [], agg


def _eval_warm_random(ctx: StudyCtx, cache_dir: Path = CACHE_DIR) -> tuple[dict[str, np.ndarray], list[dict[str, float]]]:
    p = cache_dir / "warm_random.npz"
    s = ctx.split("test")
    per_seed_summary: list[dict[str, float]] = []
    if p.exists():
        z = np.load(p)
        arr = {"users": z["users"], "ndcg": z["ndcg"], "hr": z["hr"], "recall": z["recall"], "top": z["top"]}
        per_seed_summary, _ = _seed_stats_from_cache(z)
        return arr, per_seed_summary
    per_user = []
    tops = None
    users = None
    for sd in SEEDS:
        m = models.make("Random", seed=sd).fit(s.train)
        ev = metrics.topk_metrics(m.scores, s.targets, s.seen, k=K, return_top=(sd == SEEDS[0]))
        if tops is None:
            tops = ev["top"]
            users = ev["users"]
        per_seed_summary.append(metrics.summarize(ev, k=K))
        per_user.append(np.stack([ev["ndcg"], ev["hr"], ev["recall"]]))
    pu = np.mean(per_user, axis=0)
    assert users is not None and tops is not None
    _save_user_cache(p, users, pu[0], pu[1], pu[2], tops, per_seed=per_seed_summary)
    return {"users": users, "ndcg": pu[0], "hr": pu[1], "recall": pu[2], "top": tops}, per_seed_summary


# ----------------------------------------------------------------------------------------------------- 3. Baseline Ref


def build_foodcom_baseline_ref(ctx: StudyCtx, out_dir: Path = OUT_DIR, cache_dir: Path = CACHE_DIR) -> dict[str, Any]:
    _log("building foodcom_baseline_ref.json (read-only cache + warm Random)...")
    test_locked = json.loads((BASELINE_DIR / "test.json").read_text(encoding="utf-8"))
    cold_locked = json.loads((BASELINE_DIR / "cold.json").read_text(encoding="utf-8"))

    warm_arrays: dict[str, dict[str, np.ndarray]] = {}
    for label in test_locked["models"]:
        z = np.load(BASELINE_CACHE / f"test_{_baseline_slug(label)}.npz")
        warm_arrays[label] = {"users": z["users"], "ndcg": z["ndcg"], "hr": z["hr"], "recall": z["recall"], "top": z["top"]}

    rnd_arr, rnd_seeds = _eval_warm_random(ctx, cache_dir=cache_dir)
    warm_arrays["Random"] = rnd_arr

    base_pop = warm_arrays["MostPop"]
    base_rnd = warm_arrays["Random"]
    warm_descriptives = {
        label: {m: descriptives(arr[m]) for m in ("ndcg", "hr", "recall")} for label, arr in warm_arrays.items()
    }

    vs_mostpop: dict[str, Any] = {}
    vs_random: dict[str, Any] = {}
    for label, arr in warm_arrays.items():
        if label != "MostPop":
            assert np.array_equal(arr["users"], base_pop["users"])
            vs_mostpop[label] = {
                "ndcg@10": paired_report(arr["ndcg"], base_pop["ndcg"], seed=1),
                "hr@10": paired_report(arr["hr"], base_pop["hr"], seed=2, binary_a=(arr["hr"] >= 0.5), binary_b=(base_pop["hr"] >= 0.5)),
                "recall@10": paired_report(arr["recall"], base_pop["recall"], seed=3),
            }
        if label != "Random":
            assert np.array_equal(arr["users"], base_rnd["users"])
            vs_random[label] = {
                "ndcg@10": paired_report(arr["ndcg"], base_rnd["ndcg"], seed=4),
                "hr@10": paired_report(arr["hr"], base_rnd["hr"], seed=5, binary_a=(arr["hr"] >= 0.5), binary_b=(base_rnd["hr"] >= 0.5)),
            }

    for metric_key in ("ndcg@10", "hr@10", "recall@10"):
        labels = list(vs_mostpop)
        adj = stats.holm([vs_mostpop[lbl][metric_key]["paired_bootstrap"]["p"] for lbl in labels])
        for lbl, ph in zip(labels, adj, strict=True):
            vs_mostpop[lbl][metric_key]["p_holm"] = float(ph)
    for metric_key in ("ndcg@10", "hr@10"):
        labels = list(vs_random)
        adj = stats.holm([vs_random[lbl][metric_key]["paired_bootstrap"]["p"] for lbl in labels])
        for lbl, ph in zip(labels, adj, strict=True):
            vs_random[lbl][metric_key]["p_holm"] = float(ph)

    obj = {
        "protocol_id": PROTOCOL_ID,
        "analysis_intent": "baseline_reproduction",
        "source_artifacts": [
            "data/processed/recsys/test.json",
            "data/processed/recsys/cold.json",
            "data/processed/recsys/cache/test_*.npz",
        ],
        "warm": {
            "n_users": int(test_locked["n_test_users"]),
            "n_test_positives": int(test_locked["n_test_positives"]),
            "n_test_targets_kept": int(test_locked["n_test_targets_kept"]),
            "d_mde_80": _d_mde(int(test_locked["n_test_users"])),
            "locked_models": test_locked["models"],
            "warm_random_5seeds": {
                "seeds": list(SEEDS),
                "per_seed": rnd_seeds,
                "ndcg@10": {"mean": float(rnd_arr["ndcg"].mean())},
                "hr@10": {"mean": float(rnd_arr["hr"].mean())},
                "recall@10": {"mean": float(rnd_arr["recall"].mean())},
            },
            "descriptives": warm_descriptives,
            "vs_MostPop": vs_mostpop,
            "vs_Random": vs_random,
        },
        "cold": {
            "n_cold_items": int(cold_locked["n_cold_items"]),
            "n_users": int(cold_locked["n_users"]),
            "n_targets": int(cold_locked["n_targets"]),
            "d_mde_80": _d_mde(int(cold_locked["n_users"])),
            "locked_models": cold_locked["models"],
            "locked_lightfm_minus_content_ndcg@10": cold_locked["lightfm_minus_content_ndcg@10"],
        },
    }
    _write_json(out_dir / "foodcom_baseline_ref.json", obj)
    return obj


# ----------------------------------------------------------------------------------------------------- 4. Confirmatory H3b


def _tune_hybrid_cf_content_val(ctx: StudyCtx) -> tuple[tuple[float, float, float], list[dict[str, Any]]]:
    _log("tuning HybridCFContent weights strictly on val...")
    v = ctx.split("val")
    als = models.ALS(factors=32, reg=10.0, alpha=5.0, iterations=15, seed=0).fit(v.train)
    cnt = models.ContentCosine().fit(v.train, item_features=ctx.F_only)
    pop = np.log1p(np.asarray(v.train.sum(axis=0)).ravel().astype(np.float64))
    pop_z = ((pop - pop.mean()) / max(float(pop.std()), 1e-6)).astype(np.float32)

    grid = [
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
        (0.7, 0.2, 0.1),
        (0.6, 0.3, 0.1),
        (0.6, 0.2, 0.2),
        (0.5, 0.3, 0.2),
        (0.5, 0.2, 0.3),
        (0.4, 0.4, 0.2),
        (0.4, 0.3, 0.3),
        (0.4, 0.2, 0.4),
        (0.3, 0.2, 0.5),
        (0.5, 0.0, 0.5),
        (0.7, 0.0, 0.3),
        (0.3, 0.0, 0.7),
    ]
    users = np.array(sorted(v.targets), dtype=np.int64)
    disc = 1.0 / np.log2(np.arange(2, K + 2))
    ndcg_acc = np.zeros((len(grid), len(users)), dtype=np.float64)
    hr_acc = np.zeros((len(grid), len(users)), dtype=np.float64)

    batch = 512
    for b0 in range(0, len(users), batch):
        ub = users[b0 : b0 + batch]
        cf_z = models._zscore_rows(als.scores(ub))
        cnt_z = models._zscore_rows(cnt.scores(ub))
        sub = v.seen[ub]
        rows = np.repeat(np.arange(len(ub)), np.diff(sub.indptr))
        for g_idx, (w_cf, w_cnt, w_pop) in enumerate(grid):
            s = (w_cf * cf_z + w_cnt * cnt_z + w_pop * pop_z[None, :]).astype(np.float32)
            s[rows, sub.indices] = -np.inf
            top = np.argpartition(-s, K, axis=1)[:, :K]
            order = np.argsort(-np.take_along_axis(s, top, axis=1), axis=1, kind="stable")
            top = np.take_along_axis(top, order, axis=1)
            for r, u in enumerate(ub):
                tg = v.targets[int(u)]
                hits = np.isin(top[r], tg)
                j = b0 + r
                hr_acc[g_idx, j] = float(hits.any())
                ndcg_acc[g_idx, j] = float((hits * disc).sum() / disc[: min(K, len(tg))].sum())

    rows_log: list[dict[str, Any]] = []
    best_w = grid[0]
    best_ndcg = -1.0
    for g_idx, w in enumerate(grid):
        val_ndcg = float(ndcg_acc[g_idx].mean())
        val_hr = float(hr_acc[g_idx].mean())
        rows_log.append({"weights": list(w), "val_ndcg@10": val_ndcg, "val_hr@10": val_hr})
        if val_ndcg > best_ndcg:
            best_ndcg = val_ndcg
            best_w = w
    _log(f"HybridCFContent val best={best_w} ndcg@10={best_ndcg:.5f}")
    return best_w, rows_log


def _tune_twostage_lgbm_val(ctx: StudyCtx) -> tuple[dict[str, Any], np.ndarray, np.ndarray, np.ndarray, list[dict[str, Any]]]:
    import lightgbm as lgb

    _log("building val candidate dataset & running 3-fold user-grouped CV for TwoStageLGBMReranker...")
    v = ctx.split("val")
    builder = models.TwoStageLGBMReranker(top_m=100, seed=0)
    X_val, y_val, groups_val, users_val = builder.build_dataset(v.train, v.targets, seen=v.seen, item_features=ctx.F_only)

    # Slice flat arrays per query group so user-grouped CV splits cleanly
    offsets = np.concatenate([[0], np.cumsum(groups_val)])
    rng = np.random.default_rng(0)
    n_q = len(users_val)
    fold_ids = rng.permutation(np.arange(n_q) % 3)
    disc = 1.0 / np.log2(np.arange(2, K + 2))

    lgb_grid = [
        {"num_leaves": nl, "n_estimators": ne, "learning_rate": lr, "min_child_samples": 30}
        for nl in (7, 15, 31)
        for ne in (100, 200)
        for lr in (0.05, 0.1)
    ]

    cv_rows: list[dict[str, Any]] = []
    best_params = lgb_grid[0]
    best_cv_ndcg = -1.0

    for params in lgb_grid:
        fold_ndcgs: list[float] = []
        for f in range(3):
            tr_q = np.flatnonzero(fold_ids != f)
            va_q = np.flatnonzero(fold_ids == f)
            X_tr = np.vstack([X_val[offsets[q] : offsets[q + 1]] for q in tr_q])
            y_tr = np.concatenate([y_val[offsets[q] : offsets[q + 1]] for q in tr_q])
            g_tr = groups_val[tr_q]

            ranker = lgb.LGBMRanker(
                objective="lambdarank",
                label_gain=[0, 1],
                lambdarank_truncation_level=10,
                random_state=0,
                n_jobs=min(models.N_THREADS, 8),
                verbose=-1,
                **params,
            )
            ranker.fit(X_tr, y_tr, group=g_tr)

            X_va = np.vstack([X_val[offsets[q] : offsets[q + 1]] for q in va_q])
            preds = ranker.predict(X_va)
            p_off = 0
            for q in va_q:
                g_len = int(groups_val[q])
                p_u = preds[p_off : p_off + g_len]
                y_u = y_val[offsets[q] : offsets[q + 1]]
                p_off += g_len
                order = np.argsort(-p_u, kind="stable")[:K]
                hits = y_u[order] > 0
                tg_len = len(v.targets[int(users_val[q])])
                fold_ndcgs.append(float((hits * disc[: len(hits)]).sum() / disc[: min(K, tg_len)].sum()))
        mean_ndcg = float(np.mean(fold_ndcgs))
        cv_rows.append({"lgb_params": params, "val_cv3_cand_ndcg@10": mean_ndcg})
        if mean_ndcg > best_cv_ndcg:
            best_cv_ndcg = mean_ndcg
            best_params = dict(params)
    _log(f"TwoStageLGBMReranker val CV3 best={best_params} cand_ndcg@10={best_cv_ndcg:.5f}")
    return best_params, X_val, y_val, groups_val, cv_rows


def _tune_cold_hybrid_val(ctx: StudyCtx) -> tuple[float, list[dict[str, Any]]]:
    _log("tuning ColdHybrid alpha strictly on val cold items...")
    v = ctx.split("val")
    cold_allowed = np.zeros(ctx.d.n_items, dtype=bool)
    cold_allowed[v.cold_items] = True
    alphas = (0.0, 0.25, 0.5, 0.75, 1.0)
    rows: list[dict[str, Any]] = []

    if len(v.cold_targets) == 0 or len(v.cold_items) == 0:
        return 0.5, [{"alpha": a, "note": "no val cold targets; fallback 0.5"} for a in alphas]

    base = models.ColdHybrid(alpha=0.5, seed=0).fit(v.train, item_features=ctx.F_only, allowed=cold_allowed)
    users = np.array(sorted(v.cold_targets), dtype=np.int64)
    s_lfm, s_cnt = base.component_scores(users)
    u_to_row = {int(u): idx for idx, u in enumerate(users)}

    best_alpha = 0.5
    best_ndcg = -1.0
    for alpha in alphas:
        def _score(ub: np.ndarray, _a=alpha) -> np.ndarray:
            r = np.array([u_to_row[int(u)] for u in ub], dtype=np.int64)
            return (_a * s_lfm[r] + (1.0 - _a) * s_cnt[r]).astype(np.float32)

        ev = metrics.topk_metrics(_score, v.cold_targets, v.seen, k=K, allowed=cold_allowed)
        summ = metrics.summarize(ev, k=K)
        rows.append({"alpha": alpha, "val_cold_ndcg@10": summ["ndcg@10"], "val_cold_hr@10": summ["hr@10"]})
        if summ["ndcg@10"] > best_ndcg:
            best_ndcg = summ["ndcg@10"]
            best_alpha = alpha
    _log(f"ColdHybrid val cold best alpha={best_alpha} ndcg@10={best_ndcg:.5f} (n_val_cold_users={len(v.cold_targets)})")
    return best_alpha, rows


def build_foodcom_confirmatory(ctx: StudyCtx, out_dir: Path = OUT_DIR, cache_dir: Path = CACHE_DIR) -> dict[str, Any]:
    conf_path = out_dir / "foodcom_confirmatory.json"
    pairs_path = out_dir / "foodcom_confirmatory_pairs.csv"

    s_test = ctx.split("test")
    cold_allowed = np.zeros(ctx.d.n_items, dtype=bool)
    cold_allowed[s_test.cold_items] = True

    # 1) Tune strictly on val
    best_w, hyb_val_rows = _tune_hybrid_cf_content_val(ctx)
    best_lgb, X_val, y_val, groups_val, lgb_val_rows = _tune_twostage_lgbm_val(ctx)
    best_alpha, cold_val_rows = _tune_cold_hybrid_val(ctx)

    # 2) Single-pass evaluation on warm test (n=4,834)
    _log("evaluating H3b-Warm models single-pass on test (n=4,834)...")
    warm_eval: dict[str, dict[str, Any]] = {}

    # Deterministic warm baselines: MostPop & ContentCosine
    for label, mdl in (
        ("MostPop", models.MostPop().fit(s_test.train)),
        ("ContentCosine", models.ContentCosine().fit(s_test.train, item_features=ctx.F_only)),
    ):
        cp = cache_dir / f"warm_{_baseline_slug(label)}.npz"
        if cp.exists():
            z = np.load(cp)
            ev = {"users": z["users"], "ndcg": z["ndcg"], "hr": z["hr"], "recall": z["recall"], "top": z["top"]}
            summ = metrics.summarize(ev, k=K)
        else:
            ev = metrics.topk_metrics(mdl.scores, s_test.targets, s_test.seen, k=K, return_top=True)
            summ = metrics.summarize(ev, k=K)
            _save_user_cache(cp, ev["users"], ev["ndcg"], ev["hr"], ev["recall"], ev["top"])
        warm_eval[label] = {
            "arrays": ev,
            "seeds": [0],
            "per_seed": [summ],
            "ndcg@10": {"mean": summ["ndcg@10"], "sd": 0.0},
            "hr@10": {"mean": summ["hr@10"], "sd": 0.0},
            "recall@10": {"mean": summ["recall@10"], "sd": 0.0},
        }

    # Warm Random (5 seeds)
    rnd_arr, rnd_seeds = _eval_warm_random(ctx, cache_dir=cache_dir)
    warm_eval["Random"] = {
        "arrays": rnd_arr,
        "seeds": list(SEEDS),
        "per_seed": rnd_seeds,
        "ndcg@10": {"mean": float(rnd_arr["ndcg"].mean()), "sd": float(np.std([r["ndcg@10"] for r in rnd_seeds], ddof=1)) if len(rnd_seeds) > 1 else 0.0},
        "hr@10": {"mean": float(rnd_arr["hr"].mean()), "sd": float(np.std([r["hr@10"] for r in rnd_seeds], ddof=1)) if len(rnd_seeds) > 1 else 0.0},
        "recall@10": {"mean": float(rnd_arr["recall"].mean()), "sd": float(np.std([r["recall@10"] for r in rnd_seeds], ddof=1)) if len(rnd_seeds) > 1 else 0.0},
    }

    # Warm HybridCFContent (5 seeds)
    h_cp = cache_dir / "warm_hybridcfcontent.npz"
    if h_cp.exists():
        z = np.load(h_cp)
        p_seeds, p_agg = _seed_stats_from_cache(z)
        warm_eval["HybridCFContent"] = {
            "arrays": {"users": z["users"], "ndcg": z["ndcg"], "hr": z["hr"], "recall": z["recall"], "top": z["top"]},
            "seeds": list(SEEDS),
            "weights": list(best_w),
            "per_seed": p_seeds,
            **p_agg,
        }
    else:
        per_seed, per_user, tops, users = [], [], None, None
        for sd in SEEDS:
            m = models.HybridCFContent(weights=best_w, seed=sd).fit(s_test.train, item_features=ctx.F_only)
            ev = metrics.topk_metrics(m.scores, s_test.targets, s_test.seen, k=K, return_top=(sd == SEEDS[0]))
            if tops is None:
                tops, users = ev["top"], ev["users"]
            summ = metrics.summarize(ev, k=K)
            per_seed.append(summ)
            per_user.append(np.stack([ev["ndcg"], ev["hr"], ev["recall"]]))
            _log(f"HybridCFContent test seed={sd} ndcg@10={summ['ndcg@10']:.5f} hr@10={summ['hr@10']:.5f}")
        pu = np.mean(per_user, axis=0)
        assert users is not None and tops is not None
        _save_user_cache(h_cp, users, pu[0], pu[1], pu[2], tops, per_seed=per_seed)
        warm_eval["HybridCFContent"] = {
            "arrays": {"users": users, "ndcg": pu[0], "hr": pu[1], "recall": pu[2], "top": tops},
            "seeds": list(SEEDS),
            "weights": list(best_w),
            "per_seed": per_seed,
            "ndcg@10": {"mean": float(np.mean([p["ndcg@10"] for p in per_seed])), "sd": float(np.std([p["ndcg@10"] for p in per_seed], ddof=1))},
            "hr@10": {"mean": float(np.mean([p["hr@10"] for p in per_seed])), "sd": float(np.std([p["hr@10"] for p in per_seed], ddof=1))},
            "recall@10": {"mean": float(np.mean([p["recall@10"] for p in per_seed])), "sd": float(np.std([p["recall@10"] for p in per_seed], ddof=1))},
        }

    # Warm TwoStageLGBMReranker (5 seeds; LGBMRanker trained on val, stage1 on < d_test)
    l_cp = cache_dir / "warm_twostagelgbmreranker.npz"
    if l_cp.exists():
        z = np.load(l_cp)
        p_seeds, p_agg = _seed_stats_from_cache(z)
        warm_eval["TwoStageLGBMReranker"] = {
            "arrays": {"users": z["users"], "ndcg": z["ndcg"], "hr": z["hr"], "recall": z["recall"], "top": z["top"]},
            "seeds": list(SEEDS),
            "lgb_params": best_lgb,
            "per_seed": p_seeds,
            **p_agg,
        }
    else:
        per_seed, per_user, tops, users = [], [], None, None
        for sd in SEEDS:
            m = models.TwoStageLGBMReranker(top_m=100, lgb_params=best_lgb, seed=sd)
            m.fit_reranker(X_val, y_val, groups_val)
            m.fit_stage1(s_test.train, seen=s_test.seen, item_features=ctx.F_only)
            ev = metrics.topk_metrics(m.scores, s_test.targets, s_test.seen, k=K, return_top=(sd == SEEDS[0]))
            if tops is None:
                tops, users = ev["top"], ev["users"]
            summ = metrics.summarize(ev, k=K)
            per_seed.append(summ)
            per_user.append(np.stack([ev["ndcg"], ev["hr"], ev["recall"]]))
            _log(f"TwoStageLGBMReranker test seed={sd} ndcg@10={summ['ndcg@10']:.5f} hr@10={summ['hr@10']:.5f}")
        pu = np.mean(per_user, axis=0)
        assert users is not None and tops is not None
        _save_user_cache(l_cp, users, pu[0], pu[1], pu[2], tops, per_seed=per_seed)
        warm_eval["TwoStageLGBMReranker"] = {
            "arrays": {"users": users, "ndcg": pu[0], "hr": pu[1], "recall": pu[2], "top": tops},
            "seeds": list(SEEDS),
            "lgb_params": best_lgb,
            "per_seed": per_seed,
            "ndcg@10": {"mean": float(np.mean([p["ndcg@10"] for p in per_seed])), "sd": float(np.std([p["ndcg@10"] for p in per_seed], ddof=1))},
            "hr@10": {"mean": float(np.mean([p["hr@10"] for p in per_seed])), "sd": float(np.std([p["hr@10"] for p in per_seed], ddof=1))},
            "recall@10": {"mean": float(np.mean([p["recall@10"] for p in per_seed])), "sd": float(np.std([p["recall@10"] for p in per_seed], ddof=1))},
        }

    # 3) Single-pass evaluation on cold test (n=422 users, 599 cold items)
    _log("evaluating H3b-Cold models single-pass on test cold items (n=422 users, 599 items)...")
    cold_eval: dict[str, dict[str, Any]] = {}

    for label, mdl in (
        ("MostPop", models.MostPop().fit(s_test.train)),
        ("ContentCosine", models.ContentCosine().fit(s_test.train, item_features=ctx.F_only)),
    ):
        ev = metrics.topk_metrics(mdl.scores, s_test.cold_targets, s_test.seen, k=K, allowed=cold_allowed)
        summ = metrics.summarize(ev, k=K)
        cold_eval[label] = {
            "arrays": ev,
            "seeds": [0],
            "per_seed": [summ],
            "ndcg@10": {"mean": summ["ndcg@10"], "sd": 0.0},
            "hr@10": {"mean": summ["hr@10"], "sd": 0.0},
            "recall@10": {"mean": summ["recall@10"], "sd": 0.0},
        }

    # Cold Random (5 seeds)
    c_rnd_seeds, c_rnd_pu, c_users = [], [], None
    for sd in SEEDS:
        r = models.Random(seed=sd).fit(s_test.train)
        ev = metrics.topk_metrics(r.scores, s_test.cold_targets, s_test.seen, k=K, allowed=cold_allowed)
        c_users = ev["users"]
        c_rnd_seeds.append(metrics.summarize(ev, k=K))
        c_rnd_pu.append(np.stack([ev["ndcg"], ev["hr"], ev["recall"]]))
    c_rnd_mean = np.mean(c_rnd_pu, axis=0)
    cold_eval["Random"] = {
        "arrays": {"users": c_users, "ndcg": c_rnd_mean[0], "hr": c_rnd_mean[1], "recall": c_rnd_mean[2]},
        "seeds": list(SEEDS),
        "per_seed": c_rnd_seeds,
        "ndcg@10": {"mean": float(np.mean([p["ndcg@10"] for p in c_rnd_seeds])), "sd": float(np.std([p["ndcg@10"] for p in c_rnd_seeds], ddof=1))},
        "hr@10": {"mean": float(np.mean([p["hr@10"] for p in c_rnd_seeds])), "sd": float(np.std([p["hr@10"] for p in c_rnd_seeds], ddof=1))},
        "recall@10": {"mean": float(np.mean([p["recall@10"] for p in c_rnd_seeds])), "sd": float(np.std([p["recall@10"] for p in c_rnd_seeds], ddof=1))},
    }

    # ColdHybrid (5 seeds; ALSO cache LightFMWarp tags_ing cold per-user scores for Exploratory #5 reuse!)
    c_hyb_cp = cache_dir / "cold_hybrid.npz"
    c_lfm_cp = cache_dir / "cold_lfm_tags_ing.npz"
    if c_hyb_cp.exists() and c_lfm_cp.exists():
        zh = np.load(c_hyb_cp)
        p_seeds, p_agg = _seed_stats_from_cache(zh)
        cold_eval["ColdHybrid"] = {
            "arrays": {"users": zh["users"], "ndcg": zh["ndcg"], "hr": zh["hr"], "recall": zh["recall"]},
            "seeds": list(SEEDS),
            "alpha": best_alpha,
            "per_seed": p_seeds,
            **p_agg,
        }
    else:
        ch_seeds, ch_pu = [], []
        lfm_seeds, lfm_pu = [], []
        c_u = None
        for sd in SEEDS:
            m = models.ColdHybrid(alpha=best_alpha, seed=sd).fit(s_test.train, item_features=ctx.F_only, allowed=cold_allowed)
            ev = metrics.topk_metrics(m.scores, s_test.cold_targets, s_test.seen, k=K, allowed=cold_allowed)
            c_u = ev["users"]
            summ = metrics.summarize(ev, k=K)
            ch_seeds.append(summ)
            ch_pu.append(np.stack([ev["ndcg"], ev["hr"], ev["recall"]]))

            ev_lfm = metrics.topk_metrics(m.lfm.scores, s_test.cold_targets, s_test.seen, k=K, allowed=cold_allowed)
            summ_lfm = metrics.summarize(ev_lfm, k=K)
            lfm_seeds.append(summ_lfm)
            lfm_pu.append(np.stack([ev_lfm["ndcg"], ev_lfm["hr"], ev_lfm["recall"]]))
            _log(f"ColdHybrid test seed={sd} hybrid_ndcg@10={summ['ndcg@10']:.5f} lfm_ndcg@10={summ_lfm['ndcg@10']:.5f}")

        ch_mean = np.mean(ch_pu, axis=0)
        lfm_mean = np.mean(lfm_pu, axis=0)
        assert c_u is not None
        _save_user_cache(c_hyb_cp, c_u, ch_mean[0], ch_mean[1], ch_mean[2], per_seed=ch_seeds)
        _save_user_cache(c_lfm_cp, c_u, lfm_mean[0], lfm_mean[1], lfm_mean[2], per_seed=lfm_seeds)
        cold_eval["ColdHybrid"] = {
            "arrays": {"users": c_u, "ndcg": ch_mean[0], "hr": ch_mean[1], "recall": ch_mean[2]},
            "seeds": list(SEEDS),
            "alpha": best_alpha,
            "per_seed": ch_seeds,
            "ndcg@10": {"mean": float(np.mean([p["ndcg@10"] for p in ch_seeds])), "sd": float(np.std([p["ndcg@10"] for p in ch_seeds], ddof=1))},
            "hr@10": {"mean": float(np.mean([p["hr@10"] for p in ch_seeds])), "sd": float(np.std([p["hr@10"] for p in ch_seeds], ddof=1))},
            "recall@10": {"mean": float(np.mean([p["recall@10"] for p in ch_seeds])), "sd": float(np.std([p["recall@10"] for p in ch_seeds], ddof=1))},
        }

    # 4) Confirmatory H3b-Warm & H3b-Cold paired inference + Holm-Bonferroni
    warm_contrasts = [
        ("HybridCFContent", "Random"),
        ("TwoStageLGBMReranker", "Random"),
        ("HybridCFContent", "MostPop"),
        ("TwoStageLGBMReranker", "MostPop"),
    ]
    cold_contrasts = [
        ("ColdHybrid", "Random"),
        ("ColdHybrid", "MostPop"),
        ("ColdHybrid", "ContentCosine"),
    ]

    def _run_family(eval_dict: dict[str, dict[str, Any]], pairs: list[tuple[str, str]], family_name: str, d_mde_val: float) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        family_res: dict[str, Any] = {}
        csv_rows: list[dict[str, Any]] = []
        for metric_key, arr_key in (("ndcg@10", "ndcg"), ("hr@10", "hr"), ("recall@10", "recall")):
            comp_list = []
            for ma, mb in pairs:
                aa = eval_dict[ma]["arrays"]
                ab = eval_dict[mb]["arrays"]
                assert np.array_equal(aa["users"], ab["users"])
                bin_a = (aa["hr"] >= 0.5) if metric_key == "hr@10" else None
                bin_b = (ab["hr"] >= 0.5) if metric_key == "hr@10" else None
                rep = paired_report(aa[arr_key], ab[arr_key], seed=17, n_boot=2000, binary_a=bin_a, binary_b=bin_b)
                comp_list.append((f"{ma}_vs_{mb}", ma, mb, rep))
            adj = stats.holm([c[3]["paired_bootstrap"]["p"] for c in comp_list])
            family_res[metric_key] = {}
            for (cname, ma, mb, rep), ph in zip(comp_list, adj, strict=True):
                rep["p_holm"] = float(ph)
                rep["d_mde_80"] = d_mde_val
                family_res[metric_key][cname] = rep
                mc = rep.get("mcnemar", {})
                csv_rows.append(
                    {
                        "family": family_name,
                        "metric": metric_key,
                        "model_a": ma,
                        "model_b": mb,
                        "n": rep["desc_a"]["n"],
                        "mean_a": rep["desc_a"]["mean"],
                        "sd_a": rep["desc_a"]["sd"],
                        "mean_b": rep["desc_b"]["mean"],
                        "sd_b": rep["desc_b"]["sd"],
                        "diff": rep["paired_bootstrap"]["diff"],
                        "ci_lo": rep["paired_bootstrap"]["lo"],
                        "ci_hi": rep["paired_bootstrap"]["hi"],
                        "p_boot": rep["paired_bootstrap"]["p"],
                        "p_wilcoxon": rep["wilcoxon"]["p"],
                        "p_holm": float(ph),
                        "cohen_dz": rep["cohens_dz"]["d_z"],
                        "hedges_gz": rep["cohens_dz"]["hedges_gz"],
                        "dz_lo": rep["cohens_dz"]["lo"],
                        "dz_hi": rep["cohens_dz"]["hi"],
                        "rank_biserial": rep["wilcoxon"]["rank_biserial"],
                        "mcnemar_p": mc.get("p", ""),
                        "normality_p": rep["assumptions"]["normality_p"],
                        "symmetry_flag": rep["assumptions"]["symmetry_flag"],
                        "d_mde_80": d_mde_val,
                    }
                )
        return family_res, csv_rows

    h3b_warm_res, warm_csv = _run_family(warm_eval, warm_contrasts, "H3b-Warm", _d_mde(len(s_test.targets)))
    h3b_cold_res, cold_csv = _run_family(cold_eval, cold_contrasts, "H3b-Cold", _d_mde(len(s_test.cold_targets)))

    # Reference warm contrast vs ContentCosine (non-Holm supplementary)
    warm_ref_cnt = {
        ma: {
            "ndcg@10": paired_report(warm_eval[ma]["arrays"]["ndcg"], warm_eval["ContentCosine"]["arrays"]["ndcg"], seed=19),
            "hr@10": paired_report(warm_eval[ma]["arrays"]["hr"], warm_eval["ContentCosine"]["arrays"]["hr"], seed=20),
        }
        for ma in ("HybridCFContent", "TwoStageLGBMReranker")
    }

    def _strip_arrays(d: dict[str, dict[str, Any]]) -> dict[str, Any]:
        out_m = {}
        for k, v in d.items():
            out_m[k] = {kk: vv for kk, vv in v.items() if kk != "arrays"}
            out_m[k]["descriptives"] = {m: descriptives(v["arrays"][m]) for m in ("ndcg", "hr", "recall")}
        return out_m

    payload = {
        "protocol_id": PROTOCOL_ID,
        "analysis_intent": "confirmatory",
        "hypothesis": "H3b",
        "val_tuning": {
            "hybrid_cf_content": {"best_weights": list(best_w), "grid_results": hyb_val_rows},
            "two_stage_lgbm_reranker": {"best_params": best_lgb, "cv3_results": lgb_val_rows},
            "cold_hybrid": {"best_alpha": best_alpha, "grid_results": cold_val_rows},
        },
        "warm": {
            "n_users": int(len(s_test.targets)),
            "d_mde_80": _d_mde(len(s_test.targets)),
            "models": _strip_arrays(warm_eval),
            "confirmatory_family_h3b_warm": h3b_warm_res,
            "reference_vs_ContentCosine": warm_ref_cnt,
        },
        "cold": {
            "n_cold_items": int(len(s_test.cold_items)),
            "n_users": int(len(s_test.cold_targets)),
            "n_targets": int(sum(len(v) for v in s_test.cold_targets.values())),
            "d_mde_80": _d_mde(len(s_test.cold_targets)),
            "models": _strip_arrays(cold_eval),
            "confirmatory_family_h3b_cold": h3b_cold_res,
        },
    }
    _write_json(conf_path, payload)

    all_csv = warm_csv + cold_csv
    if all_csv:
        with open(pairs_path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(all_csv[0].keys()))
            w.writeheader()
            w.writerows(all_csv)

    return payload


# ----------------------------------------------------------------------------------------------------- 5. Exploratory #5


def build_foodcom_exploratory(ctx: StudyCtx, out_dir: Path = OUT_DIR, cache_dir: Path = CACHE_DIR) -> dict[str, Any]:
    _log("building foodcom_exploratory.json (activity bins, pop deciles, LightFM cold feature ablations)...")
    s_test = ctx.split("test")
    act = np.diff(s_test.train.indptr)
    pop = np.asarray(s_test.train.sum(axis=0)).ravel()
    order = np.argsort(-pop, kind="stable")
    pct = np.empty_like(pop, dtype=float)
    pct[order] = np.arange(len(pop)) / max(1, len(pop) - 1)
    head = pct <= 0.01

    bins = [(1, 4), (5, 9), (10, 19), (20, 49), (50, 99), (100, 10**9)]
    bin_labels = [f"{a}-{b}" if b < 10**9 else f">={a}" for a, b in bins]

    # Collect cached arrays from baseline + confirmatory
    model_sources: dict[str, Path] = {
        "MostPop": cache_dir / "warm_mostpop.npz",
        "ContentCosine": cache_dir / "warm_contentcosine.npz",
        "Random": cache_dir / "warm_random.npz",
        "HybridCFContent": cache_dir / "warm_hybridcfcontent.npz",
        "TwoStageLGBMReranker": cache_dir / "warm_twostagelgbmreranker.npz",
        "EASE": BASELINE_CACHE / "test_ease.npz",
        "ALS (implicit)": BASELINE_CACHE / "test_als__implicit.npz",
        "LightFM WARP (tags+ing)": BASELINE_CACHE / "test_lightfm_warp.npz",
        "LightFM WARP (id_only)": BASELINE_CACHE / "test_lightfm_warp__chỉ_id__không_đặc_trưng.npz",
    }
    loaded: dict[str, dict[str, np.ndarray]] = {}
    for label, p in model_sources.items():
        if p.exists():
            z = np.load(p)
            loaded[label] = {k: z[k] for k in z.files}

    base_pop = loaded["MostPop"]
    activity_bins: dict[str, Any] = {}
    raw_bin_p: list[tuple[str, str, float]] = []

    for label, arr in loaded.items():
        a = act[arr["users"]]
        top = arr["top"]
        per_bin = []
        for blab, (lo, hi) in zip(bin_labels, bins, strict=True):
            m = (a >= lo) & (a <= hi)
            n_b = int(m.sum())
            mean_ndcg, lo_ci, hi_ci = stats.mean_ci(arr["ndcg"][m], n_boot=1000, seed=0) if n_b > 1 else (float("nan"),) * 3
            entry: dict[str, Any] = {
                "bin": blab,
                "n_users": n_b,
                "ndcg@10_mean": mean_ndcg,
                "ndcg@10_ci95": [lo_ci, hi_ci],
                "hr@10_mean": float(arr["hr"][m].mean()) if n_b else float("nan"),
            }
            if label != "MostPop" and n_b >= 2:
                pb = stats.paired_bootstrap(arr["ndcg"][m], base_pop["ndcg"][m], n_boot=1000, seed=1)
                entry["vs_MostPop_diff"] = pb["diff"]
                entry["vs_MostPop_ci95"] = [pb["lo"], pb["hi"]]
                entry["vs_MostPop_p_raw"] = pb["p"]
                raw_bin_p.append((label, blab, float(pb["p"])))
            per_bin.append(entry)
        activity_bins[label] = {
            "by_activity": per_bin,
            "rec_head_share": float(head[top].mean()),
            "rec_mean_pop_percentile": float(pct[top].mean()),
            "catalog_coverage@10": float(len(np.unique(top)) / len(pop)),
        }

    if raw_bin_p:
        q_bins = stats.bh_fdr([x[2] for x in raw_bin_p])
        for (lbl, blab, _), q in zip(raw_bin_p, q_bins, strict=True):
            for entry in activity_bins[lbl]["by_activity"]:
                if entry["bin"] == blab:
                    entry["vs_MostPop_q_bh"] = float(q)

    # Item-popularity deciles on test targets & top-10 recommendations
    decile_of_item = np.floor(pct * 10.0).astype(int)
    decile_of_item = np.clip(decile_of_item, 0, 9)  # 0 = top 10% popular, 9 = bottom 10% tail
    all_tg = np.concatenate(list(s_test.targets.values()))
    tg_dec_counts = np.bincount(decile_of_item[all_tg], minlength=10)
    pop_deciles: dict[str, Any] = {
        "decile_definitions": "0=top 10% most popular items in train, 9=bottom 10% long-tail",
        "target_share_by_decile": [float(c / max(1, len(all_tg))) for c in tg_dec_counts],
        "models": {},
    }
    for label, arr in loaded.items():
        top = arr["top"]
        rec_dec = np.bincount(decile_of_item[top.ravel()], minlength=10)
        pop_deciles["models"][label] = {
            "rec_share_by_decile": [float(c / max(1, top.size)) for c in rec_dec],
        }

    # Warm LightFM feature ablation paired stats
    warm_lfm_ablation: dict[str, Any] = {}
    if "LightFM WARP (tags+ing)" in loaded and "LightFM WARP (id_only)" in loaded:
        a_f = loaded["LightFM WARP (tags+ing)"]
        a_id = loaded["LightFM WARP (id_only)"]
        warm_lfm_ablation = {
            "ndcg@10": paired_report(a_f["ndcg"], a_id["ndcg"], seed=31),
            "hr@10": paired_report(a_f["hr"], a_id["hr"], seed=32, binary_a=(a_f["hr"] >= 0.5), binary_b=(a_id["hr"] >= 0.5)),
        }

    # Cold LightFM feature ablations: id_only, tags_only, ing_only, tags_ing (reusing cold_lfm_tags_ing.npz)
    _log("running LightFM cold feature ablations (id_only, tags_only, ing_only, tags_ing)...")
    cold_allowed = np.zeros(ctx.d.n_items, dtype=bool)
    cold_allowed[s_test.cold_items] = True
    cold_variants = ("id_only", "tags_only", "ing_only", "tags_ing")
    cold_ablation_arrays: dict[str, dict[str, np.ndarray]] = {}
    cold_ablation_summary: dict[str, Any] = {}

    for var in cold_variants:
        vp = cache_dir / f"cold_lfm_{var}.npz"
        if vp.exists():
            z = np.load(vp)
            cold_ablation_arrays[var] = {k: z[k] for k in z.files}
            p_seeds, p_agg = _seed_stats_from_cache(z)
            cold_ablation_summary[var] = {
                "seeds": list(SEEDS),
                "per_seed": p_seeds,
                "descriptives": {m: descriptives(z[m]) for m in ("ndcg", "hr", "recall")},
                **p_agg,
            }
            continue
        F_var = models.cold_feature_matrix(ctx.d.n_items, ctx.F_only, ctx.f_names, var)
        per_seed, per_user, u_arr = [], [], None
        for sd in SEEDS:
            m = models.LightFMWarp(dim=64, lr=0.02, item_alpha=0.0, epochs=12, seed=sd).fit(s_test.train, item_features=F_var)
            ev = metrics.topk_metrics(m.scores, s_test.cold_targets, s_test.seen, k=K, allowed=cold_allowed)
            u_arr = ev["users"]
            summ = metrics.summarize(ev, k=K)
            per_seed.append(summ)
            per_user.append(np.stack([ev["ndcg"], ev["hr"], ev["recall"]]))
            _log(f"cold LightFM ablation={var} seed={sd} ndcg@10={summ['ndcg@10']:.5f}")
        pu = np.mean(per_user, axis=0)
        assert u_arr is not None
        _save_user_cache(vp, u_arr, pu[0], pu[1], pu[2], per_seed=per_seed)
        cold_ablation_arrays[var] = {"users": u_arr, "ndcg": pu[0], "hr": pu[1], "recall": pu[2]}
        cold_ablation_summary[var] = {
            "seeds": list(SEEDS),
            "per_seed": per_seed,
            "descriptives": {m: descriptives(cold_ablation_arrays[var][m]) for m in ("ndcg", "hr", "recall")},
            "ndcg@10": {"mean": float(np.mean([p["ndcg@10"] for p in per_seed])), "sd": float(np.std([p["ndcg@10"] for p in per_seed], ddof=1))},
            "hr@10": {"mean": float(np.mean([p["hr@10"] for p in per_seed])), "sd": float(np.std([p["hr@10"] for p in per_seed], ddof=1))},
            "recall@10": {"mean": float(np.mean([p["recall@10"] for p in per_seed])), "sd": float(np.std([p["recall@10"] for p in per_seed], ddof=1))},
        }

    # BH-FDR adjusted contrasts vs tags_ing & vs id_only
    cold_ablation_contrasts: dict[str, Any] = {}
    tags_ing_arr = cold_ablation_arrays["tags_ing"]
    id_only_arr = cold_ablation_arrays["id_only"]
    p_raw_list: list[tuple[str, dict[str, Any]]] = []
    for var in ("tags_only", "ing_only", "tags_ing"):
        rep = {
            "ndcg@10": paired_report(cold_ablation_arrays[var]["ndcg"], id_only_arr["ndcg"], seed=41),
            "hr@10": paired_report(
                cold_ablation_arrays[var]["hr"],
                id_only_arr["hr"],
                seed=42,
                binary_a=(cold_ablation_arrays[var]["hr"] >= 0.5),
                binary_b=(id_only_arr["hr"] >= 0.5),
            ),
        }
        p_raw_list.append((f"{var}_vs_id_only", rep))
    for var in ("tags_only", "ing_only"):
        rep = {
            "ndcg@10": paired_report(tags_ing_arr["ndcg"], cold_ablation_arrays[var]["ndcg"], seed=43),
            "hr@10": paired_report(
                tags_ing_arr["hr"],
                cold_ablation_arrays[var]["hr"],
                seed=44,
                binary_a=(tags_ing_arr["hr"] >= 0.5),
                binary_b=(cold_ablation_arrays[var]["hr"] >= 0.5),
            ),
        }
        p_raw_list.append((f"tags_ing_vs_{var}", rep))

    assert len({x[0] for x in p_raw_list}) == len(p_raw_list)
    q_ndcg = stats.bh_fdr([x[1]["ndcg@10"]["paired_bootstrap"]["p"] for x in p_raw_list])
    q_hr = stats.bh_fdr([x[1]["hr@10"]["paired_bootstrap"]["p"] for x in p_raw_list])
    for (cname, rep), qn, qh in zip(p_raw_list, q_ndcg, q_hr, strict=True):
        rep["ndcg@10"]["q_bh"] = float(qn)
        rep["hr@10"]["q_bh"] = float(qh)
        cold_ablation_contrasts[cname] = rep

    obj = {
        "protocol_id": PROTOCOL_ID,
        "analysis_intent": "exploratory",
        "exploratory_id": "Exploratory #5",
        "multiplicity_method": "bh_fdr (q=0.05)",
        "warm_activity_bins": activity_bins,
        "warm_popularity_deciles": pop_deciles,
        "warm_lightfm_feature_ablation": warm_lfm_ablation,
        "cold_lightfm_feature_ablations": {
            "n_users": int(len(s_test.cold_targets)),
            "n_cold_items": int(len(s_test.cold_items)),
            "d_mde_80": _d_mde(len(s_test.cold_targets)),
            "models": cold_ablation_summary,
            "contrasts_bh_fdr": cold_ablation_contrasts,
        },
    }
    _write_json(out_dir / "foodcom_exploratory.json", obj)
    return obj


# ----------------------------------------------------------------------------------------------------- 6. KB vs DB Alignment


def build_kb_db_alignment(deploy_dir: Path, out_dir: Path = OUT_DIR) -> dict[str, Any]:
    _log("building kb_db_alignment.json (180 KB vs 171 publishable DB recipes)...")
    kb_audit = export_ranker.kb_publishability_audit()
    cat = kb_catalog.load()
    sd = survey.simulate(cat, seed=20261018)
    ranker = export_ranker.ExportedNumpyRanker.load(deploy_dir, verify_sha256=True)

    pub_mask = np.array([kb_audit["publishable_by_slug"][r.slug] for r in cat.recipes], dtype=bool)
    ndcg_180, ndcg_171, auc_180, auc_171, spearman_r = [], [], [], [], []
    for u, g in sd.ratings.groupby("user"):
        items = g.item.to_numpy()
        y = g.rating.to_numpy(float)
        favs = sd.favorites[int(u)].tolist()
        s_all = ranker.score_indices(favs, items.tolist())
        ndcg_180.append(metrics.ndcg_graded(y, s_all, 5))
        auc_180.append(metrics.auc_pairs(y, s_all))

        m_pub = pub_mask[items]
        if m_pub.sum() >= 2:
            s_pub = ranker.score_indices(favs, items[m_pub].tolist())
            ndcg_171.append(metrics.ndcg_graded(y[m_pub], s_pub, 5))
            auc_171.append(metrics.auc_pairs(y[m_pub], s_pub))
            # Check exact invariance of scores on the 171 overlapping dishes
            spearman_r.append(float(np.max(np.abs(s_all[m_pub] - s_pub))))

    obj = {
        "protocol_id": PROTOCOL_ID,
        "analysis_intent": "exploratory",
        "exploratory_id": "Exploratory #5",
        "kb_publishability": {
            "n_kb_total": kb_audit["n_kb_total"],
            "n_publishable": kb_audit["n_publishable"],
            "n_draft": kb_audit["n_draft"],
            "by_slot_total": kb_audit["by_slot_total"],
            "by_slot_publishable": kb_audit["by_slot_publishable"],
            "draft_recipes": kb_audit["draft_recipes"],
        },
        "ranker_stability_171_vs_180": {
            "SIMULATED": True,
            "n_users": int(sd.n_users),
            "ndcg@5_all_180_mean": float(np.nanmean(ndcg_180)),
            "ndcg@5_pub_171_mean": float(np.nanmean(ndcg_171)),
            "auc_all_180_mean": float(np.nanmean(auc_180)),
            "auc_pub_171_mean": float(np.nanmean(auc_171)),
            "max_score_drift_on_shared_171": float(np.max(spearman_r)) if spearman_r else 0.0,
            "zero_crash": True,
        },
    }
    _write_json(out_dir / "kb_db_alignment.json", obj)
    return obj


# ----------------------------------------------------------------------------------------------------- 7. Survey H3a


def build_survey_confirmatory(out_dir: Path = OUT_DIR, workers: int = 8) -> dict[str, Any]:
    _log("running VN Survey H3a confirmatory nested CV (SIMULATED=true, n=90, 5 seeds)...")
    res = survey.run(source="simulate", seeds=SEEDS, workers=workers, write=False)
    assert res["SIMULATED"] is True

    payload = {
        "protocol_id": PROTOCOL_ID,
        "analysis_intent": "confirmatory",
        "hypothesis": "H3a",
        "SIMULATED": True,
        "label": res["label"],
        "simulation_disclaimer": res["simulation_disclaimer"],
        "data": res["data"],
        "seeds": res["seeds"],
        "independent_unit": "user (seed-averaged across 5 seeds first; n=90)",
        "d_mde_80": _d_mde(int(res["data"]["n_users"])),
        "scenarios": res["scenarios"],
    }
    _write_json(out_dir / "survey_confirmatory.json", payload)

    csv_rows: list[dict[str, Any]] = []
    for sc, s_res in res["scenarios"].items():
        for cmp_family, base_name in (("comparisons", "ShrunkMean"), ("comparisons_vs_random", "Random")):
            fam_dict = s_res.get(cmp_family, {})
            for metric_key, per_model in fam_dict.items():
                for mname, entry in per_model.items():
                    csv_rows.append(
                        {
                            "scenario": sc,
                            "baseline": base_name,
                            "metric": metric_key,
                            "model": mname,
                            "n": entry["n"],
                            "mean_a": entry["desc_a"]["mean"],
                            "sd_a": entry["desc_a"]["sd"],
                            "mean_b": entry["desc_b"]["mean"],
                            "sd_b": entry["desc_b"]["sd"],
                            "diff": entry["diff"],
                            "ci_lo": entry["lo"],
                            "ci_hi": entry["hi"],
                            "p_boot": entry["p"],
                            "p_wilcoxon": entry["wilcoxon"]["p"],
                            "p_holm": entry.get("p_holm", ""),
                            "cohen_dz": entry["cohens_dz"]["d_z"],
                            "hedges_gz": entry["cohens_dz"]["hedges_gz"],
                            "dz_lo": entry["cohens_dz"]["lo"],
                            "dz_hi": entry["cohens_dz"]["hi"],
                            "rank_biserial": entry["wilcoxon"]["rank_biserial"],
                            "normality_p": entry["assumptions"]["normality_p"],
                            "symmetry_flag": entry["assumptions"]["symmetry_flag"],
                            "d_mde_80": s_res["d_mde_80"],
                            "SIMULATED": True,
                        }
                    )
    if csv_rows:
        with open(out_dir / "survey_confirmatory_pairs.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(csv_rows[0].keys()))
            w.writeheader()
            w.writerows(csv_rows)
    return payload


# ----------------------------------------------------------------------------------------------------- 8. Sanity Controls


def build_sanity_controls(
    ctx: StudyCtx,
    conf_res: dict[str, Any],
    survey_res: dict[str, Any],
    out_dir: Path = OUT_DIR,
) -> dict[str, Any]:
    _log("running negative & feature/rating-permutation sanity controls...")
    s_test = ctx.split("test")
    cold_allowed = np.zeros(ctx.d.n_items, dtype=bool)
    cold_allowed[s_test.cold_items] = True

    # 1) Food.com warm Random & MostPop sanity
    w_rnd = conf_res["warm"]["models"]["Random"]["ndcg@10"]["mean"]
    w_pop = conf_res["warm"]["models"]["MostPop"]["ndcg@10"]["mean"]
    w_hyb = conf_res["warm"]["models"]["HybridCFContent"]["ndcg@10"]["mean"]
    warm_rnd_ok = bool(w_rnd < 0.005 and w_pop > w_rnd + 0.01 and w_hyb > w_rnd + 0.01)

    # 2) Food.com cold Random & ColdHybrid sanity
    c_rnd = conf_res["cold"]["models"]["Random"]["ndcg@10"]["mean"]
    c_hyb = conf_res["cold"]["models"]["ColdHybrid"]["ndcg@10"]["mean"]
    c_cnt = conf_res["cold"]["models"]["ContentCosine"]["ndcg@10"]["mean"]
    cold_rnd_ok = bool(0.01 < c_rnd < 0.035 and c_hyb > c_rnd + 0.01 and c_cnt > c_rnd + 0.01)

    # 3) Food.com cold feature-row permutation check
    rng = np.random.default_rng(999)
    perm_items = rng.permutation(ctx.F_only.shape[0])
    F_perm = ctx.F_only[perm_items].tocsr()
    m_cnt_perm = models.ContentCosine().fit(s_test.train, item_features=F_perm)
    ev_cnt_perm = metrics.topk_metrics(m_cnt_perm.scores, s_test.cold_targets, s_test.seen, k=K, allowed=cold_allowed)
    cnt_perm_sum = metrics.summarize(ev_cnt_perm, k=K)

    alpha = conf_res["val_tuning"]["cold_hybrid"]["best_alpha"]
    m_ch_perm = models.ColdHybrid(alpha=alpha, seed=0).fit(s_test.train, item_features=F_perm, allowed=cold_allowed)
    ev_ch_perm = metrics.topk_metrics(m_ch_perm.scores, s_test.cold_targets, s_test.seen, k=K, allowed=cold_allowed)
    ch_perm_sum = metrics.summarize(ev_ch_perm, k=K)
    foodcom_perm_ok = bool(cnt_perm_sum["ndcg@10"] <= 0.028 and ch_perm_sum["ndcg@10"] <= 0.028 and ch_perm_sum["ndcg@10"] < c_hyb - 0.015)

    # 4) VN Survey RandomRanker near chance
    sv_rnd_aucs = {sc: survey_res["scenarios"][sc]["models"]["Random"]["auc"]["mean"] for sc in survey.SCENARIOS}
    sv_rnd_ok = all(abs(v - 0.5) < 0.05 for v in sv_rnd_aucs.values())

    # 5) VN Survey rating & favorite permutation check (warm & user_cold, seed=0)
    cat = kb_catalog.load()
    sd = survey.simulate(cat, seed=20261018)
    rng_s = np.random.default_rng(777)
    perm_df = sd.ratings.copy()
    for _, idx in perm_df.groupby("user").indices.items():
        perm_df.iloc[idx, perm_df.columns.get_loc("rating")] = rng_s.permutation(perm_df.iloc[idx]["rating"].to_numpy())
    user_keys = sorted(sd.favorites)
    perm_users = rng_s.permutation(user_keys)
    perm_favs = {u: sd.favorites[int(pu)] for u, pu in zip(user_keys, perm_users, strict=True)}
    sd_perm = survey.SurveyData(perm_df, sd.never, perm_favs, sd.n_users, cat, simulated=True, meta=sd.meta)

    perm_check_models = [survey.ShrunkMean, survey.BiasedMF, survey.HybridFactorRanker]
    # Use single-config speed for permutation sanity test
    orig_grids = {c: c.grid for c in perm_check_models}
    try:
        for c in perm_check_models:
            c.grid = c.grid[:1]
        r_w_perm = survey.run_scenario(sd_perm, "warm", seed=0, k_outer=5, models=perm_check_models)
        r_u_perm = survey.run_scenario(sd_perm, "user_cold", seed=0, k_outer=5, models=perm_check_models)
    finally:
        for c, g in orig_grids.items():
            c.grid = g
    s_w_perm = survey.summarise([r_w_perm])
    s_u_perm = survey.summarise([r_u_perm])
    w_diff_hyb = s_w_perm["comparisons"]["ndcg@5"]["HybridFactorRanker"]["diff"]
    u_diff_hyb = s_u_perm["comparisons"]["ndcg@5"]["HybridFactorRanker"]["diff"]
    w_auc_hyb = s_w_perm["models"]["HybridFactorRanker"]["auc"]["mean"]
    u_auc_hyb = s_u_perm["models"]["HybridFactorRanker"]["auc"]["mean"]
    survey_perm_ok = bool(abs(w_auc_hyb - 0.5) < 0.08 and abs(u_auc_hyb - 0.5) < 0.08 and w_diff_hyb <= 0.02 and u_diff_hyb <= 0.02)

    all_passed = bool(warm_rnd_ok and cold_rnd_ok and foodcom_perm_ok and sv_rnd_ok and survey_perm_ok)
    obj = {
        "protocol_id": PROTOCOL_ID,
        "passed": all_passed,
        "checks": {
            "foodcom_warm_random_baseline": {
                "passed": warm_rnd_ok,
                "random_ndcg@10": w_rnd,
                "mostpop_ndcg@10": w_pop,
                "hybrid_ndcg@10": w_hyb,
            },
            "foodcom_cold_random_baseline": {
                "passed": cold_rnd_ok,
                "random_ndcg@10": c_rnd,
                "content_ndcg@10": c_cnt,
                "cold_hybrid_ndcg@10": c_hyb,
            },
            "foodcom_cold_feature_permutation": {
                "passed": foodcom_perm_ok,
                "unpermuted_cold_hybrid_ndcg@10": c_hyb,
                "permuted_content_cosine": cnt_perm_sum,
                "permuted_cold_hybrid": ch_perm_sum,
            },
            "vn_survey_random_chance": {
                "passed": sv_rnd_ok,
                "SIMULATED": True,
                "random_auc_by_scenario": sv_rnd_aucs,
            },
            "vn_survey_rating_favorite_permutation": {
                "passed": survey_perm_ok,
                "SIMULATED": True,
                "warm_hybrid_auc": w_auc_hyb,
                "warm_hybrid_minus_shrunkmean_ndcg@5": w_diff_hyb,
                "user_cold_hybrid_auc": u_auc_hyb,
                "user_cold_hybrid_minus_shrunkmean_ndcg@5": u_diff_hyb,
            },
        },
    }
    _write_json(out_dir / "sanity_controls.json", obj)
    return obj


# ----------------------------------------------------------------------------------------------------- 9. Summary


def build_summary(
    manifest_res: dict[str, Any],
    conf_res: dict[str, Any],
    exp_res: dict[str, Any],
    kb_res: dict[str, Any],
    survey_res: dict[str, Any],
    sanity_res: dict[str, Any],
    export_res: dict[str, Any],
    out_dir: Path = OUT_DIR,
    deploy_dir: Path = export_ranker.DEFAULT_DEPLOY_DIR,
) -> dict[str, Any]:
    artifact_files = [
        out_dir / "manifest.json",
        out_dir / "foodcom_baseline_ref.json",
        out_dir / "foodcom_confirmatory.json",
        out_dir / "foodcom_confirmatory_pairs.csv",
        out_dir / "foodcom_exploratory.json",
        out_dir / "kb_db_alignment.json",
        out_dir / "survey_confirmatory.json",
        out_dir / "survey_confirmatory_pairs.csv",
        out_dir / "sanity_controls.json",
        deploy_dir / "model.npz",
        deploy_dir / "serving.json",
        deploy_dir / "metrics.json",
    ]
    sha_index = {
        str(p.relative_to(REPO)): export_ranker.sha256_file(p) for p in artifact_files if p.exists()
    }

    h3b_w = conf_res["warm"]["confirmatory_family_h3b_warm"]["ndcg@10"]
    h3b_c = conf_res["cold"]["confirmatory_family_h3b_cold"]["ndcg@10"]

    h3a_verdicts = {}
    for sc, s_data in survey_res["scenarios"].items():
        hyb_cmp = s_data["comparisons"]["ndcg@5"]["HybridFactorRanker"]
        lm_cmp = s_data["comparisons"]["ndcg@5"]["LambdaMART"]
        best_cmp = s_data["comparisons"]["ndcg@5"][survey.BEST]
        h3a_verdicts[sc] = {
            "SIMULATED": True,
            "HybridFactorRanker_vs_ShrunkMean": {
                "diff": hyb_cmp["diff"],
                "ci95": [hyb_cmp["lo"], hyb_cmp["hi"]],
                "p_holm": hyb_cmp["p_holm"],
            },
            "LambdaMART_vs_ShrunkMean": {
                "diff": lm_cmp["diff"],
                "ci95": [lm_cmp["lo"], lm_cmp["hi"]],
                "p_holm": lm_cmp["p_holm"],
            },
            "Best_vs_ShrunkMean": {
                "diff": best_cmp["diff"],
                "ci95": [best_cmp["lo"], best_cmp["hi"]],
                "p": best_cmp["p"],
            },
        }

    obj = {
        "protocol_id": PROTOCOL_ID,
        "SIMULATED_survey_and_ranker": True,
        "simulation_disclaimer": survey_res["simulation_disclaimer"],
        "artifact_sha256": sha_index,
        "verdicts": {
            "H3b_Warm": {
                "HybridCFContent_vs_Random": {
                    "diff": h3b_w["HybridCFContent_vs_Random"]["paired_bootstrap"]["diff"],
                    "p_holm": h3b_w["HybridCFContent_vs_Random"]["p_holm"],
                },
                "HybridCFContent_vs_MostPop": {
                    "diff": h3b_w["HybridCFContent_vs_MostPop"]["paired_bootstrap"]["diff"],
                    "ci95": [h3b_w["HybridCFContent_vs_MostPop"]["paired_bootstrap"]["lo"], h3b_w["HybridCFContent_vs_MostPop"]["paired_bootstrap"]["hi"]],
                    "p_holm": h3b_w["HybridCFContent_vs_MostPop"]["p_holm"],
                },
                "TwoStageLGBMReranker_vs_MostPop": {
                    "diff": h3b_w["TwoStageLGBMReranker_vs_MostPop"]["paired_bootstrap"]["diff"],
                    "ci95": [h3b_w["TwoStageLGBMReranker_vs_MostPop"]["paired_bootstrap"]["lo"], h3b_w["TwoStageLGBMReranker_vs_MostPop"]["paired_bootstrap"]["hi"]],
                    "p_holm": h3b_w["TwoStageLGBMReranker_vs_MostPop"]["p_holm"],
                },
            },
            "H3b_Cold": {
                "ColdHybrid_vs_Random": {
                    "diff": h3b_c["ColdHybrid_vs_Random"]["paired_bootstrap"]["diff"],
                    "p_holm": h3b_c["ColdHybrid_vs_Random"]["p_holm"],
                },
                "ColdHybrid_vs_ContentCosine": {
                    "diff": h3b_c["ColdHybrid_vs_ContentCosine"]["paired_bootstrap"]["diff"],
                    "ci95": [h3b_c["ColdHybrid_vs_ContentCosine"]["paired_bootstrap"]["lo"], h3b_c["ColdHybrid_vs_ContentCosine"]["paired_bootstrap"]["hi"]],
                    "p_holm": h3b_c["ColdHybrid_vs_ContentCosine"]["p_holm"],
                },
            },
            "H3a_Survey_SIMULATED": h3a_verdicts,
            "Exploratory_5": {
                "kb_total": kb_res["kb_publishability"]["n_kb_total"],
                "kb_publishable": kb_res["kb_publishability"]["n_publishable"],
                "kb_draft": kb_res["kb_publishability"]["n_draft"],
                "cold_ablation_ndcg@10": {
                    k: v["ndcg@10"]["mean"] for k, v in exp_res["cold_lightfm_feature_ablations"]["models"].items()
                },
            },
            "sanity_controls_passed": sanity_res["passed"],
            "exported_ranker": export_res,
        },
        "mde_sensitivity": manifest_res["mde_sensitivity"],
    }
    _write_json(out_dir / "summary.json", obj)
    return obj


# ----------------------------------------------------------------------------------------------------- CLI


def run_all(
    out_dir: Path = OUT_DIR,
    deploy_dir: Path = export_ranker.DEFAULT_DEPLOY_DIR,
    workers: int = 8,
    force: bool = False,
) -> dict[str, Any]:
    out_dir = Path(out_dir)
    cache_dir = out_dir / "cache"
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    if force:
        for p in out_dir.glob("*.json"):
            p.unlink(missing_ok=True)
        for p in out_dir.glob("*.csv"):
            p.unlink(missing_ok=True)
        for p in cache_dir.glob("*.npz"):
            p.unlink(missing_ok=True)

    manifest_res = build_manifest(out_dir=out_dir)
    survey_res = build_survey_confirmatory(out_dir=out_dir, workers=workers)
    export_res = export_ranker.train_and_export(
        output_dir=deploy_dir,
        seed=20261018,
        cv_metrics={
            sc: {
                m: survey_res["scenarios"][sc]["models"][m]["ndcg@5"]
                for m in ("ShrunkMean", "Biased MF", "BPR (cặp chênh điểm)", "HybridFactorRanker", "LambdaMART")
                if m in survey_res["scenarios"][sc]["models"]
            }
            for sc in survey.SCENARIOS
        },
    )
    kb_res = build_kb_db_alignment(deploy_dir=deploy_dir, out_dir=out_dir)

    ctx = StudyCtx()
    build_foodcom_baseline_ref(ctx, out_dir=out_dir, cache_dir=cache_dir)
    conf_res = build_foodcom_confirmatory(ctx, out_dir=out_dir, cache_dir=cache_dir)
    exp_res = build_foodcom_exploratory(ctx, out_dir=out_dir, cache_dir=cache_dir)
    sanity_res = build_sanity_controls(ctx, conf_res=conf_res, survey_res=survey_res, out_dir=out_dir)
    return build_summary(
        manifest_res=manifest_res,
        conf_res=conf_res,
        exp_res=exp_res,
        kb_res=kb_res,
        survey_res=survey_res,
        sanity_res=sanity_res,
        export_res=export_res,
        out_dir=out_dir,
        deploy_dir=deploy_dir,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run Problem 3 RecSys M1.3a confirmatory & exploratory studies.")
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    ap.add_argument("--deploy-dir", type=Path, default=export_ranker.DEFAULT_DEPLOY_DIR)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    summary = run_all(out_dir=args.out_dir, deploy_dir=args.deploy_dir, workers=args.workers, force=args.force)
    _log("P3 research complete. sanity_controls_passed=", summary["verdicts"]["sanity_controls_passed"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
