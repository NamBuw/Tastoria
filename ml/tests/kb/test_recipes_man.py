"""Recipe files of the "man" slot (data/kb/recipes/man/*.yaml)."""

from pathlib import Path

import pytest
import yaml

from tastoria_ml.kb.recipes import Recipe, check_recipes
from tastoria_ml.kb.validate import load_kb

REPO = Path(__file__).resolve().parents[3]
KB = REPO / "data" / "kb"
MAN = KB / "recipes" / "man"


@pytest.fixture(scope="module")
def kb():
    kb, errors = load_kb(KB)
    assert kb is not None, errors
    return kb


@pytest.fixture(scope="module")
def report(kb):
    return check_recipes(KB, kb)


@pytest.fixture(scope="module")
def man(report):
    return {r.slug: r for p, r in report.recipes.items() if p.parent == MAN}


def test_every_man_file_parses():
    for path in sorted(MAN.glob("*.yaml")):
        Recipe.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def test_no_errors_in_man_recipes(report):
    errs = [e for e in report.errors if e.startswith("recipes/man/") or "proposed" in e]
    assert not errs, "\n".join(errs)


def test_every_man_dish_has_a_recipe(kb, man):
    want = {d.slug for d in kb.dishes.dishes if d.slot == "man"}
    assert len(want) == 75
    assert sorted(want - man.keys()) == []
    assert sorted(man.keys() - want) == []


def test_recipe_shape(man):
    for slug, r in man.items():
        assert r.slot == "man", slug
        assert all(i.grams > 0 for i in r.ingredients), slug
        assert len(r.steps) >= 2 and all(s.minutes > 0 for s in r.steps), slug
        assert any(s.kind == "active" for s in r.steps), slug
        assert any(i.role == "main" for i in r.ingredients), slug
        assert r.sources, slug
        assert r.servings >= 1, slug


def test_recipe_keeps_dish_list_ingredients(kb, man):
    """The dish list's main + seasonings were reviewed for allergens/diet; a recipe must not drop any."""
    missing = []
    for d in kb.dishes.dishes:
        if d.slot != "man" or d.slug not in man:
            continue
        names = {i.name for i in man[d.slug].ingredients}
        missing += [f"{d.slug}: {n}" for n in d.main + d.seasonings if n not in names]
    assert not missing, "\n".join(missing)


def test_most_recipes_have_two_sources(man):
    few = sorted(s for s, r in man.items() if len(r.sources) < 2)
    assert len(few) <= len(man) // 10, f"dishes with < 2 sources: {few}"


def test_no_cookpad_sources(man):
    bad = [s for s, r in man.items() for src in r.sources if "cookpad" in src.url]
    assert not bad, bad
