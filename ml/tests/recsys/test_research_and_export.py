"""Tests for M1.3a RecSys confirmatory models, ExportedNumpyRanker, KB alignment, and P3 research artifacts."""

from __future__ import annotations

import csv
import json
import uuid
from types import SimpleNamespace

import numpy as np
import pytest
import scipy.sparse as sp

from tastoria_ml import stats
from tastoria_ml.recsys import export_ranker, kb_catalog, metrics, models, research, survey


def _planted_with_features(seed: int = 0, n_users: int = 160, n_items: int = 60, dim: int = 4):
    rng = np.random.default_rng(seed)
    item_feats = rng.random((n_items, 20)) < 0.35
    # Guarantee every item has at least 1 feature
    item_feats[:, 0] = True
    F_only = sp.csr_matrix(item_feats.astype(np.float32))
    deg = np.asarray(F_only.sum(axis=1)).ravel()
    F_only = (sp.diags(1.0 / np.maximum(deg, 1.0)).astype(np.float32) @ F_only).tocsr()
    f_names = [f"tag:t{j}" if j < 10 else f"ing:i{j}" for j in range(20)]

    W = rng.standard_normal((20, dim))
    qi = (F_only.toarray() @ W) + 0.3 * rng.standard_normal((n_items, dim))
    pu = rng.standard_normal((n_users, dim))
    s = pu @ qi.T
    top = np.argsort(-s, axis=1)[:, :12]
    rows = np.repeat(np.arange(n_users), 12)
    full = sp.csr_matrix((np.ones(rows.size, np.float32), (rows, top.ravel())), shape=(n_users, n_items))
    mask = rng.random(rows.size) < 0.75
    train = sp.csr_matrix((np.ones(mask.sum(), np.float32), (rows[mask], top.ravel()[mask])), shape=full.shape)
    targets = {}
    for u in range(n_users):
        t = np.setdiff1d(full[u].indices, train[u].indices)
        if len(t) and train[u].nnz:
            targets[u] = t
    return train, targets, F_only, f_names


def test_models_make_random_and_confirmatory_beat_random():
    rnd0 = models.make("Random", seed=0)
    assert isinstance(rnd0, models.Random)

    train, targets, F_only, f_names = _planted_with_features(seed=42)
    rnd = models.make("Random", seed=0).fit(train)
    base = metrics.summarize(metrics.topk_metrics(rnd.scores, targets, train, k=5), k=5)["ndcg@5"]

    for cls, kw in (
        (models.ContentCosine, {}),
        (models.HybridCFContent, {"weights": (0.5, 0.3, 0.2), "als_params": {"factors": 8, "reg": 0.1, "alpha": 5.0, "iterations": 10}, "seed": 0}),
        (models.TwoStageLGBMReranker, {"top_m": 25, "als_params": {"factors": 8, "reg": 0.1, "alpha": 5.0, "iterations": 10}, "lgb_params": {"num_leaves": 7, "n_estimators": 40, "learning_rate": 0.1, "min_child_samples": 5}, "seed": 0}),
        (models.ColdHybrid, {"alpha": 0.5, "lfm_params": {"dim": 8, "lr": 0.05, "item_alpha": 0.0, "epochs": 8}, "seed": 0}),
    ):
        m = cls(**kw).fit(train, item_features=F_only)
        score = metrics.summarize(metrics.topk_metrics(m.scores, targets, train, k=5), k=5)["ndcg@5"]
        assert score > base + 0.05, f"{cls.__name__} failed to beat Random: {score:.4f} vs {base:.4f}"

    # Cold feature ablation matrices handle all variants cleanly
    for var in ("id_only", "tags_only", "ing_only", "tags_ing"):
        Fv = models.cold_feature_matrix(train.shape[1], F_only, f_names, var)
        assert Fv.shape[0] == train.shape[1]
        assert np.isfinite(Fv.data).all()


def test_survey_random_and_hybrid_and_user_level_aggregation(monkeypatch):
    cat = kb_catalog.load()
    sd = survey.simulate(cat, seed=11, n_users=45, taste_scale=1.5, noise_sd=0.4)
    monkeypatch.setattr(survey.ShrunkMean, "grid", survey.ShrunkMean.grid[:1])
    monkeypatch.setattr(survey.HybridFactorRanker, "grid", survey.HybridFactorRanker.grid[:2])

    for scenario in ("warm", "user_cold"):
        runs = [
            survey.run_scenario(
                sd,
                scenario,
                seed=s,
                k_outer=3,
                models=[survey.RandomRanker, survey.ShrunkMean, survey.HybridFactorRanker],
            )
            for s in (0, 1)
        ]
        summ = survey.summarise(runs)
        assert summ["n_users"] == sd.n_users  # strictly user-level (NEVER n_users * n_seeds)
        assert "d_mde_80" in summ and np.isfinite(summ["d_mde_80"])
        assert "comparisons_vs_random" in summ

        rnd_auc = summ["models"]["Random"]["auc"]["mean"]
        hyb_ndcg = summ["models"]["HybridFactorRanker"]["ndcg@5"]["mean"]
        pop_ndcg = summ["models"]["ShrunkMean"]["ndcg@5"]["mean"]
        rnd_ndcg = summ["models"]["Random"]["ndcg@5"]["mean"]
        assert 0.35 <= rnd_auc <= 0.65
        assert hyb_ndcg > rnd_ndcg + 0.05
        assert hyb_ndcg > pop_ndcg

        cmp_entry = summ["comparisons"]["ndcg@5"]["HybridFactorRanker"]
        assert cmp_entry["n"] == sd.n_users
        assert "wilcoxon" in cmp_entry and "cohens_dz" in cmp_entry and "assumptions" in cmp_entry


def test_kb_publishability_m7_and_draft_slugs():
    audit = export_ranker.kb_publishability_audit()
    assert audit["n_kb_total"] == 569
    assert audit["n_publishable"] == 560
    assert audit["n_draft"] == 9
    assert audit["by_slot_total"] == {"canh": 123, "man": 304, "rau": 142}
    draft_slugs = {d["slug"] for d in audit["draft_recipes"]}
    assert draft_slugs == {
        "bo-cuon-nam-kim-cham",
        "bo-sot-vang",
        "bo-xao-ca-chua",
        "cai-ngot-xao-toi",
        "trung-sot-ca-chua",
        "canh-ga-la-giang",
        "canh-rong-bien-dau-hu",
        "canh-xuong-ham-cu-cai",
        "ngon-su-su-xao-toi",
    }


def test_export_ranker_roundtrip_sha256_foldin_unseen_and_no_pickle(tmp_path):
    res = export_ranker.train_and_export(
        output_dir=tmp_path,
        seed=20261018,
        weights=(0.40, 0.35, 0.20, 0.05),
    )
    assert res["parity_max_abs_diff"] < 1e-4

    npz_path = tmp_path / "model.npz"
    serving_path = tmp_path / "serving.json"
    serving = json.loads(serving_path.read_text(encoding="utf-8"))
    assert serving["SIMULATED"] is True
    assert serving["artifact_sha256"] == export_ranker.sha256_file(npz_path)
    assert serving["training_data"]["n_kb_recipes"] == 569
    assert serving["training_data"]["n_published_db_recipes"] == 560

    with np.load(npz_path, allow_pickle=False) as z:
        assert all(z[k].dtype != object for k in z.files)
        assert int(z["publishable"].sum()) == 560
        assert len(z["recipe_names"]) == 569

    # Determinism across reloads
    r1 = export_ranker.ExportedNumpyRanker.load(tmp_path, verify_sha256=True)
    r2 = export_ranker.ExportedNumpyRanker.load(tmp_path, verify_sha256=True)
    favs = r1.recipe_names[:5]
    s1 = r1.score(favs, r1.recipe_names)
    s2 = r2.score(favs, r2.recipe_names)
    assert np.array_equal(s1, s2)
    assert np.isfinite(s1).all()
    # Fold-in pushes user favorites above catalog median
    assert float(np.mean(s1[:5])) > float(np.median(s1))

    # Empty favorites fallback is finite
    s_empty = r1.score([], r1.recipe_names)
    assert np.isfinite(s_empty).all()

    # Unseen item fallback (duck-typed backend RecipeView)
    fav0 = r1.recipe_names[0]
    fav_feats = [f for f, v in zip(r1.feature_names, r1.X_content[0], strict=True) if v > 0]
    ing_fav = next((f.split("ing:", 1)[1] for f in fav_feats if f.startswith("ing:")), None)
    method_fav = next((f.split("method:", 1)[1] for f in fav_feats if f.startswith("method:")), "xao")

    unseen_match = SimpleNamespace(
        id=uuid.uuid4(),
        name_vi="Món thử nghiệm mới hợp gu",
        slot="man",
        method_code=method_fav,
        tag_codes=[],
        lines=[SimpleNamespace(role="main", ingredient=SimpleNamespace(name_vi=ing_fav, is_staple=False))] if ing_fav else [],
    )
    unseen_empty = SimpleNamespace(
        id=uuid.uuid4(),
        name_vi="Món thử nghiệm không trùng",
        slot="man",
        method_code="unknown_method",
        tag_codes=[],
        lines=[],
    )
    s_unseen = r1.score([fav0], [unseen_match, unseen_empty])
    assert np.isfinite(s_unseen).all()
    if ing_fav is not None:
        assert s_unseen[0] > s_unseen[1]

    # Live signal blending (personal & popularity)
    s_blend = r1.score(
        [fav0],
        [unseen_match],
        popularity={unseen_match.id: SimpleNamespace(positive=10, negative=0)},
        personal={unseen_match.id: SimpleNamespace(positive=5, negative=0)},
        popularity_weight=0.1,
        personal_weight=0.25,
    )
    assert float(s_blend[0]) > float(s_unseen[0])

    # SHA-256 tamper detection
    npz_path.write_bytes(npz_path.read_bytes() + b"\x00")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        export_ranker.ExportedNumpyRanker.load(tmp_path, verify_sha256=True)


def test_p3_generated_artifacts_schema_and_invariants():
    research_dir = research.OUT_DIR
    deploy_dir = export_ranker.DEFAULT_DEPLOY_DIR
    if not (research_dir / "summary.json").exists() or not (deploy_dir / "serving.json").exists():
        pytest.skip("P3 research artifacts not generated yet")

    required_files = [
        "manifest.json",
        "foodcom_baseline_ref.json",
        "foodcom_confirmatory.json",
        "foodcom_confirmatory_pairs.csv",
        "foodcom_exploratory.json",
        "kb_db_alignment.json",
        "survey_confirmatory.json",
        "survey_confirmatory_pairs.csv",
        "sanity_controls.json",
        "summary.json",
    ]
    for fn in required_files:
        assert (research_dir / fn).exists(), f"Missing P3 artifact: {fn}"

    manifest = json.loads((research_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["protocol_id"] == "TASTORIA-ML-PREREG-2026-11-18"
    assert manifest["mde_sensitivity"]["observed_power_computed"] is False
    assert manifest["kb_recipe_counts"]["total"] in (180, 569)
    assert manifest["kb_recipe_counts"]["publishable"] in (171, 560)

    baseline_ref = json.loads((research_dir / "foodcom_baseline_ref.json").read_text(encoding="utf-8"))
    assert baseline_ref["analysis_intent"] == "baseline_reproduction"
    assert baseline_ref["warm"]["n_users"] == 4834

    conf = json.loads((research_dir / "foodcom_confirmatory.json").read_text(encoding="utf-8"))
    assert conf["analysis_intent"] == "confirmatory"
    assert conf["warm"]["n_users"] == 4834
    assert conf["cold"]["n_users"] == 422
    assert conf["cold"]["n_cold_items"] == 599
    with open(research_dir / "foodcom_confirmatory_pairs.csv", encoding="utf-8") as f:
        fc_rows = list(csv.DictReader(f))
    assert len(fc_rows) >= 21

    exp = json.loads((research_dir / "foodcom_exploratory.json").read_text(encoding="utf-8"))
    assert exp["analysis_intent"] == "exploratory"
    assert set(exp["cold_lightfm_feature_ablations"]["models"]) == {"id_only", "tags_only", "ing_only", "tags_ing"}

    kb_align = json.loads((research_dir / "kb_db_alignment.json").read_text(encoding="utf-8"))
    assert kb_align["kb_publishability"]["n_kb_total"] in (180, 569)
    assert kb_align["kb_publishability"]["n_publishable"] in (171, 560)

    sv = json.loads((research_dir / "survey_confirmatory.json").read_text(encoding="utf-8"))
    assert sv["SIMULATED"] is True
    assert sv["analysis_intent"] == "confirmatory"
    for sc in ("warm", "item_cold", "user_cold"):
        assert sv["scenarios"][sc]["n_users"] == 90

    sanity = json.loads((research_dir / "sanity_controls.json").read_text(encoding="utf-8"))
    assert sanity["passed"] is True

    # Deployed ranker parity & checksum
    ranker = export_ranker.ExportedNumpyRanker.load(deploy_dir, verify_sha256=True)
    assert ranker.serving["SIMULATED"] is True
    assert int(ranker.publishable.sum()) in (171, 560)


def test_p3_exploratory_bh_fdr_and_summary_sha256():
    research_dir = research.OUT_DIR
    summary_path = research_dir / "summary.json"
    exp_path = research_dir / "foodcom_exploratory.json"
    if not summary_path.exists() or not exp_path.exists():
        pytest.skip("P3 research artifacts not generated yet")

    exp = json.loads(exp_path.read_text(encoding="utf-8"))
    contrasts = exp["cold_lightfm_feature_ablations"]["contrasts_bh_fdr"]
    assert len(contrasts) == 5
    for mk in ("ndcg@10", "hr@10"):
        ps = [contrasts[k][mk]["paired_bootstrap"]["p"] for k in contrasts]
        qs = [contrasts[k][mk]["q_bh"] for k in contrasts]
        assert np.allclose(qs, stats.bh_fdr(ps), atol=1e-12), f"{mk}: {qs} vs {stats.bh_fdr(ps)}"

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    sha_map = summary["artifact_sha256"]
    assert len(sha_map) == 12
    for rel_path, expected_sha in sha_map.items():
        target = research.REPO / rel_path
        assert target.exists(), f"Missing artifact indexed in summary.json: {rel_path}"
        assert export_ranker.sha256_file(target) == expected_sha, f"SHA-256 mismatch for {rel_path}"
