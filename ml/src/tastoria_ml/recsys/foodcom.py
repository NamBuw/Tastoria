"""Food.com top-N experiments (design v2 §6.1, "Food.com" bullet): implementation check and reproducibility, not
model selection for Vietnamese dishes.

Stages (each writes JSON under data/processed/recsys/ and is skipped when its file exists, unless --force):
  tune      grid per model on the validation phase (train < d_val, evaluate [d_val, d_test)); NDCG@10 selects
  test      best config retrained on train+validation (< d_test), evaluated once on the test phase; 5 seeds for
            stochastic models; paired bootstrap by user vs MostPop (NDCG@10 and HR@10), Holm over the comparisons
  curve     learning curve: 25/50/75/100 % of training users (3 user samples), test phase, best configs
  errors    error analysis by user activity (train+val positives) and popularity of the recommended items
  cold      item cold start: test positives on items with no positive before d_test, ranked among those items
  figures   PNGs in docs/reports/hoc-may/fig/

Run: CUDA_VISIBLE_DEVICES= uv run --package tastoria-ml python -m tastoria_ml.recsys.foodcom [stage ...]
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from importlib import metadata
from pathlib import Path

import numpy as np

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

from tastoria_ml.recsys import data, metrics, models, stats  # noqa: E402

REPO = data.REPO
OUT = REPO / "data" / "processed" / "recsys"
CACHE = OUT / "cache"
FIG = REPO / "docs" / "reports" / "hoc-may" / "fig"
SEEDS = (0, 1, 2, 3, 4)
K = 10

GRIDS: dict[str, list[dict]] = {
    "ItemKNN": [{"k": k, "shrink": h} for k in (10, 20, 50, 100, 200, 500, 1000) for h in (0.0, 20.0)]
    + [{"k": k, "shrink": h} for k in (1000, 2000) for h in (100.0,)] + [{"k": 2000, "shrink": 20.0}],
    "EASE": [{"lam": lam, "max_items": 20000} for lam in (100.0, 300.0, 1000.0, 3000.0, 10000.0, 30000.0, 100000.0)],
    # validation NDCG peaks within the first epochs on the time split (checked in a first 100-epoch sweep,
    # data/processed/recsys/tuning_bpr_first_sweep.json), so 30 epochs with a checkpoint every 2
    "BPR-MF (NumPy)": [
        {"dim": d, "lam": lam, "lr": lr, "epochs": 30}
        for d in (16, 32, 64, 128)
        for lam in (1e-5, 1e-4, 1e-3, 1e-2)
        for lr in (0.01, 0.05)
    ],
    "BPR (implicit)": [
        {"factors": f, "lr": lr, "reg": reg, "iterations": it}
        for f in (32, 64, 128)
        for lr in (0.01, 0.05, 0.1)
        for reg in (0.001, 0.01, 0.1)
        for it in (20, 50, 100, 300)
    ],
    "ALS (implicit)": [
        {"factors": f, "reg": reg, "alpha": a, "iterations": 15}
        for f in (32, 64, 128)
        for reg in (0.01, 0.1, 1.0, 10.0)
        for a in (1.0, 5.0, 20.0, 50.0)
    ],
    "LightFM WARP": [
        {"dim": d, "lr": lr, "item_alpha": ia, "epochs": 20} for d in (32, 64) for lr in (0.05,) for ia in (0.0, 1e-6)
    ]
    + [{"dim": 64, "lr": 0.02, "item_alpha": 0.0, "epochs": 20}],
}
CHECKPOINTED = {"BPR-MF (NumPy)": ("epochs", 2), "LightFM WARP": ("epochs", 2)}
USES_FEATURES = {"LightFM WARP"}


def log(*a: object) -> None:
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def _dump(name: str, obj: object) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(obj, indent=1, ensure_ascii=False, default=float) + "\n", encoding="utf-8")


def _load(name: str):
    p = OUT / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _eval(model, split: data.Split, return_top: bool = False) -> dict[str, np.ndarray]:
    return metrics.topk_metrics(
        model.scores, split.targets, split.seen, k=K, allowed=getattr(model, "allowed", None), return_top=return_top
    )


class Ctx:
    def __init__(self) -> None:
        log("loading Food.com")
        self.d = data.load()
        self.F, self.f_names = data.item_features(self.d.items)  # identity + tags/ingredients
        self.F_only, _ = data.item_features(self.d.items, identity=False)
        self._splits: dict[str, data.Split] = {}

    def split(self, phase: str) -> data.Split:
        if phase not in self._splits:
            self._splits[phase] = self.d.split(phase)
        return self._splits[phase]


# ----------------------------------------------------------------------------------------------------- tune


def tune(ctx: Ctx, only: list[str] | None = None) -> dict:
    s = ctx.split("val")
    res = _load("tuning.json") or {"rows": []}
    done = {(r["model"], json.dumps(r["params"], sort_keys=True)) for r in res["rows"]}
    for name, grid in GRIDS.items():
        if only and name not in only:
            continue
        for params in grid:
            key_params = dict(params)
            if (name, json.dumps(key_params, sort_keys=True)) in done:
                continue
            t0 = time.time()
            rows = []
            if name in CHECKPOINTED:
                field, every = CHECKPOINTED[name]

                def cb(ep, m, _p=params, _n=name):
                    r = metrics.summarize(_eval(m, s))
                    rows.append({"model": _n, "params": {**_p, field: ep}, **r})
                    log(_n, {**_p, field: ep}, round(r["ndcg@10"], 5))
                    return r["ndcg@10"]

                m = models.make(name, **params, seed=0)
                m.fit(s.train, item_features=ctx.F, callback=cb, eval_every=every)
                # the last checkpoint carries the full-length params, which mark the grid point as done
            else:
                kw = dict(params)
                if models.make(name).stochastic:
                    kw["seed"] = 0
                m = models.make(name, **kw)
                m.fit(s.train, item_features=ctx.F if name in USES_FEATURES else None)
                r = metrics.summarize(_eval(m, s))
                rows.append({"model": name, "params": params, **r})
                log(name, params, round(r["ndcg@10"], 5))
            for r in rows:
                r["fit_eval_seconds"] = round(time.time() - t0, 1)
            res["rows"].extend(rows)
            _dump("tuning.json", res)
    # MostPop has nothing to tune but its validation score is reported next to the others
    if not any(r["model"] == "MostPop" for r in res["rows"]):
        r = metrics.summarize(_eval(models.MostPop().fit(s.train), s))
        res["rows"].append({"model": "MostPop", "params": {}, **r})
    res["best"] = best_configs(res)
    res["phase"] = {"train": f"< {ctx.d.d_val.date()}", "eval": f"[{ctx.d.d_val.date()}, {ctx.d.d_test.date()})"}
    res["n_val_users"] = len(s.targets)
    _dump("tuning.json", res)
    return res


def best_configs(res: dict) -> dict[str, dict]:
    best: dict[str, dict] = {}
    for r in res["rows"]:
        b = best.get(r["model"])
        if b is None or r["ndcg@10"] > b["ndcg@10"]:
            best[r["model"]] = r
    return {k: {"params": v["params"], "val_ndcg@10": v["ndcg@10"], "val_hr@10": v["hr@10"]} for k, v in best.items()}


# ----------------------------------------------------------------------------------------------------- test


def _fit_best(ctx: Ctx, name: str, params: dict, train, seed: int, features=None):
    kw = dict(params)
    m0 = models.make(name)
    if m0.stochastic:
        kw["seed"] = seed
    m = models.make(name, **kw)
    m.fit(train, item_features=(features if features is not None else ctx.F) if name in USES_FEATURES else None)
    return m


def test(ctx: Ctx) -> dict:
    tun = _load("tuning.json")
    if tun is None:
        raise SystemExit("run the tune stage first")
    s = ctx.split("test")
    CACHE.mkdir(parents=True, exist_ok=True)
    out = _load("test.json") or {"models": {}}
    best = {"MostPop": {"params": {}}, **{k: v for k, v in tun["best"].items() if k != "MostPop"}}
    variants = dict(best)
    if "LightFM WARP" in best:
        variants["LightFM WARP (chỉ id, không đặc trưng)"] = best["LightFM WARP"]
    for label, cfg in variants.items():
        name = "LightFM WARP" if label.startswith("LightFM WARP") else label
        if label in out["models"]:
            continue
        seeds = SEEDS if models.make(name).stochastic else (0,)
        per_seed, per_user = [], []
        tops = None
        t0 = time.time()
        for sd in seeds:
            feats = None
            if label != name:  # identity-only ablation
                import scipy.sparse as sp

                feats = sp.identity(ctx.d.n_items, dtype=np.float32, format="csr")
            m = _fit_best(ctx, name, cfg["params"], s.train, sd, feats)
            ev = _eval(m, s, return_top=(sd == seeds[0]))
            if tops is None:
                tops = ev["top"]
            per_seed.append(metrics.summarize(ev))
            per_user.append(np.stack([ev["ndcg"], ev["hr"], ev["recall"]]))
            log("test", label, sd, round(per_seed[-1]["ndcg@10"], 5))
            extra = {}
            if hasattr(m, "allowed"):
                extra["catalog_items"] = int(m.allowed.sum())
                tg = np.concatenate(list(s.targets.values()))
                extra["targets_in_catalog"] = float(m.allowed[tg].mean())
        pu = np.mean(per_user, axis=0)
        np.savez_compressed(CACHE / f"test_{_slug(label)}.npz", users=ev["users"], ndcg=pu[0], hr=pu[1], recall=pu[2], top=tops)
        agg = {
            key: {"mean": float(np.mean([p[key] for p in per_seed])), "sd": float(np.std([p[key] for p in per_seed], ddof=1)) if len(per_seed) > 1 else 0.0}
            for key in ("hr@10", "recall@10", "ndcg@10")
        }
        out["models"][label] = {
            "params": cfg["params"],
            "seeds": list(seeds),
            "per_seed": per_seed,
            **agg,
            "seconds": round(time.time() - t0, 1),
            **extra,
        }
        _dump("test.json", out)
    out["n_test_users"] = len(s.targets)
    out["n_test_positives"] = s.n_target_pos
    out["n_test_targets_kept"] = s.n_target_kept
    out["coverage_note"] = (
        "targets = test positives of users with ≥1 positive before d_test on items with ≥1 positive before d_test, "
        "not seen before; the rest are cold users/items"
    )
    out["comparisons"] = compare(out)
    _dump("test.json", out)
    _write_test_ids(ctx, s)
    return out


def _slug(label: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in label).strip("_").lower()


def compare(out: dict) -> dict:
    base = np.load(CACHE / "test_mostpop.npz")
    rows = {}
    for label in out["models"]:
        if label == "MostPop":
            continue
        z = np.load(CACHE / f"test_{_slug(label)}.npz")
        assert np.array_equal(z["users"], base["users"])
        rows[label] = {
            "ndcg@10": stats.paired_bootstrap(z["ndcg"], base["ndcg"], n_boot=5000, seed=1),
            "hr@10": stats.paired_bootstrap(z["hr"], base["hr"], n_boot=5000, seed=2),
        }
    for metric in ("ndcg@10", "hr@10"):
        labels = list(rows)
        adj = stats.holm([rows[x][metric]["p"] for x in labels])
        for x, a in zip(labels, adj, strict=True):
            rows[x][metric]["p_holm"] = float(a)
    # own BPR vs library BPR (implementation cross-check, not part of the Holm family)
    a, b = CACHE / "test_bpr_mf__numpy.npz", CACHE / "test_bpr__implicit.npz"
    cross = None
    if a.exists() and b.exists():
        za, zb = np.load(a), np.load(b)
        cross = stats.paired_bootstrap(za["ndcg"], zb["ndcg"], n_boot=5000, seed=3)
    return {"vs": "MostPop", "per_model": rows, "bpr_numpy_minus_implicit_ndcg@10": cross}


def _write_test_ids(ctx: Ctx, s: data.Split) -> None:
    import gzip

    with gzip.open(OUT / "test_targets.csv.gz", "wt", encoding="utf-8") as f:
        f.write("user_id,recipe_id\n")
        for u, items in sorted(s.targets.items()):
            for i in items:
                f.write(f"{ctx.d.users[u]},{ctx.d.items[i]}\n")


# ----------------------------------------------------------------------------------------------------- curve


def curve(ctx: Ctx, fracs=(0.25, 0.5, 0.75, 1.0), reps: int = 3) -> dict:
    tun = _load("tuning.json")
    s = ctx.split("test")
    out = _load("curve.json") or {"rows": []}
    have = {(r["model"], r["frac"], r["rep"]) for r in out["rows"]}
    users_all = np.flatnonzero(np.diff(s.train.indptr) > 0)
    names = ["MostPop", "ItemKNN", "EASE", "BPR-MF (NumPy)", "BPR (implicit)", "ALS (implicit)", "LightFM WARP"]
    for frac in fracs:
        for rep in range(reps):
            rng = np.random.default_rng(1000 + rep)
            keep = np.sort(rng.choice(users_all, size=int(round(frac * len(users_all))), replace=False))
            mask = np.zeros(s.train.shape[0], bool)
            mask[keep] = True
            import scipy.sparse as sp

            tr = sp.diags(mask.astype(np.float32)) @ s.train
            tr = tr.tocsr()
            tr.eliminate_zeros()
            tg = {u: v for u, v in s.targets.items() if mask[u]}
            sub = data.Split(tr, s.seen, tg, s.n_target_pos, sum(len(v) for v in tg.values()))
            for name in names:
                if (name, frac, rep) in have:
                    continue
                if name == "LightFM WARP" and rep > 0:
                    continue  # one sample only: LightFM is the slowest model
                params = {} if name == "MostPop" else tun["best"][name]["params"]
                m = _fit_best(ctx, name, params, tr, seed=rep)
                r = metrics.summarize(_eval(m, sub))
                out["rows"].append({"model": name, "frac": frac, "rep": rep, "n_train_users": int(mask.sum()), "train_positives": int(tr.nnz), **r})
                log("curve", name, frac, rep, round(r["ndcg@10"], 5))
                _dump("curve.json", out)
    return out


# ----------------------------------------------------------------------------------------------------- errors


def errors(ctx: Ctx) -> dict:
    s = ctx.split("test")
    res = _load("test.json")
    act = np.diff(s.train.indptr)
    pop = np.asarray(s.train.sum(axis=0)).ravel()
    order = np.argsort(-pop, kind="stable")
    pct = np.empty_like(pop, dtype=float)
    pct[order] = np.arange(len(pop)) / (len(pop) - 1)  # 0 = most popular
    head = pct <= 0.01  # top 1 % of items by training popularity
    bins = [(1, 4), (5, 9), (10, 19), (20, 49), (50, 99), (100, 10**9)]
    out = {"bins": [f"{a}-{b}" if b < 10**9 else f"≥{a}" for a, b in bins], "models": {}}
    for label in res["models"]:
        z = np.load(CACHE / f"test_{_slug(label)}.npz")
        a = act[z["users"]]
        per_bin = []
        for lo, hi in bins:
            m = (a >= lo) & (a <= hi)
            mean, lo_ci, hi_ci = stats.mean_ci(z["ndcg"][m], n_boot=1000) if m.sum() > 1 else (float("nan"),) * 3
            per_bin.append({"n_users": int(m.sum()), "ndcg@10": mean, "ci": [lo_ci, hi_ci], "hr@10": float(z["hr"][m].mean()) if m.any() else float("nan")})
        top = z["top"]
        out["models"][label] = {
            "by_activity": per_bin,
            "rec_head_share": float(head[top].mean()),  # share of recommended slots taken by the top-1 % items
            "rec_mean_pop_percentile": float(pct[top].mean()),
            "catalog_coverage@10": float(len(np.unique(top)) / len(pop)),
        }
    tg = np.concatenate(list(s.targets.values()))
    out["targets_head_share"] = float(head[tg].mean())
    out["users_per_bin"] = [int(((act[np.array(sorted(s.targets))] >= lo) & (act[np.array(sorted(s.targets))] <= hi)).sum()) for lo, hi in bins]
    _dump("errors.json", out)
    return out


# ----------------------------------------------------------------------------------------------------- cold


def cold(ctx: Ctx) -> dict:
    """Items with no positive before d_test. Candidates = all such items; users = warm users with a test positive
    on one of them. CF models cannot score these items; compared: Random, content cosine (user profile = mean of the
    feature rows of their training positives), LightFM WARP trained with features only (no identity column)."""
    tun = _load("tuning.json")
    s = ctx.split("test")
    cold_items = s.cold_items
    seen_none = s.seen  # the cold items have no positive before d_test; a rating-0/low rating can still be "seen"
    allowed = np.zeros(ctx.d.n_items, bool)
    allowed[cold_items] = True
    tg = s.cold_targets
    out = {"n_cold_items": int(len(cold_items)), "n_users": len(tg), "n_targets": int(sum(len(v) for v in tg.values())), "models": {}}
    F = ctx.F_only.tocsr()
    # content cosine
    import scipy.sparse as sp

    Fn = sp.diags(1.0 / np.maximum(np.sqrt(np.asarray(F.multiply(F).sum(axis=1)).ravel()), 1e-12)) @ F
    prof = s.train @ Fn
    prof = sp.diags(1.0 / np.maximum(np.sqrt(np.asarray(prof.multiply(prof).sum(axis=1)).ravel()), 1e-12)) @ prof
    prof = prof.tocsr()

    def content(users):
        return (prof[users] @ Fn.T).toarray()

    ev = metrics.topk_metrics(content, tg, seen_none, k=K, allowed=allowed)
    out["models"]["Content cosine (tags + ingredients)"] = {**metrics.summarize(ev), "seeds": [0]}
    per_user = {"content": ev["ndcg"]}
    rnd_runs, lfm_runs, lfm_users = [], [], []
    for sd in SEEDS:
        r = models.Random(seed=sd).fit(s.train)
        e = metrics.topk_metrics(r.scores, tg, seen_none, k=K, allowed=allowed)
        rnd_runs.append(metrics.summarize(e))
        params = dict(tun["best"]["LightFM WARP"]["params"])
        m = models.LightFMWarp(**params, seed=sd).fit(s.train, item_features=ctx.F_only)
        e2 = metrics.topk_metrics(m.scores, tg, seen_none, k=K, allowed=allowed)
        lfm_runs.append(metrics.summarize(e2))
        lfm_users.append(e2["ndcg"])
        log("cold", sd, rnd_runs[-1]["ndcg@10"], lfm_runs[-1]["ndcg@10"])
    for label, runs in (("Random", rnd_runs), ("LightFM WARP (chỉ đặc trưng)", lfm_runs)):
        out["models"][label] = {
            key: {"mean": float(np.mean([x[key] for x in runs])), "sd": float(np.std([x[key] for x in runs], ddof=1))}
            for key in ("hr@10", "recall@10", "ndcg@10")
        } | {"seeds": list(SEEDS)}
    lfm_mean = np.mean(lfm_users, axis=0)
    out["lightfm_minus_content_ndcg@10"] = stats.paired_bootstrap(lfm_mean, per_user["content"], n_boot=5000, seed=4)
    out["random_expected_hr@10_note"] = "Random ranks among the cold items only"
    _dump("cold.json", out)
    return out


# ----------------------------------------------------------------------------------------------------- manifest


def manifest(ctx: Ctx) -> dict:
    try:
        commit = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    except OSError:
        commit = ""
    libs = {p: metadata.version(p) for p in ("numpy", "scipy", "pandas", "implicit", "lightfm-next", "threadpoolctl")}
    m = {
        "commit_at_run": commit,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "threads": models.N_THREADS,
        "gpu": "none (CUDA_VISIBLE_DEVICES empty)",
        "seeds_test": list(SEEDS),
        "seed_tuning": 0,
        "dataset": ctx.d.stats,
        "item_features": {"n_features_excl_identity": int(ctx.F_only.shape[1]), "min_count": 20},
        "libraries": libs,
        "test_targets_file": "data/processed/recsys/test_targets.csv.gz",
    }
    _dump("manifest.json", m)
    return m


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("stages", nargs="*", default=["tune", "test", "curve", "errors", "cold", "figures"])
    ap.add_argument("--only", nargs="*", help="tune: restrict to these model names")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    if a.stages == ["figures"]:
        from tastoria_ml.recsys import figures

        figures.foodcom()
        return 0
    ctx = Ctx()
    manifest(ctx)
    for st in a.stages:
        if a.force and st != "figures":
            for f in {"tune": ["tuning.json"], "test": ["test.json"], "curve": ["curve.json"], "errors": ["errors.json"], "cold": ["cold.json"]}.get(st, []):
                (OUT / f).unlink(missing_ok=True)
        if st == "tune":
            tune(ctx, a.only)
        elif st == "test":
            test(ctx)
        elif st == "curve":
            curve(ctx)
        elif st == "errors":
            errors(ctx)
        elif st == "cold":
            cold(ctx)
        elif st == "figures":
            from tastoria_ml.recsys import figures

            figures.foodcom()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
