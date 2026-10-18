"""Incomplete block design of a survey form (UC23 step 6, UC24 step 4): pure functions, no database.

* `allocate` splits n items over the slots (man, rau, canh) in proportion to the number of published recipes per
  slot, by largest remainder (Hamilton): every slot gets ⌊n·w/W⌋ and the leftover goes to the largest fractional
  parts, ties broken at random so that a 10.5 / 10.5 split alternates between respondents instead of always
  favouring the same slot. When a slot has fewer candidates than its share, the excess is re-split over the other
  slots the same way. Without capping, every share is within 1 of n·w/W (FR-23-06, FR-24-02).
* `pick_balanced` draws k candidates of one slot, least-shown first: candidates are shuffled, then stably sorted by
  how many respondents of this form already got them. Over a run of respondents every non-anchor recipe of a slot is
  shown a number of times that differs by at most 1 from the others (the ratings per item stay balanced), while the
  set each person gets is still random.
"""

from __future__ import annotations

import random
from collections.abc import Hashable, Mapping, Sequence
from fractions import Fraction
from typing import TypeVar

K = TypeVar("K", bound=Hashable)


def allocate(n: int, weights: Mapping[str, int], capacity: Mapping[str, int], rng: random.Random) -> dict[str, int]:
    """Split `n` over the keys of `weights`, proportionally, never above `capacity[key]`."""
    keys = sorted(weights)
    if n < 0:
        raise ValueError("n must be >= 0")
    if n > sum(max(0, capacity.get(k, 0)) for k in keys):
        raise ValueError(f"cannot place {n} items into capacity {dict(capacity)}")
    alloc = dict.fromkeys(keys, 0)
    remaining = n
    active = [k for k in keys if capacity.get(k, 0) > 0]
    while remaining > 0:
        w = {k: weights[k] if any(weights[x] > 0 for x in active) else capacity[k] for k in active}
        total = sum(w.values())
        quota = {k: Fraction(remaining * w[k], total) for k in active}
        share = {k: int(quota[k]) for k in active}
        left = remaining - sum(share.values())
        tie = {k: rng.random() for k in active}
        for k in sorted(active, key=lambda k: (-(quota[k] - share[k]), tie[k]))[:left]:
            share[k] += 1
        for k in active:
            alloc[k] += min(share[k], capacity[k] - alloc[k])
        remaining = n - sum(alloc.values())
        active = [k for k in active if alloc[k] < capacity[k]]
    return alloc


def pick_balanced(candidates: Sequence[K], k: int, shown: Mapping[K, int], rng: random.Random) -> list[K]:
    """k distinct candidates, those shown least often so far first, random among equals."""
    if k > len(candidates):
        raise ValueError(f"need {k} candidates, have {len(candidates)}")
    pool = list(candidates)
    rng.shuffle(pool)
    pool.sort(key=lambda c: shown.get(c, 0))  # stable: the shuffle breaks ties
    return pool[:k]


def pick_stratified(
    by_slot: Mapping[str, Sequence[K]], n: int, weights: Mapping[str, int], rng: random.Random,
    shown: Mapping[K, int] | None = None,
) -> list[K]:  # fmt: skip
    """n candidates spread over slots by `allocate`; within a slot least-shown first (`shown` empty = plain random)."""
    quota = allocate(n, weights, {s: len(c) for s, c in by_slot.items()}, rng)
    out: list[K] = []
    for slot in sorted(quota):
        out += pick_balanced(by_slot.get(slot, ()), quota[slot], shown or {}, rng)
    return out
