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

import itertools
import json
import math
import os
import time
import uuid
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass

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
ALPHAS = (0.0, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0)
BETAS = (0.0, 0.5, 1.0, 2.0, 4.0)
GAMMAS = (0.0, 0.25, 0.5, 1.0)
TASTE_LOSS_MAX = 0.2
KCAL_DEV_MAX = 0.15
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


def prepare(s: dict, v: Views, rice_kcal: float) -> Prepared:
    favs = [v.recipes[x] for x in s["favorites"]]
    recipes = list(v.recipes.values())
    raw = BaselineRanker().score(RankContext(user_id=_id("user", s["id"]), favorites=favs), recipes)
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


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="composer weight grid on synthetic fridge scenarios")
    ap.add_argument("--n", type=int, default=150)
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args(argv)
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
        weights = {
            "version": "tray-p1-synthetic-20261018",
            "alpha": pick["alpha"], "beta": pick["beta"], "gamma": pick["gamma"], "top_k": 20,
            "chosen_by": "pre-registered rule on 75 synthetic tuning scenarios (data/processed/composer_eval/summary.json)",
            "taste_signal": "PROXY: BaselineRanker content cosine to 5 random favourites; re-run with survey ratings as the taste oracle before treating these as final",
            "tuning_means": {k: pick[k] for k in ("urgency", "taste_loss", "kcal_dev", "diversity")},
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
