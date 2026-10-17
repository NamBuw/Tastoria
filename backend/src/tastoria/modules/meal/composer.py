"""Tray composer (design v2 §6.2): pure functions over pre-loaded options, no database.

    maximise  Σ ŝ'(u, r) + α·U(m) − β·|E(m) − E_mâm| / E_mâm − γ·D(m)
    subject to BR-TRAY-01 (structure), BR-TRAY-04 (pooled stock by g_min), BR-TRAY-05 (makespan), BR-TRAY-08 (pins),
               BR-ALG-01 / BR-DIET-01 (applied before: only allowed recipes become options)

  * U(m) = Σ_l u_l · min(1, used_l / g_min_l) / Σ_l u_l over the rewarded lots (u ∈ [0.5, 1.0], not at check level);
    a tray's need of an ingredient is taken from its lots pinned-first, then most urgent first — the order the
    pantry deducts in when the tray is cooked.
  * E(m) per person = Σ kcal of the dishes + rice bowls × E_bát, bowls = clip(round½((E_mâm − Σ kcal) / E_bát), 0.5, 3)
    (BR-TRAY-03); without a target (BR-CONSENT-02) β = 0 and no bowls.
  * D(m) = (pairs sharing the cooking method + pairs sharing a main ingredient) / pairs.
  * Candidates: options that cannot fit the stock on their own are dropped first; then the top-K (K = 20) of each
    slot by the slot-level score ŝ' + α·U_r − β·|kcal_r − share| / E_mâm, share = (E_mâm − 1.5·E_bát) / dishes;
    combinations are enumerated with the pooled checks and a makespan lower bound; if none passes, K = all.
The caller verifies the best trays with the exact CP-SAT schedule (schedule.solve) in objective order.
"""

from __future__ import annotations

import itertools
import math
import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from tastoria.modules.catalog.schemas import RecipeView
from tastoria.modules.meal import schedule as sch

EPS = 1e-6


@dataclass(frozen=True)
class Params:
    """Objective weights. PROVISIONAL: design v2 §6.2 fixes them later by a pre-registered rule on 100–200 fridge
    scenarios; until then these values are a documented starting point, recorded in meal_plans.params_version."""

    version: str = "tray-p0-provisional"
    alpha: float = 1.0
    beta: float = 1.0
    gamma: float = 0.5
    top_k: int = 20
    pin_share: float = 0.5  # BR-TRAY-08
    bowls_min: float = 0.5  # BR-TRAY-03
    bowls_max: float = 3.0
    bowls_share_guess: float = 1.5  # bowls assumed when splitting E_mâm into dish shares for the slot score


@dataclass(frozen=True)
class Option:
    recipe: RecipeView
    s_prime: float
    needs: dict[uuid.UUID, float]  # stock-checked grams for this tray's persons (staples and optional lines exempt)
    item: uuid.UUID | None  # whole make-ahead dish: the made-ahead item that must be in stock
    kcal_pp: float | None
    sched: sch.Dish
    item_grams: float = 0.0  # what cooking deducts from the made-ahead item (raw grams × n / servings, uncalibrated)

    @property
    def slot(self) -> str:
        return self.recipe.slot


@dataclass(frozen=True)
class Lot:
    id: uuid.UUID
    ingredient_id: uuid.UUID
    g_min: float
    urgency: float | None
    rewarded: bool


@dataclass(frozen=True)
class Problem:
    options: dict[str, list[Option]]
    lots: Sequence[Lot]  # available lots only
    pins: Sequence[Lot]
    burners: int
    max_minutes: int
    e_target: float | None  # per person (BR-TRAY-07 multiplies by persons for display only)
    rice_kcal: float | None
    params: Params = field(default_factory=Params)


@dataclass(frozen=True)
class Tray:
    dishes: tuple[Option, ...]
    objective: float
    taste: float  # mean ŝ'
    urgency: float  # U(m)
    kcal_dev: float  # |E(m) − E_mâm| / E_mâm (0 without a target)
    diversity: float  # D(m)
    bowls: float | None
    e_pp: float | None
    lower_bound: int
    used_lots: dict[uuid.UUID, float]

    @property
    def recipe_ids(self) -> tuple[uuid.UUID, ...]:
        return tuple(d.recipe.id for d in self.dishes)


class Context:
    """Stock, lot order and constants shared by every evaluation of one request."""

    def __init__(self, p: Problem, *, use_stock: bool = True, use_pins: bool = True) -> None:
        self.p = p
        self.use_stock, self.use_pins = use_stock, use_pins
        self.avail: dict[uuid.UUID, float] = defaultdict(float)
        for lot in p.lots:
            self.avail[lot.ingredient_id] += lot.g_min
        pin_ids = [x.id for x in p.pins]
        self.order: dict[uuid.UUID, list[Lot]] = defaultdict(list)
        for lot in sorted(
            p.lots, key=lambda x: (x.id not in pin_ids, -(x.urgency if x.urgency is not None else -1.0), str(x.id))
        ):
            self.order[lot.ingredient_id].append(lot)
        self.reward_total = sum(x.urgency or 0.0 for x in p.lots if x.rewarded)

    # -- single option checks
    def fits_alone(self, o: Option) -> bool:
        if self.use_stock:
            if o.item is not None and self.avail.get(o.item, 0.0) <= EPS:
                return False
            if any(g > self.avail.get(i, 0.0) + EPS for i, g in o.needs.items()):
                return False
        return sch.lower_bound([o.sched], self.p.burners) <= self.p.max_minutes

    def slot_score(self, o: Option, n_dishes: int) -> float:
        p = self.p
        score = o.s_prime + p.params.alpha * self.urgency_of({**o.needs})
        if p.e_target and o.kcal_pp is not None:
            share = max(0.0, p.e_target - p.params.bowls_share_guess * (p.rice_kcal or 0.0)) / n_dishes
            score -= p.params.beta * abs(o.kcal_pp - share) / p.e_target
        return score

    # -- tray
    def urgency_of(self, totals: dict[uuid.UUID, float]) -> float:
        if self.reward_total <= 0:
            return 0.0
        acc = 0.0
        for iid, need in totals.items():
            left = need
            for lot in self.order.get(iid, ()):
                if left <= EPS:
                    break
                used = min(lot.g_min, left)
                left -= used
                if lot.rewarded and lot.g_min > 0:
                    acc += (lot.urgency or 0.0) * min(1.0, used / lot.g_min)
        return acc / self.reward_total

    def _used(self, totals: dict[uuid.UUID, float]) -> dict[uuid.UUID, float]:
        out = {}
        for iid, need in totals.items():
            left = need
            for lot in self.order.get(iid, ()):
                if left <= EPS:
                    break
                used = min(lot.g_min, left)
                left -= used
                out[lot.id] = used
        return out

    def pins_met(self, totals: dict[uuid.UUID, float], pins: Iterable[Lot] | None = None) -> bool:
        before: dict[uuid.UUID, float] = defaultdict(float)
        for pin in self.p.pins if pins is None else pins:
            used = min(pin.g_min, max(0.0, totals.get(pin.ingredient_id, 0.0) - before[pin.ingredient_id]))
            before[pin.ingredient_id] += pin.g_min
            if used + EPS < self.p.params.pin_share * pin.g_min:
                return False
        return True

    def evaluate(self, dishes: Sequence[Option]) -> Tray | None:
        p, prm = self.p, self.p.params
        totals: dict[uuid.UUID, float] = defaultdict(float)
        for d in dishes:
            for i, g in d.needs.items():
                totals[i] += g
        if self.use_stock:
            if any(g > self.avail.get(i, 0.0) + EPS for i, g in totals.items()):
                return None
            if any(d.item is not None and self.avail.get(d.item, 0.0) <= EPS for d in dishes):
                return None
        if self.use_pins and p.pins and not self.pins_met(totals):
            return None
        lb = sch.lower_bound([d.sched for d in dishes], p.burners)
        if lb > p.max_minutes:
            return None
        taste = sum(d.s_prime for d in dishes)
        u = self.urgency_of(totals)
        kcal = [d.kcal_pp for d in dishes]
        dish_kcal = sum(k for k in kcal if k is not None)
        bowls = e_pp = None
        dev = 0.0
        if p.e_target and p.rice_kcal:
            raw = (p.e_target - dish_kcal) / p.rice_kcal
            bowls = min(prm.bowls_max, max(prm.bowls_min, round_half(raw)))
            e_pp = dish_kcal + bowls * p.rice_kcal
            dev = abs(e_pp - p.e_target) / p.e_target
        elif p.e_target:
            e_pp = dish_kcal
            dev = abs(e_pp - p.e_target) / p.e_target
        else:
            e_pp = dish_kcal if all(k is not None for k in kcal) else None
        pairs = list(itertools.combinations(dishes, 2))
        same = sum(
            (a.recipe.method_code == b.recipe.method_code)
            + bool(a.recipe.main_ingredient_ids & b.recipe.main_ingredient_ids)
            for a, b in pairs
        )
        div = same / len(pairs) if pairs else 0.0
        beta = prm.beta if p.e_target else 0.0
        obj = taste + prm.alpha * u - beta * dev - prm.gamma * div
        return Tray(tuple(dishes), obj, taste / len(dishes), u, dev, div, bowls, e_pp, lb, self._used(dict(totals)))


def compose(
    p: Problem,
    structures: Sequence[Sequence[str]],
    *,
    fixed: Sequence[Option] = (),
    use_stock: bool = True,
    use_pins: bool = True,
    expand: bool = True,
) -> list[Tray]:
    """All trays passing the checks, best objective first. `fixed` dishes stay (swap, BR-SWAP-01); `structures` lists
    the slots to fill. Top-K per slot first, every option second (when nothing passed and `expand`)."""
    ctx = Context(p, use_stock=use_stock, use_pins=use_pins)
    fixed_slots = {d.slot for d in fixed}
    pools: dict[str, list[Option]] = {}
    for slot in {s for st in structures for s in st} - fixed_slots:
        pools[slot] = [o for o in p.options.get(slot, []) if ctx.fits_alone(o)]
    for k in (p.params.top_k, None) if expand else (p.params.top_k,):
        trays: list[Tray] = []
        for st in structures:
            free = [s for s in st if s not in fixed_slots]
            n = len(st)
            lists = []
            for s in free:
                ranked = sorted(pools.get(s, []), key=lambda o: (-ctx.slot_score(o, n), str(o.recipe.id)))
                lists.append(ranked if k is None else ranked[:k])
            for combo in itertools.product(*lists):
                t = ctx.evaluate([*fixed, *combo])
                if t is not None:
                    trays.append(t)
        if trays:
            trays.sort(key=lambda t: (-t.objective, t.recipe_ids))
            return trays
        if k is not None and all(len(v) <= k for v in pools.values()):
            break  # K already covered every option
    return []


def unmet_pins(p: Problem, structures: Sequence[Sequence[str]], fixed: Sequence[Option] = ()) -> list[uuid.UUID]:
    """Pins no stock- and time-feasible tray can use at ≥ 50 % on its own (BR-TRAY-08 report); every pin when each
    alone is reachable but not together."""
    trays = compose(p, structures, fixed=fixed, use_pins=False)
    if not trays:
        return []
    ctx = Context(p)
    alone = []
    for pin in p.pins:
        ok = False
        for t in trays:
            totals: dict[uuid.UUID, float] = defaultdict(float)
            for d in t.dishes:
                for i, g in d.needs.items():
                    totals[i] += g
            if ctx.pins_met(totals, [pin]):
                ok = True
                break
        if not ok:
            alone.append(pin.id)
    return alone or [x.id for x in p.pins]


def shortfall(p: Problem, tray: Tray) -> list[tuple[uuid.UUID, float, float]]:
    """(ingredient, need, available g_min) for every ingredient the stock cannot cover (BR-TRAY-06)."""
    ctx = Context(p)
    totals: dict[uuid.UUID, float] = defaultdict(float)
    for d in tray.dishes:
        for i, g in d.needs.items():
            totals[i] += g
    out = [(i, g, ctx.avail.get(i, 0.0)) for i, g in totals.items() if g > ctx.avail.get(i, 0.0) + EPS]
    for d in tray.dishes:
        if d.item is not None and ctx.avail.get(d.item, 0.0) <= EPS:
            out.append((d.item, d.item_grams, 0.0))
    return out


def round_half(x: float) -> float:
    return math.floor(x * 2 + 0.5) / 2
