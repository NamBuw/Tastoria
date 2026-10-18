"""Synthetic fridge scenarios for tuning and testing the composer weights (design v2 §6.2, review ml#5).

Generator (all draws from one seed; the scenario file records it):
  1. Incidence: for every KB dish, its stock-checked ingredients (not staple, not optional), as the backend
     `_needs` defines them. Co-occurrence C[a, b] = number of dishes using both a and b.
  2. Pantry ingredients: one seed dish per slot (man, rau, canh) plus U{0, …, 3} more, drawn uniformly; their
     ingredients form the start set S. Then n_extra ~ U{4, …, 12} times: draw b ∉ S with probability
     ∝ Σ_{a ∈ S} C[a, b] (co-occurrence with what is already in the fridge) and add it to S.
  3. Amounts: for ingredient i, g*_i = 75th percentile over dishes of grams_ri × n / servings_r (n = persons of the
     scenario); amount = g*_i × exp(U(ln 0.8, ln 3.0)); an ingredient of a seed dish gets at least that dish's
     need × U(1, 2) (the fridge was shopped for the seed dishes); countable ingredients are rounded up to whole
     units.
  4. Lots: with probability 0.3 an ingredient is split into two lots (share U(0.3, 0.7)). Each lot gets
     u ~ U(0, 1.05) if the ingredient has a shelf life L (acquired u·L days ago; u > 1 is the "kiểm tra" level and
     the lot is not available, BR-FRESH-04), u = None otherwise (not tracked: available, never rewarded).
  5. Person and meal: n ∈ {1, 2, 3, 4} with P = (0.20, 0.35, 0.20, 0.25); meal lunch/dinner (½ each);
     TEE ~ U(1700, 2700) kcal, E_mâm = 0.35·TEE (lunch) or 0.30·TEE (dinner) (BR-NUT-04); max minutes
     ∈ {60, 90, 120}; 2 burners; no pinned lot; no allergy or diet (every dish allowed).
  6. Taste: 5 favourite dishes drawn uniformly from the catalog (a stand-in user; real taste needs the survey).
  7. Split: scenarios are shuffled and halved into `tuning` and `test`.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from tastoria_ml.recsys.kb_catalog import REPO, Catalog

OUT = REPO / "data" / "processed" / "composer_eval"
SEED = 20261018
PERSONS = (1, 2, 3, 4)
P_PERSONS = (0.20, 0.35, 0.20, 0.25)


def stock_lines(cat: Catalog) -> list[dict[str, float]]:
    """Per dish: ingredient -> grams for `servings`, stock-checked lines only (not staple, not optional)."""
    out = []
    for r in cat.recipes:
        d = {}
        for ln in r.ingredients:
            ing = cat.ingredients.get(ln.name)
            if ln.optional or (ing is not None and ing.is_staple):
                continue
            d[ln.name] = d.get(ln.name, 0.0) + ln.grams
        out.append(d)
    return out


def _unit_g(cat: Catalog, name: str) -> float | None:
    ing = cat.ingredients.get(name)
    if ing is None or not ing.countable or not ing.units:
        return None
    return min(u.grams_per_unit for u in ing.units)


def generate(cat: Catalog, n: int = 150, seed: int = SEED) -> dict:
    rng = np.random.default_rng(seed)
    lines = stock_lines(cat)
    names = sorted({k for d in lines for k in d})
    col = {k: j for j, k in enumerate(names)}
    inc = np.zeros((len(lines), len(names)))
    for r, d in enumerate(lines):
        for k in d:
            inc[r, col[k]] = 1
    C = inc.T @ inc
    np.fill_diagonal(C, 0)
    scen = []
    for sid in range(n):
        persons = int(rng.choice(PERSONS, p=P_PERSONS))
        meal = "lunch" if rng.random() < 0.5 else "dinner"
        tee = float(rng.uniform(1700, 2700))
        e_target = tee * (0.35 if meal == "lunch" else 0.30)
        max_minutes = int(rng.choice([60, 90, 120]))
        slots = np.array([r.slot for r in cat.recipes])
        seeds = [int(rng.choice(np.flatnonzero(slots == sl))) for sl in ("man", "rau", "canh")]
        rest = np.setdiff1d(np.arange(len(lines)), seeds)
        seeds += rng.choice(rest, size=int(rng.integers(0, 4)), replace=False).tolist()
        S = set()
        for r in seeds:
            S |= set(lines[r])
        for _ in range(int(rng.integers(4, 13))):
            idx = np.array([col[k] for k in S])
            w = C[idx].sum(0)
            w[idx] = 0
            if w.sum() <= 0:
                break
            S.add(names[int(rng.choice(len(names), p=w / w.sum()))])
        lots = []
        for name in sorted(S):
            per = [d[name] * persons / cat.recipes[r].servings for r, d in enumerate(lines) if name in d]
            g = float(np.percentile(per, 75)) * math.exp(rng.uniform(math.log(0.8), math.log(3.0)))
            seed_need = sum(lines[r][name] * persons / cat.recipes[r].servings for r in seeds if name in lines[r])
            if seed_need > 0:
                g = max(g, seed_need * float(rng.uniform(1.0, 2.0)))
            ug = _unit_g(cat, name)
            if ug:
                g = math.ceil(g / ug) * ug
            parts = [g]
            if rng.random() < 0.3:
                s = rng.uniform(0.3, 0.7)
                parts = [g * s, g * (1 - s)]
                if ug:
                    a = max(ug, math.floor(parts[0] / ug) * ug)
                    parts = [a, g - a] if g - a > 0 else [g]
            ing = cat.ingredients.get(name)
            L = ing.shelf_life.days if ing is not None else None
            for p in parts:
                u = float(rng.uniform(0, 1.05)) if L else None
                lots.append({"ingredient": name, "g_min": round(float(p), 1), "urgency": u, "shelf_life_days": L})
        favs = sorted(rng.choice(len(cat.recipes), size=5, replace=False).tolist())
        scen.append(
            {
                "id": f"s{sid:03d}",
                "persons": persons,
                "meal": meal,
                "tee_kcal": round(tee, 1),
                "e_target_kcal": round(e_target, 1),
                "max_minutes": max_minutes,
                "burners": 2,
                "seed_dishes": [cat.recipes[int(r)].slug for r in seeds],
                "favorites": [cat.recipes[i].slug for i in favs],
                "lots": lots,
            }
        )
    order = rng.permutation(n)
    half = set(order[: n // 2].tolist())
    for i, s in enumerate(scen):
        s["split"] = "tuning" if i in half else "test"
    return {"seed": seed, "n": n, "generator": __doc__, "scenarios": scen}


def write(cat: Catalog, path: Path | None = None, **kw) -> dict:
    data = generate(cat, **kw)
    path = path or OUT / "scenarios.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return data
