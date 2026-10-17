"""Recipe files of the "rau" and "canh" slots (data/kb/recipes/{rau,canh}/*.yaml)."""

import shutil
from pathlib import Path

import pytest
import yaml

from tastoria_ml.kb.recipes import Recipe, check_recipes, load_proposed
from tastoria_ml.kb.validate import load_kb

REPO = Path(__file__).resolve().parents[3]
KB = REPO / "data" / "kb"
SLOTS = ("rau", "canh")
DIRS = {s: KB / "recipes" / s for s in SLOTS}


@pytest.fixture(scope="module")
def kb():
    kb, errors = load_kb(KB)
    assert kb is not None, errors
    return kb


@pytest.fixture(scope="module")
def report(kb):
    return check_recipes(KB, kb)


@pytest.fixture(scope="module")
def recipes(report):
    return {r.slug: r for p, r in report.recipes.items() if p.parent.name in SLOTS}


@pytest.mark.parametrize("slot", SLOTS)
def test_every_file_parses(slot):
    paths = sorted(DIRS[slot].glob("*.yaml"))
    assert paths
    for path in paths:
        Recipe.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def test_no_validator_errors(report):
    errs = [
        e
        for e in report.errors
        if e.startswith(("recipes/rau/", "recipes/canh/")) or "proposed" in e
    ]
    assert not errs, "\n".join(errs)


def test_every_rau_canh_dish_has_a_recipe(kb, recipes):
    want = {d.slug for d in kb.dishes.dishes if d.slot in SLOTS}
    assert len(want) == 105
    assert sorted(want - recipes.keys()) == []
    assert sorted(recipes.keys() - want) == []


def test_slot_matches_dish_list(kb, recipes):
    dishes = {d.slug: d for d in kb.dishes.dishes}
    for slug, r in recipes.items():
        assert r.slot == dishes[slug].slot, slug


def test_names_resolve_to_canonical_ingredients(kb, recipes):
    known = {i.name_vi for i in kb.ingredients.ingredients}
    proposed, errors = load_proposed(KB)
    assert not errors, errors
    known |= {i.name_vi for i in proposed}
    unknown = sorted({f"{s}: {i.name}" for s, r in recipes.items() for i in r.ingredients if i.name not in known})
    assert not unknown, "\n".join(unknown)


def test_recipe_shape(recipes):
    for slug, r in recipes.items():
        assert r.servings >= 1, slug
        assert all(i.grams > 0 for i in r.ingredients), slug
        assert any(i.role == "main" and not i.optional for i in r.ingredients), slug
        assert len(r.steps) >= 2 and all(s.minutes > 0 for s in r.steps), slug
        assert any(s.kind == "active" for s in r.steps), slug
        assert r.sources, slug


def test_burner_steps_for_cooked_methods(kb, recipes):
    """Methods that use the stove (BR-COOK-01 scheduling) need at least one step on a burner."""
    burner = {m.code: m.uses_burner for m in kb.methods.cooking_methods}
    for slug, r in recipes.items():
        if burner[r.method]:
            assert any(s.uses_burner for s in r.steps), slug


def test_recipe_keeps_dish_list_ingredients(kb, recipes):
    """The dish list's main + seasonings were reviewed for allergens/diet; a recipe must not drop any."""
    missing = []
    for d in kb.dishes.dishes:
        if d.slot in SLOTS and d.slug in recipes:
            names = {i.name for i in recipes[d.slug].ingredients}
            missing += [f"{d.slug}: {n}" for n in d.main + d.seasonings if n not in names]
    assert not missing, "\n".join(missing)


def test_dish_list_main_is_main_role(kb, recipes):
    wrong = []
    for d in kb.dishes.dishes:
        if d.slot in SLOTS and d.slug in recipes:
            roles = {i.name: i.role for i in recipes[d.slug].ingredients}
            wrong += [f"{d.slug}: {n} is {roles[n]}" for n in d.main if roles.get(n) == "seasoning"]
    assert not wrong, "\n".join(wrong)


def test_most_recipes_have_two_sources(recipes):
    few = sorted(s for s, r in recipes.items() if len(r.sources) < 2)
    assert len(few) <= len(recipes) // 10, f"dishes with < 2 sources: {few}"


def test_no_cookpad_sources(recipes):
    bad = [s for s, r in recipes.items() for src in r.sources if "cookpad" in src.url]
    assert not bad, bad


# ---------------------------------------------------------------- validator catches mistakes


@pytest.fixture
def kb_copy(tmp_path):
    dst = tmp_path / "kb"
    shutil.copytree(KB, dst)
    return dst


def _edit(path: Path, fn):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    fn(data)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def test_validator_flags_unknown_ingredient(kb_copy):
    path = kb_copy / "recipes" / "rau" / "rau-muong-xao-toi.yaml"
    _edit(path, lambda d: d["ingredients"].append({"name": "rau muống tím", "grams": 10, "role": "side"}))
    errs = check_recipes(kb_copy).errors
    assert any("rau-muong-xao-toi" in e and "rau muống tím" in e for e in errs)


def test_validator_flags_meat_in_vegetarian_dish(kb_copy):
    path = kb_copy / "recipes" / "canh" / "canh-rau-cu.yaml"
    _edit(path, lambda d: d["ingredients"].append({"name": "nước mắm", "grams": 15, "role": "seasoning"}))
    errs = check_recipes(kb_copy).errors
    assert any("canh-rau-cu" in e and "vegetarian" in e for e in errs)


def test_validator_flags_wrong_slot_folder(kb_copy):
    src = kb_copy / "recipes" / "canh" / "canh-moc.yaml"
    src.rename(kb_copy / "recipes" / "rau" / "canh-moc.yaml")
    errs = check_recipes(kb_copy).errors
    assert any("canh-moc" in e and "file must be" in e for e in errs)
