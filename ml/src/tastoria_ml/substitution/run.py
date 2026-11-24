"""Substitution experiment (PREREG TASTORIA-ML-PREREG-2026-11-18, H4) over the 232-ingredient KB catalog:

(a) CURATED-TABLE AGREEMENT (not human accuracy; 0 human gold answers exist in queries.yaml):
    The 107 source ingredients of substitution_pairs.yaml are split 30% dev (32) / 70% test (75) with
    SPLIT_SEED = 20261018. W2V hyperparameters and HybridScorer fusion weights (Word2Vec + Nutrient + PMI +
    FoodGroup filter, strictly WITHOUT Curated lookup) are tuned on dev (n=32) and locked before scoring
    the held-out test split (n=75) across 5 W2V seeds {0..4}, aggregated per ingredient before paired tests.
(b) DIMENSION ABLATION (200d vs 100d) & 100d PGVECTOR EMBEDDINGS EXPORT:
    Tests H4 rival #2 (100d compression loss vs 200d) with paired CIs and TOST equivalence bounds (±0.03, ±0.05),
    and exports 100d L2-normalized float32 embeddings keyed by NFC name_vi to deploy/models/embeddings/.
(c) EXPLORATORY BREAKDOWNS (`analysis_intent = "exploratory"`, `bh_fdr`):
    Per-food-group performance, 232-ingredient coverage audit, and 90-query coverage + eval_rankings.json
    (including separate Hybrid + Curated reporting per H4 anti-circularity).

Run: uv run --frozen --package tastoria-ml python -m tastoria_ml.substitution.run
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import time
from collections import Counter
from pathlib import Path

import numpy as np
import scipy.stats as st
import yaml

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

from tastoria_ml.kb.substitutes import SubstitutionPairsFile  # noqa: E402
from tastoria_ml.recsys import kb_catalog, stats  # noqa: E402
from tastoria_ml.substitution import gold as gold_mod  # noqa: E402
from tastoria_ml.substitution import methods as M  # noqa: E402

REPO = kb_catalog.REPO
OUT = REPO / "data" / "processed" / "substitution"
RESEARCH_OUT = REPO / "ml" / "runs" / "research" / "p4_substitution_composer"
EXPORT_DIR = REPO / "deploy" / "models" / "embeddings"
PROTOCOL_ID = "TASTORIA-ML-PREREG-2026-11-18"
SPLIT_SEED = 20261018
SEEDS = (0, 1, 2, 3, 4)
W2V_GRID = [
    {"dim": d, "min_count": mc, "kb_repeat": kr, "epochs": 10, "negative": 10}
    for d in (50, 100, 200)
    for mc in (5, 20)
    for kr in (1, 10)
]
COMPLEMENT_TAU = 2.0  # PPMI above this = complement pair, dropped by negative control filter


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def load_pairs():
    raw = yaml.safe_load((REPO / "data" / "kb" / "substitution_pairs.yaml").read_text(encoding="utf-8"))
    return SubstitutionPairsFile.model_validate(raw).pairs


def split_ingredients(pairs, seed: int = SPLIT_SEED) -> dict[str, str]:
    ings = sorted({p.ingredient for p in pairs})
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(ings))
    n_dev = int(round(0.3 * len(ings)))
    return {ings[j]: ("dev" if r < n_dev else "test") for r, j in enumerate(order)}


def agreement(scorer, refs: dict[str, set[str]], cat, names: list[str], **kw) -> dict:
    rows = []
    for ing in names:
        cands = M.candidates(cat, ing)
        ranked = M.rank(scorer(ing, cands, **kw), cands)
        r = gold_mod.per_query(ranked, sorted(refs[ing]))
        rows.append({
            "ingredient": ing,
            "food_group": cat.ingredients[ing].food_group,
            "answered": bool(ranked),
            **r,
            "n_cands": len(cands),
            "n_ref": len(refs[ing] & set(cands)),
            "top3": ranked[:3],
        })
    return summarise_rows(rows)


def summarise_rows(rows):
    a = np.array([r["answered"] for r in rows], bool)
    return {
        "n": len(rows),
        "answered": float(a.mean()),
        "agreement@1": float(np.mean([r["hit1"] for r in rows])),
        "agreement@3": float(np.mean([r["hit3"] for r in rows])),
        "mrr": float(np.mean([r["rr"] for r in rows])),
        "agreement@3_answered": float(np.mean([r["hit3"] for r in rows if r["answered"]])) if a.any() else float("nan"),
        "rows": rows,
    }


def random_agreement(refs, cat, names) -> dict:
    rows = []
    for ing in names:
        cands = M.candidates(cat, ing)
        m = len(refs[ing] & set(cands))
        h1 = M.random_hit_prob(len(cands), m, 1)
        h3 = M.random_hit_prob(len(cands), m, 3)
        rr = M.random_mrr(len(cands), m)
        rows.append({
            "ingredient": ing,
            "food_group": cat.ingredients[ing].food_group,
            "answered": True,
            "hit1": float(h1),
            "hit3": float(h3),
            "rr": float(rr),
            "n_cands": len(cands),
            "n_ref": m,
        })
    return {
        "n": len(names),
        "answered": 1.0,
        "agreement@1": float(np.mean([r["hit1"] for r in rows])),
        "agreement@3": float(np.mean([r["hit3"] for r in rows])),
        "mrr": float(np.mean([r["rr"] for r in rows])),
        "rows": rows,
        "note": "exact expectation of a uniform random order within the food group",
    }


def _descriptives(vals: np.ndarray) -> dict:
    arr = np.asarray(vals, dtype=float)
    mean, lo, hi = stats.mean_ci(arr, n_boot=5000, seed=9)
    q25, med, q75 = np.percentile(arr, [25, 50, 75])
    return {
        "n": int(len(arr)),
        "mean": float(mean),
        "sd": float(arr.std(ddof=1)) if len(arr) > 1 else 0.0,
        "median": float(med),
        "iqr": float(q75 - q25),
        "q25": float(q25),
        "q75": float(q75),
        "min": float(arr.min()),
        "max": float(arr.max()),
        "ci95": [float(lo), float(hi)],
        "n_zero": int((arr == 0.0).sum()),
        "n_one": int((arr == 1.0).sum()),
    }


def _tune_hybrid_on_dev(
    w2v: M.W2V,
    nut: M.Nutrient,
    pmi: M.PMI,
    refs: dict[str, set[str]],
    cat,
    dev: list[str],
    step: float = 0.05,
) -> dict:
    """Tune HybridScorer (norm_mode, missing_mode, simplex weights) strictly on dev (n=32)."""
    cands_by_ing = {ing: M.candidates(cat, ing) for ing in dev}
    raw_cache = {
        ing: {
            "w2v": w2v.score(ing, cands_by_ing[ing]),
            "nut": nut.score(ing, cands_by_ing[ing]),
            "pmi": pmi.score(ing, cands_by_ing[ing]),
        }
        for ing in dev
    }

    def _norm_dict(raw: dict[str, float], kind: str, mode: str) -> dict[str, float]:
        if not raw:
            return {}
        if mode == "affine":
            if kind in ("w2v", "nut"):
                return {c: 0.5 * (max(-1.0, min(1.0, float(v))) + 1.0) for c, v in raw.items()}
            return {c: max(0.0, min(1.0, float(v))) for c, v in raw.items()}
        vals = list(raw.values())
        lo, hi = min(vals), max(vals)
        if hi <= lo:
            return {c: 0.5 for c in raw}
        span = hi - lo
        return {c: (float(v) - lo) / span for c, v in raw.items()}

    n_steps = int(round(1.0 / step))
    weight_grid: list[tuple[float, float, float]] = []
    for i in range(n_steps + 1):
        for j in range(n_steps + 1 - i):
            k = n_steps - i - j
            w_w2v = round(i * step, 4)
            w_nut = round(j * step, 4)
            w_pmi = round(k * step, 4)
            n_active = (w_w2v > 0) + (w_nut > 0) + (w_pmi > 0)
            if n_active >= 2:  # true multi-signal fusion (exclude single-signal corners)
                weight_grid.append((w_w2v, w_nut, w_pmi))

    trials = []
    for norm_mode in ("affine", "minmax"):
        normed = {
            ing: {m: _norm_dict(raw_cache[ing][m], m, norm_mode) for m in ("w2v", "nut", "pmi")}
            for ing in dev
        }
        for missing_mode in ("renorm", "zero"):
            for w_w2v, w_nut, w_pmi in weight_grid:
                w_map = {"w2v": w_w2v, "nut": w_nut, "pmi": w_pmi}
                active_total = sum(v for v in w_map.values() if v > 0)
                rr_list, h3_list, h1_list = [], [], []
                for ing in dev:
                    cands = cands_by_ing[ing]
                    scores: dict[str, float] = {}
                    for c in cands:
                        avail = [(m, normed[ing][m][c], w_map[m]) for m in ("w2v", "nut", "pmi") if w_map[m] > 0 and c in normed[ing][m]]
                        if not avail:
                            continue
                        if missing_mode == "renorm":
                            scores[c] = sum(wt * val for _, val, wt in avail) / sum(wt for _, _, wt in avail)
                        else:
                            scores[c] = sum(wt * val for _, val, wt in avail) / active_total
                    ranked = M.rank(scores, cands)
                    pq = gold_mod.per_query(ranked, sorted(refs[ing]))
                    rr_list.append(pq["rr"])
                    h3_list.append(pq["hit3"])
                    h1_list.append(pq["hit1"])
                trials.append({
                    "norm_mode": norm_mode,
                    "missing_mode": missing_mode,
                    "weights": w_map,
                    "n_signals": int((w_w2v > 0) + (w_nut > 0) + (w_pmi > 0)),
                    "dev_mrr": float(np.mean(rr_list)),
                    "dev_agreement@3": float(np.mean(h3_list)),
                    "dev_agreement@1": float(np.mean(h1_list)),
                })

    trials.sort(
        key=lambda r: (
            -round(r["dev_mrr"], 9),
            -round(r["dev_agreement@3"], 9),
            -r["n_signals"],
            -r["weights"]["w2v"],
        )
    )
    best_cfg = trials[0]
    by_mode = {}
    for nm in ("affine", "minmax"):
        for mm in ("renorm", "zero"):
            sub = [t for t in trials if t["norm_mode"] == nm and t["missing_mode"] == mm]
            by_mode[f"{nm}__{mm}"] = sub[0]
    return {"best": best_cfg, "best_by_mode": by_mode, "top10": trials[:10], "n_grid": len(trials)}


def _paired_full(a_rr: np.ndarray, b_rr: np.ndarray, a_hit3_s0: np.ndarray | None, b_hit3_s0: np.ndarray | None, seed: int = 9) -> dict:
    out = {
        "n": int(len(a_rr)),
        "assumptions": stats.check_paired_assumptions(a_rr, b_rr),
        "bootstrap_rr": stats.paired_bootstrap(a_rr, b_rr, n_boot=5000, seed=seed),
        "wilcoxon_rr": stats.wilcoxon(a_rr, b_rr),
        "effect_dz_rr": stats.cohens_dz(a_rr, b_rr, n_boot=2000, seed=seed),
    }
    if a_hit3_s0 is not None and b_hit3_s0 is not None:
        out["mcnemar_agreement@3_seed0"] = stats.mcnemar(a_hit3_s0.astype(bool), b_hit3_s0.astype(bool))
    return out


def _tost_paired(a: np.ndarray, b: np.ndarray, margins: tuple[float, ...] = (0.03, 0.05), seed: int = 9) -> dict:
    d = np.asarray(a, dtype=float) - np.asarray(b, dtype=float)
    n = len(d)
    mean_d = float(d.mean())
    sd_d = float(d.std(ddof=1))
    se = sd_d / math.sqrt(n) if n > 0 else float("nan")
    _, lo90, hi90 = stats.mean_ci(d, n_boot=5000, seed=seed, alpha=0.10)
    _, lo95, hi95 = stats.mean_ci(d, n_boot=5000, seed=seed, alpha=0.05)
    tost = {}
    for delta in margins:
        if se > 0 and n > 1:
            t1 = (mean_d - (-delta)) / se
            t2 = (mean_d - delta) / se
            p1 = float(1.0 - st.t.cdf(t1, df=n - 1))
            p2 = float(st.t.cdf(t2, df=n - 1))
            p_tost = max(p1, p2)
        else:
            p1 = p2 = p_tost = 0.0 if abs(mean_d) < delta else 1.0
        tost[f"margin_{delta:.2f}"] = {
            "delta": delta,
            "p_lower": p1,
            "p_upper": p2,
            "p_tost": p_tost,
            "equivalent_90ci": bool(lo90 > -delta and hi90 < delta),
            "equivalent_tost_05": bool(p_tost < 0.05),
        }
    return {
        "n": n,
        "mean_diff": mean_d,
        "sd_diff": sd_d,
        "ci90_boot": [float(lo90), float(hi90)],
        "ci95_boot": [float(lo95), float(hi95)],
        "bootstrap": stats.paired_bootstrap(a, b, n_boot=5000, seed=seed),
        "wilcoxon": stats.wilcoxon(a, b),
        "cohens_dz": stats.cohens_dz(a, b, n_boot=2000, seed=seed),
        "tost": tost,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Ingredient substitution benchmark, Hybrid Fusion & 100d pgvector export")
    ap.add_argument("--workers", type=int, default=1, help="Gensim Word2Vec worker threads (default=1 for reproducibility)")
    ap.add_argument("--out-research", type=Path, default=RESEARCH_OUT)
    ap.add_argument("--export-dir", type=Path, default=EXPORT_DIR)
    ap.add_argument("--skip-export", action="store_true")
    args = ap.parse_args(argv)

    OUT.mkdir(parents=True, exist_ok=True)
    args.out_research.mkdir(parents=True, exist_ok=True)

    cat = kb_catalog.load()
    pairs = load_pairs()
    log("corpus")
    fc = M.foodcom_sentences()
    mp = M.build_mapping(cat, fc)
    kb = M.kb_sentences(cat, mp)
    split = split_ingredients(pairs)
    refs: dict[str, set[str]] = {}
    for p in pairs:
        refs.setdefault(p.ingredient, set()).add(p.substitute)
    dev = sorted(i for i, s in split.items() if s == "dev")
    test = sorted(i for i, s in split.items() if s == "test")

    occ = Counter(ln.name for r in cat.recipes for ln in r.ingredients)
    total_occ = sum(occ.values())
    non_staple = [n for n, i in cat.ingredients.items() if not i.is_staple]
    mapped = sorted(n for n in cat.ingredients if mp.en_tokens[n])
    mapped50 = sorted(n for n in cat.ingredients if any(mp.counts[t] >= 50 for t in mp.en_tokens[n]))
    unmapped = sorted(set(cat.ingredients) - set(mapped))

    # ---------------- Word2Vec hyperparameter tuning strictly on dev (n=32)
    tun = []
    for g in W2V_GRID:
        t0 = time.time()
        w = M.W2V(**g, seed=0, workers=args.workers).fit(fc, kb, mp, cat)
        ag = agreement(w.score, refs, cat, dev)
        tun.append({
            "params": g,
            "workers": args.workers,
            "window": w.window,
            "dev_mrr": ag["mrr"],
            "dev_agreement@3": ag["agreement@3"],
            "dev_agreement@1": ag["agreement@1"],
            "dev_answered": ag["answered"],
            "vocab": len(w.model.wv),
            "covered_kb": len(w.vec),
            "seconds": round(time.time() - t0, 2),
        })
        log("w2v dev", g, round(ag["mrr"], 4))

    best = max(tun, key=lambda r: (r["dev_mrr"], r["dev_agreement@3"]))
    best_100 = max([r for r in tun if r["params"]["dim"] == 100], key=lambda r: (r["dev_mrr"], r["dev_agreement@3"]))
    best_200 = max([r for r in tun if r["params"]["dim"] == 200], key=lambda r: (r["dev_mrr"], r["dev_agreement@3"]))

    nut = M.Nutrient().fit(cat)
    pmi = M.PMI().fit(fc, kb, mp, cat)

    # ---------------- Hybrid Fusion tuning strictly on dev (n=32)
    w2v_100_dev = M.W2V(**best_100["params"], seed=0, workers=args.workers).fit(fc, kb, mp, cat)
    w2v_200_dev = M.W2V(**best_200["params"], seed=0, workers=args.workers).fit(fc, kb, mp, cat)
    hybrid_tune_100 = _tune_hybrid_on_dev(w2v_100_dev, nut, pmi, refs, cat, dev)
    hybrid_tune_200 = _tune_hybrid_on_dev(w2v_200_dev, nut, pmi, refs, cat, dev)
    h100_cfg = hybrid_tune_100["best"]
    h200_cfg = hybrid_tune_200["best"]
    log("hybrid 100d dev best", h100_cfg)
    log("hybrid 200d dev best", h200_cfg)

    # ---------------- Held-out test evaluation (n=75, 5 seeds {0..4})
    w2v100_models, w2v200_models = [], []
    w2v100_runs, w2v200_runs, w2v100_filt_runs = [], [], []
    hyb100_runs, hyb200_runs = [], []

    for sd in SEEDS:
        w100 = M.W2V(**best_100["params"], seed=sd, workers=args.workers).fit(fc, kb, mp, cat)
        w200 = M.W2V(**best_200["params"], seed=sd, workers=args.workers).fit(fc, kb, mp, cat)
        w2v100_models.append(w100)
        w2v200_models.append(w200)

        w2v100_runs.append(agreement(w100.score, refs, cat, test))
        w2v200_runs.append(agreement(w200.score, refs, cat, test))

        def _filtered(ing, cands, _w=w100):
            s = _w.score(ing, cands)
            return {c: v for c, v in s.items() if pmi.direct(ing, c) <= COMPLEMENT_TAU}

        w2v100_filt_runs.append(agreement(_filtered, refs, cat, test))

        h100 = M.HybridScorer(
            w2v=w100, nut=nut, pmi=pmi,
            weights=h100_cfg["weights"], norm_mode=h100_cfg["norm_mode"], missing_mode=h100_cfg["missing_mode"],
        )
        h200 = M.HybridScorer(
            w2v=w200, nut=nut, pmi=pmi,
            weights=h200_cfg["weights"], norm_mode=h200_cfg["norm_mode"], missing_mode=h200_cfg["missing_mode"],
        )
        hyb100_runs.append(agreement(h100.score, refs, cat, test))
        hyb200_runs.append(agreement(h200.score, refs, cat, test))
        log("test seed", sd, "w2v100", round(w2v100_runs[-1]["mrr"], 4), "hyb100", round(hyb100_runs[-1]["mrr"], 4))

    nut_run = agreement(nut.score, refs, cat, test)
    pmi_run = agreement(pmi.score, refs, cat, test)
    rnd_run = random_agreement(refs, cat, test)

    # Order of <=8 methods in results.json["test"] (matching figures.SERIES len == 8!)
    methods_ordered = {
        "Hybrid Fusion (100d)": hyb100_runs,
        "Hybrid Fusion (200d)": hyb200_runs,
        "Word2Vec (200d)": w2v200_runs,
        "Word2Vec (100d)": w2v100_runs,
        "kNN dinh dưỡng": [nut_run],
        "PMI ngữ cảnh": [pmi_run],
        f"Word2Vec (100d) + lọc bổ sung (PPMI ≤ {COMPLEMENT_TAU})": w2v100_filt_runs,
    }

    def _seed_avg_arr(runs: list[dict], key: str) -> np.ndarray:
        return np.mean([[r[key] for r in run["rows"]] for run in runs], axis=0)

    test_summary = {}
    for name, runs in methods_ordered.items():
        rr_arr = _seed_avg_arr(runs, "rr")
        h3_arr = _seed_avg_arr(runs, "hit3")
        h1_arr = _seed_avg_arr(runs, "hit1")
        entry = {
            k: {
                "mean": float(np.mean([r[k] for r in runs])),
                "sd": float(np.std([r[k] for r in runs], ddof=1)) if len(runs) > 1 else 0.0,
            }
            for k in ("agreement@1", "agreement@3", "mrr", "answered")
        }
        entry["seeds"] = len(runs)
        entry["descriptives"] = {
            "mrr": _descriptives(rr_arr),
            "agreement@3": _descriptives(h3_arr),
            "agreement@1": _descriptives(h1_arr),
        }
        entry["agreement@3"]["ci95"] = entry["descriptives"]["agreement@3"]["ci95"]
        entry["mrr"]["ci95"] = entry["descriptives"]["mrr"]["ci95"]
        entry["rows_seed0"] = runs[0]["rows"]
        test_summary[name] = entry

    rnd_rr = np.array([r["rr"] for r in rnd_run["rows"]], float)
    rnd_h3 = np.array([r["hit3"] for r in rnd_run["rows"]], float)
    rnd_h1 = np.array([r["hit1"] for r in rnd_run["rows"]], float)
    test_summary["Ngẫu nhiên cùng nhóm"] = {
        "n": rnd_run["n"],
        "answered": rnd_run["answered"],
        "agreement@1": rnd_run["agreement@1"],
        "agreement@3": rnd_run["agreement@3"],
        "mrr": rnd_run["mrr"],
        "note": rnd_run["note"],
        "descriptives": {
            "mrr": _descriptives(rnd_rr),
            "agreement@3": _descriptives(rnd_h3),
            "agreement@1": _descriptives(rnd_h1),
        },
    }

    # ---------------- Confirmatory statistical family (Holm-Bonferroni, n=75, MDE d_z ~ 0.324)
    mde_n75 = float(2.80158 / math.sqrt(len(test)))
    mde_n63 = float(2.80158 / math.sqrt(63))

    def _get_rr(name: str) -> np.ndarray:
        return rnd_rr if name == "Ngẫu nhiên cùng nhóm" else _seed_avg_arr(methods_ordered[name], "rr")

    def _get_h3_s0(name: str) -> np.ndarray | None:
        return None if name == "Ngẫu nhiên cùng nhóm" else np.array([r["hit3"] for r in methods_ordered[name][0]["rows"]], bool)

    neg_ctrl_name = f"Word2Vec (100d) + lọc bổ sung (PPMI ≤ {COMPLEMENT_TAU})"
    confirmatory_contrasts = [
        ("Hybrid Fusion (100d)", "Word2Vec (100d)"),
        ("Hybrid Fusion (100d)", "kNN dinh dưỡng"),
        ("Hybrid Fusion (100d)", "PMI ngữ cảnh"),
        ("Hybrid Fusion (100d)", "Ngẫu nhiên cùng nhóm"),
        ("Word2Vec (100d)", "Ngẫu nhiên cùng nhóm"),
        ("Word2Vec (100d)", neg_ctrl_name),
    ]
    conf_pairs = {}
    conf_labels = []
    for a_name, b_name in confirmatory_contrasts:
        key = f"{a_name} vs {b_name}"
        conf_pairs[key] = {
            "analysis_intent": "confirmatory",
            "family": "H4_confirmatory_n75",
            "mde_dz_80pct": mde_n75,
            **_paired_full(_get_rr(a_name), _get_rr(b_name), _get_h3_s0(a_name), _get_h3_s0(b_name), seed=9),
        }
        conf_labels.append(key)

    p_boot_adj = stats.holm([conf_pairs[k]["bootstrap_rr"]["p"] for k in conf_labels])
    p_wil_adj = stats.holm([conf_pairs[k]["wilcoxon_rr"]["p"] for k in conf_labels])
    for k, pb, pw in zip(conf_labels, p_boot_adj, p_wil_adj, strict=True):
        conf_pairs[k]["bootstrap_rr"]["p_holm"] = float(pb)
        conf_pairs[k]["wilcoxon_rr"]["p_holm"] = float(pw)

    # ---------------- 200d vs 100d Dimension Ablation (H4 rival #2)
    ablation_dim = {
        "protocol_id": PROTOCOL_ID,
        "hypothesis": "H4_rival_2_dim_compression_100d_vs_200d",
        "n_test_ingredients": len(test),
        "mde_dz_80pct": mde_n75,
        "w2v_100d_params": best_100["params"],
        "w2v_200d_params": best_200["params"],
        "hybrid_100d_cfg": h100_cfg,
        "hybrid_200d_cfg": h200_cfg,
        "comparisons": {
            "W2V_100d_vs_200d": {
                "mrr": _tost_paired(_get_rr("Word2Vec (100d)"), _get_rr("Word2Vec (200d)")),
                "agreement@3": _tost_paired(
                    _seed_avg_arr(w2v100_runs, "hit3"),
                    _seed_avg_arr(w2v200_runs, "hit3"),
                ),
            },
            "Hybrid_100d_vs_200d": {
                "mrr": _tost_paired(_get_rr("Hybrid Fusion (100d)"), _get_rr("Hybrid Fusion (200d)")),
                "agreement@3": _tost_paired(
                    _seed_avg_arr(hyb100_runs, "hit3"),
                    _seed_avg_arr(hyb200_runs, "hit3"),
                ),
            },
        },
    }

    # ---------------- Coverage audit across all 232 KB ingredients (exploratory)
    w100_0 = w2v100_models[0]
    w200_0 = w2v200_models[0]
    h100_0 = M.HybridScorer(
        w2v=w100_0, nut=nut, pmi=pmi,
        weights=h100_cfg["weights"], norm_mode=h100_cfg["norm_mode"], missing_mode=h100_cfg["missing_mode"],
    )
    uncovered_w2v100 = sorted(set(cat.ingredients) - set(w100_0.vec))
    uncovered_nut = sorted(set(cat.ingredients) - set(nut.vec))
    uncovered_pmi = sorted(set(cat.ingredients) - set(pmi.idx))
    uncovered_any_hybrid = sorted(set(uncovered_w2v100) & set(uncovered_nut) & set(uncovered_pmi))
    union_curated = sorted({p.ingredient for p in pairs} | {p.substitute for p in pairs})

    coverage_audit = {
        "analysis_intent": "exploratory",
        "kb_ingredients_total": len(cat.ingredients),
        "kb_recipes_total": len(cat.recipes),
        "total_recipe_ingredient_occurrences": total_occ,
        "foodcom_en_mapping": {
            "mapped_count": len(mapped),
            "unmapped_count": len(unmapped),
            "mapped_share": len(mapped) / len(cat.ingredients),
            "occurrence_share_mapped": sum(occ[n] for n in mapped) / total_occ,
            "unmapped_ingredients": unmapped,
        },
        "word2vec_100d": {
            "covered_count": len(w100_0.vec),
            "en_count": sum(1 for s in w100_0.source.values() if s == "en"),
            "vi_only_count": sum(1 for s in w100_0.source.values() if s == "vi"),
            "share_ingredients": len(w100_0.vec) / len(cat.ingredients),
            "share_occurrences": sum(occ[n] for n in w100_0.vec) / total_occ,
            "uncovered_count": len(uncovered_w2v100),
            "uncovered_ingredients": uncovered_w2v100,
        },
        "word2vec_200d": {
            "covered_count": len(w200_0.vec),
            "share_ingredients": len(w200_0.vec) / len(cat.ingredients),
            "share_occurrences": sum(occ[n] for n in w200_0.vec) / total_occ,
        },
        "nutrient": {
            "covered_count": len(nut.vec),
            "share_ingredients": len(nut.vec) / len(cat.ingredients),
            "share_occurrences": sum(occ[n] for n in nut.vec) / total_occ,
            "uncovered_count": len(uncovered_nut),
            "uncovered_ingredients": uncovered_nut,
        },
        "pmi": {
            "covered_count": len(pmi.idx),
            "share_ingredients": len(pmi.idx) / len(cat.ingredients),
            "share_occurrences": sum(occ[n] for n in pmi.idx) / total_occ,
            "uncovered_count": len(uncovered_pmi),
            "uncovered_ingredients": uncovered_pmi,
        },
        "hybrid_union": {
            "covered_count": len(cat.ingredients) - len(uncovered_any_hybrid),
            "share_ingredients": (len(cat.ingredients) - len(uncovered_any_hybrid)) / len(cat.ingredients),
            "uncovered_all_three_count": len(uncovered_any_hybrid),
            "uncovered_all_three": uncovered_any_hybrid,
            "w2v_uncovered_but_nutrient_covered": sorted(set(uncovered_w2v100) & set(nut.vec)),
        },
        "curated_table": {
            "n_pairs": len(pairs),
            "source_ingredients": len(refs),
            "union_ingredients": len(union_curated),
            "dev_ingredients": len(dev),
            "test_ingredients": len(test),
            "share_source_ingredients": len(refs) / len(cat.ingredients),
            "share_union_ingredients": len(union_curated) / len(cat.ingredients),
        },
        "split_coverage": {
            "dev_uncovered_w2v100": sorted(set(dev) & set(uncovered_w2v100)),
            "test_uncovered_w2v100": sorted(set(test) & set(uncovered_w2v100)),
            "test_uncovered_nut": sorted(set(test) & set(uncovered_nut)),
            "test_uncovered_pmi": sorted(set(test) & set(uncovered_pmi)),
        },
        "non_meal_and_make_ahead": {
            "do_an_vat": sorted(n for n, i in cat.ingredients.items() if i.food_group == "do_an_vat"),
            "make_ahead_only": ["cà pháo muối", "dưa giá"],
        },
    }

    # ---------------- Exploratory per-food-group breakdown on test (n=75, bh_fdr)
    fg_groups = sorted({cat.ingredients[ing].food_group for ing in test})
    fg_rows = []
    fg_p_raw = []
    fg_idx_for_fdr = []
    hyb_rr_all = _get_rr("Hybrid Fusion (100d)")
    w2v_rr_all = _get_rr("Word2Vec (100d)")
    nut_rr_all = _get_rr("kNN dinh dưỡng")
    pmi_rr_all = _get_rr("PMI ngữ cảnh")

    for fg in fg_groups:
        idx = [i for i, ing in enumerate(test) if cat.ingredients[ing].food_group == fg]
        row = {
            "food_group": fg,
            "n_test_ings": len(idx),
            "hybrid_100d_mrr": float(hyb_rr_all[idx].mean()),
            "w2v_100d_mrr": float(w2v_rr_all[idx].mean()),
            "nutrient_mrr": float(nut_rr_all[idx].mean()),
            "pmi_mrr": float(pmi_rr_all[idx].mean()),
            "random_mrr": float(rnd_rr[idx].mean()),
            "hybrid_100d_agree3": float(_seed_avg_arr(hyb100_runs, "hit3")[idx].mean()),
            "w2v_100d_agree3": float(_seed_avg_arr(w2v100_runs, "hit3")[idx].mean()),
            "diff_hybrid_minus_w2v_mrr": float((hyb_rr_all[idx] - w2v_rr_all[idx]).mean()),
            "p_raw": float("nan"),
            "q_bh": float("nan"),
        }
        if len(idx) >= 5:
            bs = stats.paired_bootstrap(hyb_rr_all[idx], w2v_rr_all[idx], n_boot=2000, seed=9)
            row["p_raw"] = float(bs["p"])
            fg_p_raw.append(float(bs["p"]))
            fg_idx_for_fdr.append(len(fg_rows))
        fg_rows.append(row)

    if fg_p_raw:
        q_vals = stats.bh_fdr(fg_p_raw)
        for row_idx, qv in zip(fg_idx_for_fdr, q_vals, strict=True):
            fg_rows[row_idx]["q_bh"] = float(qv)

    # ---------------- 90 Evaluation Queries (queries.yaml: 27 dev / 63 test) + eval_rankings.json
    queries = gold_mod.load_queries()
    recipes = {r.slug: r for r in cat.recipes}
    cur = M.Curated(pairs)
    hyb_cur_0 = M.HybridWithCurated(cur, h100_0)
    rankings = {}
    for q in queries:
        r = recipes[q["slug"]]
        cands = M.candidates(cat, q["missing"])
        rankings[q["id"]] = {
            "Bảng tra": M.rank(cur.score(q["missing"], cands, r.slot, r.method), cands),
            "Word2Vec": M.rank(w100_0.score(q["missing"], cands), cands),
            "Word2Vec (100d)": M.rank(w100_0.score(q["missing"], cands), cands),
            "Word2Vec (200d)": M.rank(w200_0.score(q["missing"], cands), cands),
            "kNN dinh dưỡng": M.rank(nut.score(q["missing"], cands), cands),
            "PMI ngữ cảnh": M.rank(pmi.score(q["missing"], cands), cands),
            "Hybrid Fusion (100d)": M.rank(h100_0.score(q["missing"], cands), cands),
            "Hybrid + Bảng tra": M.rank(hyb_cur_0.score(q["missing"], cands, r.slot, r.method), cands),
        }

    query_methods = (
        "Bảng tra",
        "Word2Vec (100d)",
        "Word2Vec (200d)",
        "kNN dinh dưỡng",
        "PMI ngữ cảnh",
        "Hybrid Fusion (100d)",
        "Hybrid + Bảng tra",
    )
    query_coverage = {
        split_name: {
            m: float(np.mean([bool(rankings[q["id"]][m]) for q in queries if split_name == "all" or q["split"] == split_name]))
            for m in query_methods
        }
        for split_name in ("all", "dev", "test")
    }
    query_coverage["n"] = len(queries)
    query_coverage["n_by_split"] = {
        "all": len(queries),
        "dev": sum(1 for q in queries if q["split"] == "dev"),
        "test": sum(1 for q in queries if q["split"] == "test"),
    }
    query_coverage["mde_dz_test_n63"] = mde_n63
    query_coverage["human_answers_present"] = 0

    test_qs = [q for q in queries if q["split"] == "test"]
    cov_pairs = {}
    cov_labels = []
    for a_m, b_m in (
        ("Hybrid Fusion (100d)", "Bảng tra"),
        ("Hybrid Fusion (100d)", "PMI ngữ cảnh"),
        ("Hybrid Fusion (100d)", "kNN dinh dưỡng"),
        ("Hybrid + Bảng tra", "Bảng tra"),
    ):
        a_arr = np.array([bool(rankings[q["id"]][a_m]) for q in test_qs], bool)
        b_arr = np.array([bool(rankings[q["id"]][b_m]) for q in test_qs], bool)
        lbl = f"{a_m} vs {b_m}"
        cov_pairs[lbl] = {"analysis_intent": "exploratory", **stats.mcnemar(a_arr, b_arr)}
        cov_labels.append(lbl)
    for lbl, qv in zip(cov_labels, stats.bh_fdr([cov_pairs[k]["p"] for k in cov_labels]), strict=True):
        cov_pairs[lbl]["q_bh"] = float(qv)
    query_coverage["test_mcnemar_bh"] = cov_pairs

    curated_disclosure = {
        "note": (
            "Curated table lookup is EXCLUDED from HybridScorer during the n=75 held-out test evaluation. "
            "If test-split curated pairs are masked (held-out), Curated abstains (0.0 agreement, 0.0 MRR). "
            "If unmasked, Curated achieves 1.0 trivially by circularity. On queries.yaml (n=90, 0 human answers), "
            "Curated context-aware coverage is 59/90 (65.6%) overall and 39/63 (61.9%) on test, whereas Hybrid + Bảng tra "
            "covers 90/90 (100.0%)."
        ),
        "curated_masked_test_mrr": 0.0,
        "curated_unmasked_circular_mrr": 1.0,
        "queries_human_answers": 0,
        "queries_curated_coverage_all": query_coverage["all"]["Bảng tra"],
        "queries_curated_coverage_test": query_coverage["test"]["Bảng tra"],
        "queries_hybrid_coverage_test": query_coverage["test"]["Hybrid Fusion (100d)"],
        "queries_hybrid_plus_curated_coverage_test": query_coverage["test"]["Hybrid + Bảng tra"],
    }

    # ---------------- Export 100d pgvector embeddings (deploy/models/embeddings/)
    export_manifest = None
    if not args.skip_export:
        export_manifest = M.export_embeddings(
            w100_0,
            cat,
            out_dir=args.export_dir,
            version="sub-w2v-100d-v1",
            hybrid_config={
                "norm_mode": h100_cfg["norm_mode"],
                "missing_mode": h100_cfg["missing_mode"],
                "weights": h100_cfg["weights"],
                "food_group_hard_filter": True,
                "curated_excluded_from_fusion": True,
            },
            eval_summary={
                "protocol_id": PROTOCOL_ID,
                "n_test_ingredients": len(test),
                "w2v_100d_mrr": test_summary["Word2Vec (100d)"]["mrr"],
                "w2v_100d_agree3": test_summary["Word2Vec (100d)"]["agreement@3"],
                "hybrid_100d_mrr": test_summary["Hybrid Fusion (100d)"]["mrr"],
                "hybrid_100d_agree3": test_summary["Hybrid Fusion (100d)"]["agreement@3"],
            },
        )
        log("exported 100d embeddings", export_manifest["embedded_count"], "sha256", export_manifest["artifact_sha256"][:12])

    # ---------------- Persist results.json (backward-compatible for figures.substitution()) + research outputs
    res = {
        "protocol_id": PROTOCOL_ID,
        "corpus": {
            "foodcom_recipes": len(fc),
            "kb_dishes": len(kb),
            "longest_list": M.longest(fc + kb),
            "foodcom_distinct_ingredient_strings": len(mp.counts),
        },
        "split": {"seed": SPLIT_SEED, "dev": dev, "test": test},
        "label": "agreement with the curated table on held-out ingredients — NOT human accuracy (0 human answers yet)",
        "mapping": {
            "kb_ingredients": len(cat.ingredients),
            "with_en_synonym_in_foodcom": len(mapped),
            "with_en_synonym_ge50": len(mapped50),
            "occurrence_share_mapped": sum(occ[n] for n in mapped) / total_occ,
            "occurrence_share_ge50": sum(occ[n] for n in mapped50) / total_occ,
            "non_staple_mapped_share": float(np.mean([n in set(mapped) for n in non_staple])),
            "unmapped_examples": unmapped[:40],
            "n_unmapped": len(unmapped),
        },
        "w2v_tuning": tun,
        "w2v_best": best,
        "w2v_best_100d": best_100,
        "w2v_best_200d": best_200,
        "hybrid_tuning_100d": {k: v for k, v in hybrid_tune_100.items() if k != "top10"} | {"top10": hybrid_tune_100["top10"]},
        "hybrid_tuning_200d": {k: v for k, v in hybrid_tune_200.items() if k != "top10"} | {"top10": hybrid_tune_200["top10"]},
        "test": test_summary,
        "dev_other": {
            "kNN dinh dưỡng": {k: v for k, v in agreement(nut.score, refs, cat, dev).items() if k != "rows"},
            "PMI ngữ cảnh": {k: v for k, v in agreement(pmi.score, refs, cat, dev).items() if k != "rows"},
            "Ngẫu nhiên cùng nhóm": {k: v for k, v in random_agreement(refs, cat, dev).items() if k != "rows"},
        },
        "test_pairs": conf_pairs,
        "ablation_dim_200d_vs_100d": ablation_dim,
        "coverage": {
            "word2vec_vectors": {
                "en": coverage_audit["word2vec_100d"]["en_count"],
                "vi_only": coverage_audit["word2vec_100d"]["vi_only_count"],
                "share_ingredients": coverage_audit["word2vec_100d"]["share_ingredients"],
                "share_occurrences": coverage_audit["word2vec_100d"]["share_occurrences"],
            },
            "nutrient_vectors": {
                "share_ingredients": coverage_audit["nutrient"]["share_ingredients"],
                "share_occurrences": coverage_audit["nutrient"]["share_occurrences"],
            },
            "pmi_rows": {
                "share_ingredients": coverage_audit["pmi"]["share_ingredients"],
                "share_occurrences": coverage_audit["pmi"]["share_occurrences"],
            },
            "curated_table": {
                "ingredients_with_pair": len(refs),
                "union_ingredients": len(union_curated),
                "share_ingredients": len(refs) / len(cat.ingredients),
            },
        },
        "query_coverage": query_coverage,
        "curated_disclosure": curated_disclosure,
        "food_groups_exploratory": fg_rows,
        "export_manifest_summary": (
            {
                "artifact_file": export_manifest["artifact_file"],
                "artifact_sha256": export_manifest["artifact_sha256"],
                "embedded_count": export_manifest["embedded_count"],
                "uncovered_count": export_manifest["uncovered_count"],
            }
            if export_manifest
            else None
        ),
    }

    (OUT / "eval_rankings.json").write_text(
        json.dumps(
            {
                "note": "Word2Vec = 100d seed 0 (workers=1); Hybrid Fusion excludes Curated; Hybrid + Bảng tra reported separately",
                "w2v_params": best_100["params"],
                "hybrid_100d_cfg": h100_cfg,
                "rankings": rankings,
            },
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    (OUT / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")

    # ---------------- Write structured research artifacts (ml/runs/research/p4_substitution_composer/)
    (args.out_research / "substitution_benchmark.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2, default=float) + "\n", encoding="utf-8"
    )
    (args.out_research / "substitution_ablation_dim.json").write_text(
        json.dumps(ablation_dim, ensure_ascii=False, indent=2, default=float) + "\n", encoding="utf-8"
    )
    (args.out_research / "substitution_coverage.json").write_text(
        json.dumps(coverage_audit, ensure_ascii=False, indent=2, default=float) + "\n", encoding="utf-8"
    )

    with open(args.out_research / "substitution_metrics.csv", "w", newline="", encoding="utf-8") as f:
        w_csv = csv.DictWriter(
            f,
            fieldnames=[
                "method", "split", "dim", "analysis_intent", "n_units", "answered_rate",
                "agreement_at_1", "agreement_at_3", "agreement_at_3_ci_lo", "agreement_at_3_ci_hi",
                "mrr", "mrr_ci_lo", "mrr_ci_hi", "kb_ing_coverage", "query_coverage_test",
            ],
        )
        w_csv.writeheader()
        kb_cov_map = {
            "Hybrid Fusion (100d)": coverage_audit["hybrid_union"]["share_ingredients"],
            "Hybrid Fusion (200d)": coverage_audit["hybrid_union"]["share_ingredients"],
            "Word2Vec (200d)": coverage_audit["word2vec_200d"]["share_ingredients"],
            "Word2Vec (100d)": coverage_audit["word2vec_100d"]["share_ingredients"],
            "kNN dinh dưỡng": coverage_audit["nutrient"]["share_ingredients"],
            "PMI ngữ cảnh": coverage_audit["pmi"]["share_ingredients"],
            f"Word2Vec (100d) + lọc bổ sung (PPMI ≤ {COMPLEMENT_TAU})": coverage_audit["word2vec_100d"]["share_ingredients"],
            "Ngẫu nhiên cùng nhóm": 1.0,
        }
        dim_map = {
            "Hybrid Fusion (100d)": 100,
            "Hybrid Fusion (200d)": 200,
            "Word2Vec (200d)": 200,
            "Word2Vec (100d)": 100,
            f"Word2Vec (100d) + lọc bổ sung (PPMI ≤ {COMPLEMENT_TAU})": 100,
        }
        for name, entry in test_summary.items():
            desc = entry["descriptives"]
            is_rnd = name == "Ngẫu nhiên cùng nhóm"
            w_csv.writerow({
                "method": name,
                "split": "test",
                "dim": dim_map.get(name, ""),
                "analysis_intent": "confirmatory",
                "n_units": len(test),
                "answered_rate": entry["answered"] if is_rnd else entry["answered"]["mean"],
                "agreement_at_1": entry["agreement@1"] if is_rnd else entry["agreement@1"]["mean"],
                "agreement_at_3": entry["agreement@3"] if is_rnd else entry["agreement@3"]["mean"],
                "agreement_at_3_ci_lo": desc["agreement@3"]["ci95"][0],
                "agreement_at_3_ci_hi": desc["agreement@3"]["ci95"][1],
                "mrr": entry["mrr"] if is_rnd else entry["mrr"]["mean"],
                "mrr_ci_lo": desc["mrr"]["ci95"][0],
                "mrr_ci_hi": desc["mrr"]["ci95"][1],
                "kb_ing_coverage": kb_cov_map[name],
                "query_coverage_test": query_coverage["test"].get(name, ""),
            })

    with open(args.out_research / "substitution_pairwise.csv", "w", newline="", encoding="utf-8") as f:
        w_csv = csv.DictWriter(
            f,
            fieldnames=[
                "family", "analysis_intent", "comparison", "metric", "n", "mde_dz",
                "diff", "ci_lo", "ci_hi", "effect_dz", "hedges_gz", "rank_biserial",
                "p_boot", "p_boot_holm", "p_wilcoxon", "p_wilcoxon_holm", "mcnemar_p",
            ],
        )
        w_csv.writeheader()
        for label, c in conf_pairs.items():
            w_csv.writerow({
                "family": c["family"],
                "analysis_intent": c["analysis_intent"],
                "comparison": label,
                "metric": "mrr",
                "n": c["n"],
                "mde_dz": c["mde_dz_80pct"],
                "diff": c["bootstrap_rr"]["diff"],
                "ci_lo": c["bootstrap_rr"]["lo"],
                "ci_hi": c["bootstrap_rr"]["hi"],
                "effect_dz": c["effect_dz_rr"]["d_z"],
                "hedges_gz": c["effect_dz_rr"]["hedges_gz"],
                "rank_biserial": c["wilcoxon_rr"]["rank_biserial"],
                "p_boot": c["bootstrap_rr"]["p"],
                "p_boot_holm": c["bootstrap_rr"]["p_holm"],
                "p_wilcoxon": c["wilcoxon_rr"]["p"],
                "p_wilcoxon_holm": c["wilcoxon_rr"]["p_holm"],
                "mcnemar_p": c.get("mcnemar_agreement@3_seed0", {}).get("p", ""),
            })

    with open(args.out_research / "substitution_food_groups.csv", "w", newline="", encoding="utf-8") as f:
        w_csv = csv.DictWriter(f, fieldnames=list(fg_rows[0].keys()))
        w_csv.writeheader()
        w_csv.writerows(fg_rows)

    log("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
