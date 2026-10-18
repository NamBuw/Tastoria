"""Food.com ranking pipeline: core/split rules, metrics, own BPR gradient, EASE and ItemKNN closed forms, stats."""

import numpy as np
import pandas as pd
import pytest
import scipy.sparse as sp

from tastoria_ml.recsys import data, metrics, models, stats


def _toy_interactions(seed=0, n_users=40, n_items=30, n=900):
    rng = np.random.default_rng(seed)
    u = rng.integers(0, n_users, n)
    i = rng.integers(0, n_items, n)
    days = rng.integers(0, 1000, n)
    rating = rng.choice([0, 2, 4, 5], size=n, p=[0.05, 0.1, 0.25, 0.6])
    df = pd.DataFrame(
        {
            "user_id": u + 1000,
            "recipe_id": i + 5000,
            "date": pd.Timestamp("2005-01-01") + pd.to_timedelta(days, unit="D"),
            "rating": rating,
        }
    )
    return df.drop_duplicates(["user_id", "recipe_id"]).reset_index(drop=True)


def test_kcore_fixed_point():
    df = _toy_interactions()
    core = data.kcore(df[df.rating >= 4], 5)
    assert (core.user_id.value_counts() >= 5).all()
    assert (core.recipe_id.value_counts() >= 5).all()


def test_time_cutoffs_shares():
    dates = pd.Series(pd.date_range("2000-01-01", periods=1000, freq="D"))
    d_val, d_test = data.time_cutoffs(dates)
    assert (dates < d_val).mean() == pytest.approx(0.8, abs=0.002)
    assert (dates >= d_test).mean() == pytest.approx(0.1, abs=0.002)


def test_split_rules_rating0_is_seen_not_target():
    d = data.prepare(_toy_interactions(), k=3)
    for phase in ("val", "test"):
        s = d.split(phase)
        lo = d.d_val if phase == "val" else d.d_test
        tr = d.pos[d.pos.date < lo]
        assert s.train.nnz == len(tr.drop_duplicates(["u", "i"]))
        # every positive in train is "seen"; every target is unseen, warm and a positive
        assert (s.seen.multiply(s.train) != s.train).nnz == 0
        warm_i = np.asarray(s.train.sum(0)).ravel() > 0
        for u, items in s.targets.items():
            assert s.train[u].nnz > 0
            assert warm_i[items].all()
            assert s.seen[u, items].sum() == 0
        zero = d.inter[(d.inter.rating == 0) & (d.inter.date < lo)]
        for u, i in zip(zero.u, zero.i, strict=True):
            assert s.seen[u, i] == 1  # rating 0 is an interaction ...
            assert s.train[u, i] == 0  # ... but never a positive


def test_topk_metrics_hand_computed():
    scores = np.array([[0.9, 0.8, 0.7, 0.1, 0.0], [0.0, 0.1, 0.2, 0.3, 0.4]], dtype=np.float32)
    seen = sp.csr_matrix(np.array([[1, 0, 0, 0, 0], [0, 0, 0, 0, 0]], dtype=np.float32))
    targets = {0: np.array([2, 4]), 1: np.array([0])}
    m = metrics.topk_metrics(lambda u: scores[u], targets, seen, k=2)
    # user 0: item 0 seen → list [1, 2]: hit at rank 2
    assert m["hr"][0] == 1.0
    assert m["recall"][0] == pytest.approx(0.5)
    assert m["ndcg"][0] == pytest.approx((1 / np.log2(3)) / (1 + 1 / np.log2(3)))
    # user 1: list [4, 3], target 0 missed
    assert m["hr"][1] == 0.0 and m["ndcg"][1] == 0.0


def test_graded_ndcg_and_auc():
    y = np.array([5, 1, 3, 4])
    assert metrics.ndcg_graded(y, np.array([4.0, 0.0, 2.0, 3.0]), k=5) == pytest.approx(1.0)
    worst = metrics.ndcg_graded(y, np.array([0.0, 4.0, 2.0, 1.0]), k=2)
    assert 0 < worst < 1
    assert metrics.auc_pairs(y, y.astype(float)) == 1.0
    assert metrics.auc_pairs(y, -y.astype(float)) == 0.0
    assert metrics.auc_pairs(y, np.zeros(4)) == 0.5
    assert np.isnan(metrics.ndcg_graded(np.array([1, 1]), np.array([0.1, 0.2])))


def test_bpr_numpy_gradient_matches_finite_difference():
    rng = np.random.default_rng(0)
    p, qi, qj = rng.standard_normal((3, 4))
    lam = 0.01

    def loss(p, qi, qj):
        x = p @ (qi - qj)
        return np.logaddexp(0, -x) + lam * (p @ p + qi @ qi + qj @ qj)

    x = p @ (qi - qj)
    g = models._sigmoid(-x)
    # the update direction used in BPRNumpy.fit is the negative gradient
    ana = {"p": -(g * (qi - qj) - 2 * lam * p), "qi": -(g * p - 2 * lam * qi), "qj": -(-g * p - 2 * lam * qj)}
    eps = 1e-6
    for name, vec in (("p", p), ("qi", qi), ("qj", qj)):
        num = np.zeros(4)
        for k in range(4):
            e = np.zeros(4)
            e[k] = eps
            args = {"p": p, "qi": qi, "qj": qj}
            hi = loss(**{**args, name: vec + e})
            lo = loss(**{**args, name: vec - e})
            num[k] = (hi - lo) / (2 * eps)
        assert np.allclose(num, ana[name], atol=1e-5)


def _planted(seed=0, n_users=200, n_items=60, dim=3):
    rng = np.random.default_rng(seed)
    pu = rng.standard_normal((n_users, dim))
    qi = rng.standard_normal((n_items, dim))
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
    return train, targets


@pytest.mark.parametrize(
    "model",
    [
        models.BPRNumpy(dim=8, lam=1e-4, lr=0.05, epochs=40, batch=256, seed=0),
        models.EASE(lam=10.0, max_items=None),
        models.ItemKNN(k=20),
        models.ALS(factors=8, reg=0.1, alpha=5.0, iterations=10, seed=0),
    ],
    ids=lambda m: m.name,
)
def test_models_beat_random_on_planted_structure(model):
    train, targets = _planted()
    model.fit(train)
    ours = metrics.summarize(metrics.topk_metrics(model.scores, targets, train, k=5), k=5)["ndcg@5"]
    rnd = models.Random(seed=0).fit(train)
    base = metrics.summarize(metrics.topk_metrics(rnd.scores, targets, train, k=5), k=5)["ndcg@5"]
    assert ours > base + 0.1


def test_bpr_numpy_loss_decreases_and_is_seeded():
    train, _ = _planted()
    a = models.BPRNumpy(dim=8, epochs=10, batch=256, seed=3).fit(train)
    b = models.BPRNumpy(dim=8, epochs=10, batch=256, seed=3).fit(train)
    assert a.history[-1]["loss"] < a.history[0]["loss"]
    assert np.array_equal(a.P, b.P)


def test_negative_sampler_never_returns_a_positive():
    train, _ = _planted()
    coo = train.tocoo()
    keys = np.sort(coo.row.astype(np.int64) * train.shape[1] + coo.col)
    rng = np.random.default_rng(0)
    u = np.repeat(np.arange(train.shape[0]), 50)
    j = models._sample_negatives(rng, u, keys, train.shape[1])
    assert train[u, j].sum() == 0


def test_ease_closed_form_and_zero_diagonal():
    rng = np.random.default_rng(1)
    x = sp.csr_matrix((rng.random((30, 12)) < 0.3).astype(np.float32))
    m = models.EASE(lam=5.0, max_items=None).fit(x)
    g = (x.T @ x).toarray().astype(float) + 5.0 * np.eye(12)
    p = np.linalg.inv(g)
    b = np.eye(12) - p / np.diag(p)
    assert np.allclose(np.diag(m.b), 0)
    assert np.allclose(m.b, b, atol=1e-5)


def test_ease_catalog_cap_marks_unscorable_items():
    rng = np.random.default_rng(2)
    x = sp.csr_matrix((rng.random((40, 10)) < 0.3).astype(np.float32))
    m = models.EASE(lam=5.0, max_items=4).fit(x)
    assert m.allowed.sum() == 4
    assert np.isinf(m.scores(np.arange(3))[:, ~m.allowed]).all()


def test_itemknn_matches_bruteforce_cosine():
    rng = np.random.default_rng(3)
    x = sp.csr_matrix((rng.random((25, 9)) < 0.4).astype(np.float32))
    m = models.ItemKNN(k=8, chunk=4).fit(x)
    d = x.toarray()
    n = np.sqrt(d.sum(0))
    c = (d.T @ d) / np.maximum(np.outer(n, n), 1e-12)
    np.fill_diagonal(c, 0)
    assert np.allclose(m.sim.toarray(), c, atol=1e-6)


def test_paired_bootstrap_and_holm():
    rng = np.random.default_rng(0)
    a = rng.normal(0.1, 1, 500)
    r = stats.paired_bootstrap(a + 0.5, a, n_boot=500)
    assert r["diff"] == pytest.approx(0.5)
    assert r["lo"] <= 0.5 <= r["hi"] and r["p"] < 0.01
    same = stats.paired_bootstrap(a, a + rng.normal(0, 0.01, 500), n_boot=500)
    assert same["p"] > 0.01 or abs(same["diff"]) < 0.01
    adj = stats.holm([0.01, 0.04, 0.03])
    assert np.allclose(adj, [0.03, 0.06, 0.06])
    mc = stats.mcnemar(np.array([1, 1, 1, 0, 1], bool), np.array([0, 0, 1, 0, 1], bool))
    assert mc["a_only"] == 2 and mc["b_only"] == 0
