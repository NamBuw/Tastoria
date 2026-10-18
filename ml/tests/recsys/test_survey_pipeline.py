"""Survey explicit-rating pipeline (design v2 §6.1). Runs on a SIMULATED survey only: a pipeline test, not a result."""

import csv
import json
import uuid

import numpy as np
import pytest

from tastoria_ml.recsys import kb_catalog, survey


@pytest.fixture(scope="module")
def cat():
    return kb_catalog.load()


@pytest.fixture(scope="module")
def sim(cat):
    return survey.simulate(cat, seed=7, n_users=40, taste_scale=1.5, noise_sd=0.4)


def test_simulation_is_labelled_and_follows_the_block_design(sim, cat):
    assert sim.simulated and "MÔ PHỎNG" in sim.meta["SIMULATION"]
    shown = sim.ratings.groupby("user").size() + sim.never.groupby("user").size().reindex(range(sim.n_users), fill_value=0)
    assert (shown == 45).all()  # 10 anchors + 35 random per respondent
    counts = (
        np.bincount(sim.ratings.item, minlength=sim.n_items) + np.bincount(sim.never.item, minlength=sim.n_items)
    )
    assert (counts == sim.n_users).sum() == 10  # anchors are shown to everyone
    assert all(len(v) == 5 for v in sim.favorites.values())
    assert set(sim.ratings.rating.unique()) <= {1.0, 2.0, 3.0, 4.0, 5.0}
    again = survey.simulate(cat, seed=7, n_users=40, taste_scale=1.5, noise_sd=0.4)
    assert again.ratings.equals(sim.ratings)


def test_load_export_reads_the_backend_export_format(tmp_path, sim, cat):
    """Write the six CSV files exactly as `tastoria survey export` does (service.export) and read them back."""
    rid = {i: str(uuid.UUID(int=i + 1)) for i in range(sim.n_items)}
    resp = {u: str(uuid.UUID(int=10_000 + u)) for u in range(sim.n_users)}

    def write(name, header, rows):
        with open(tmp_path / name, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(header)
            w.writerows(rows)

    write("respondents.csv", ["respondent_id", "policy_version", "consented_at", "completed_at", "channel"],
          [[resp[u], "v1", "", "", "web"] for u in range(sim.n_users)])
    rows = [[resp[r.user], rid[r.item], int(r.rating), "false", ""] for r in sim.ratings.itertuples()]
    rows += [[resp[r.user], rid[r.item], "", "true", ""] for r in sim.never.itertuples()]
    write("ratings.csv", ["respondent_id", "recipe_id", "rating", "never_eaten", "answered_at"], rows)
    write("favorites.csv", ["respondent_id", "recipe_id"], [[resp[u], rid[i]] for u, v in sim.favorites.items() for i in v])
    write("recipes.csv", ["recipe_id", "name_vi", "slot", "status"],
          [[rid[i], r.name_vi, r.slot, "published"] for i, r in enumerate(cat.recipes)])
    write("assignments.csv", ["respondent_id", "recipe_id", "display_order", "is_anchor"], [])
    write("anchors.csv", ["recipe_id", "slot"], [])
    (tmp_path / "manifest.json").write_text(json.dumps({"form_version": "test"}), encoding="utf-8")
    back = survey.load_export(tmp_path, cat)
    assert not back.simulated
    assert len(back.ratings) == len(sim.ratings) and len(back.never) == len(sim.never)
    a = sim.ratings.sort_values(["user", "item"]).to_numpy()
    b = back.ratings.sort_values(["user", "item"]).to_numpy()
    assert np.array_equal(a, b)
    assert {u: list(v) for u, v in back.favorites.items()} == {u: list(v) for u, v in sim.favorites.items()}
    assert back.meta["unmapped_recipes"] == []


@pytest.mark.parametrize("cls", survey.MODELS, ids=lambda c: c.name)
def test_every_model_fits_and_scores_all_scenarios(cls, sim):
    rows = sim.ratings
    test_users = np.array([0, 1, 2])
    tr = rows[~rows.user.isin(test_users)]
    f = survey.Fold(tr, sim.favorites, sim.n_users, sim.n_items, sim.cat, frozenset(int(u) for u in test_users))
    m = cls(seed=0, **cls.grid[0]).fit(f)
    s = m.score(0, np.arange(sim.n_items))
    assert s.shape == (sim.n_items,) and np.isfinite(s).all()


def test_biased_mf_recovers_taste_better_than_item_mean(sim, monkeypatch):
    for cls in survey.MODELS:
        monkeypatch.setattr(cls, "grid", cls.grid[:1])
    res = survey.run_scenario(sim, "warm", seed=0, k_outer=3, models=[survey.ShrunkMean, survey.BiasedMF])
    s = survey.summarise([res])
    assert s["models"]["Biased MF"]["auc"]["mean"] > s["models"]["ShrunkMean"]["auc"]["mean"]
    assert survey.BEST in s["models"]


def test_scenarios_hold_out_the_right_unit(sim):
    rng = np.random.default_rng(0)
    rows = sim.ratings.reset_index(drop=True)
    f = survey._assign_folds(sim, "user_cold", rows, 5, rng)
    for k in range(5):
        assert not set(rows.user[f == k]) & set(rows.user[f != k])
    f = survey._assign_folds(sim, "item_cold", rows, 5, rng)
    for k in range(5):
        assert not set(rows.item[f == k]) & set(rows.item[f != k])
    f = survey._assign_folds(sim, "warm", rows, 5, rng)
    per_user = rows.assign(f=f).groupby("user").f.nunique()
    assert (per_user == 5).all()


def test_cold_users_have_no_training_rating_and_mf_folds_them_in(sim):
    rows = sim.ratings
    cold = frozenset({3, 4})
    tr = rows[~rows.user.isin(cold)]
    f = survey.Fold(tr, sim.favorites, sim.n_users, sim.n_items, sim.cat, cold)
    m = survey.BiasedMF(seed=0, dim=4, lam=0.05).fit(f)
    assert not tr.user.isin(cold).any()
    s = m.score(3, np.arange(sim.n_items))
    # the fold-in pushes the user's own favourites up
    fav = sim.favorites[3]
    assert s[fav].mean() > np.median(s)
