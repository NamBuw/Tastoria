"""UC25: `tastoria catalog import data/kb` — validation, idempotent upsert, BR-CATALOG-01 versions, make-ahead,
nutrition, audit, rollback on blocking problems."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml
from conftest import KB_DIR, PROCESSED_DIR
from sqlalchemy import create_engine, text

from tastoria.core.db import make_engine, make_sessionmaker
from tastoria.modules.admin.service import import_catalog


def _run(url: str, bundle: Path = KB_DIR):
    engine = make_engine(url, pool_size=1)
    try:
        return import_catalog(make_sessionmaker(engine), bundle, PROCESSED_DIR)
    finally:
        engine.dispose()


def _one(url: str, sql: str, **params):
    eng = create_engine(url)
    try:
        with eng.connect() as c:
            return c.execute(text(sql), params).scalar()
    finally:
        eng.dispose()


def _rows(url: str, sql: str, **params):
    eng = create_engine(url)
    try:
        with eng.connect() as c:
            return c.execute(text(sql), params).all()
    finally:
        eng.dispose()


@pytest.fixture
def bundle_copy(tmp_path: Path) -> Path:
    dst = tmp_path / "kb"
    shutil.copytree(KB_DIR, dst)
    return dst


def _edit_yaml(path: Path, fn) -> None:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    fn(data)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


# ---------------------------------------------------------------- the real KB


def test_kb_import_loads_the_whole_catalog(kb_database_url: str) -> None:
    url = kb_database_url
    assert _one(url, "SELECT count(*) FROM recipes WHERE status = 'published'") == 171
    assert _one(url, "SELECT count(*) FROM recipes WHERE status = 'draft'") == 9  # < 2 sources or unmapped main
    assert _one(url, "SELECT count(*) FROM recipes WHERE status = 'retired'") == 0
    assert _one(url, "SELECT count(*) FROM ingredients WHERE is_active") == 225  # 223 + 2 made-ahead products
    assert _one(url, "SELECT count(*) FROM allergen_groups") == 10
    assert _one(url, "SELECT count(*) FROM nutrient_sources") == 3
    assert _one(url, "SELECT count(*) FROM nutrients") == 7
    assert _one(url, "SELECT count(*) FROM diet_exclusions WHERE diet_code = 'chay'") == 6
    assert _one(url, "SELECT count(*) FROM qty_levels") == 18 * 3
    # every published recipe has energy, with the data version of the rules that computed it (BR-NUT-05)
    assert _one(url, "SELECT count(DISTINCT recipe_id) FROM recipe_nutrition rn JOIN recipes r ON r.id = rn.recipe_id "
                     "WHERE r.status = 'published' AND rn.nutrient_code = 'energy_kcal'") == 171  # fmt: skip
    assert _one(url, "SELECT count(DISTINCT data_version) FROM recipe_nutrition") == 1
    # composition rows only for codes the ingredients use (+ rice for E_bát)
    used = _one(url, "SELECT count(DISTINCT (comp_source_id, comp_source_code)) FROM ingredients "
                     "WHERE comp_source_id IS NOT NULL")  # fmt: skip
    assert _one(url, "SELECT count(*) FROM food_items") in (used, used + 1)
    # countable ingredients have units; staples are flagged (BR-QTY-02, BR-TRAY-04)
    assert _one(url, "SELECT count(*) FROM ingredients i WHERE countable AND NOT EXISTS "
                     "(SELECT 1 FROM ingredient_units u WHERE u.ingredient_id = i.id)") == 0  # fmt: skip
    assert _one(url, "SELECT count(*) FROM ingredients WHERE is_staple") == 8
    egg = _rows(url, "SELECT u.unit_code, u.grams_per_unit FROM ingredient_units u JOIN ingredients i "
                     "ON i.id = u.ingredient_id WHERE i.name_vi = 'trứng gà'")  # fmt: skip
    assert egg and egg[0].grams_per_unit > 0
    # nước mắm carries fish (BR-ALG-01 covers staples)
    assert _one(url, "SELECT count(*) FROM ingredient_allergens a JOIN ingredients i ON i.id = a.ingredient_id "
                     "WHERE i.name_vi = 'nước mắm' AND a.allergen_code = 'ca'") == 1  # fmt: skip


def test_make_ahead_recipes_are_tagged_and_mapped(kb_database_url: str) -> None:
    rows = _rows(
        kb_database_url,
        "SELECT r.name_vi, i.name_vi AS item, m.through_step_no, (SELECT max(step_no) FROM recipe_steps s "
        "WHERE s.recipe_id = r.id) AS last_step, EXISTS (SELECT 1 FROM recipe_tags t WHERE t.recipe_id = r.id "
        "AND t.tag_code = 'lam_san') AS tagged FROM recipe_make_ahead m JOIN recipes r ON r.id = m.recipe_id "
        "JOIN ingredients i ON i.id = m.item_ingredient_id ORDER BY r.name_vi",
    )
    got = {r.name_vi: (r.item, r.through_step_no, r.last_step, r.tagged) for r in rows}
    assert got == {
        "Canh măng nấu chân giò": ("măng khô", 2, 9, True),
        "Cà pháo muối": ("cà pháo muối", 5, 5, True),
        "Dưa cải muối": ("dưa cải chua", 5, 5, True),
        "Dưa giá": ("dưa giá", 4, 4, True),
    }
    assert _one(kb_database_url, "SELECT count(*) FROM recipe_tags WHERE tag_code = 'lam_san'") == 4
    assert _one(kb_database_url, "SELECT kind FROM tags WHERE code = 'lam_san'") == "occasion"


def test_rice_bowl_energy_is_set_for_the_journal_view(kb_database_url: str) -> None:
    v = _one(kb_database_url, "SELECT app_param('rice_bowl_kcal')")
    assert v is not None and 150 < float(v) < 200  # 150 g cooked rice ≈ 50 g gạo tẻ máy × 346 kcal/100 g


def test_calorie_range_is_calibrated_from_the_validation_file(kb_database_url: str) -> None:
    summary = yaml.safe_load((KB_DIR / "validation/nin_dishes.yaml").read_text(encoding="utf-8"))["summary"]
    assert summary["n"] >= 30
    stored = _one(kb_database_url, "SELECT current_setting('tastoria.kcal_half_width', true)")
    assert float(stored) == pytest.approx(summary["p80_abs_rel_error"])  # BR-NUT-06


def test_too_few_validated_dishes_leave_the_range_uncalibrated(fresh_database, bundle_copy: Path) -> None:
    url = fresh_database()
    path = bundle_copy / "validation/nin_dishes.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["summary"]["n"] = 12
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    res = _run(url, bundle_copy)
    assert res.ok and res.report["kcal_half_width"] is None
    assert any("needs ≥ 30" in w for w in res.report["warnings"])
    assert _one(url, "SELECT current_setting('tastoria.kcal_half_width', true)") in (None, "")


def test_reimport_of_the_same_bundle_changes_nothing(kb_database_url: str) -> None:
    before = _rows(kb_database_url, "SELECT recipe_id, nutrient_code, computed_at FROM recipe_nutrition ORDER BY 1, 2")
    res = _run(kb_database_url)
    assert res.ok, res.errors
    assert res.report["changes"] == 0 and res.report["nutrition_recomputed"] == 0
    assert res.report["new_versions"] == []
    after = _rows(kb_database_url, "SELECT recipe_id, nutrient_code, computed_at FROM recipe_nutrition ORDER BY 1, 2")
    assert after == before  # FR-25-09: computed_at unchanged


# ---------------------------------------------------------------- versions, retire, deactivate (BR-CATALOG-01)


def test_changed_published_recipe_gets_a_new_version(fresh_database, bundle_copy: Path) -> None:
    url = fresh_database()
    assert _run(url, bundle_copy).ok
    old = _one(url, "SELECT id FROM recipes WHERE name_vi = 'Đậu đũa xào tỏi'")
    eng = create_engine(url)
    with eng.begin() as c:  # an old meal plan item points at the old version
        uid = c.execute(text("INSERT INTO users (email, password_hash) VALUES ('a@b.vn', 'x') RETURNING id")).scalar()
        plan = c.execute(text("INSERT INTO meal_plans (user_id, meal, persons, max_minutes, reason_vi, params_version) "
                              "VALUES (:u, 'dinner', 2, 45, 'x', 'p') RETURNING id"), {"u": uid}).scalar()  # fmt: skip
        c.execute(text("INSERT INTO meal_plan_items (meal_plan_id, slot, recipe_id, rank_score, servings_scale) "
                       "VALUES (:p, 'rau', :r, 0.5, 0.5)"), {"p": plan, "r": old})  # fmt: skip
    eng.dispose()

    _edit_yaml(bundle_copy / "recipes/rau/dau-dua-xao-toi.yaml", lambda d: d["ingredients"][0].update(grams=450))
    res = _run(url, bundle_copy)
    assert res.ok, res.errors
    assert [v["name_vi"] for v in res.report["new_versions"]] == ["Đậu đũa xào tỏi"]
    rows = _rows(url, "SELECT id, status FROM recipes WHERE name_vi = 'Đậu đũa xào tỏi' ORDER BY created_at, status")
    assert {(str(r.id) == str(old), r.status) for r in rows} == {(True, "retired"), (False, "published")}
    new = next(r.id for r in rows if r.status == "published")
    assert _one(url, "SELECT grams FROM recipe_ingredients ri JOIN ingredients i ON i.id = ri.ingredient_id "
                     "WHERE ri.recipe_id = :r AND i.name_vi = 'đậu đũa'", r=new) == 450  # fmt: skip
    assert _one(url, "SELECT grams FROM recipe_ingredients ri JOIN ingredients i ON i.id = ri.ingredient_id "
                     "WHERE ri.recipe_id = :r AND i.name_vi = 'đậu đũa'", r=old) == 400  # fmt: skip
    assert _one(url, "SELECT recipe_id FROM meal_plan_items") == old  # the plan still points at what it used
    assert _one(url, "SELECT count(*) FROM recipe_nutrition WHERE recipe_id = :r", r=new) >= 5
    assert _one(url, "SELECT count(*) FROM audit_log WHERE action = 'catalog.import' AND purpose LIKE 'ok:%' "
                     "AND actor_role = 'curator'") == 2  # fmt: skip


def test_published_recipes_cannot_be_edited_in_place(fresh_database, bundle_copy: Path) -> None:
    url = fresh_database()
    assert _run(url, bundle_copy).ok
    eng = create_engine(url)
    with pytest.raises(Exception, match="BR-CATALOG-01"), eng.begin() as c:
        c.execute(text("UPDATE recipe_ingredients SET grams = 1 WHERE recipe_id = "
                       "(SELECT id FROM recipes WHERE status = 'published' LIMIT 1)"))  # fmt: skip
    eng.dispose()


def test_missing_items_are_retired_and_deactivated_not_deleted(fresh_database, bundle_copy: Path) -> None:
    url = fresh_database()
    assert _run(url, bundle_copy).ok
    (bundle_copy / "recipes/rau/dau-dua-xao-toi.yaml").unlink()
    _edit_yaml(bundle_copy / "make_ahead.yaml", lambda d: d["ingredients"].pop())  # drop "dưa giá" product …
    _edit_yaml(bundle_copy / "make_ahead.yaml", lambda d: d["make_ahead"].pop(2))  # … and its mapping
    (bundle_copy / "recipes/rau/dua-gia.yaml").unlink()
    res = _run(url, bundle_copy)
    assert res.ok, res.errors
    assert res.report["tables"]["recipes"]["retired"] == 2
    assert _one(url, "SELECT status FROM recipes WHERE name_vi = 'Đậu đũa xào tỏi'") == "retired"
    assert _one(url, "SELECT is_active FROM ingredients WHERE name_vi = 'dưa giá'") is False


# ---------------------------------------------------------------- blocking problems write nothing


def _catalog_rows(url: str) -> int:
    return _one(url, "SELECT (SELECT count(*) FROM recipes) + (SELECT count(*) FROM ingredients) "
                     "+ (SELECT count(*) FROM food_groups)")  # fmt: skip


def test_validation_errors_are_all_listed_with_file_and_line(fresh_database, bundle_copy: Path) -> None:
    url = fresh_database()
    _edit_yaml(bundle_copy / "recipes/rau/dau-dua-xao-toi.yaml", lambda d: d.update(slot="to", servings=0))
    _edit_yaml(bundle_copy / "recipes/man/ba-chi-chien-nuoc-mam.yaml", lambda d: d["steps"][0].update(kind="nau"))

    def break_ingredients(d):
        d["ingredients"][0]["allergens"] = ["shellfish_x"]
        del d["ingredients"][1]["allergens"]
        egg = next(i for i in d["ingredients"] if i["name_vi"] == "trứng gà")
        egg["units"] = []

    _edit_yaml(bundle_copy / "ingredients.yaml", break_ingredients)
    res = _run(url, bundle_copy)
    assert not res.ok
    text_ = "\n".join(res.errors)
    assert "recipes/rau/dau-dua-xao-toi.yaml:" in text_ and "slot" in text_ and "servings" in text_
    assert "recipes/man/ba-chi-chien-nuoc-mam.yaml:" in text_ and "steps.0.kind" in text_
    assert "shellfish_x" in text_
    assert "allergens: Field required" in text_  # FR-25-04: no declaration is an error, [] is a declaration
    assert "countable ingredient needs at least one unit" in text_
    for e in res.errors:
        file_, line, *_ = e.split(":", 2)
        assert file_ and line.isdigit(), e
    assert _catalog_rows(url) == 0
    assert _one(url, "SELECT count(*) FROM audit_log WHERE action = 'catalog.import' AND purpose LIKE 'failed%'") == 1


def test_long_passive_step_without_make_ahead_entry_is_an_error(fresh_database, bundle_copy: Path) -> None:
    url = fresh_database()
    _edit_yaml(bundle_copy / "make_ahead.yaml", lambda d: d["make_ahead"].pop(0))
    res = _run(url, bundle_copy)
    assert not res.ok
    assert any("make_ahead_missing" in e and "dua-cai-muoi" in e for e in res.errors)
    assert _catalog_rows(url) == 0


def test_made_ahead_item_must_carry_the_recipe_allergens(fresh_database, bundle_copy: Path) -> None:
    url = fresh_database()
    _edit_yaml(bundle_copy / "make_ahead.yaml", lambda d: d["make_ahead"][0].update(recipe="dua-cai-muoi"))

    def add_fish(d):
        d["ingredients"].append({"name": "nước mắm", "grams": 10, "role": "seasoning"})

    _edit_yaml(bundle_copy / "recipes/rau/dua-cai-muoi.yaml", add_fish)
    res = _run(url, bundle_copy)
    assert not res.ok and any("make_ahead_allergen" in e for e in res.errors)


def test_safety_check_failure_rolls_back_everything(fresh_database, bundle_copy: Path) -> None:
    url = fresh_database()

    def meat_marked_vegetarian(d):
        dish = next(x for x in d["dishes"] if x["slug"] == "ba-chi-chien-nuoc-mam")
        dish["vegetarian"] = True

    _edit_yaml(bundle_copy / "dish_list.yaml", meat_marked_vegetarian)
    res = _run(url, bundle_copy)
    assert not res.ok and any("Ba chỉ chiên nước mắm" in e for e in res.errors)
    assert _catalog_rows(url) == 0
    assert _one(url, "SELECT count(*) FROM audit_log WHERE purpose = 'failed: safety check'") == 1
