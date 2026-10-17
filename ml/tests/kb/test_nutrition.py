"""Recipe nutrition (tastoria_ml.kb.nutrition): hand-computed fixture + sanity checks on the real KB."""

import datetime as dt
from pathlib import Path

import pytest

from tastoria_ml.kb import nutrition as nut
from tastoria_ml.kb.models import Ingredient
from tastoria_ml.kb.recipes import Recipe

REPO = Path(__file__).resolve().parents[3]
KB = REPO / "data" / "kb"


# ---------------------------------------------------------------- tiny fixture, numbers computed by hand


def _ing(name, source, code=None):
    cs = ({"source": None, "reason": "không có"} if source is None
          else {"source": source, "code": code, "source_name": name, "match": "exact"})
    return Ingredient.model_validate({
        "name_vi": name, "food_group": "thit", "comp_source": cs,
        "shelf_life": {"days": None, "basis": "not_tracked", "note": "x"},
    })


@pytest.fixture
def resolver():
    fct = {
        # E = 4·20 + 9·10 = 170; refuse 10 %
        "7001": nut.Comp(170, 20, 10, 0, 0, 50, 10.0),
        # E = 4·2 + 4·3 = 20; refuse 20 %
        "4001": nut.Comp(20, 2, 0, 3, 1, 10, 20.0),
        "6002": nut.Comp(900, 0, 100, 0, 0, None, 0.0),
        "1004": nut.Comp(344, 7.9, 1.0, 75.9, 0.4, 5, 0.0),
    }
    usda = {"1": nut.Comp(200, 18, 14, 0, 0, 80), "2": nut.Comp(370, 75, 1.9, 10, 0.6, 29)}
    ings = [_ing("thịt lợn", "fct2007", "7001"), _ing("rau", "fct2007", "4001"), _ing("dầu ăn", "fct2007", "6002"),
            _ing("cánh gà", "usda", "1"), _ing("mì căn", "usda", "2"), _ing("lá chanh", None),
            _ing("bột ngọt", None)]
    return nut.Resolver(ings, fct, usda, data_version="fixture")


def test_sum_with_edible_portion_and_uncovered_share(resolver):
    dn = nut.compute([("thịt lợn", 400), ("rau", 500), ("dầu ăn", 20), ("lá chanh", 5)], resolver)
    t = dn.totals
    # thịt 400·0.9 = 360 g -> 612 kcal, 72 P, 36 L, 180 mg Na
    # rau  500·0.8 = 400 g ->  80 kcal,  8 P, 12 G, 4 fibre, 40 mg Na
    # dầu  20 g            -> 180 kcal, 20 L
    assert t["energy_kcal"] == pytest.approx(872)
    assert t["protein_g"] == pytest.approx(80)
    assert t["lipid_g"] == pytest.approx(56)
    assert t["glucid_g"] == pytest.approx(12)
    assert t["fiber_g"] == pytest.approx(4)
    assert t["sodium_mg"] == pytest.approx(220)
    assert dn.uncovered_gram_share == pytest.approx(5 / 925)
    assert dn.atwater_kcal == pytest.approx(872)


def test_edible_weights_skip_refuse(resolver):
    dn = nut.compute([("thịt lợn", 400)], resolver, edible_weights=True)
    assert dn.totals["energy_kcal"] == pytest.approx(680)


def test_deep_fry_counts_only_absorbed_fat(resolver):
    # food 400 g as purchased -> 5 g / 100 g -> 20 g oil absorbed out of 300 g
    dn = nut.compute([("thịt lợn", 400), ("dầu ăn", 300)], resolver, deep_fried=True)
    assert dn.oil_absorbed_g == pytest.approx(20)
    assert dn.totals["energy_kcal"] == pytest.approx(612 + 180)
    # pan-fry: all oil counts
    pan = nut.compute([("thịt lợn", 400), ("dầu ăn", 300)], resolver)
    assert pan.totals["energy_kcal"] == pytest.approx(612 + 2700)


def test_absorbed_fat_capped_at_oil_used(resolver):
    dn = nut.compute([("thịt lợn", 1000), ("dầu ăn", 10)], resolver, deep_fried=True)
    assert dn.oil_absorbed_g == pytest.approx(10)


def test_bone_override_and_moisture_scale(resolver):
    # cánh gà bought with bone: USDA row is edible part, refuse borrowed from FCT 7013 (52 %)
    dn = nut.compute([("cánh gà", 600)], resolver)
    assert dn.totals["energy_kcal"] == pytest.approx(600 * 0.48 * 2.0)
    mc = nut.compute([("mì căn", 100)], resolver)
    assert mc.totals["energy_kcal"] == pytest.approx(370 * 32 / 91.8)


def test_sodium_only_ingredient(resolver):
    dn = nut.compute([("bột ngọt", 2)], resolver)
    assert dn.totals["energy_kcal"] == 0
    assert dn.totals["sodium_mg"] == pytest.approx(246)
    assert dn.uncovered_gram_share == 0


def _recipe(method="chien", notes=None, servings=4):
    return Recipe.model_validate({
        "slug": "mon-thu", "name_vi": "Món thử", "slot": "man", "servings": servings, "method": method,
        "ingredients": [{"name": "thịt lợn", "grams": 400, "role": "main"},
                        {"name": "dầu ăn", "grams": 300, "role": "seasoning"},
                        {"name": "rau", "grams": 100, "role": "side", "optional": True}],
        "steps": [{"step_no": 1, "text_vi": "a", "kind": "active", "minutes": 1},
                  {"step_no": 2, "text_vi": "b", "kind": "active", "minutes": 1}],
        "sources": [{"url": "https://example.org/x", "title": "x", "accessed_on": dt.date(2026, 10, 17)}],
        "notes": notes,
    })


def test_recipe_row_per_serving_deep_fry_marker_and_optional(resolver):
    fried = nut.recipe_row(_recipe(notes="Chiên ngập dầu (BR-NUT-05)."), resolver)
    assert fried.deep_fried
    assert fried.kcal_per_serving == pytest.approx((612 + 180) / 4, abs=0.05)
    assert fried.data_version == "fixture"
    pan = nut.recipe_row(_recipe(notes="Áp chảo."), resolver)
    assert not pan.deep_fried
    assert pan.kcal_per_serving == pytest.approx((612 + 2700) / 4, abs=0.05)


def test_rice_bowl(resolver):
    b = nut.rice_bowl(resolver.fct)
    assert b["raw_rice_g"] == pytest.approx(150 / 2.98, abs=0.05)
    assert b["energy_kcal"] == pytest.approx(150 / 2.98 * 3.44, abs=0.05)


def test_flags_ranges_and_atwater():
    row = nut.RecipeRow("x", "rau", 4, 400, 1, 1, 1, 0, None, 0, 0.5, False, 0, 400 * 0.5, "v")
    f = nut.flags(row)
    assert any("outside" in s for s in f)
    assert any("Atwater" in s for s in f)
    assert any("no composition" in s for s in f)


# ---------------------------------------------------------------- real KB

# Recipes outside the plausibility checks, each with the reason it is accepted (see docs/research/kiem-dinh-calo.md).
JUSTIFIED = {
    "canh-mang-chan-gio": "chân giò nhiều mỡ, nồi canh là món chính",
    "canh-xuong-ham-cu-cai": "xương ống chưa có thành phần (51 % khối lượng)",
    "ghe-hap-gung": "hải sản hấp, nạc, thải bỏ vỏ lớn",
    "muc-hap-gung": "hải sản hấp, nạc",
    "ngheu-hap-sa": "nghêu cả vỏ, phần ăn được 20 %",
    "tom-hap-sa": "tôm hấp, thải bỏ 54 %",
    "ca-bung": "có 300 g ba chỉ và đậu phụ, món rau nhưng đủ đạm",
    "dau-bap-luoc": "USDA đậu bắp: năng lượng theo hệ số Atwater riêng, carb gồm chất xơ",
    "goi-ga-bap-cai": "gỏi có thịt gà",
    "goi-ngo-sen-tom-thit": "gỏi có tôm và thịt ba chỉ",
    "ngon-su-su-xao-toi": "ngọn su su chưa có thành phần",
}


@pytest.fixture(scope="module")
def real(tmp_path_factory):
    out = tmp_path_factory.mktemp("kb")
    rows, bowl = nut.run(KB, out)
    return rows, bowl, out


def test_every_recipe_has_a_row(real):
    rows, _, out = real
    assert len(rows) == len(list((KB / "recipes").glob("*/*.yaml")))
    assert (out / "recipe_nutrition.csv").exists()
    assert all(r.kcal_per_serving > 0 for r in rows)
    assert len({r.data_version for r in rows}) == 1


def test_atwater_consistency(real):
    rows, _, _ = real
    for r in rows:
        dev = abs(r.atwater_kcal_per_serving / r.kcal_per_serving - 1)
        assert dev <= nut.ATWATER_TOLERANCE or r.slug in JUSTIFIED, (r.slug, dev)


def test_outliers_are_all_justified(real):
    rows, _, _ = real
    flagged = {r.slug for r in rows if nut.flags(r)}
    assert flagged <= set(JUSTIFIED), sorted(flagged - set(JUSTIFIED))


def test_slot_medians_plausible(real):
    rows, _, _ = real
    for slot, (lo, hi) in {"man": (180, 350), "rau": (40, 150), "canh": (50, 200)}.items():
        ks = sorted(r.kcal_per_serving for r in rows if r.slot == slot)
        assert lo <= ks[len(ks) // 2] <= hi, (slot, ks[len(ks) // 2])


def test_deep_fried_recipes_absorb_a_fraction_of_the_oil(real):
    rows, _, _ = real
    fried = [r for r in rows if r.deep_fried]
    assert len(fried) >= 5
    for r in fried:
        assert 0 < r.oil_absorbed_g


def test_rice_bowl_real(real):
    _, bowl, _ = real
    assert 150 <= bowl["energy_kcal"] <= 220


# ---------------------------------------------------------------- validation against Viện Dinh dưỡng (BR-NUT-06)

NIN = KB / "validation" / "nin_dishes.yaml"


def test_quantile_matches_numpy_type7():
    assert nut.quantile([1, 2, 3, 4, 5], 0.8) == pytest.approx(4.2)
    assert nut.quantile([0.5], 0.8) == 0.5


def test_nin_file_is_complete_and_up_to_date(tmp_path):
    import shutil

    import yaml

    stored = yaml.safe_load(NIN.read_text(encoding="utf-8"))
    dishes = stored["dishes"]
    assert len(dishes) >= 30
    assert len({d["nin_code"] for d in dishes}) == len(dishes)
    resolver = nut.Resolver.from_dirs(KB)
    for d in dishes:
        assert d["url"].startswith("https://viendinhduong.vn/")
        assert d["nin_kcal"] > 0
        assert d["composition"]
        for c in d["composition"]:
            if c["ingredient"]:
                resolver.resolve(c["ingredient"])  # raises on unknown names
    # recomputing must reproduce the stored numbers (no drift between code, data and the file)
    copy = tmp_path / "nin.yaml"
    shutil.copy(NIN, copy)
    summary = nut.validate_nin(copy, resolver)
    assert summary == stored["summary"]
    assert [d["our_kcal"] for d in yaml.safe_load(copy.read_text(encoding="utf-8"))["dishes"]] == \
        [d["our_kcal"] for d in dishes]
