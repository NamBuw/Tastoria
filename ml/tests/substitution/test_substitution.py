"""Substitution scorers, VN↔EN mapping, Hybrid fusion, 100d export, and gold-set scorer tests."""

import hashlib
import json
import math
from types import SimpleNamespace

import numpy as np
import pytest
import yaml

from tastoria_ml.recsys import figures, kb_catalog
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


def test_catalog_pairs_and_queries_counts(cat):
    assert len(cat.ingredients) == 233
    assert len(cat.recipes) == 180
    pairs = R.load_pairs()
    assert len(pairs) == 197
    assert len({p.ingredient for p in pairs}) == 107
    queries = gold.load_queries()
    assert len(queries) == 90
    assert sum(1 for q in queries if q["split"] == "dev") == 27
    assert sum(1 for q in queries if q["split"] == "test") == 63


def test_hybrid_scorer_fusion_missing_modes_and_curated(cat):
    cands = M.candidates(cat, "thịt ba chỉ")
    a, b, c = cands[0], cands[1], cands[2]
    fake_w2v = SimpleNamespace(score=lambda m, cs: {a: 0.8, b: 0.2})
    fake_nut = SimpleNamespace(score=lambda m, cs: {a: 0.4, b: 0.9, c: 0.7})
    fake_pmi = SimpleNamespace(score=lambda m, cs: {a: 0.5})

    hyb_renorm = M.HybridScorer(
        w2v=fake_w2v, nut=fake_nut, pmi=fake_pmi,
        weights={"w2v": 0.5, "nut": 0.3, "pmi": 0.2},
        norm_mode="affine", missing_mode="renorm",
    )
    sc_renorm = hyb_renorm.score("thịt ba chỉ", cands)
    assert set(sc_renorm) == {a, b, c}
    # c has only nut=0.7 -> affine (0.7+1)/2 = 0.85; renorm keeps 0.85 while zero-mode scales by 0.3
    assert sc_renorm[c] == pytest.approx(0.85)

    hyb_zero = M.HybridScorer(
        w2v=fake_w2v, nut=fake_nut, pmi=fake_pmi,
        weights={"w2v": 0.5, "nut": 0.3, "pmi": 0.2},
        norm_mode="affine", missing_mode="zero",
    )
    sc_zero = hyb_zero.score("thịt ba chỉ", cands)
    assert sc_zero[c] == pytest.approx(0.3 * 0.85)

    pairs = R.load_pairs()
    cur = M.Curated(pairs)
    hc = M.HybridWithCurated(cur, hyb_renorm)
    ranked = M.rank(hc.score("thịt ba chỉ", cands, "man", "kho"), cands)
    assert ranked[0] == "thịt nạc vai"


def test_slugify_vi_and_export_embeddings_contract(cat, tmp_path):
    assert M.slugify_vi("Đậu phụ non") == "dau-phu-non"
    assert M.slugify_vi("Thịt ba chỉ") == "thit-ba-chi"

    fc = [["pork_belly", "pork_shoulder", "garlic", "fish_sauce"]] * 5
    mp = M.build_mapping(cat, fc)
    kb = M.kb_sentences(cat, mp)
    w100 = M.W2V(dim=100, min_count=1, epochs=1, seed=0, workers=1).fit(fc, kb, mp, cat)
    man = M.export_embeddings(
        w100,
        cat,
        out_dir=tmp_path,
        hybrid_config={"weights": {"w2v": 0.7, "nut": 0.2, "pmi": 0.1}},
        eval_summary={"n_test_ingredients": 75},
    )
    npz_path = tmp_path / "ingredient_embeddings.npz"
    man_path = tmp_path / "manifest.json"
    assert npz_path.exists() and man_path.exists()
    assert man["dim"] == 100 and man["l2_normalized"] is True and man["key_field"] == "name_vi"
    assert man["catalog_total"] == 233
    assert man["embedded_count"] + len(man["uncovered_ingredients"]) == 233
    assert man["artifact_sha256"] == hashlib.sha256(npz_path.read_bytes()).hexdigest()

    d = np.load(npz_path)
    vecs = d["vectors"]
    assert vecs.dtype == np.float32 and vecs.shape == (man["embedded_count"], 100)
    assert np.isfinite(vecs).all()
    assert np.allclose(np.linalg.norm(vecs, axis=1), 1.0, atol=1e-5)
    assert len(set(d["names_vi"].tolist())) == man["embedded_count"]

    w50 = M.W2V(dim=50, min_count=1, epochs=1, seed=0, workers=1).fit(fc, kb, mp, cat)
    with pytest.raises(ValueError, match="dim=100"):
        M.export_embeddings(w50, cat, out_dir=tmp_path)


def test_tost_paired_and_figures_substitution_smoke(tmp_path, monkeypatch):
    a = np.array([0.50, 0.60, 0.55, 0.70, 0.45, 0.65, 0.52, 0.58])
    b = a + 0.005
    tost = R._tost_paired(a, b, margins=(0.03, 0.05), seed=0)
    assert tost["tost"]["margin_0.03"]["equivalent_tost_05"] is True

    sub_dir = tmp_path / "substitution"
    sub_dir.mkdir(parents=True)
    fig_dir = tmp_path / "fig"
    fake_res = {
        "test": {
            "Hybrid Fusion (100d)": {"agreement@3": {"mean": 0.62, "sd": 0.01}},
            "Hybrid Fusion (200d)": {"agreement@3": {"mean": 0.61, "sd": 0.01}},
            "Word2Vec (200d)": {"agreement@3": {"mean": 0.56, "sd": 0.01}},
            "Word2Vec (100d)": {"agreement@3": {"mean": 0.55, "sd": 0.01}},
            "kNN dinh dưỡng": {"agreement@3": {"mean": 0.44, "sd": 0.0}},
            "PMI ngữ cảnh": {"agreement@3": {"mean": 0.40, "sd": 0.0}},
            "Word2Vec (100d) + lọc bổ sung (PPMI ≤ 2.0)": {"agreement@3": {"mean": 0.35, "sd": 0.01}},
            "Ngẫu nhiên cùng nhóm": {"agreement@3": 0.32},
        }
    }
    (sub_dir / "results.json").write_text(json.dumps(fake_res), encoding="utf-8")
    monkeypatch.setattr(figures, "PROC", tmp_path)
    monkeypatch.setattr(figures, "FIG", fig_dir)
    figures.substitution()
    assert (fig_dir / "substitution_agreement.png").exists()

