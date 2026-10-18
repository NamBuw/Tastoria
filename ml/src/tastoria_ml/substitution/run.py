"""Substitution experiment (design v2 §6.3) with what is legitimate before the human gold set exists:

(a) AGREEMENT WITH THE CURATED TABLE (not accuracy): the 107 ingredients of substitution_pairs.yaml are split
    30 % dev / 70 % test by ingredient (seed below). For a held-out ingredient i the reference set is every
    substitute the table lists for i (any context); each method ranks the KB ingredients of i's food group.
    agreement@k = top-k contains a reference substitute; RR = 1 / rank of the first one. A method that has no
    vector for i abstains (counted as a miss, and in `answered`). Random = exact expectation within the group.
    Word2Vec settings are chosen on dev (MRR); test is scored once per setting, 5 seeds for Word2Vec.
(b) COVERAGE: share of KB ingredients and of ingredient occurrences in KB dishes with a vector, and share of the
    90 evaluation queries (substitution_eval/queries.yaml) for which each method proposes ≥ 1 candidate.
Rankings for the 90 queries are written for `substitution.gold`, which scores them when the answers exist.

Run: uv run --package tastoria-ml python -m tastoria_ml.substitution.run
"""

from __future__ import annotations

import itertools
import json
import os
import time
from collections import Counter

import numpy as np
import yaml

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

from tastoria_ml.kb.substitutes import SubstitutionPairsFile  # noqa: E402
from tastoria_ml.recsys import kb_catalog, stats  # noqa: E402
from tastoria_ml.substitution import gold as gold_mod  # noqa: E402
from tastoria_ml.substitution import methods as M  # noqa: E402

REPO = kb_catalog.REPO
OUT = REPO / "data" / "processed" / "substitution"
SPLIT_SEED = 20261018
SEEDS = (0, 1, 2, 3, 4)
W2V_GRID = [
    {"dim": d, "min_count": mc, "kb_repeat": kr, "epochs": 10, "negative": 10}
    for d in (50, 100, 200)
    for mc in (5, 20)
    for kr in (1, 10)
]
COMPLEMENT_TAU = 2.0  # PPMI above this = complement pair, dropped by the "không phải cặp bổ sung" filter


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
        rows.append({"ingredient": ing, "answered": bool(ranked), **r, "n_cands": len(cands), "n_ref": len(refs[ing] & set(cands)), "top3": ranked[:3]})
    return summarise_rows(rows)


def summarise_rows(rows):
    a = np.array([r["answered"] for r in rows], bool)
    out = {
        "n": len(rows),
        "answered": float(a.mean()),
        "agreement@1": float(np.mean([r["hit1"] for r in rows])),
        "agreement@3": float(np.mean([r["hit3"] for r in rows])),
        "mrr": float(np.mean([r["rr"] for r in rows])),
        "agreement@3_answered": float(np.mean([r["hit3"] for r in rows if r["answered"]])) if a.any() else float("nan"),
        "rows": rows,
    }
    return out


def random_agreement(refs, cat, names) -> dict:
    h1, h3, mrr = [], [], []
    for ing in names:
        cands = M.candidates(cat, ing)
        m = len(refs[ing] & set(cands))
        h1.append(M.random_hit_prob(len(cands), m, 1))
        h3.append(M.random_hit_prob(len(cands), m, 3))
        mrr.append(M.random_mrr(len(cands), m))
    return {"n": len(names), "answered": 1.0, "agreement@1": float(np.mean(h1)), "agreement@3": float(np.mean(h3)), "mrr": float(np.mean(mrr)),
            "note": "exact expectation of a uniform random order within the food group"}


def main(argv: list[str] | None = None) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
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
    res: dict = {
        "corpus": {
            "foodcom_recipes": len(fc),
            "kb_dishes": len(kb),
            "longest_list": M.longest(fc + kb),
            "foodcom_distinct_ingredient_strings": len(mp.counts),
        },
        "split": {"seed": SPLIT_SEED, "dev": dev, "test": test},
        "label": "agreement with the curated table on held-out ingredients — NOT accuracy (no human gold yet)",
    }
    # ---------------- mapping coverage
    occ = Counter(ln.name for r in cat.recipes for ln in r.ingredients)
    non_staple = [n for n, i in cat.ingredients.items() if not i.is_staple]
    mapped = [n for n in cat.ingredients if mp.en_tokens[n]]
    mapped50 = [n for n in cat.ingredients if any(mp.counts[t] >= 50 for t in mp.en_tokens[n])]
    res["mapping"] = {
        "kb_ingredients": len(cat.ingredients),
        "with_en_synonym_in_foodcom": len(mapped),
        "with_en_synonym_ge50": len(mapped50),
        "occurrence_share_mapped": sum(occ[n] for n in mapped) / sum(occ.values()),
        "occurrence_share_ge50": sum(occ[n] for n in mapped50) / sum(occ.values()),
        "non_staple_mapped_share": float(np.mean([n in set(mapped) for n in non_staple])),
        "unmapped_examples": sorted(set(cat.ingredients) - set(mapped))[:40],
        "n_unmapped": len(set(cat.ingredients) - set(mapped)),
    }
    log("mapping", res["mapping"]["with_en_synonym_in_foodcom"], "/", len(cat.ingredients))
    # ---------------- word2vec tuning on dev
    tun = []
    for g in W2V_GRID:
        t0 = time.time()
        w = M.W2V(**g, seed=0).fit(fc, kb, mp, cat)
        ag = agreement(w.score, refs, cat, dev)
        tun.append({"params": g, "window": w.window, "dev_mrr": ag["mrr"], "dev_agreement@3": ag["agreement@3"],
                    "dev_answered": ag["answered"], "vocab": len(w.model.wv), "seconds": round(time.time() - t0, 1)})
        log("w2v", g, round(ag["mrr"], 3))
    best = max(tun, key=lambda r: (r["dev_mrr"], r["dev_agreement@3"]))
    res["w2v_tuning"] = tun
    res["w2v_best"] = best
    # ---------------- test, seeds
    nut = M.Nutrient().fit(cat)
    pmi = M.PMI().fit(fc, kb, mp, cat)
    w2v_runs, w2v_filtered_runs, models = [], [], []
    for sd in SEEDS:
        w = M.W2V(**best["params"], seed=sd).fit(fc, kb, mp, cat)
        models.append(w)
        w2v_runs.append(agreement(w.score, refs, cat, test))

        def filtered(ing, cands, _w=w):
            s = _w.score(ing, cands)
            return {c: v for c, v in s.items() if pmi.direct(ing, c) <= COMPLEMENT_TAU}

        w2v_filtered_runs.append(agreement(filtered, refs, cat, test))
        log("w2v test seed", sd, round(w2v_runs[-1]["mrr"], 3))
    methods = {
        "Word2Vec": w2v_runs,
        f"Word2Vec + lọc bổ sung (PPMI ≤ {COMPLEMENT_TAU})": w2v_filtered_runs,
        "kNN dinh dưỡng": [agreement(nut.score, refs, cat, test)],
        "PMI ngữ cảnh": [agreement(pmi.score, refs, cat, test)],
    }
    res["test"] = {}
    for name, runs in methods.items():
        res["test"][name] = {
            k: {"mean": float(np.mean([r[k] for r in runs])), "sd": float(np.std([r[k] for r in runs], ddof=1)) if len(runs) > 1 else 0.0}
            for k in ("agreement@1", "agreement@3", "mrr", "answered")
        } | {"seeds": len(runs), "rows_seed0": runs[0]["rows"]}
    res["test"]["Ngẫu nhiên cùng nhóm"] = random_agreement(refs, cat, test)
    res["dev_other"] = {
        "kNN dinh dưỡng": {k: v for k, v in agreement(nut.score, refs, cat, dev).items() if k != "rows"},
        "PMI ngữ cảnh": {k: v for k, v in agreement(pmi.score, refs, cat, dev).items() if k != "rows"},
        "Ngẫu nhiên cùng nhóm": random_agreement(refs, cat, dev),
    }
    # paired tests on test ingredients (Word2Vec: hit/RR averaged over seeds per ingredient; McNemar on seed 0)
    def arr(runs, key):
        return np.mean([[r[key] for r in run["rows"]] for run in runs], axis=0)

    comps, labels = {}, []
    names = ["Word2Vec", "kNN dinh dưỡng", "PMI ngữ cảnh", f"Word2Vec + lọc bổ sung (PPMI ≤ {COMPLEMENT_TAU})"]
    for a, b in itertools.combinations(names, 2):
        ra, rb = methods[a], methods[b]
        comps[f"{a} vs {b}"] = {
            "mcnemar_agreement@3_seed0": stats.mcnemar(np.array([r["hit3"] for r in ra[0]["rows"]], bool), np.array([r["hit3"] for r in rb[0]["rows"]], bool)),
            "bootstrap_rr": stats.paired_bootstrap(arr(ra, "rr"), arr(rb, "rr"), n_boot=5000, seed=9),
        }
        labels.append(f"{a} vs {b}")
    adj = stats.holm([comps[x]["bootstrap_rr"]["p"] for x in labels])
    for x, p in zip(labels, adj, strict=True):
        comps[x]["bootstrap_rr"]["p_holm"] = float(p)
    res["test_pairs"] = comps
    # ---------------- coverage of KB ingredients
    w0 = models[0]
    res["coverage"] = {
        "word2vec_vectors": {"en": sum(1 for s in w0.source.values() if s == "en"), "vi_only": sum(1 for s in w0.source.values() if s == "vi"),
                              "share_ingredients": len(w0.vec) / len(cat.ingredients),
                              "share_occurrences": sum(occ[n] for n in w0.vec) / sum(occ.values())},
        "nutrient_vectors": {"share_ingredients": len(nut.vec) / len(cat.ingredients), "share_occurrences": sum(occ[n] for n in nut.vec) / sum(occ.values())},
        "pmi_rows": {"share_ingredients": len(pmi.idx) / len(cat.ingredients), "share_occurrences": sum(occ[n] for n in pmi.idx) / sum(occ.values())},
        "curated_table": {"ingredients_with_pair": len(refs), "share_ingredients": len(refs) / len(cat.ingredients)},
    }
    # ---------------- rankings for the 90 evaluation queries (gold scorer input) + query coverage
    queries = gold_mod.load_queries()
    recipes = {r.slug: r for r in cat.recipes}
    cur = M.Curated(pairs)
    rankings = {}
    for q in queries:
        r = recipes[q["slug"]]
        cands = M.candidates(cat, q["missing"])
        rankings[q["id"]] = {
            "Bảng tra": M.rank(cur.score(q["missing"], cands, r.slot, r.method), cands),
            "Word2Vec": M.rank(w0.score(q["missing"], cands), cands),
            "kNN dinh dưỡng": M.rank(nut.score(q["missing"], cands), cands),
            "PMI ngữ cảnh": M.rank(pmi.score(q["missing"], cands), cands),
        }
    res["query_coverage"] = {
        split_name: {m: float(np.mean([bool(rankings[q["id"]][m]) for q in queries if split_name == "all" or q["split"] == split_name]))
                     for m in ("Bảng tra", "Word2Vec", "kNN dinh dưỡng", "PMI ngữ cảnh")}
        for split_name in ("all", "dev", "test")
    }
    res["query_coverage"]["n"] = len(queries)
    (OUT / "eval_rankings.json").write_text(
        json.dumps({"note": "Word2Vec = seed 0 of the chosen setting; candidates = same food group", "w2v_params": best["params"], "rankings": rankings}, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    (OUT / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")
    log("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
