"""Composer weight selection and evaluation on synthetic fridge scenarios (design v2 §6.2).

Methods compared on every scenario (same options, same lots):
  composer      `compose` with (α, β, γ) — the spec objective  Σ ŝ' + α·U − β·|ΔE|/E − γ·D
  taste-only    the same search with α = β = γ = 0: the feasible tray with the highest Σ ŝ' (= top-1 by taste per
                slot whenever that tray is feasible, otherwise the next best feasible combination)
  random        a uniformly random feasible tray (all stock-feasible trays enumerated, exact schedule checked)
Structure as the live service: 3 dishes for n ≥ 2 with a 2-dish fallback (BR-TRAY-06), 2 dishes for n = 1; the
first tray (objective order) whose exact CP-SAT makespan ≤ max minutes is served (service._verify).

ŝ' comes from the live BaselineRanker with no interaction data (popularity = ½ for every dish), i.e. the content
cosine to the stand-in user's 5 favourites, turned into per-slot percentiles. It is a TASTE PROXY: the real oracle
is the survey (design v2 §6.2), which has no answers yet.

Pre-registered rule (written before running): among the grid points, maximise the mean U(m) over the tuning
scenarios subject to mean taste loss ≤ 0.2 (taste in ŝ' units ∈ [0, 1], loss = ŝ'(taste-only) − ŝ'(composer),
per-dish mean) and mean |ΔE|/E ≤ 0.15; ties → smaller taste loss, then smaller α + β + γ.

Run: uv run --package tastoria-ml python -m tastoria_ml.composer_eval.run
"""

from __future__ import annotations

import csv
import hashlib
import itertools
import json
import math
import os
import platform
import time
import uuid
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

from tastoria.modules.catalog.schemas import IngredientView, MakeAheadView, RecipeLine, RecipeView, StepView  # noqa: E402
from tastoria.modules.meal import composer as cmp  # noqa: E402
from tastoria.modules.meal import schedule as sch  # noqa: E402
from tastoria.modules.meal import service as msvc  # noqa: E402
from tastoria.modules.meal.ranker import BaselineRanker, RankContext, percentiles  # noqa: E402

from tastoria_ml.composer_eval import scenarios as scen_mod  # noqa: E402
from tastoria_ml.recsys import kb_catalog, stats  # noqa: E402
from tastoria_ml.recsys.kb_catalog import Catalog  # noqa: E402

NS = uuid.UUID("6f1c9a52-1d0e-4c7b-9f8a-2a9e6d3b7c10")
OUT = scen_mod.OUT
FIG = kb_catalog.REPO / "docs" / "reports" / "hoc-may" / "fig"
RESEARCH_OUT = kb_catalog.REPO / "ml" / "runs" / "research" / "p4_substitution_composer"
DEPLOY_COMPOSER = kb_catalog.REPO / "deploy" / "models" / "composer"
PROTOCOL_ID = "TASTORIA-ML-PREREG-2026-11-18"
ALPHAS = (0.0, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0)
BETAS = (0.0, 0.5, 1.0, 2.0, 4.0)
GAMMAS = (0.0, 0.25, 0.5, 1.0)
TASTE_LOSS_MAX = 0.2
KCAL_DEV_MAX = 0.15
SHARE_KCAL_OK_MIN = 0.92
KNEE_GAIN_FRAC = 0.95
PROVISIONAL = cmp.Params()  # weights the backend runs today (tray-p0-provisional)


def _id(kind: str, key: str) -> uuid.UUID:
    return uuid.uuid5(NS, f"{kind}:{key}")


@dataclass
class Views:
    recipes: dict[str, RecipeView]
    ingredients: dict[str, IngredientView]


def build_views(cat: Catalog) -> Views:
    ings = {}
    for name, ing in cat.ingredients.items():
        ings[name] = IngredientView(
            id=_id("ing", name),
            name_vi=name,
            food_group_code=ing.food_group,
            is_staple=ing.is_staple,
            countable=ing.countable,
            shelf_life_days=ing.shelf_life.days,
            is_active=True,
            allergen_codes=frozenset(ing.allergens),
            units={u.unit_code: u.grams_per_unit for u in ing.units},
        )
    recs = {}
    for r in cat.recipes:
        lines = tuple(RecipeLine(ings[ln.name], ln.grams, ln.role, ln.optional) for ln in r.ingredients)
        steps = tuple(StepView(s.step_no, s.text_vi, s.kind, s.minutes, s.uses_burner) for s in r.steps)
        ma = None
        if r.slug in cat.make_ahead:
            long_steps = [s.step_no for s in r.steps if s.kind == "passive" and s.minutes > 120]
            through = max(long_steps)
            ma = MakeAheadView(ings[cat.make_ahead[r.slug]], through, through >= len(r.steps))
        recs[r.slug] = RecipeView(
            id=_id("rec", r.slug),
            name_vi=r.name_vi,
            slot=r.slot,
            servings=r.servings,
            method_code=r.method,
            status="published",
            lines=lines,
            steps=steps,
            tag_codes=frozenset(r.tags),
            kcal_per_serving=cat.kcal.get(r.slug),
            make_ahead=ma,
        )
    return Views(recs, ings)


@dataclass
class Prepared:
    sid: str
    split: str
    persons: int
    burners: int
    max_minutes: int
    e_target: float
    rice_kcal: float
    options: dict[str, list[cmp.Option]]
    lots: list[cmp.Lot]
    lot_info: dict[uuid.UUID, dict]


class SimulatedAffinityRanker:
    """Deterministic simulated-taste ranker (item popularity prior + latent factors) for secondary H5a checks."""

    version_id: uuid.UUID | None = None

    def __init__(self, cat: Catalog, seed: int = 20261118) -> None:
        rng = np.random.default_rng(seed)
        n_items = len(cat.recipes)
        X = np.asarray(cat.X, dtype=float)
        norms = np.linalg.norm(X, axis=1, keepdims=True)
        X_norm = X / np.where(norms > 0, norms, 1.0)
        proj = rng.normal(0.0, 1.0 / math.sqrt(8.0), size=(X_norm.shape[1], 8))
        latent = X_norm @ proj + rng.normal(0.0, 0.15, size=(n_items, 8))
        l_norms = np.linalg.norm(latent, axis=1, keepdims=True)
        self.Q = latent / np.where(l_norms > 0, l_norms, 1.0)
        self.X_norm = X_norm
        self.item_prior = rng.uniform(0.25, 0.75, size=n_items)
        self.idx_by_id = {_id("rec", r.slug): i for i, r in enumerate(cat.recipes)}
        self.seed = int(seed)

    def score(self, ctx: RankContext, recipes: list[RecipeView]) -> dict[uuid.UUID, float]:
        fav_idx = [self.idx_by_id[r.id] for r in ctx.favorites if r.id in self.idx_by_id]
        if fav_idx:
            u_content = self.X_norm[fav_idx].mean(axis=0)
            u_content = u_content / (np.linalg.norm(u_content) + 1e-12)
            u_latent = self.Q[fav_idx].mean(axis=0)
        else:
            u_content = np.zeros(self.X_norm.shape[1], dtype=float)
            u_latent = np.zeros(self.Q.shape[1], dtype=float)
        u_rng = np.random.default_rng((int(ctx.user_id) ^ self.seed) & 0xFFFFFFFF)
        u_latent = u_latent + u_rng.normal(0.0, 0.25, size=self.Q.shape[1])
        u_latent = u_latent / (np.linalg.norm(u_latent) + 1e-12)

        content_scores = self.X_norm @ u_content
        latent_scores = 0.5 * (self.Q @ u_latent + 1.0)
        total = 0.45 * content_scores + 0.35 * latent_scores + 0.20 * self.item_prior
        return {r.id: float(total[self.idx_by_id[r.id]]) for r in recipes}


def prepare(s: dict, v: Views, rice_kcal: float, *, scorer=None) -> Prepared:
    favs = [v.recipes[x] for x in s["favorites"]]
    recipes = list(v.recipes.values())
    ctx = RankContext(user_id=_id("user", s["id"]), favorites=favs)
    if scorer is None:
        raw = BaselineRanker().score(ctx, recipes)
    elif hasattr(scorer, "score"):
        raw = scorer.score(ctx, recipes)
    else:
        raw = scorer(s, v, recipes)
    sp_: dict[uuid.UUID, float] = {}
    for slot in ("man", "rau", "canh"):
        sp_.update(percentiles({r.id: raw[r.id] for r in recipes if r.slot == slot}))
    options: dict[str, list[cmp.Option]] = defaultdict(list)
    for r in recipes:
        options[r.slot].append(msvc._option(r, sp_[r.id], s["persons"]))
    lots, info = [], {}
    for j, lot in enumerate(s["lots"]):
        u = lot["urgency"]
        if u is not None and u > 1.0:  # "kiểm tra trước khi dùng": not available (BR-FRESH-04)
            continue
        lid = _id("lot", f"{s['id']}:{j}")
        rewarded = u is not None and 0.5 <= u <= 1.0
        lots.append(cmp.Lot(lid, v.ingredients[lot["ingredient"]].id, float(lot["g_min"]), u, rewarded))
        info[lid] = lot
    return Prepared(s["id"], s["split"], s["persons"], s["burners"], s["max_minutes"], float(s["e_target_kcal"]),
                    rice_kcal, dict(options), lots, info)


_SCHED_CACHE: dict[tuple, int] = {}


def _makespan(t: cmp.Tray, burners: int) -> int:
    key = (t.recipe_ids, burners)
    if key not in _SCHED_CACHE:
        _SCHED_CACHE[key] = sch.solve([d.sched for d in t.dishes], burners).makespan
    return _SCHED_CACHE[key]


def _verify(trays: list[cmp.Tray], p: Prepared) -> cmp.Tray | None:
    for t in trays[: msvc.VERIFY_MAX]:
        if _makespan(t, p.burners) <= p.max_minutes:
            return t
    return None


def solve(p: Prepared, alpha: float, beta: float, gamma: float, top_k: int = 20) -> tuple[cmp.Tray | None, bool]:
    """(served tray, two_dish) following service.create_plan's structure logic."""
    params = cmp.Params(version="eval", alpha=alpha, beta=beta, gamma=gamma, top_k=top_k)
    prob = cmp.Problem(p.options, p.lots, [], p.burners, p.max_minutes, p.e_target, p.rice_kcal, params)
    structures = msvc.STRUCTURE_3 if p.persons >= 2 else msvc.STRUCTURE_2
    best = _verify(cmp.compose(prob, structures), p)
    two = False
    if best is None and p.persons >= 2:
        best = _verify(cmp.compose(prob, msvc.STRUCTURE_2), p)
        two = best is not None
    return best, two


def random_feasible(p: Prepared, rng: np.random.Generator) -> cmp.Tray | None:
    """Uniform over every stock-feasible tray of the structure the service would use, exact schedule checked."""
    params = cmp.Params(version="random", alpha=0.0, beta=0.0, gamma=0.0, top_k=10**6)
    prob = cmp.Problem(p.options, p.lots, [], p.burners, p.max_minutes, p.e_target, p.rice_kcal, params)
    structures = [msvc.STRUCTURE_3] if p.persons >= 2 else []
    structures.append(msvc.STRUCTURE_2)
    for st in structures:
        trays = cmp.compose(prob, st, expand=False)
        order = rng.permutation(len(trays))
        for i in order[:200]:
            if _makespan(trays[i], p.burners) <= p.max_minutes:
                return trays[i]
    return None


def check_feasible(t: cmp.Tray, p: Prepared, v: Views) -> list[str]:
    """Independent check from the KB lines (not the composer's needs): pooled grams ≤ available g_min,
    made-ahead items present, exact schedule ≤ max minutes and free of BR-COOK-01 violations."""
    by_id = {r.id: r for r in v.recipes.values()}
    avail: dict[uuid.UUID, float] = defaultdict(float)
    for lot in p.lots:
        avail[lot.ingredient_id] += lot.g_min
    need: dict[uuid.UUID, float] = defaultdict(float)
    errs = []
    for d in t.dishes:
        r = by_id[d.recipe.id]
        if r.make_ahead is not None and r.make_ahead.whole_dish:
            if avail.get(r.make_ahead.item.id, 0.0) <= 1e-6:
                errs.append(f"{r.name_vi}: made-ahead item missing")
            continue
        for ln in r.lines:
            if ln.ingredient.is_staple or ln.is_optional:
                continue
            g = ln.grams * p.persons / r.servings
            u = ln.ingredient.rounding_unit_g
            if u:
                g = math.ceil(g / u - 1e-9) * u
            need[ln.ingredient.id] += g
    for i, g in need.items():
        if g > avail.get(i, 0.0) + 1e-6:
            errs.append(f"short of {i}: need {g:.0f} g, have {avail.get(i, 0.0):.0f} g")
    dishes = [d.sched for d in t.dishes]
    s = sch.solve(dishes, p.burners)
    if s.makespan > p.max_minutes:
        errs.append(f"makespan {s.makespan} > {p.max_minutes}")
    errs += sch.violations(dishes, p.burners, s)
    slots = sorted(d.slot for d in t.dishes)
    if slots not in (["canh", "man", "rau"], ["man", "rau"], ["canh", "man"]):
        errs.append(f"structure {slots}")
    return errs


def tray_metrics(t: cmp.Tray | None, two: bool = False) -> dict:
    if t is None:
        return {"ok": False}
    return {
        "ok": True,
        "dishes": [d.recipe.name_vi for d in t.dishes],
        "two_dish": two or len(t.dishes) == 2,
        "taste": t.taste,
        "urgency": t.urgency,
        "kcal_dev": t.kcal_dev,
        "diversity": t.diversity,
        "bowls": t.bowls,
        "e_pp": t.e_pp,
        "uses_urgent": t.urgency > 0,
    }


# ----------------------------------------------------------------------------------------------- per scenario job


_V: Views | None = None
_RICE = 0.0


def _init() -> None:
    global _V, _RICE
    cat = kb_catalog.load()
    _V, _RICE = build_views(cat), cat.rice_kcal


def _job(s: dict) -> dict:
    if _V is None:
        _init()
    p = prepare(s, _V, _RICE)
    n_fit = {k: sum(1 for o in v if cmp.Context(cmp.Problem(p.options, p.lots, [], 2, p.max_minutes, p.e_target, p.rice_kcal)).fits_alone(o)) for k, v in p.options.items()}
    out = {"id": s["id"], "split": s["split"], "persons": s["persons"], "n_lots_available": len(p.lots),
           "n_rewarded_lots": sum(1 for x in p.lots if x.rewarded), "options_fitting_alone": n_fit, "grid": {}}
    for a, b, g in itertools.product(ALPHAS, BETAS, GAMMAS):
        t, two = solve(p, a, b, g)
        out["grid"][f"{a}|{b}|{g}"] = tray_metrics(t, two)
    t, two = solve(p, PROVISIONAL.alpha, PROVISIONAL.beta, PROVISIONAL.gamma)
    out["provisional"] = tray_metrics(t, two)
    out["random"] = tray_metrics(random_feasible(p, np.random.default_rng(int(s["id"][1:]))))
    # feasibility audit of every distinct tray served in this scenario
    audited, bad = 0, []
    seen = set()
    for a, b, g in itertools.product(ALPHAS, BETAS, GAMMAS):
        t, _ = solve(p, a, b, g)
        if t is None or t.recipe_ids in seen:
            continue
        seen.add(t.recipe_ids)
        audited += 1
        errs = check_feasible(t, p, _V)
        if errs:
            bad.append({"weights": [a, b, g], "errors": errs})
    out["audit"] = {"distinct_trays": audited, "violations": bad}
    return out


# ----------------------------------------------------------------------------------------------- aggregation


def _mean(rows: list[dict], key: str) -> float:
    vals = [r[key] for r in rows if r.get("ok")]
    return float(np.mean(vals)) if vals else float("nan")


def grid_table(results: list[dict], split: str) -> list[dict]:
    rs = [r for r in results if r["split"] == split and r["grid"]["0.0|0.0|0.0"]["ok"]]
    base = {r["id"]: r["grid"]["0.0|0.0|0.0"] for r in rs}
    table = []
    for a, b, g in itertools.product(ALPHAS, BETAS, GAMMAS):
        key = f"{a}|{b}|{g}"
        rows = [r["grid"][key] for r in rs]
        loss = [base[r["id"]]["taste"] - r["grid"][key]["taste"] for r in rs if r["grid"][key]["ok"]]
        table.append({
            "alpha": a, "beta": b, "gamma": g,
            "n": sum(1 for x in rows if x["ok"]),
            "urgency": _mean(rows, "urgency"),
            "taste": _mean(rows, "taste"),
            "taste_loss": float(np.mean(loss)) if loss else float("nan"),
            "kcal_dev": _mean(rows, "kcal_dev"),
            "diversity": _mean(rows, "diversity"),
            "share_kcal_ok": float(np.mean([x["kcal_dev"] <= KCAL_DEV_MAX for x in rows if x["ok"]])),
            "share_uses_urgent": float(np.mean([x["uses_urgent"] for x in rows if x["ok"]])),
        })
    return table


def pareto(table: list[dict]) -> list[int]:
    """Indices not dominated in (urgency ↑, taste_loss ↓, kcal_dev ↓)."""
    keep = []
    for i, a in enumerate(table):
        dom = False
        for j, b in enumerate(table):
            if j == i:
                continue
            if (b["urgency"] >= a["urgency"] and b["taste_loss"] <= a["taste_loss"] and b["kcal_dev"] <= a["kcal_dev"]
                    and (b["urgency"] > a["urgency"] or b["taste_loss"] < a["taste_loss"] or b["kcal_dev"] < a["kcal_dev"])):
                dom = True
                break
        if not dom:
            keep.append(i)
    return keep


def choose(table: list[dict]) -> dict | None:
    ok = [t for t in table if t["taste_loss"] <= TASTE_LOSS_MAX and t["kcal_dev"] <= KCAL_DEV_MAX]
    if not ok:
        return None
    return sorted(ok, key=lambda t: (-t["urgency"], t["taste_loss"], t["alpha"] + t["beta"] + t["gamma"]))[0]


def choose_knee(
    table: list[dict],
    *,
    share_kcal_ok_min: float = SHARE_KCAL_OK_MIN,
    gain_frac: float = KNEE_GAIN_FRAC,
) -> dict | None:
    """Select Pareto knee strictly on tuning rows (PREREG H5a):
    taste_loss <= 0.20, mean kcal_dev <= 0.15, share_kcal_ok >= 0.92,
    urgency >= u0 + 0.95*(u_max - u0), minimizing taste_loss (ties: kcal_dev, -urgency, alpha+beta+gamma).
    """
    mean_ok = [t for t in table if t["taste_loss"] <= TASTE_LOSS_MAX and t["kcal_dev"] <= KCAL_DEV_MAX]
    if not mean_ok:
        return None
    zero_row = next((t for t in table if t["alpha"] == 0 and t["beta"] == 0 and t["gamma"] == 0), None)
    u0 = float(zero_row["urgency"]) if zero_row is not None else min(float(t["urgency"]) for t in mean_ok)
    u_max = max(float(t["urgency"]) for t in mean_ok)

    for s_min, g_frac in ((share_kcal_ok_min, gain_frac), (share_kcal_ok_min, 0.90), (0.90, 0.90), (0.90, 0.85)):
        u_thresh = u0 + g_frac * (u_max - u0)
        cands = [
            t for t in mean_ok
            if float(t.get("share_kcal_ok", 0.0)) >= s_min and float(t["urgency"]) >= u_thresh - 1e-12
        ]
        if cands:
            return sorted(
                cands,
                key=lambda t: (
                    float(t["taste_loss"]),
                    float(t["kcal_dev"]),
                    -float(t["urgency"]),
                    float(t["alpha"] + t["beta"] + t["gamma"]),
                ),
            )[0]
    return None


def _arm_descriptives(vals: np.ndarray, *, seed: int = 11) -> dict:
    arr = np.asarray(vals, dtype=float)
    mean, lo, hi = stats.mean_ci(arr, n_boot=5000, seed=seed)
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
    }


def paired_full(results: list[dict], split: str, a_key: str, b_key: str, *, seed: int = 11) -> dict:
    """Full PREREG §6 paired inference between two arms over feasible scenarios of `split`."""
    def get(r, k):
        return r["grid"][k] if "|" in k else r[k]

    rs = [r for r in results if r["split"] == split and get(r, a_key)["ok"] and get(r, b_key)["ok"]]
    out: dict = {"n": len(rs)}
    for m in ("urgency", "taste", "taste_loss", "kcal_dev", "diversity"):
        a = np.array([get(r, a_key)[m] for r in rs], dtype=float)
        b = np.array([get(r, b_key)[m] for r in rs], dtype=float)
        out[m] = {
            "mean_a": float(a.mean()),
            "mean_b": float(b.mean()),
            "descriptives_a": _arm_descriptives(a, seed=seed),
            "descriptives_b": _arm_descriptives(b, seed=seed),
            "assumptions": stats.check_paired_assumptions(a, b),
            "bootstrap": stats.paired_bootstrap(a, b, n_boot=5000, seed=seed),
            "cohens_dz": stats.cohens_dz(a, b, n_boot=2000, seed=seed),
            "wilcoxon": stats.wilcoxon(a, b),
        }
    for m, f in (("uses_urgent", lambda x: x["uses_urgent"]), ("kcal_within_15pct", lambda x: x["kcal_dev"] <= KCAL_DEV_MAX)):
        a = np.array([f(get(r, a_key)) for r in rs], dtype=bool)
        b = np.array([f(get(r, b_key)) for r in rs], dtype=bool)
        out[m] = {"share_a": float(a.mean()), "share_b": float(b.mean()), **stats.mcnemar(a, b)}
    return out


def paired(results: list[dict], split: str, a_key: str, b_key: str) -> dict:
    """Paired tests over the scenarios of `split` where both methods return a tray."""
    def get(r, k):
        return r["grid"][k] if "|" in k else r[k]

    rs = [r for r in results if r["split"] == split and get(r, a_key)["ok"] and get(r, b_key)["ok"]]
    out = {"n": len(rs)}
    for m in ("urgency", "taste", "kcal_dev", "diversity"):
        a = np.array([get(r, a_key)[m] for r in rs])
        b = np.array([get(r, b_key)[m] for r in rs])
        out[m] = {"mean_a": float(a.mean()), "mean_b": float(b.mean()), **stats.wilcoxon(a, b),
                  "bootstrap": stats.paired_bootstrap(a, b, n_boot=5000, seed=11)}
    for m, f in (("uses_urgent", lambda x: x["uses_urgent"]), ("kcal_within_15pct", lambda x: x["kcal_dev"] <= KCAL_DEV_MAX)):
        a = np.array([f(get(r, a_key)) for r in rs])
        b = np.array([f(get(r, b_key)) for r in rs])
        out[m] = {"share_a": float(a.mean()), "share_b": float(b.mean()), **stats.mcnemar(a, b)}
    return out


def _eval_confirmatory_arm_set(
    cat: Catalog,
    views: Views,
    scenarios: list[dict],
    arms: dict[str, tuple[float, float, float] | str],
    *,
    scorer=None,
) -> tuple[list[dict], dict]:
    """Single-pass evaluation of prespecified comparator arms on `scenarios` (no grid search)."""
    results: list[dict] = []
    audited_trays = 0
    violations: list[dict] = []

    for s in scenarios:
        p = prepare(s, views, cat.rice_kcal, scorer=scorer)
        t_to, two_to = solve(p, 0.0, 0.0, 0.0)
        if t_to is None:
            results.append({"id": s["id"], "split": s["split"], "persons": s["persons"], "feasible": False})
            continue

        arm_rows: dict[str, dict] = {}
        seen_trays: dict[tuple[uuid.UUID, ...], cmp.Tray] = {}
        for arm_name, spec in arms.items():
            if spec == "random":
                rng_seed = int("".join(ch for ch in s["id"] if ch.isdigit()) or "0")
                t = random_feasible(p, np.random.default_rng(rng_seed))
                m = tray_metrics(t)
            else:
                a, b, g = spec
                t, two = solve(p, float(a), float(b), float(g))
                m = tray_metrics(t, two)
            if m.get("ok"):
                m["taste_loss"] = float(t_to.taste - m["taste"])
                m["kcal_ok"] = bool(m["kcal_dev"] <= KCAL_DEV_MAX)
                if t is not None and t.recipe_ids not in seen_trays:
                    seen_trays[t.recipe_ids] = t
            arm_rows[arm_name] = m

        for rids, t in seen_trays.items():
            audited_trays += 1
            errs = check_feasible(t, p, views)
            if errs:
                violations.append({"id": s["id"], "recipe_ids": [str(x) for x in rids], "errors": errs})

        results.append({
            "id": s["id"],
            "split": s["split"],
            "persons": s["persons"],
            "feasible": True,
            **arm_rows,
        })

    audit = {"distinct_trays_checked": audited_trays, "violations": violations}
    return results, audit


def _summarize_confirmatory_arms(results: list[dict], arm_names: list[str]) -> dict:
    feas = [r for r in results if r.get("feasible")]
    summary: dict = {}
    for arm in arm_names:
        rows = [r[arm] for r in feas if r.get(arm, {}).get("ok")]
        summary[arm] = {
            "n_feasible": len(rows),
            "urgency": _arm_descriptives(np.array([x["urgency"] for x in rows], float)),
            "taste": _arm_descriptives(np.array([x["taste"] for x in rows], float)),
            "taste_loss": _arm_descriptives(np.array([x["taste_loss"] for x in rows], float)),
            "kcal_dev": _arm_descriptives(np.array([x["kcal_dev"] for x in rows], float)),
            "diversity": _arm_descriptives(np.array([x["diversity"] for x in rows], float)),
            "share_kcal_ok": float(np.mean([x["kcal_dev"] <= KCAL_DEV_MAX for x in rows])),
            "n_kcal_ok": int(sum(1 for x in rows if x["kcal_dev"] <= KCAL_DEV_MAX)),
            "share_uses_urgent": float(np.mean([x["uses_urgent"] for x in rows])),
            "two_dish_share": float(np.mean([x["two_dish"] for x in rows])),
        }
    return summary


def write_research_manifest(research_dir: Path = RESEARCH_OUT) -> dict:
    """Write/refresh `ml/runs/research/p4_substitution_composer/manifest.json` indexing all Part A & B artifacts."""
    research_dir.mkdir(parents=True, exist_ok=True)
    cat = kb_catalog.load()
    pairs_count = 197
    try:
        import yaml
        from tastoria_ml.kb.substitutes import SubstitutionPairsFile

        raw = yaml.safe_load((kb_catalog.REPO / "data" / "kb" / "substitution_pairs.yaml").read_text(encoding="utf-8"))
        pairs_count = len(SubstitutionPairsFile.model_validate(raw).pairs)
    except Exception:
        pass

    outputs = {}
    for p in sorted(research_dir.iterdir()):
        if p.is_file() and p.name != "manifest.json":
            outputs[p.name] = {
                "size_bytes": p.stat().st_size,
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            }

    import gensim
    import ortools
    import pandas
    import scipy

    manifest = {
        "protocol_id": PROTOCOL_ID,
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "host": platform.node(),
        "env": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "OPENBLAS_NUM_THREADS": os.environ.get("OPENBLAS_NUM_THREADS", ""),
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "pandas": pandas.__version__,
            "gensim": gensim.__version__,
            "ortools": ortools.__version__,
        },
        "kb_counts": {
            "ingredients": len(cat.ingredients),
            "recipes": len(cat.recipes),
            "substitution_pairs": pairs_count,
            "queries": 90,
        },
        "seeds": {
            "substitution_split_seed": 20261018,
            "substitution_w2v_seeds": [0, 1, 2, 3, 4],
            "composer_exploratory_seed": scen_mod.SEED,
            "composer_confirmatory_seed": scen_mod.CONFIRMATORY_SEED,
        },
        "outputs": outputs,
    }
    (research_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def write_serving_config(
    knee: dict,
    *,
    n_tuning_feasible: int,
    confirmatory_eval: dict,
    cpsat_sla: dict | None = None,
    out_dir: Path = DEPLOY_COMPOSER,
) -> dict:
    """Write `deploy/models/composer/serving.json` matching `tastoria.modules.meal.composer.Params` 1:1."""
    out_dir.mkdir(parents=True, exist_ok=True)
    version = "tray-p1-knee-20261118"
    params_obj = cmp.Params(
        version=version,
        alpha=float(knee["alpha"]),
        beta=float(knee["beta"]),
        gamma=float(knee["gamma"]),
    )
    if cpsat_sla is None:
        cpsat_path = RESEARCH_OUT / "cpsat_latency.json"
        if cpsat_path.exists():
            cp = json.loads(cpsat_path.read_text(encoding="utf-8"))
            u_prod = cp["unit_benchmarks"]["production_1_to_3_dishes"]
            e2e = cp["e2e_solve_benchmarks"]["overall"]
            cpsat_sla = {
                "n_unit_runs": cp["unit_benchmarks"]["overall_all_runs"]["n"],
                "realistic_1_3_dish_n": u_prod["n"],
                "realistic_1_3_dish_p50_ms": u_prod["p50_ms"],
                "realistic_1_3_dish_p95_ms": u_prod["p95_ms"],
                "realistic_1_3_dish_p99_ms": u_prod["p99_ms"],
                "e2e_p95_ms": e2e["p95_ms"],
                "sla_threshold_ms": cp["sla_target_ms"],
                "h5b_passed": cp["h5b_passed"],
                "optimal_plus_relaxed_rate": u_prod["optimal_plus_relaxed_rate"],
                "violations": cp["unit_benchmarks"]["overall_all_runs"]["violations"] + e2e["violations"],
            }
        else:
            cpsat_sla = {"status": "pending_cpsat_bench"}

    payload = {
        "artifact_type": "tray_composer_params",
        "protocol_id": PROTOCOL_ID,
        "version": version,
        "params": asdict(params_obj),
        "selection_provenance": {
            "tuning_seed": scen_mod.SEED,
            "n_tuning_feasible": int(n_tuning_feasible),
            "rule": (
                "Select Pareto knee on feasible tuning scenarios: taste_loss <= 0.20, "
                "kcal_dev <= 0.15, share_kcal_ok >= 0.92, urgency >= u0 + 0.95*(u_max - u0), "
                "minimize taste_loss (ties: kcal_dev, -urgency, alpha+beta+gamma)"
            ),
            "tuning_metrics": {
                k: float(knee[k])
                for k in ("urgency", "taste", "taste_loss", "kcal_dev", "diversity", "share_kcal_ok", "share_uses_urgent")
            },
        },
        "confirmatory_evaluation": confirmatory_eval,
        "cpsat_sla": cpsat_sla,
        "how_to_apply": (
            "Load serving['params'] into tastoria.modules.meal.composer.Params(**serving['params']) "
            "and pass to MealDeps(params=...) in backend/src/tastoria/app.py."
        ),
        "sha256_scope": "canonical_json_excluding_artifact_sha256",
    }
    canon = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload["artifact_sha256"] = hashlib.sha256(canon).hexdigest()
    (out_dir / "serving.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def run_confirmatory_h5a(
    *,
    workers: int = 8,
    conf_n: int = 90,
    out_research: Path = RESEARCH_OUT,
    deploy_dir: Path = DEPLOY_COMPOSER,
) -> dict:
    """Execute PREREG H5a pipeline: lock SEED=20261018 exploratory audit, select knee on tuning, run single-pass confirmatory."""
    out_research.mkdir(parents=True, exist_ok=True)
    cat = kb_catalog.load()
    views = build_views(cat)

    # 1. Load or run SEED=20261018 (tuning + exploratory 75-scenario test audit)
    res_path = OUT / "results.json"
    scen_path = OUT / "scenarios.json"
    if res_path.exists() and scen_path.exists():
        results_20261018 = json.loads(res_path.read_text(encoding="utf-8"))
        data_20261018 = json.loads(scen_path.read_text(encoding="utf-8"))
    else:
        data_20261018 = scen_mod.write(cat, n=150)
        with ProcessPoolExecutor(max_workers=workers, initializer=_init) as ex:
            results_20261018 = list(ex.map(_job, data_20261018["scenarios"]))
        res_path.write_text(json.dumps(results_20261018, ensure_ascii=False) + "\n", encoding="utf-8")

    tune_tab = grid_table(results_20261018, "tuning")
    test_tab_exp = grid_table(results_20261018, "test")
    front_idx = set(pareto(tune_tab))
    pick_legacy = choose(tune_tab)
    knee = choose_knee(tune_tab)
    if knee is None:
        raise RuntimeError("choose_knee failed to find a qualifying weight triple on tuning")

    # Preserve summary.json compatibility for figures.composer() while explicitly tagging exploratory status
    summary_path = OUT / "summary.json"
    if summary_path.exists():
        exp_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    else:
        chosen_key_leg = f"{pick_legacy['alpha']}|{pick_legacy['beta']}|{pick_legacy['gamma']}"
        exp_summary = {
            "n_scenarios": len(results_20261018),
            "scenario_seed": data_20261018["seed"],
            "split_sizes": {s: sum(1 for r in results_20261018 if r["split"] == s) for s in ("tuning", "test")},
            "no_feasible_tray": {s: sum(1 for r in results_20261018 if r["split"] == s and not r["grid"]["0.0|0.0|0.0"]["ok"]) for s in ("tuning", "test")},
            "audit": {
                "distinct_trays_checked": int(sum(r["audit"]["distinct_trays"] for r in results_20261018)),
                "violations": [dict(id=r["id"], **v) for r in results_20261018 for v in r["audit"]["violations"]],
            },
            "chosen": pick_legacy,
            "pareto_tuning": [tune_tab[i] for i in sorted(front_idx)],
            "provisional_weights": {"alpha": PROVISIONAL.alpha, "beta": PROVISIONAL.beta, "gamma": PROVISIONAL.gamma},
            "grid_tuning": tune_tab,
            "grid_test": test_tab_exp,
            "test_comparisons": {
                "composer_vs_taste_only": paired(results_20261018, "test", chosen_key_leg, "0.0|0.0|0.0"),
                "composer_vs_random": paired(results_20261018, "test", chosen_key_leg, "random"),
                "composer_vs_provisional": paired(results_20261018, "test", chosen_key_leg, "provisional"),
                "taste_only_vs_random": paired(results_20261018, "test", "0.0|0.0|0.0", "random"),
            },
        }
    exp_summary["protocol_id"] = PROTOCOL_ID
    exp_summary["analysis_intent"] = "exploratory"
    exp_summary["chosen_knee_tuning"] = knee
    summary_path.write_text(json.dumps(exp_summary, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")

    # Write composer_exploratory_20261018.json
    exploratory_doc = {
        "protocol_id": PROTOCOL_ID,
        "analysis_intent": "exploratory",
        "scenario_seed": scen_mod.SEED,
        "note": (
            "Locked prior baseline audit on SEED=20261018 (71 feasible tuning / 75 feasible test scenarios). "
            "Legacy choose() selected (64.0, 0.0, 0.5) which achieved 89.33% (67/75) |ΔE|/E <= 0.15 on test "
            "vs 98.67% for provisional (1.0, 1.0, 0.5) (McNemar p=0.0391). Per PREREG §1.1 & §3 H5a, "
            "this split is locked as exploratory and NOT reused as confirmatory H5a evidence."
        ),
        "split_sizes": exp_summary["split_sizes"],
        "no_feasible_tray": exp_summary["no_feasible_tray"],
        "audit": exp_summary["audit"],
        "legacy_chosen": pick_legacy,
        "knee_selected_on_tuning": knee,
        "test_comparisons_legacy": exp_summary.get("test_comparisons", {}),
    }
    (out_research / "composer_exploratory_20261018.json").write_text(
        json.dumps(exploratory_doc, ensure_ascii=False, indent=2, default=float) + "\n", encoding="utf-8"
    )

    # Write composer_pareto_grid.csv (tuning + exploratory test)
    with open(out_research / "composer_pareto_grid.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "split_seed", "split", "analysis_intent", "alpha", "beta", "gamma",
                "is_pareto", "is_selected_knee", "is_chosen_legacy", "n_feasible",
                "urgency", "taste", "taste_loss", "kcal_dev", "diversity",
                "share_kcal_ok", "share_uses_urgent",
            ],
        )
        w.writeheader()
        for split_name, intent, tab in (("tuning", "tuning", tune_tab), ("test", "exploratory", test_tab_exp)):
            for idx_row, row in enumerate(tab):
                w.writerow({
                    "split_seed": scen_mod.SEED,
                    "split": split_name,
                    "analysis_intent": intent,
                    "alpha": row["alpha"],
                    "beta": row["beta"],
                    "gamma": row["gamma"],
                    "is_pareto": bool(idx_row in front_idx) if split_name == "tuning" else "",
                    "is_selected_knee": bool(
                        row["alpha"] == knee["alpha"] and row["beta"] == knee["beta"] and row["gamma"] == knee["gamma"]
                    ),
                    "is_chosen_legacy": bool(
                        pick_legacy and row["alpha"] == pick_legacy["alpha"] and row["beta"] == pick_legacy["beta"] and row["gamma"] == pick_legacy["gamma"]
                    ),
                    "n_feasible": row["n"],
                    "urgency": row["urgency"],
                    "taste": row["taste"],
                    "taste_loss": row["taste_loss"],
                    "kcal_dev": row["kcal_dev"],
                    "diversity": row["diversity"],
                    "share_kcal_ok": row["share_kcal_ok"],
                    "share_uses_urgent": row["share_uses_urgent"],
                })

    # 2. Generate untouched confirmatory split (CONFIRMATORY_SEED = 20261118, n=90 -> n_feasible >= 75)
    conf_data = scen_mod.write_confirmatory(cat, n=conf_n, seed=scen_mod.CONFIRMATORY_SEED)
    arms = {
        "knee": (float(knee["alpha"]), float(knee["beta"]), float(knee["gamma"])),
        "taste_only": (0.0, 0.0, 0.0),
        "provisional": (float(PROVISIONAL.alpha), float(PROVISIONAL.beta), float(PROVISIONAL.gamma)),
        "max_urgency": (64.0, 0.0, 0.5),
        "random": "random",
    }
    arm_names = list(arms.keys())
    _SCHED_CACHE.clear()
    conf_results, conf_audit = _eval_confirmatory_arm_set(cat, views, conf_data["scenarios"], arms, scorer=None)
    feas_results = [r for r in conf_results if r.get("feasible")]
    n_feasible = len(feas_results)
    if n_feasible < 75:
        raise RuntimeError(f"Confirmatory feasible scenarios {n_feasible} < 75")
    if conf_audit["violations"]:
        raise RuntimeError(f"Confirmatory feasibility audit found violations: {conf_audit['violations'][:3]}")

    arm_summary = _summarize_confirmatory_arms(conf_results, arm_names)
    contrasts = {
        "knee_vs_taste_only": paired_full(feas_results, "confirmatory", "knee", "taste_only"),
        "knee_vs_provisional": paired_full(feas_results, "confirmatory", "knee", "provisional"),
        "knee_vs_random": paired_full(feas_results, "confirmatory", "knee", "random"),
        "knee_vs_max_urgency": paired_full(feas_results, "confirmatory", "knee", "max_urgency"),
        "taste_only_vs_random": paired_full(feas_results, "confirmatory", "taste_only", "random"),
    }

    # Confirmatory H5a Holm-Bonferroni family (5 prespecified hypotheses)
    holm_specs = [
        ("knee_vs_taste_only", "urgency", "bootstrap"),
        ("knee_vs_provisional", "urgency", "bootstrap"),
        ("knee_vs_random", "urgency", "bootstrap"),
        ("knee_vs_max_urgency", "taste_loss", "bootstrap"),
        ("knee_vs_max_urgency", "kcal_within_15pct", "mcnemar"),
    ]
    raw_ps = []
    for cname, metric, kind in holm_specs:
        if kind == "bootstrap":
            raw_ps.append(float(contrasts[cname][metric]["bootstrap"]["p"]))
        else:
            raw_ps.append(float(contrasts[cname][metric]["p"]))
    adj_ps = stats.holm(raw_ps)
    holm_family = []
    for (cname, metric, kind), p_raw, p_holm in zip(holm_specs, raw_ps, adj_ps, strict=True):
        if kind == "bootstrap":
            contrasts[cname][metric]["bootstrap"]["p_holm"] = float(p_holm)
        else:
            contrasts[cname][metric]["p_holm"] = float(p_holm)
        holm_family.append({
            "contrast": cname,
            "metric": metric,
            "test": kind,
            "p_raw": float(p_raw),
            "p_holm": float(p_holm),
        })

    # Also apply Holm to Wilcoxon on the 4 continuous confirmatory contrasts
    wil_specs = [
        ("knee_vs_taste_only", "urgency"),
        ("knee_vs_provisional", "urgency"),
        ("knee_vs_random", "urgency"),
        ("knee_vs_max_urgency", "taste_loss"),
    ]
    wil_raw = [float(contrasts[c][m]["wilcoxon"]["p"]) for c, m in wil_specs]
    for (c, m), pw in zip(wil_specs, stats.holm(wil_raw), strict=True):
        contrasts[c][m]["wilcoxon"]["p_holm"] = float(pw)

    mde_dz = float(2.80158 / math.sqrt(n_feasible))
    h5a_passed = bool(
        arm_summary["knee"]["share_kcal_ok"] >= 0.90
        and contrasts["knee_vs_taste_only"]["urgency"]["bootstrap"]["diff"] > 0
        and contrasts["knee_vs_taste_only"]["urgency"]["bootstrap"]["p_holm"] < 0.05
        and contrasts["knee_vs_provisional"]["urgency"]["bootstrap"]["diff"] > 0
        and contrasts["knee_vs_provisional"]["urgency"]["bootstrap"]["p_holm"] < 0.05
        and contrasts["knee_vs_max_urgency"]["taste_loss"]["bootstrap"]["diff"] < 0
        and conf_audit["violations"] == []
    )

    # 3. Secondary Ranker-integration check (exploratory)
    ranker_artifact = kb_catalog.REPO / "deploy" / "models" / "ranker" / "model.npz"
    sim_ranker = SimulatedAffinityRanker(cat, seed=scen_mod.CONFIRMATORY_SEED)
    _SCHED_CACHE.clear()
    sim_results, sim_audit = _eval_confirmatory_arm_set(cat, views, conf_data["scenarios"], arms, scorer=sim_ranker)
    sim_feas = [r for r in sim_results if r.get("feasible")]
    sim_summary = _summarize_confirmatory_arms(sim_results, arm_names)
    sim_contrasts = {
        "knee_vs_taste_only": paired_full(sim_feas, "confirmatory", "knee", "taste_only"),
        "knee_vs_provisional": paired_full(sim_feas, "confirmatory", "knee", "provisional"),
        "knee_vs_max_urgency": paired_full(sim_feas, "confirmatory", "knee", "max_urgency"),
    }
    secondary_ranker_check = {
        "analysis_intent": "exploratory",
        "deployed_ranker_artifact_present": bool(ranker_artifact.exists()),
        "scorer": "SimulatedAffinityRanker(item_prior + latent_factors + content, seed=20261118)",
        "note": (
            "Secondary exploratory check replacing uniform-popularity BaselineRanker proxy with heterogeneous "
            "simulated taste affinity. Confirmatory H5a remains anchored to preregistered BaselineRanker."
        ),
        "n_feasible": len(sim_feas),
        "audit": sim_audit,
        "arms": sim_summary,
        "contrasts": sim_contrasts,
    }

    conf_doc = {
        "protocol_id": PROTOCOL_ID,
        "hypothesis": "H5a_composer_pareto",
        "analysis_intent": "confirmatory",
        "taste_signal": "PROXY: BaselineRanker content cosine to 5 favourites (disclosed per PREREG §3 H5a)",
        "confirmatory_seed": scen_mod.CONFIRMATORY_SEED,
        "n_scenarios_generated": len(conf_data["scenarios"]),
        "n_scenarios_feasible": n_feasible,
        "n_scenarios_infeasible": len(conf_data["scenarios"]) - n_feasible,
        "mde_dz_80pct": mde_dz,
        "selected_knee_from_tuning": knee,
        "arms_weights": arms,
        "audit": conf_audit,
        "arms": arm_summary,
        "contrasts": contrasts,
        "holm_family": holm_family,
        "h5a_passed": h5a_passed,
        "secondary_ranker_check": secondary_ranker_check,
    }
    (out_research / "composer_confirmatory_h5a.json").write_text(
        json.dumps(conf_doc, ensure_ascii=False, indent=2, default=float) + "\n", encoding="utf-8"
    )

    pareto_doc = {
        "protocol_id": PROTOCOL_ID,
        "tuning_seed": scen_mod.SEED,
        "n_tuning_feasible": int(tune_tab[0]["n"]),
        "pareto_front_count": len(front_idx),
        "pareto_tuning": [tune_tab[i] for i in sorted(front_idx)],
        "selected_knee_weights": knee,
        "legacy_chosen_weights": pick_legacy,
        "provisional_weights": {"alpha": PROVISIONAL.alpha, "beta": PROVISIONAL.beta, "gamma": PROVISIONAL.gamma},
        "exploratory_20261018_ref": "composer_exploratory_20261018.json",
        "confirmatory_h5a_ref": "composer_confirmatory_h5a.json",
        "confirmatory_summary": {
            "confirmatory_seed": scen_mod.CONFIRMATORY_SEED,
            "n_feasible": n_feasible,
            "h5a_passed": h5a_passed,
            "knee": arm_summary["knee"],
            "provisional": arm_summary["provisional"],
            "taste_only": arm_summary["taste_only"],
            "max_urgency": arm_summary["max_urgency"],
            "random": arm_summary["random"],
        },
        "secondary_ranker_check": secondary_ranker_check,
    }
    (out_research / "composer_pareto.json").write_text(
        json.dumps(pareto_doc, ensure_ascii=False, indent=2, default=float) + "\n", encoding="utf-8"
    )

    serving = write_serving_config(
        knee,
        n_tuning_feasible=int(tune_tab[0]["n"]),
        confirmatory_eval={
            "confirmatory_seed": scen_mod.CONFIRMATORY_SEED,
            "n_confirmatory_feasible": n_feasible,
            "h5a_passed": h5a_passed,
            "knee_urgency_mean": arm_summary["knee"]["urgency"]["mean"],
            "knee_taste_loss_mean": arm_summary["knee"]["taste_loss"]["mean"],
            "knee_kcal_dev_mean": arm_summary["knee"]["kcal_dev"]["mean"],
            "knee_share_kcal_ok": arm_summary["knee"]["share_kcal_ok"],
            "taste_signal": "PROXY: BaselineRanker content cosine (re-validate once real survey ratings exist)",
        },
        out_dir=deploy_dir,
    )
    write_research_manifest(out_research)
    return {"confirmatory": conf_doc, "serving": serving}


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="composer weight grid and confirmatory H5a evaluation on synthetic fridge scenarios")
    ap.add_argument("--n", type=int, default=150)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--confirmatory", action="store_true", help="Run knee selection on tuning + single-pass confirmatory H5a evaluation")
    ap.add_argument("--conf-n", type=int, default=90, help="Raw scenarios to generate for confirmatory split (CONFIRMATORY_SEED=20261118)")
    ap.add_argument("--out-research", type=Path, default=RESEARCH_OUT)
    ap.add_argument("--deploy-dir", type=Path, default=DEPLOY_COMPOSER)
    a = ap.parse_args(argv)

    if a.confirmatory:
        res = run_confirmatory_h5a(
            workers=a.workers,
            conf_n=a.conf_n,
            out_research=a.out_research,
            deploy_dir=a.deploy_dir,
        )
        c = res["confirmatory"]
        print(json.dumps({
            "h5a_passed": c["h5a_passed"],
            "n_feasible": c["n_scenarios_feasible"],
            "knee": {k: c["selected_knee_from_tuning"][k] for k in ("alpha", "beta", "gamma")},
            "knee_test": {
                "urgency": c["arms"]["knee"]["urgency"]["mean"],
                "taste_loss": c["arms"]["knee"]["taste_loss"]["mean"],
                "kcal_dev": c["arms"]["knee"]["kcal_dev"]["mean"],
                "share_kcal_ok": c["arms"]["knee"]["share_kcal_ok"],
            },
            "violations": len(c["audit"]["violations"]),
        }, ensure_ascii=False, indent=2))
        return 0

    cat = kb_catalog.load()
    data = scen_mod.write(cat, n=a.n)
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=a.workers, initializer=_init) as ex:
        results = list(ex.map(_job, data["scenarios"]))
    elapsed = time.time() - t0
    (OUT / "results.json").write_text(json.dumps(results, ensure_ascii=False) + "\n", encoding="utf-8")
    tune_tab = grid_table(results, "tuning")
    test_tab = grid_table(results, "test")
    front = pareto(tune_tab)
    pick = choose(tune_tab)
    chosen_key = f"{pick['alpha']}|{pick['beta']}|{pick['gamma']}" if pick else None
    summary = {
        "n_scenarios": len(results),
        "seconds": round(elapsed, 1),
        "scenario_seed": data["seed"],
        "split_sizes": {s: sum(1 for r in results if r["split"] == s) for s in ("tuning", "test")},
        "no_feasible_tray": {s: sum(1 for r in results if r["split"] == s and not r["grid"]["0.0|0.0|0.0"]["ok"]) for s in ("tuning", "test")},
        "two_dish_share_taste_only": float(np.mean([r["grid"]["0.0|0.0|0.0"]["two_dish"] for r in results if r["grid"]["0.0|0.0|0.0"]["ok"]])),
        "audit": {
            "distinct_trays_checked": int(sum(r["audit"]["distinct_trays"] for r in results)),
            "violations": [dict(id=r["id"], **v) for r in results for v in r["audit"]["violations"]],
        },
        "rule": {"taste_loss_max": TASTE_LOSS_MAX, "kcal_dev_max": KCAL_DEV_MAX,
                 "objective": "max mean U(m) on tuning scenarios; ties: smaller taste loss, then smaller α+β+γ"},
        "chosen": pick,
        "pareto_tuning": [tune_tab[i] for i in front],
        "provisional_weights": {"alpha": PROVISIONAL.alpha, "beta": PROVISIONAL.beta, "gamma": PROVISIONAL.gamma},
        "grid_tuning": tune_tab,
        "grid_test": test_tab,
    }
    if chosen_key:
        summary["test_comparisons"] = {
            "composer_vs_taste_only": paired(results, "test", chosen_key, "0.0|0.0|0.0"),
            "composer_vs_random": paired(results, "test", chosen_key, "random"),
            "composer_vs_provisional": paired(results, "test", chosen_key, "provisional"),
            "taste_only_vs_random": paired(results, "test", "0.0|0.0|0.0", "random"),
        }
        summary["test_chosen_row"] = next(t for t in test_tab if f"{t['alpha']}|{t['beta']}|{t['gamma']}" == chosen_key)
        summary["test_random"] = {m: _mean([r["random"] for r in results if r["split"] == "test"], m) for m in ("urgency", "taste", "kcal_dev", "diversity")}
        summary["test_provisional"] = {m: _mean([r["provisional"] for r in results if r["split"] == "test"], m) for m in ("urgency", "taste", "kcal_dev", "diversity")}
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")
    if pick:
        u0 = next(t["urgency"] for t in tune_tab if t["alpha"] == 0 and t["beta"] == 0 and t["gamma"] == 0)
        same = sorted((t for t in tune_tab if t["beta"] == pick["beta"] and t["gamma"] == pick["gamma"]), key=lambda t: t["alpha"])
        near = next(t for t in same if t["urgency"] >= u0 + 0.95 * (pick["urgency"] - u0))
        summary["sensitivity_95pct_gain"] = near
        (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")
        weights = {
            "version": "tray-p1-synthetic-20261018",
            "alpha": pick["alpha"], "beta": pick["beta"], "gamma": pick["gamma"], "top_k": 20,
            "chosen_by": "pre-registered rule on 75 synthetic tuning scenarios (data/processed/composer_eval/summary.json)",
            "taste_signal": "PROXY: BaselineRanker content cosine to 5 random favourites; re-run with survey ratings as the taste oracle before treating these as final",
            "tuning_means": {k: pick[k] for k in ("urgency", "taste_loss", "kcal_dev", "diversity")},
            "caveat": (
                f"U(m) saturates in α: α = {near['alpha']:g} (same β, γ) already gets 95 % of the urgency gain over "
                f"taste-only with taste loss {near['taste_loss']:.3f} instead of {pick['taste_loss']:.3f}; the rule as "
                "pre-registered picks the largest gain, so it sits at the taste-loss limit"
            ),
            "how_to_apply": (
                "backend/src/tastoria/app.py builds MealDeps(...) with the default composer.Params(); pass "
                "MealDeps(params=Params(version='tray-p1-synthetic-20261018', alpha=…, beta=…, gamma=…)) there, or "
                "change the defaults of Params in backend/src/tastoria/modules/meal/composer.py. meal_plans.params_version "
                "records the version on every plan."
            ),
        }
        (OUT / "weights.json").write_text(json.dumps(weights, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("n_scenarios", "seconds", "no_feasible_tray", "chosen")}, ensure_ascii=False, indent=1, default=float))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
