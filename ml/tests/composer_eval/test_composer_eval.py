"""Composer evaluation: scenario generator, live-composer reuse, feasibility audit, knee selection, and CP-SAT bench."""

import hashlib
import json
from dataclasses import fields

import numpy as np
import pytest

from tastoria.modules.meal import composer as cmp
from tastoria_ml.composer_eval import cpsat_bench as CB
from tastoria_ml.composer_eval import run as R
from tastoria_ml.composer_eval import scenarios as S
from tastoria_ml.recsys import kb_catalog


@pytest.fixture(scope="module")
def cat():
    return kb_catalog.load()


@pytest.fixture(scope="module")
def views(cat):
    return R.build_views(cat)


@pytest.fixture(scope="module")
def scen(cat):
    return S.generate(cat, n=12, seed=5)


def test_generator_is_seeded_and_split_in_halves(cat, scen):
    again = S.generate(cat, n=12, seed=5)
    assert again["scenarios"] == scen["scenarios"]
    splits = [s["split"] for s in scen["scenarios"]]
    assert splits.count("tuning") == 6 and splits.count("test") == 6
    for s in scen["scenarios"]:
        assert s["persons"] in (1, 2, 3, 4)
        assert 0.30 * 1700 <= s["e_target_kcal"] <= 0.35 * 2700
        assert len(s["favorites"]) == 5
        for lot in s["lots"]:
            assert lot["g_min"] > 0
            assert (lot["urgency"] is None) == (not lot["shelf_life_days"])


def test_seed_dishes_are_stocked(cat, scen):
    lines = S.stock_lines(cat)
    idx = cat.index()
    for s in scen["scenarios"]:
        have = {}
        for lot in s["lots"]:
            have[lot["ingredient"]] = have.get(lot["ingredient"], 0) + lot["g_min"]
        for slug in s["seed_dishes"]:
            r = idx[slug]
            for name, g in lines[r].items():
                assert have.get(name, 0) + 1e-6 >= g * s["persons"] / cat.recipes[r].servings


def test_views_match_the_kb(cat, views):
    assert len(views.recipes) == len(cat.recipes)
    r = views.recipes["ba-chi-chien-nuoc-mam"]
    assert r.method_code == "chien" and r.slot == "man" and r.kcal_per_serving == cat.kcal["ba-chi-chien-nuoc-mam"]
    ma = [v for v in views.recipes.values() if v.make_ahead is not None]
    assert len(ma) == len(cat.make_ahead)


def test_every_served_tray_passes_the_independent_audit(cat, views, scen):
    rng = np.random.default_rng(0)
    served = 0
    for s in scen["scenarios"]:
        p = R.prepare(s, views, cat.rice_kcal)
        for a, b, g in ((0, 0, 0), (1, 1, 0.5), (8, 0, 0.5), (0, 4, 1)):
            t, _ = R.solve(p, a, b, g)
            if t is not None:
                served += 1
                assert R.check_feasible(t, p, views) == []
        t = R.random_feasible(p, rng)
        if t is not None:
            assert R.check_feasible(t, p, views) == []
    assert served > 0


def test_audit_detects_an_infeasible_tray(cat, views, scen):
    s = next(x for x in scen["scenarios"] if R.solve(R.prepare(x, views, cat.rice_kcal), 0, 0, 0)[0] is not None)
    p = R.prepare(s, views, cat.rice_kcal)
    t, _ = R.solve(p, 0, 0, 0)
    starved = R.Prepared(**{**p.__dict__, "lots": [lot.__class__(lot.id, lot.ingredient_id, 0.0, lot.urgency, lot.rewarded) for lot in p.lots]})
    assert R.check_feasible(t, starved, views)


def test_taste_only_maximises_taste_and_alpha_raises_urgency(cat, views, scen):
    up = 0
    for s in scen["scenarios"]:
        p = R.prepare(s, views, cat.rice_kcal)
        t0, _ = R.solve(p, 0, 0, 0)
        t1, _ = R.solve(p, 64, 0, 0)
        if t0 is None or t1 is None or len(t0.dishes) != len(t1.dishes):
            continue
        assert t0.taste >= t1.taste - 1e-9
        assert t1.urgency >= t0.urgency - 1e-9
        up += t1.urgency > t0.urgency
    assert up >= 1


def test_rule_and_pareto():
    table = [
        {"alpha": 0, "beta": 0, "gamma": 0, "urgency": 0.1, "taste_loss": 0.0, "kcal_dev": 0.1},
        {"alpha": 1, "beta": 0, "gamma": 0, "urgency": 0.3, "taste_loss": 0.1, "kcal_dev": 0.1},
        {"alpha": 4, "beta": 0, "gamma": 0, "urgency": 0.4, "taste_loss": 0.3, "kcal_dev": 0.1},
        {"alpha": 1, "beta": 1, "gamma": 0, "urgency": 0.3, "taste_loss": 0.1, "kcal_dev": 0.2},
    ]
    assert R.choose(table)["alpha"] == 1 and R.choose(table)["beta"] == 0
    assert R.pareto(table) == [0, 1, 2]
    assert R.choose([{**table[2]}]) is None


def test_generate_confirmatory_distinct_from_exploratory(cat):
    assert S.CONFIRMATORY_SEED != S.SEED
    c1 = S.generate_confirmatory(cat, n=8)
    c2 = S.generate_confirmatory(cat, n=8)
    assert c1["scenarios"] == c2["scenarios"]
    assert all(s["split"] == "confirmatory" and s["id"].startswith("c") for s in c1["scenarios"])
    exp = S.generate(cat, n=8, seed=S.SEED)
    assert c1["scenarios"][0]["favorites"] != exp["scenarios"][0]["favorites"]


def test_choose_knee_enforces_tail_kcal_and_urgency_gain():
    table = [
        {"alpha": 0.0, "beta": 0.0, "gamma": 0.0, "urgency": 0.18, "taste_loss": 0.00, "kcal_dev": 0.08, "share_kcal_ok": 0.96},
        {"alpha": 64.0, "beta": 0.0, "gamma": 0.5, "urgency": 0.33, "taste_loss": 0.19, "kcal_dev": 0.06, "share_kcal_ok": 0.89},
        {"alpha": 16.0, "beta": 2.0, "gamma": 1.0, "urgency": 0.323, "taste_loss": 0.160, "kcal_dev": 0.055, "share_kcal_ok": 0.93},
        {"alpha": 16.0, "beta": 4.0, "gamma": 0.5, "urgency": 0.325, "taste_loss": 0.165, "kcal_dev": 0.052, "share_kcal_ok": 0.93},
        {"alpha": 4.0, "beta": 1.0, "gamma": 0.5, "urgency": 0.25, "taste_loss": 0.08, "kcal_dev": 0.04, "share_kcal_ok": 0.96},
    ]
    pick = R.choose_knee(table)
    assert pick is not None
    # Rejects alpha=64 (share_kcal_ok=0.89 < 0.92) and alpha=4 (urgency < 95% gain), picks min taste_loss
    assert (pick["alpha"], pick["beta"], pick["gamma"]) == (16.0, 2.0, 1.0)


def test_prepare_supports_pluggable_scorer(cat, views, scen):
    sim = R.SimulatedAffinityRanker(cat, seed=42)
    p = R.prepare(scen["scenarios"][0], views, cat.rice_kcal, scorer=sim)
    for slot in ("man", "rau", "canh"):
        vals = [o.s_prime for o in p.options[slot]]
        assert vals and all(0.0 <= v <= 1.0 for v in vals)


def test_cpsat_bench_smoke(cat, views):
    rows, summary = CB.run_unit_benchmarks(cat, views, seed=123, runs_per_cell=1, stress_runs=4)
    assert len(rows) == 16
    assert summary["overall_all_runs"]["violations"] == 0
    assert summary["production_1_to_3_dishes"]["sla_pass"] is True
    assert all(r["latency_ms"] > 0 and r["status"] in {"optimal", "feasible", "relaxed", "empty"} for r in rows)


def test_serving_json_matches_composer_params_if_present():
    p = R.DEPLOY_COMPOSER / "serving.json"
    if not p.exists():
        pytest.skip("deploy/models/composer/serving.json not yet exported")
    sv = json.loads(p.read_text(encoding="utf-8"))
    param_fields = {f.name for f in fields(cmp.Params)}
    assert set(sv["params"]) == param_fields
    sha = sv["artifact_sha256"]
    body = {k: v for k, v in sv.items() if k != "artifact_sha256"}
    canon = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert sha == hashlib.sha256(canon).hexdigest()
