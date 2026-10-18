"""Chips from boxes: BR-SCAN-01 (max within a shelf, sum across shelves), FR-12-12 (one chip per ingredient),
FR-12-16 (u_img of the chip = its box with the largest u_img), FR-13-01 labels."""

from __future__ import annotations

import uuid

import pytest

from tastoria.modules.pantry.service import image_freshness
from tastoria.modules.scan.aggregate import ClassRule, FoundBox, build_chips, u_img

EGG, TOMATO, CHERRY, SPINACH, UNMAPPED = 1, 2, 3, 4, 5
ING_EGG, ING_TOMATO, ING_SPINACH = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
RULES = {
    EGG: ClassRule(True, ING_EGG),
    TOMATO: ClassRule(True, ING_TOMATO),
    CHERRY: ClassRule(True, ING_TOMATO),  # two classes, one ingredient (UC12 9b)
    SPINACH: ClassRule(False, ING_SPINACH),
    UNMAPPED: ClassRule(True, None),
}


def boxes(image: int, group: int, cls: int, n: int, conf: float = 0.5) -> list[FoundBox]:
    return [FoundBox(image, group, cls, conf) for _ in range(n)]


def by_ing(chips):  # noqa: ANN001
    return {c.ingredient_id: c for c in chips}


def test_same_shelf_takes_the_max_across_photos() -> None:  # FR-12-13
    chips = by_ing(build_chips(boxes(0, 1, EGG, 4) + boxes(1, 1, EGG, 3), RULES))
    assert chips[ING_EGG].model_count == 4
    assert len(chips[ING_EGG].boxes) == 7  # every box still points at the chip


def test_other_shelf_adds() -> None:  # FR-12-13
    chips = by_ing(build_chips(boxes(0, 1, EGG, 4) + boxes(1, 2, EGG, 3), RULES))
    assert chips[ING_EGG].model_count == 7


def test_classes_of_one_ingredient_make_one_chip() -> None:  # FR-12-12
    chips = build_chips(boxes(0, 1, TOMATO, 3) + boxes(0, 1, CHERRY, 1), RULES)
    assert len(chips) == 1
    assert chips[0].ingredient_id == ING_TOMATO and chips[0].model_count == 4 and len(chips[0].boxes) == 4


def test_count_is_per_class_then_summed() -> None:
    # photo 1: 3 tomatoes; photo 2 (same shelf): 2 cherry tomatoes -> max per class (3, 2) then sum = 5
    chips = by_ing(build_chips(boxes(0, 1, TOMATO, 3) + boxes(1, 1, CHERRY, 2), RULES))
    assert chips[ING_TOMATO].model_count == 5


def test_uncountable_class_has_no_model_count_and_unmapped_class_no_chip() -> None:
    chips = by_ing(build_chips(boxes(0, 1, SPINACH, 2) + boxes(0, 1, UNMAPPED, 5), RULES))
    assert set(chips) == {ING_SPINACH}
    assert chips[ING_SPINACH].model_count is None


def test_no_boxes_no_chips() -> None:  # UC12 9a
    assert build_chips([], RULES) == []


def test_chip_takes_the_box_with_the_largest_u_img_and_best_confidence() -> None:  # FR-12-16
    low = (0.8, 0.2, 0.0, 0.0)  # u = 0.33
    high = (0.1, 0.2, 0.6, 0.1)  # u = 0.815
    found = [FoundBox(0, 1, SPINACH, 0.9, low), FoundBox(1, 1, SPINACH, 0.4, high)]
    chip = build_chips(found, RULES)[0]
    assert chip.probs == high and chip.best_confidence == 0.9
    assert u_img(high) == pytest.approx(0.025 + 0.13 + 0.54 + 0.12)


def test_chips_ordered_by_confidence() -> None:
    chips = build_chips(boxes(0, 1, EGG, 1, 0.3) + boxes(0, 1, SPINACH, 1, 0.8), RULES)
    assert [c.ingredient_id for c in chips] == [ING_SPINACH, ING_EGG]


@pytest.mark.parametrize(
    ("probs", "label"),
    [
        ((1.0, 0.0, 0.0, 0.0), "tuoi"),  # u = 0.25
        ((0.0, 1.0, 0.0, 0.0), "dung_som"),  # u = 0.65
        ((0.0, 0.0, 1.0, 0.0), "dung_ngay"),  # u = 0.9
        ((0.3, 0.1, 0.2, 0.4), "kiem_tra"),  # u = 0.8 but P(kiểm tra) is the largest (FR-13-01)
        ((0.0, 0.0, 0.9, 0.1), "dung_ngay"),  # u = 0.93
        ((0.0, 0.0, 0.6, 0.4), "kiem_tra"),  # u = 1.02 > 1.0
    ],
)
def test_freshness_label_of_probabilities(probs, label) -> None:  # noqa: ANN001
    assert image_freshness(probs)[1] == label


def test_no_probabilities_no_label() -> None:
    assert image_freshness(None) is None
