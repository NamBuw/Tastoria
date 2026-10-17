import json
import math
import zipfile
from pathlib import Path

import pytest

from tastoria_ml.data import usda

RAW = Path(__file__).resolve().parents[3] / "data" / "raw" / "usda"
HAVE_RAW = any(RAW.glob("*foundation_food_json*.zip")) and any(RAW.glob("*sr_legacy_food_csv*.zip"))

COLUMNS = ["fdc_id", "data_type", "description", "category", "energy_kcal",
           "protein_g", "fat_g", "carb_g", "fiber_g", "sugars_g", "sodium_mg"]


# ---------- offline: tiny synthetic release in the real file layout ----------

def _fn(nid, amount, unit="g"):
    return {"nutrient": {"id": nid, "unitName": unit}, "amount": amount}


def _write_fake_release(d: Path) -> None:
    foundation = {"FoundationFoods": [
        {"fdcId": 1, "dataType": "Foundation", "description": "Kale, raw",
         "foodCategory": {"description": "Vegetables and Vegetable Products"},
         # no 1008: energy must fall back to Atwater specific (2048)
         "foodNutrients": [_fn(2047, 40.0, "kcal"), _fn(2048, 35.0, "kcal"),
                           _fn(1003, 2.9), _fn(1004, 1.5), _fn(1005, 4.4),
                           _fn(1093, 53.0, "mg")]},
        {"fdcId": 2, "dataType": "Foundation", "description": "Salt, table",
         "foodCategory": {"description": "Spices and Herbs"},
         "foodNutrients": [_fn(1008, 0.0, "kcal"), _fn(1093, 38758.0, "mg")]},
        None, None,  # the 2026-04-30 release ends its list with 32 null entries
    ]}
    with zipfile.ZipFile(d / "FoodData_Central_foundation_food_json_2026-04-30.zip", "w") as z:
        z.writestr("foundationDownload.json", json.dumps(foundation))

    files = {
        "food.csv": 'fdc_id,data_type,description,food_category_id,publication_date\n'
                    '10,sr_legacy_food,"Spinach, raw",11,2019-04-01\n'
                    '11,sr_legacy_food,"Water, tap",14,2019-04-01\n',
        "food_category.csv": 'id,code,description\n11,1100,Vegetables and Vegetable Products\n'
                             '14,1400,Beverages\n',
        "food_nutrient.csv": 'id,fdc_id,nutrient_id,amount\n'
                             '1,10,1008,23\n2,10,1003,2.86\n3,10,1004,0.39\n4,10,1005,3.63\n'
                             '5,10,1079,2.2\n6,10,2000,0.42\n7,10,1093,79\n8,11,1093,4\n',
    }
    with zipfile.ZipFile(d / "FoodData_Central_sr_legacy_food_csv_2018-04.zip", "w") as z:
        for name, text in files.items():
            z.writestr(f"FoodData_Central_sr_legacy_food_csv_2018-04/{name}", text)


def test_sr_legacy_row_count_mismatch_is_rejected(tmp_path):
    _write_fake_release(tmp_path)
    zp = tmp_path / "FoodData_Central_sr_legacy_food_csv_2018-04.zip"
    with zipfile.ZipFile(zp, "a") as z:
        z.writestr("FoodData_Central_sr_legacy_food_csv_2018-04/all_downloaded_table_record_counts.csv",
                   '"Table","Number of Records"\n"food","3"\n"food_nutrient","8"\n')
    with pytest.raises(ValueError, match="food.csv has 2 rows"):
        usda.build(tmp_path)


@pytest.fixture
def fake(tmp_path):
    _write_fake_release(tmp_path)
    return usda.build(tmp_path)


def test_build_columns_and_types(fake):
    assert len(fake) == 4
    assert list(fake.columns) == COLUMNS
    assert set(fake.data_type) == {"foundation_food", "sr_legacy_food"}
    assert fake.fdc_id.is_unique and fake.fdc_id.dtype.kind == "i"


def test_energy_falls_back_to_atwater_specific(fake):
    kale = fake.set_index("fdc_id").loc[1]
    assert kale.energy_kcal == 35.0 and kale.category == "Vegetables and Vegetable Products"


def test_missing_nutrient_is_nan_not_zero(fake):
    by = fake.set_index("fdc_id")
    assert math.isnan(by.loc[11, "energy_kcal"])      # water: no energy row at all
    assert math.isnan(by.loc[1, "fiber_g"])
    assert by.loc[2, "energy_kcal"] == 0.0            # a real reported 0 stays 0
    assert by.loc[10, "sugars_g"] == 0.42 and by.loc[10, "sodium_mg"] == 79


def test_latest_release_links_are_picked():
    page = ('<a href="/fdc-datasets/FoodData_Central_foundation_food_json_2025-12-18.zip">'
            '<a href="/fdc-datasets/FoodData_Central_foundation_food_json_2026-04-30.zip">'
            '<a href="/fdc-datasets/FoodData_Central_foundation_food_csv_2026-04-30.zip">'
            '<a href="/fdc-datasets/FoodData_Central_sr_legacy_food_csv_2018-04.zip">'
            '<a href="/fdc-datasets/FoodData_Central_sr_legacy_food_json_2018-04.zip">')
    urls = usda.latest_release_urls(page)
    assert urls == [
        "https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_foundation_food_json_2026-04-30.zip",
        "https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_sr_legacy_food_csv_2018-04.zip",
    ]


# ---------- real data (skipped until downloaded) ----------

real = pytest.mark.skipif(not HAVE_RAW, reason="USDA zips not downloaded to data/raw/usda")


@pytest.fixture(scope="module")
def usda_df():
    return usda.build(RAW)


# the plan's tests use the fixture name `usda`, which would shadow the module here
@pytest.fixture(name="usda")
def _usda(usda_df):
    return usda_df


@real
def test_usda_counts(usda):
    assert (usda.data_type == "sr_legacy_food").sum() >= 7000
    assert (usda.data_type == "foundation_food").sum() >= 200


@real
def test_usda_energy_coverage(usda):
    assert usda["energy_kcal"].notna().mean() >= 0.95


@real
def test_usda_spinach_raw(usda):
    row = usda[usda.description.str.fullmatch(r"Spinach, raw", case=False)]
    assert len(row) >= 1 and 15 <= row.energy_kcal.iloc[0] <= 30


@real
def test_usda_sr_legacy_matches_published_count(usda_df):
    # SR Legacy (April 2018) documentation: 7,793 food items.
    assert (usda_df.data_type == "sr_legacy_food").sum() == usda.SR_LEGACY_PUBLISHED_FOODS
    assert usda_df.fdc_id.is_unique
