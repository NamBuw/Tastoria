"""Cooking schedule of a tray with CP-SAT (OR-Tools), BR-COOK-01 — shared by meal (makespan for BR-TRAY-05) and
cooking (the schedule of POST /cook-sessions), so both use one algorithm (UC15 TBD-02).

Model (time unit = 1 minute, t = 0 is the first step):
  * one interval per step; steps of a dish in step_no order (end(i) ≤ start(i+1));
  * the cook does one active step at a time: NoOverlap over active steps;
  * steps that use a burner: Cumulative ≤ burners (user_settings.burners, default 2);
  * every dish ends in the window [M − 5, M], M = makespan = serving time (the dishes are hot together);
  * stir-fried dishes (method `xao`) end after every other dish;
  * minimise M.
Passive steps occupy no cook (they may still hold a burner). Make-ahead steps are not passed in (catalog cook_steps).

The window can be impossible to meet — with one burner a 30-minute braise and a stir-fry cannot both end in the last
5 minutes. Then the model is solved again without the window (status `relaxed`: dishes ready earlier wait, stir-fry
still last). If CP-SAT finds nothing within the time limit, a sequential schedule is returned (UC19 8a: `fallback`):
one step after the other, stir-fries last; it keeps NoOverlap, Cumulative and step order.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from ortools.sat.python import cp_model

SERVE_WINDOW_MIN = 5  # BR-COOK-01
TIME_LIMIT_S = 2.0


@dataclass(frozen=True)
class Step:
    step_no: int
    minutes: int
    active: bool
    burner: bool


@dataclass(frozen=True)
class Dish:
    key: object  # recipe id (opaque here)
    steps: tuple[Step, ...]
    stir_fry: bool = False


@dataclass(frozen=True)
class Slot:
    dish: int  # index into the dishes passed in
    step_no: int
    start: int  # minutes from t = 0
    end: int


@dataclass(frozen=True)
class Schedule:
    entries: tuple[Slot, ...]
    makespan: int  # minutes
    status: str  # optimal | feasible | fallback | empty


def lower_bound(dishes: Sequence[Dish], burners: int) -> int:
    """Cheap bound on the makespan used to prune trays before the exact solve (never above the optimum)."""
    steps = [s for d in dishes for s in d.steps]
    if not steps:
        return 0
    active = sum(s.minutes for s in steps if s.active)
    burner = math.ceil(sum(s.minutes for s in steps if s.burner) / max(1, burners))
    chain = max(sum(s.minutes for s in d.steps) for d in dishes)
    return max(active, burner, chain)


def solve(dishes: Sequence[Dish], burners: int, *, time_limit_s: float = TIME_LIMIT_S) -> Schedule:
    if not any(d.steps for d in dishes):
        return Schedule((), 0, "empty")
    sched = _solve(dishes, burners, time_limit_s, window=True)
    if sched is None:
        sched = _solve(dishes, burners, time_limit_s, window=False)
    return sched if sched is not None else sequential(dishes)


def _solve(dishes: Sequence[Dish], burners: int, time_limit_s: float, *, window: bool) -> Schedule | None:
    cooking = [i for i, d in enumerate(dishes) if d.steps]
    horizon = sum(s.minutes for i in cooking for s in dishes[i].steps) + SERVE_WINDOW_MIN
    m = cp_model.CpModel()
    starts: dict[tuple[int, int], cp_model.IntVar] = {}
    ends: dict[tuple[int, int], cp_model.IntVar] = {}
    active, burner_iv = [], []
    for i in cooking:
        prev_end = None
        for s in dishes[i].steps:
            st = m.new_int_var(0, horizon, f"s{i}_{s.step_no}")
            en = m.new_int_var(0, horizon, f"e{i}_{s.step_no}")
            iv = m.new_interval_var(st, s.minutes, en, f"i{i}_{s.step_no}")
            starts[(i, s.step_no)], ends[(i, s.step_no)] = st, en
            if s.active:
                active.append(iv)
            if s.burner:
                burner_iv.append(iv)
            if prev_end is not None:
                m.add(st >= prev_end)
            prev_end = en
    m.add_no_overlap(active)
    if burner_iv:
        m.add_cumulative(burner_iv, [1] * len(burner_iv), max(1, burners))
    makespan = m.new_int_var(0, horizon, "makespan")
    dish_end = {i: ends[(i, dishes[i].steps[-1].step_no)] for i in cooking}
    for e in dish_end.values():
        m.add(e <= makespan)
        if window:
            m.add(e >= makespan - SERVE_WINDOW_MIN)
    for i in cooking:
        if dishes[i].stir_fry:
            for j in cooking:
                if j != i and not dishes[j].stir_fry:
                    m.add(dish_end[i] >= dish_end[j])
    m.minimize(makespan)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.num_workers = 1
    solver.parameters.random_seed = 0
    res = solver.solve(m)
    if res not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    entries = tuple(
        Slot(i, s.step_no, solver.value(starts[(i, s.step_no)]), solver.value(ends[(i, s.step_no)]))
        for i in cooking
        for s in dishes[i].steps
    )
    status = ("optimal" if res == cp_model.OPTIMAL else "feasible") if window else "relaxed"
    return Schedule(entries, solver.value(makespan), status)


def sequential(dishes: Sequence[Dish]) -> Schedule:
    order = sorted((i for i, d in enumerate(dishes) if d.steps), key=lambda i: dishes[i].stir_fry)
    t, entries = 0, []
    for i in order:
        for s in dishes[i].steps:
            entries.append(Slot(i, s.step_no, t, t + s.minutes))
            t += s.minutes
    return Schedule(tuple(entries), t, "fallback" if entries else "empty")


def violations(dishes: Sequence[Dish], burners: int, sched: Schedule) -> list[str]:
    """Every BR-COOK-01 rule checked on a finished schedule (used by tests and as a guard before saving)."""
    out: list[str] = []
    by_key = {(e.dish, e.step_no): e for e in sched.entries}
    step = {(i, s.step_no): s for i, d in enumerate(dishes) for s in d.steps}
    if set(by_key) != set(step):
        out.append("steps missing or extra")
        return out
    for (i, no), e in by_key.items():
        if e.end - e.start != step[(i, no)].minutes or e.start < 0:
            out.append(f"dish {i} step {no}: wrong duration")
    for i, d in enumerate(dishes):
        for a, b in zip(d.steps, d.steps[1:], strict=False):
            if by_key[(i, a.step_no)].end > by_key[(i, b.step_no)].start:
                out.append(f"dish {i}: step {b.step_no} starts before step {a.step_no} ends")
    act = [e for k, e in by_key.items() if step[k].active]
    for x in range(len(act)):
        for y in range(x + 1, len(act)):
            if act[x].start < act[y].end and act[y].start < act[x].end:
                out.append("two active steps overlap")
    burn = [e for k, e in by_key.items() if step[k].burner]
    for t in {e.start for e in burn}:
        if sum(1 for e in burn if e.start <= t < e.end) > burners:
            out.append(f"more than {burners} burners at t={t}")
    ends = {i: by_key[(i, d.steps[-1].step_no)].end for i, d in enumerate(dishes) if d.steps}
    if ends and max(ends.values()) != sched.makespan:
        out.append("makespan is not the last end")
    for i, e in ends.items():
        if sched.status in ("optimal", "feasible") and e < sched.makespan - SERVE_WINDOW_MIN:
            out.append(f"dish {i} ready more than {SERVE_WINDOW_MIN} min before serving")
        if dishes[i].stir_fry and any(e < ends[j] for j in ends if not dishes[j].stir_fry):
            out.append(f"stir-fry dish {i} is not last")
    return out
