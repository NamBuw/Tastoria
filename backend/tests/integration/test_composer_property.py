"""Composer properties on the real catalog with random pantries (design v2 §6.2 "khả thi = kiểm thử tính chất"):
every tray returned uses at most the pooled usable stock (BR-TRAY-04, shared ingredients summed across dishes),
uses each pin ≥ 50 % (BR-TRAY-08), fits the makespan bound (BR-TRAY-05), has the BR-TRAY-01 structure and holds no
ingredient of a banned allergen group or excluded food group (BR-ALG-01, BR-DIET-01). Needs are recomputed here from
the recipe lines, independently of the composer."""

from __future__ import annotations

import uuid
from collections import defaultdict

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy.orm import Session

from tastoria.modules.catalog import service as catalog
from tastoria.modules.meal import composer as cmp
from tastoria.modules.meal import schedule as sch
from tastoria.modules.meal.service import _option, line_need


@pytest.fixture(scope="module")
def world(kb_engine):
    with Session(kb_engine) as s:
        views = catalog.published_recipes(s)
        codes = sorted({a for v in views for a in v.allergen_codes})
        chay = catalog.excluded_food_groups(s, "chay")
    ingredients = sorted({ln.ingredient.id for v in views for ln in v.lines if not ln.ingredient.is_staple}
                         | {v.make_ahead.item.id for v in views if v.make_ahead}, key=str)  # fmt: skip
    return views, codes, chay, ingredients


def _independent_needs(recipe, persons: int) -> dict[uuid.UUID, float]:
    if recipe.make_ahead and recipe.make_ahead.whole_dish:
        return {}
    out: dict[uuid.UUID, float] = defaultdict(float)
    for ln in recipe.lines:
        if not ln.ingredient.is_staple and not ln.is_optional:
            out[ln.ingredient.id] += line_need(ln.grams, ln.ingredient, persons, recipe.servings)
    return out


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(data=st.data())
def test_every_returned_tray_is_feasible(world, data) -> None:
    views, codes, chay, ingredients = world
    persons = data.draw(st.integers(1, 6))
    banned = data.draw(st.sets(st.sampled_from(codes), max_size=3))
    excl = chay if data.draw(st.booleans()) else frozenset()
    full = data.draw(st.booleans())
    stocked = (
        ingredients
        if full
        else data.draw(st.lists(st.sampled_from(ingredients), min_size=3, max_size=len(ingredients), unique=True))
    )
    lots = [
        cmp.Lot(uuid.uuid4(), i, 10_000.0 if full else float(data.draw(st.integers(50, 3000))), data.draw(st.one_of(st.none(), st.floats(0, 1.3))),
                False)
        for i in stocked
    ]  # fmt: skip
    lots = [cmp.Lot(x.id, x.ingredient_id, x.g_min, x.urgency, x.urgency is not None and 0.5 <= x.urgency <= 1.0)
            for x in lots]  # fmt: skip
    pins = data.draw(st.lists(st.sampled_from(lots), max_size=2, unique_by=lambda x: x.id))
    burners = data.draw(st.integers(1, 4))
    max_minutes = data.draw(st.integers(10, 180))
    allowed = [v for v in views if catalog.recipe_allowed(v, banned, excl)]
    options: dict[str, list[cmp.Option]] = defaultdict(list)
    for v in allowed:
        options[v.slot].append(_option(v, data.draw(st.floats(0, 1)), persons))
    problem = cmp.Problem(dict(options), lots, pins, burners, max_minutes, data.draw(st.one_of(st.none(),
                          st.floats(300, 900))), 173.2)  # fmt: skip
    structures = (("man", "rau", "canh"),) if persons >= 2 else (("man", "rau"), ("man", "canh"))
    have: dict[uuid.UUID, float] = defaultdict(float)
    for x in lots:
        have[x.ingredient_id] += x.g_min
    trays = cmp.compose(problem, structures)[:25]
    if full and max_minutes >= 120 and not pins and not banned:
        assert trays  # a full pantry and enough time always gives a tray: the property is not vacuous
    for tray in trays:
        slots = tuple(d.slot for d in tray.dishes)
        assert slots in structures
        need: dict[uuid.UUID, float] = defaultdict(float)
        for d in tray.dishes:
            assert not (d.recipe.allergen_codes & banned) and not (d.recipe.food_group_codes & excl)
            for i, g in _independent_needs(d.recipe, persons).items():
                need[i] += g
            if d.recipe.make_ahead and d.recipe.make_ahead.whole_dish:
                assert have.get(d.recipe.make_ahead.item.id, 0) > 0
        assert all(g <= have.get(i, 0) + 1e-6 for i, g in need.items())
        before: dict[uuid.UUID, float] = defaultdict(float)
        for pin in pins:
            used = min(pin.g_min, max(0.0, need.get(pin.ingredient_id, 0.0) - before[pin.ingredient_id]))
            before[pin.ingredient_id] += pin.g_min
            assert used + 1e-6 >= 0.5 * pin.g_min
        assert sch.lower_bound([d.sched for d in tray.dishes], burners) <= max_minutes
        if tray.bowls is not None:
            assert 0.5 <= tray.bowls <= 3 and tray.bowls * 2 == int(tray.bowls * 2)
