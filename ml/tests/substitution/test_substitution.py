"""Substitution scorers, VN↔EN mapping and the gold-set scorer (run on synthetic answers in a temp dir only)."""

import json
import math

import numpy as np
import pytest
import yaml

from tastoria_ml.recsys import kb_catalog
from tastoria_ml.substitution import gold, methods as M, run as R


@pytest.fixture(scope="module")
def cat():
    return kb_catalog.load()


def test_mapping_uses_synonyms_present_in_the_corpus(cat):
    fc = [["white_rice", "salt"], ["rice", "water"], ["pork_belly", "garlic"]] * 3
    mp = M.build_mapping(cat, fc)
    assert set(mp.en_tokens["gạo tẻ"]) <= {"rice", "white_rice", "long_grain_rice"}
    assert mp.canonical["gạo tẻ"] in {"rice", "white_rice"}
    kb = M.kb_sentences(cat, mp)
    assert len(kb) == len(cat.recipes)
    assert any(t.startswith("vi:") for s in kb for t in s)


def test_word2vec_config_is_skipgram_full_window(cat):
    fc = [["a_tok", "b_tok", "c_tok"], ["a_tok", "b_tok"]] * 20 + [["x"] * 1 + ["y"] * 1]
    mp = M.build_mapping(cat, fc)
    kb = M.kb_sentences(cat, mp)
    w = M.W2V(dim=8, min_count=1, epochs=1, seed=0, workers=1).fit(fc, kb, mp, cat)
    assert w.model.sg == 1
    assert w.model.window == M.longest(fc + kb)
    assert w.model.shrink_windows is False


def test_candidates_are_same_group_and_exclude_self(cat):
    c = M.candidates(cat, "thịt ba chỉ")
    g = cat.ingredients["thịt ba chỉ"].food_group
    assert "thịt ba chỉ" not in c and c
    assert all(cat.ingredients[x].food_group == g for x in c)


def test_rank_abstains_on_unscored_and_breaks_ties_by_name():
    assert M.rank({}, ["a", "b"]) == []
    assert M.rank({"b": 1.0, "a": 1.0, "c": 0.5}, ["a", "b", "c"]) == ["a", "b", "c"]


def test_random_expectations_match_simulation():
    rng = np.random.default_rng(0)
    n, m, k = 12, 2, 3
    sims = []
    rr = []
    for _ in range(20000):
        order = rng.permutation(n)
        sims.append(bool(set(order[:k]) & {0, 1}))
        first = min(np.flatnonzero(np.isin(order, [0, 1]))) + 1
        rr.append(1 / first)
    assert M.random_hit_prob(n, m, k) == pytest.approx(np.mean(sims), abs=0.01)
    assert M.random_mrr(n, m) == pytest.approx(np.mean(rr), abs=0.01)
    assert M.random_hit_prob(5, 1, 1) == pytest.approx(0.2)


def test_curated_scorer_respects_context(cat):
    pairs = R.load_pairs()
    cur = M.Curated(pairs)
    cands = M.candidates(cat, "thịt ba chỉ")
    s_kho = cur.score("thịt ba chỉ", cands, "man", "kho")
    assert "thịt nạc vai" in s_kho
    assert s_kho["thịt nạc vai"] == pytest.approx(0.85, abs=0.01)


def test_split_by_ingredient_is_disjoint_and_30_70():
    pairs = R.load_pairs()
    sp = R.split_ingredients(pairs)
    dev = [i for i, s in sp.items() if s == "dev"]
    assert len(dev) == round(0.3 * len(sp))
    assert sp == R.split_ingredients(pairs)


def test_nutrient_vectors_cover_most_ingredients(cat):
    nut = M.Nutrient().fit(cat)
    assert len(nut.vec) / len(cat.ingredients) > 0.8
    s = nut.score("thịt ba chỉ", M.candidates(cat, "thịt ba chỉ"))
    assert all(-1.0001 <= v <= 1.0001 for v in s.values())


def test_gold_scorer_on_synthetic_answers(tmp_path):
    """The scorer itself, on made-up answers in a temp dir (never written to data/)."""
    queries = [{"id": "q001", "split": "dev"}, {"id": "q002", "split": "dev"}, {"id": "q003", "split": "dev"}]
    gold_ans = {"q001": {"acceptable": ["b", "c"], "none": False}, "q002": {"acceptable": ["x"], "none": False},
                "q003": {"acceptable": [], "none": True}}
    rankings = {
        "q001": {"m1": ["c", "a"], "m2": ["a", "z", "y", "b"]},
        "q002": {"m1": ["y", "x"], "m2": []},
        "q003": {"m1": ["a"], "m2": []},
    }
    res = gold.evaluate(rankings, gold_ans, queries, "dev")
    assert res["methods"]["m1"]["hit@1"] == pytest.approx(0.5)
    assert res["methods"]["m1"]["mrr"] == pytest.approx((1 + 0.5) / 2)
    assert res["methods"]["m2"]["hit@3"] == 0.0 and res["methods"]["m2"]["mrr"] == pytest.approx(0.25 / 2)
    assert res["methods"]["m2"]["coverage"] == pytest.approx(1 / 3)
    assert res["methods"]["m2"]["correct_refusals"] == 1 and res["methods"]["m1"]["correct_refusals"] == 0
    a = {"q1": {"acceptable": ["a", "b"], "none": False}, "q2": {"acceptable": [], "none": True}}
    b = {"q1": {"acceptable": ["a"], "none": False}, "q2": {"acceptable": [], "none": True}}
    ag = gold.annotator_agreement(a, b)
    assert ag["mean_jaccard"] == pytest.approx(0.5) and ag["none_agreement"] == 1.0 and ag["top1_match"] == 1.0
    # CLI end to end on a temp eval dir
    (tmp_path / "queries.yaml").write_text(yaml.safe_dump({"queries": queries}, allow_unicode=True), encoding="utf-8")
    for name, ans in (("answers_adjudicated.yaml", gold_ans), ("answers_A.yaml", a), ("answers_B.yaml", b)):
        (tmp_path / name).write_text(yaml.safe_dump({"answers": [{"id": k, **v} for k, v in ans.items()]}, allow_unicode=True), encoding="utf-8")
    rk = tmp_path / "rk" / "eval_rankings.json"
    rk.parent.mkdir()
    rk.write_text(json.dumps({"rankings": rankings}), encoding="utf-8")
    assert gold.main(["--split", "dev", "--eval-dir", str(tmp_path), "--rankings", str(rk)]) == 0
    out = json.loads((rk.parent / "gold_dev.json").read_text(encoding="utf-8"))
    assert math.isclose(out["methods"]["m1"]["hit@1"], 0.5)


def test_gold_cli_reports_missing_answers(tmp_path):
    assert gold.main(["--eval-dir", str(tmp_path)]) == 2

