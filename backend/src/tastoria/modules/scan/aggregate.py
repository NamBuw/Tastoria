"""Boxes of 1–2 photos -> one chip per ingredient (FR-12-12, FR-12-13, FR-12-16, BR-SCAN-01). Pure functions.

* class -> ingredient through the default row of vision_class_ingredients; boxes of classes without a default
  ingredient are stored (detections) but make no chip;
* several classes of one ingredient make one chip (UC12 9b);
* count of a countable class = Σ over shelf groups of (max over the photos of that group of the boxes of the class
  in the photo): two photos of the same shelf see the same eggs; a photo marked "ngăn khác" adds;
  chip count = Σ over its countable classes; no countable class -> no model count (amount by level, FR-13-11);
* freshness of the chip = probabilities of its box with the largest u_img (the cautious choice, UC12 open question 1).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field

M = {"tuoi": 0.25, "dung_som": 0.65, "dung_ngay": 0.9, "kiem_tra": 1.2}  # BR-FRESH-02 (= pantry urgency.M)

Probs = tuple[float, float, float, float]  # tuoi, dung_som, dung_ngay, kiem_tra


@dataclass(frozen=True)
class FoundBox:
    image: int  # index of the photo in the scan (0-based)
    shelf_group: int
    vision_class_id: int
    confidence: float
    probs: Probs | None = None


@dataclass(frozen=True)
class ClassRule:
    countable: bool
    ingredient_id: uuid.UUID | None


@dataclass
class Chip:
    ingredient_id: uuid.UUID
    model_count: int | None
    boxes: list[int] = field(default_factory=list)  # indices into the input list
    best_confidence: float = 0.0
    probs: Probs | None = None


def u_img(p: Probs) -> float:
    return p[0] * M["tuoi"] + p[1] * M["dung_som"] + p[2] * M["dung_ngay"] + p[3] * M["kiem_tra"]


def build_chips(found: list[FoundBox], rules: dict[int, ClassRule]) -> list[Chip]:
    chips: dict[uuid.UUID, Chip] = {}
    # per (ingredient, class, shelf group, photo): number of boxes
    counts: dict[tuple[uuid.UUID, int, int, int], int] = defaultdict(int)
    for i, b in enumerate(found):
        rule = rules.get(b.vision_class_id)
        if rule is None or rule.ingredient_id is None:
            continue
        chip = chips.setdefault(rule.ingredient_id, Chip(rule.ingredient_id, None))
        chip.boxes.append(i)
        chip.best_confidence = max(chip.best_confidence, b.confidence)
        if b.probs is not None and (chip.probs is None or u_img(b.probs) > u_img(chip.probs)):
            chip.probs = b.probs
        if rule.countable:
            counts[(rule.ingredient_id, b.vision_class_id, b.shelf_group, b.image)] += 1
    per_group: dict[tuple[uuid.UUID, int, int], int] = defaultdict(int)  # max over photos of a shelf group
    for (ing, cls, group, _img), n in counts.items():
        per_group[(ing, cls, group)] = max(per_group[(ing, cls, group)], n)
    for (ing, _cls, _group), n in per_group.items():
        c = chips[ing]
        c.model_count = (c.model_count or 0) + n
    return sorted(chips.values(), key=lambda c: (-c.best_confidence, str(c.ingredient_id)))
