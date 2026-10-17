import shutil
import unicodedata
from pathlib import Path

import pytest
import yaml

from tastoria_ml.kb.validate import main, validate

REPO = Path(__file__).resolve().parents[3]
KB = REPO / "data" / "kb"
PROCESSED = REPO / "data" / "processed"


def _need_processed():
    for rel in ("fct2007/foods.csv", "usda/foods.csv", "foodkeeper/products.csv"):
        if not (PROCESSED / rel).exists():
            pytest.skip(f"missing data/processed/{rel}")


@pytest.fixture(scope="module")
def real_report():
    _need_processed()
    return validate(KB, PROCESSED)


@pytest.fixture
def kb_copy(tmp_path):
    _need_processed()
    dst = tmp_path / "kb"
    shutil.copytree(KB, dst)
    return dst


def _edit(kb_dir: Path, rel: str, fn):
    path = kb_dir / rel
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    fn(data)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _ing(data, name):
    return next(i for i in data["ingredients"] if i["name_vi"] == name)


def _dish(data, slug):
    return next(d for d in data["dishes"] if d["slug"] == slug)


def _errors(kb_dir):
    rep = validate(kb_dir, PROCESSED)
    assert not rep.ok, "expected the validator to fail"
    return "\n".join(rep.errors)


# ------------------------------------------------------------- the committed KB


def test_committed_kb_is_valid(real_report):
    assert real_report.ok, "\n".join(real_report.errors)


def test_committed_kb_meets_targets(real_report):
    s = real_report.stats
    assert s["dishes"] == 180
    assert s["by_slot"] == {"man": 75, "rau": 55, "canh": 50}
    assert s["vegetarian"] >= 15
    assert len(s["vegetarian_by_slot"]) == 3, "vegetarian dishes in every slot"
    assert s["le_20_min"] >= 20
    assert 200 <= s["ingredients"] <= 260
    assert {"muối", "đường", "nước mắm", "dầu ăn", "tiêu"} <= set(s["staples"])


def test_every_kb_text_file_is_nfc():
    for path in KB.rglob("*.yaml"):
        text = path.read_text(encoding="utf-8")
        assert unicodedata.normalize("NFC", text) == text, path


def test_cli_ok(capsys, real_report):
    assert main([str(KB), "--processed", str(PROCESSED)]) == 0
    assert "OK" in capsys.readouterr().out


def test_cli_fails_on_broken_kb(kb_copy, capsys):
    _edit(kb_copy, "dish_list.yaml", lambda d: _dish(d, "thit-luoc")["main"].append("thịt rồng"))
    assert main([str(kb_copy), "--processed", str(PROCESSED)]) == 1
    assert "thịt rồng" in capsys.readouterr().err


# ------------------------------------------------------------- each check fires


def test_unknown_dish_ingredient(kb_copy):
    _edit(kb_copy, "dish_list.yaml", lambda d: _dish(d, "canh-cua-rau-day-mong-toi")["seasonings"].append("bột cua"))
    assert "'bột cua' not in ingredients.yaml" in _errors(kb_copy)


def test_duplicate_ingredient_name(kb_copy):
    def dup(d):
        d["ingredients"].append(dict(_ing(d, "muối")))

    _edit(kb_copy, "ingredients.yaml", dup)
    assert "duplicate name_vi muối" in _errors(kb_copy)


def test_duplicate_dish_slug_and_name(kb_copy):
    def dup(d):
        d["dishes"].append(dict(_dish(d, "thit-luoc")))

    _edit(kb_copy, "dish_list.yaml", dup)
    errs = _errors(kb_copy)
    assert "duplicate slug thit-luoc" in errs
    assert "duplicate name thịt luộc" in errs


def test_fct_code_must_exist(kb_copy):
    _edit(kb_copy, "ingredients.yaml", lambda d: _ing(d, "rau muống")["comp_source"].update(code="99999"))
    assert "fct2007 code 99999 not in processed table" in _errors(kb_copy)


def test_source_name_must_match_table(kb_copy):
    _edit(kb_copy, "ingredients.yaml", lambda d: _ing(d, "sả")["comp_source"].update(source_name="Lemon"))
    assert "source_name 'Lemon'" in _errors(kb_copy)


def test_null_source_needs_reason(kb_copy):
    _edit(kb_copy, "ingredients.yaml", lambda d: _ing(d, "lá giang").update(comp_source={"source": None}))
    assert "needs a reason" in _errors(kb_copy)


def test_unknown_allergen_and_group(kb_copy):
    def bad(d):
        _ing(d, "lạc")["allergens"] = ["peanut"]
        _ing(d, "tỏi")["food_group"] = "rau_gia_vi"

    _edit(kb_copy, "ingredients.yaml", bad)
    errs = _errors(kb_copy)
    assert "unknown allergen peanut" in errs
    assert "unknown food group rau_gia_vi" in errs


def test_units_must_be_positive(kb_copy):
    _edit(kb_copy, "ingredients.yaml", lambda d: _ing(d, "trứng gà")["units"][0].update(grams_per_unit=0))
    assert "greater than 0" in _errors(kb_copy)


def test_unknown_unit_code(kb_copy):
    _edit(kb_copy, "ingredients.yaml", lambda d: _ing(d, "trứng gà")["units"][0].update(unit_code="vi"))
    assert "unknown unit vi" in _errors(kb_copy)


def test_vegetarian_flag_must_match_ingredients(kb_copy):
    def bad(d):
        _dish(d, "thit-luoc")["vegetarian"] = True  # pork
        _dish(d, "cai-ngot-xao-toi")["seasonings"].append("nước mắm")  # fish sauce in a 'chay' dish
        _dish(d, "rau-muong-luoc")["seasonings"] = ["muối"]  # now vegetarian but flagged false

    _edit(kb_copy, "dish_list.yaml", bad)
    errs = _errors(kb_copy)
    assert "thit-luoc: marked vegetarian but uses ['thịt ba chỉ']" in errs
    assert "cai-ngot-xao-toi: marked vegetarian but uses ['nước mắm']" in errs
    assert "rau-muong-luoc: no excluded ingredient" in errs


def test_core_staples_required(kb_copy):
    _edit(kb_copy, "ingredients.yaml", lambda d: _ing(d, "nước mắm").update(is_staple=False))
    assert "core seasoning 'nước mắm' is not a staple" in _errors(kb_copy)


def test_only_seasonings_can_be_staples(kb_copy):
    _edit(kb_copy, "ingredients.yaml", lambda d: _ing(d, "thịt ba chỉ").update(is_staple=True))
    errs = _errors(kb_copy)
    assert "staples: thịt ba chỉ is in group thit" in errs
    assert "staples: thịt ba chỉ must have shelf_life basis not_tracked" in errs


def test_foodkeeper_days_in_range(kb_copy):
    _edit(kb_copy, "ingredients.yaml", lambda d: _ing(d, "rau muống")["shelf_life"].update(days=30))
    assert "outside FoodKeeper range [1, 4]" in _errors(kb_copy)


def test_foodkeeper_product_must_exist(kb_copy):
    _edit(kb_copy, "ingredients.yaml", lambda d: _ing(d, "rau muống")["shelf_life"].update(foodkeeper_id=999999))
    assert "FoodKeeper product 999999 not found" in _errors(kb_copy)


def test_fish_needs_fish_allergen(kb_copy):
    _edit(kb_copy, "ingredients.yaml", lambda d: _ing(d, "cá thu").update(allergens=[]))
    assert "cá thu: group ca needs one of allergens ['ca']" in _errors(kb_copy)


def test_non_nfc_name_rejected(kb_copy):
    nfd = unicodedata.normalize("NFD", "rau muống")
    _edit(kb_copy, "ingredients.yaml", lambda d: _ing(d, "rau muống").update(name_vi=nfd))
    assert "not NFC" in _errors(kb_copy)


def test_synonym_cannot_shadow_other_ingredient(kb_copy):
    _edit(kb_copy, "ingredients.yaml", lambda d: _ing(d, "cải ngọt")["synonyms"]["vi"].append("cải thìa"))
    assert "synonym 'cải thìa' of cải ngọt is itself an ingredient name" in _errors(kb_copy)


def test_qty_levels_cover_every_group(kb_copy):
    _edit(kb_copy, "ref/qty_levels.yaml", lambda d: d["qty_levels"].pop("nam"))
    assert "no levels for food group nam" in _errors(kb_copy)


def test_qty_levels_must_not_decrease(kb_copy):
    _edit(kb_copy, "ref/qty_levels.yaml", lambda d: d["qty_levels"]["thit"].update(nhieu=[100, 200]))
    assert "must not decrease" in _errors(kb_copy)


def test_vegetarian_diet_must_exclude_animal_groups(kb_copy):
    _edit(kb_copy, "ref/diets.yaml", lambda d: d["diets"][0]["excluded_food_groups"].remove("gia_vi_dong_vat"))
    errs = _errors(kb_copy)
    assert "keeps animal-origin groups ['gia_vi_dong_vat']" in errs


# ------------------------------------------------------------- BR-ALG-01 over the whole catalog


def _dish_allergens():
    ings = yaml.safe_load((KB / "ingredients.yaml").read_text(encoding="utf-8"))["ingredients"]
    dishes = yaml.safe_load((KB / "dish_list.yaml").read_text(encoding="utf-8"))["dishes"]
    alg = {i["name_vi"]: set(i["allergens"]) for i in ings}
    return {d["slug"]: set().union(*(alg[n] for n in d["main"] + d["seasonings"])) for d in dishes}


@pytest.mark.parametrize(
    "slug, allergen",
    [
        ("canh-chua-ca-loc", "ca"),
        ("rau-muong-xao-toi", "ca"),  # nước mắm is a staple but still carries the fish allergen
        ("bo-xao-hanh-tay", "nhuyen_the"),  # dầu hào
        ("canh-cua-rau-day-mong-toi", "giap_xac"),
        ("nem-ran", "trung"),
        ("dau-phu-sot-ca-chua", "dau_nanh"),
        ("nam-kim-cham-xao-bo-toi", "sua"),  # bơ
        ("canh-bi-do-dau-phong", "dau_phong"),
        ("mi-can-kho-sa", "gluten"),
    ],
)
def test_dish_allergens_include_seasonings(slug, allergen):
    assert allergen in _dish_allergens()[slug]


def test_some_dishes_are_free_of_each_major_allergen():
    """BR-ALG-01 filtering must leave a usable catalog for every single allergen."""
    by_dish = _dish_allergens()
    for code in ("ca", "giap_xac", "trung", "dau_nanh", "gluten", "sua", "dau_phong", "vung", "hat_cay", "nhuyen_the"):
        assert sum(code not in a for a in by_dish.values()) >= 50, code
