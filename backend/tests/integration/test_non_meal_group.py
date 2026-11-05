"""Snacks, sweets and soft drinks (food group `do_an_vat`) are recognised by the detector and kept in the pantry, but
never enter a meal tray: the hard filter, the composer context and the substitute picker leave the group out with or
without a diet (data/kb/ref/food_groups.yaml, data/kb/vision_classes.yaml `meal_ingredient: false`)."""

from __future__ import annotations

import dataclasses

from sqlalchemy import text
from sqlalchemy.orm import Session

from tastoria.modules.catalog import service as catalog


def test_non_meal_group_is_always_excluded(kb_engine) -> None:
    with Session(kb_engine) as s:
        diets = list(s.scalars(text("SELECT code FROM diets")))
        snacks = catalog.active_ingredients(s, "do_an_vat")
        views = catalog.published_recipes(s)
        for d in [None, *diets]:
            assert "do_an_vat" in catalog.excluded_food_groups(s, d), d
    names = {v.name_vi for v in snacks.values()}
    assert {"bim bim", "kẹo", "nước ngọt"} <= names
    for ing in snacks.values():
        assert not catalog.ingredient_allowed(ing, (), ())
    # no published recipe uses a snack, so the always-on exclusion removes no dish from the composer's pool
    assert all("do_an_vat" not in v.food_group_codes for v in views)
    # a recipe holding a snack line is rejected even when the caller passes no excluded groups
    v = next(v for v in views if v.lines)
    snack = next(iter(snacks.values()))
    tainted = dataclasses.replace(v, lines=[dataclasses.replace(v.lines[0], ingredient=snack), *v.lines[1:]])
    assert catalog.recipe_allowed(v, (), ())
    assert not catalog.recipe_allowed(tainted, (), ())
