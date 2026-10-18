"""Incomplete block design of the survey (TC-SURV-02, FR-23-06, FR-24-02): proportional split and balance."""

from __future__ import annotations

import random
from collections import Counter

from hypothesis import given, settings
from hypothesis import strategies as st

from tastoria.modules.survey.design import allocate, pick_balanced, pick_stratified

SLOTS = ("man", "rau", "canh")


@given(
    counts=st.tuples(st.integers(1, 80), st.integers(1, 80), st.integers(1, 80)),
    n=st.integers(0, 60),
    seed=st.integers(0, 2**32 - 1),
)
@settings(max_examples=300, deadline=None)
def test_allocation_is_within_one_of_the_proportional_share(counts, n, seed) -> None:
    weights = dict(zip(SLOTS, counts, strict=True))
    if n > sum(counts):
        return
    got = allocate(n, weights, weights, random.Random(seed))
    assert sum(got.values()) == n
    total = sum(counts)
    for s in SLOTS:
        assert 0 <= got[s] <= weights[s]
        assert abs(got[s] - n * weights[s] / total) < 1  # largest remainder: never a whole item off


def test_fr_23_06_example_40_30_30_gives_14_and_10_or_11() -> None:
    seen = Counter()
    for seed in range(200):
        got = allocate(35, {"man": 40, "rau": 30, "canh": 30}, {"man": 40, "rau": 30, "canh": 30}, random.Random(seed))
        assert got["man"] == 14 and {got["rau"], got["canh"]} == {10, 11}
        seen[got["rau"]] += 1
    assert seen[10] > 50 and seen[11] > 50  # the tie (10.5 / 10.5) goes either way, not always to the same slot


def test_capacity_shortfall_is_redistributed() -> None:
    got = allocate(10, {"man": 10, "rau": 10, "canh": 10}, {"man": 1, "rau": 20, "canh": 20}, random.Random(1))
    assert got["man"] == 1 and got["rau"] + got["canh"] == 9 and abs(got["rau"] - got["canh"]) <= 1


@given(seed=st.integers(0, 2**32 - 1), respondents=st.integers(1, 60))
@settings(max_examples=50, deadline=None)
def test_least_shown_first_keeps_exposure_balanced(seed, respondents) -> None:
    rng = random.Random(seed)
    items = list(range(57))
    shown: Counter[int] = Counter()
    for _ in range(respondents):
        got = pick_balanced(items, 12, shown, rng)
        assert len(set(got)) == 12
        shown.update(got)
    counts = [shown[i] for i in items]
    assert max(counts) - min(counts) <= 1


def test_stratified_pick_respects_slots_and_seed() -> None:
    by_slot = {
        "man": [f"m{i}" for i in range(80)],
        "rau": [f"r{i}" for i in range(50)],
        "canh": [f"c{i}" for i in range(41)],
    }
    w = {s: len(v) for s, v in by_slot.items()}
    a = pick_stratified(by_slot, 10, w, random.Random(7))
    b = pick_stratified(by_slot, 10, w, random.Random(7))
    assert a == b and len(set(a)) == 10
    per = Counter(x[0] for x in a)
    for s, letter in (("man", "m"), ("rau", "r"), ("canh", "c")):
        assert abs(per[letter] - 10 * w[s] / 171) < 1
