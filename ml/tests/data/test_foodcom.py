"""Food.com Recipes and Interactions (Kaggle shuyangli94/food-com-recipes-and-user-interactions).

Two kinds of tests:
- small synthetic CSVs, checking parsing rules (rating 0 = review without stars, size guard);
- the real processed tables, checking scale against the numbers the paper reports.
  They are built from data/raw/foodcom/ on first use; if the raw files are missing, run
  `uv run --package tastoria-ml python -m tastoria_ml.data.foodcom` first.
"""

import json
import math
from pathlib import Path

import pandas as pd
import pytest

from tastoria_ml.data import foodcom

REPO = Path(__file__).resolve().parents[3]
RAW_DIR = REPO / "data" / "raw" / "foodcom"
OUT_DIR = REPO / "data" / "processed" / "foodcom"


# ---------- synthetic fixtures ----------

RECIPES_CSV = """name,id,minutes,contributor_id,submitted,tags,nutrition,n_steps,steps,description,ingredients,n_ingredients
arriba   baked winter squash mexican style,137739,55,47892,2005-09-16,"['60-minutes-or-less', 'vegetables']","[51.5, 0.0, 13.0, 0.0, 2.0, 0.0, 4.0]",11,"['make a choice']",autumn is my favorite time,"['winter squash', 'honey']",2
,999,10,1,2010-01-01,[],"[1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]",1,"['x']",,['salt'],1
"""

INTERACTIONS_CSV = """user_id,recipe_id,date,rating,review
38094,137739,2003-02-17,4,Great with a salad.
1293707,137739,2011-12-21,0,"So simple, so delicious!"
8937,999,2002-12-01,5,
"""


@pytest.fixture
def tiny_raw(tmp_path):
    (tmp_path / "RAW_recipes.csv").write_text(RECIPES_CSV)
    (tmp_path / "RAW_interactions.csv").write_text(INTERACTIONS_CSV)
    return tmp_path


def test_build_tiny_schema(tiny_raw, tmp_path):
    out = tmp_path / "out"
    stats = foodcom.build(tiny_raw, out, check_scale=False)
    rec = pd.read_parquet(out / "recipes.parquet")
    inter = pd.read_parquet(out / "interactions.parquet")
    assert list(rec.columns) == [
        "recipe_id", "name", "minutes", "tags", "nutrition", "n_steps", "ingredients", "n_ingredients",
    ]
    assert list(inter.columns) == ["user_id", "recipe_id", "date", "rating", "has_rating"]
    r = rec.set_index("recipe_id").loc[137739]
    assert list(r.tags) == ["60-minutes-or-less", "vegetables"]
    assert list(r.nutrition) == [51.5, 0.0, 13.0, 0.0, 2.0, 0.0, 4.0]
    assert list(r.ingredients) == ["winter squash", "honey"]
    # a missing name stays missing, it does not become the string "nan"
    assert pd.isna(rec.set_index("recipe_id").loc[999, "name"])
    assert stats["n_recipes"] == 2 and stats["n_users"] == 3 and stats["n_interactions"] == 3
    assert stats["n_rated"] == 2
    assert stats["date_min"] == "2002-12-01" and stats["date_max"] == "2011-12-21"
    assert stats["rating_hist"] == {"0": 1, "4": 1, "5": 1}
    assert json.loads((out / "stats.json").read_text()) == stats


def test_zero_rating_flag_tiny(tiny_raw, tmp_path):
    foodcom.build(tiny_raw, tmp_path / "out", check_scale=False)
    inter = pd.read_parquet(tmp_path / "out" / "interactions.parquet")
    # the row is kept, the rating stays 0, only the flag says "no stars"
    assert len(inter) == 3
    z = inter[inter.rating == 0]
    assert len(z) == 1 and not z.has_rating.any()
    assert inter[inter.rating > 0].has_rating.all()


def test_scale_check_rejects_small_table(tiny_raw, tmp_path):
    with pytest.raises(ValueError, match="n_interactions"):
        foodcom.build(tiny_raw, tmp_path / "out")


def test_size_guard(tmp_path):
    f = tmp_path / "RAW_recipes.csv"
    f.write_bytes(b"x" * 1000)
    foodcom.check_size(f, 1000)
    foodcom.check_size(f, 1005)  # within 1%
    with pytest.raises(ValueError, match="size"):
        foodcom.check_size(f, 2000)


def test_published_sizes():
    # bytes reported by the Kaggle API for dataset version 2 (2019-11-08)
    assert foodcom.EXPECTED_BYTES["RAW_recipes.csv"] == 294_520_189
    assert foodcom.EXPECTED_BYTES["RAW_interactions.csv"] == 349_436_524
    assert math.isclose(foodcom.EXPECTED_BYTES["RAW_recipes.csv"] / 1e6, 295, rel_tol=0.01)
    assert math.isclose(foodcom.EXPECTED_BYTES["RAW_interactions.csv"] / 1e6, 349, rel_tol=0.01)


# ---------- real data ----------


@pytest.fixture(scope="module")
def stats():
    path = OUT_DIR / "stats.json"
    if not path.is_file():
        missing = [n for n in foodcom.FILES if not (RAW_DIR / n).is_file()]
        assert not missing, f"missing {missing}; run python -m tastoria_ml.data.foodcom"
        return foodcom.build(RAW_DIR, OUT_DIR)
    return json.loads(path.read_text())


@pytest.fixture(scope="module")
def interactions(stats):
    return pd.read_parquet(OUT_DIR / "interactions.parquet")


@pytest.fixture(scope="module")
def recipes(stats):
    return pd.read_parquet(OUT_DIR / "recipes.parquet")


def test_raw_files_match_published_size():
    for name in foodcom.FILES:
        foodcom.check_size(RAW_DIR / name, foodcom.EXPECTED_BYTES[name])


def test_foodcom_scale(stats):
    assert stats["n_interactions"] >= 1_000_000
    assert stats["n_recipes"] >= 230_000
    assert "2000" <= stats["date_min"][:4] and stats["date_max"][:4] <= "2018"


def test_foodcom_zero_rating_flag(interactions):
    z = interactions[interactions.rating == 0]
    assert len(z) > 0 and not z.has_rating.any()
    assert interactions[interactions.rating > 0].has_rating.all()


def test_foodcom_counts_consistent(stats, interactions, recipes):
    assert len(interactions) == stats["n_interactions"]
    assert len(recipes) == stats["n_recipes"] == recipes.recipe_id.nunique()
    assert interactions.user_id.nunique() == stats["n_users"]
    assert sum(stats["rating_hist"].values()) == stats["n_interactions"]
    assert stats["n_rated"] == int(interactions.has_rating.sum())
    assert set(interactions.rating.unique()) <= {0, 1, 2, 3, 4, 5}


def test_foodcom_nutrition_shape(recipes):
    # PDV-style nutrition: calories, total fat, sugar, sodium, protein, saturated fat, carbs
    assert recipes.nutrition.map(len).eq(7).all()
    assert (recipes.n_ingredients == recipes.ingredients.map(len)).mean() > 0.99
