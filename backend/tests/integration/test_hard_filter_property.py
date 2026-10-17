"""BR-ALG-01 / BR-DIET-01 over the whole imported catalog: for every recipe × every allergen group (and any set of
groups a user and co-eaters may declare, and any diet), the hard filter never lets through a recipe holding — staples,
optional lines and the made-ahead item included — an ingredient of an excluded group. Truth comes from raw SQL."""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import text
from sqlalchemy.orm import Session

from tastoria.modules.catalog import service as catalog

_ALLERGENS_SQL = (
    "SELECT ri.recipe_id, ia.allergen_code FROM recipe_ingredients ri "
    "JOIN ingredient_allergens ia ON ia.ingredient_id = ri.ingredient_id "
    "UNION SELECT ma.recipe_id, ia.allergen_code FROM recipe_make_ahead ma "
    "JOIN ingredient_allergens ia ON ia.ingredient_id = ma.item_ingredient_id"
)
_GROUPS_SQL = (
    "SELECT ri.recipe_id, i.food_group_code FROM recipe_ingredients ri JOIN ingredients i ON i.id = ri.ingredient_id "
    "UNION SELECT ma.recipe_id, i.food_group_code FROM recipe_make_ahead ma JOIN ingredients i "
    "ON i.id = ma.item_ingredient_id"
)


@pytest.fixture(scope="module")
def catalog_facts(kb_engine):
    with Session(kb_engine) as s:
        views = catalog.published_recipes(s)
        allergens = {(r, a) for r, a in s.execute(text(_ALLERGENS_SQL))}
        groups = {(r, g) for r, g in s.execute(text(_GROUPS_SQL))}
        codes = list(s.scalars(text("SELECT code FROM allergen_groups ORDER BY code")))
        diets = {d: catalog.excluded_food_groups(s, d) for d in s.scalars(text("SELECT code FROM diets"))}
    return views, allergens, groups, codes, diets


def test_every_recipe_times_every_allergen_group(catalog_facts) -> None:
    views, allergens, _, codes, _ = catalog_facts
    assert len(views) == 171 and len(codes) == 10
    staples_with_allergen = 0
    violations = []
    for v in views:
        for code in codes:
            contains = (v.id, code) in allergens
            if catalog.recipe_allowed(v, {code}, ()) and contains:
                violations.append((v.name_vi, code))
            if not catalog.recipe_allowed(v, {code}, ()) and not contains:
                violations.append((v.name_vi, f"over-excluded {code}"))
            staples_with_allergen += contains and all(
                code not in ln.ingredient.allergen_codes for ln in v.lines if not ln.ingredient.is_staple
            )
    assert violations == []
    assert staples_with_allergen > 0  # e.g. nước mắm (cá) as the only fish: staples are really checked


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(data=st.data())
def test_any_user_plus_coeater_allergens_and_diet(catalog_facts, data) -> None:
    views, allergens, groups, codes, diets = catalog_facts
    user = data.draw(st.sets(st.sampled_from(codes), max_size=4))
    coeaters = data.draw(st.sets(st.sampled_from(codes), max_size=4))
    diet = data.draw(st.sampled_from([None, *sorted(diets)]))
    excl = diets[diet] if diet else frozenset()
    banned = user | coeaters
    for v in views:
        allowed = catalog.recipe_allowed(v, banned, excl)
        truth = not any((v.id, a) in allergens for a in banned) and not any((v.id, g) in groups for g in excl)
        assert allowed == truth, (v.name_vi, banned, diet)
