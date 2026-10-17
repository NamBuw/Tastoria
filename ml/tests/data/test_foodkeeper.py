import math
from pathlib import Path

import pytest

from tastoria_ml.data.foodkeeper import build, to_days

REPO = Path(__file__).resolve().parents[3]
RAW_JSON = REPO / "data" / "raw" / "foodkeeper" / "foodkeeper.json"


@pytest.fixture(scope="module")
def products():
    if not RAW_JSON.exists():
        pytest.skip(f"missing {RAW_JSON}; run python -m tastoria_ml.data.foodkeeper")
    return build(RAW_JSON)


def test_foodkeeper_days_normalization():
    assert to_days(1, "Weeks") == 7
    assert to_days(2, "Months") == 60
    assert to_days(3, "Days") == 3
    assert math.isnan(to_days(1, "When ripe"))


def test_foodkeeper_days_edge_cases():
    assert to_days(1, "Years") == 365
    assert to_days(1, "Week") == 7  # singular form
    assert to_days(1, " months ") == 30  # case/whitespace
    assert math.isnan(to_days(None, "Days"))
    assert math.isnan(to_days(float("nan"), "Days"))
    assert math.isnan(to_days(2, None))


def test_foodkeeper_products(products):
    assert len(products) >= 300
    both = products.dropna(subset=["fridge_min_days", "fridge_max_days"])
    assert (both.fridge_min_days <= both.fridge_max_days).all()


def test_foodkeeper_columns(products):
    assert list(products.columns) == [
        "product_id", "category", "name", "subtitle", "keywords",
        "fridge_min_days", "fridge_max_days", "fridge_tips",
    ]
    assert products.product_id.is_unique


def test_foodkeeper_missing_is_nan_not_zero(products):
    # products without a fridge entry must be NaN, never 0
    assert not (products.fridge_max_days == 0).any()
