"""Vision class table (data/kb/vision_classes.yaml): loading, checks and source-label mapping."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[4]
VISION_CLASSES = REPO / "data" / "kb" / "vision_classes.yaml"
INGREDIENTS = REPO / "data" / "kb" / "ingredients.yaml"
DISH_LIST = REPO / "data" / "kb" / "dish_list.yaml"

INSTANCE_DEFS = {"item", "group_of", "package"}


@dataclass(frozen=True)
class VisionClass:
    index: int
    id: str
    name_vi: str
    name_en: str
    ingredients: tuple[str, ...]
    countable: bool
    instance_def: str
    has_freshness_model: bool
    public_data: dict[str, tuple[str, ...]] = field(default_factory=dict)
    dish_main_count: int = 0


def load_classes(path: Path = VISION_CLASSES) -> list[VisionClass]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    out = []
    for i, c in enumerate(raw["classes"]):
        out.append(
            VisionClass(
                index=i,
                id=c["id"],
                name_vi=c["name_vi"],
                name_en=c["name_en"],
                ingredients=tuple(c["ingredients"]),
                countable=bool(c["countable"]),
                instance_def=c["instance_def"],
                has_freshness_model=bool(c["has_freshness_model"]),
                public_data={k: tuple(v) for k, v in (c.get("public_data") or {}).items()},
                dish_main_count=int(c["dish_main_count"]),
            )
        )
    return out


def source_label_map(classes: list[VisionClass], source: str) -> dict[str, VisionClass]:
    """Map an original label of ``source`` (e.g. 'openimages_v7' -> 'Tomato') to its vision class."""
    out: dict[str, VisionClass] = {}
    for c in classes:
        for label in c.public_data.get(source, ()):
            if label in out:
                raise ValueError(f"{source} label {label!r} mapped to both {out[label].id} and {c.id}")
            out[label] = c
    return out


def trained_classes(classes: list[VisionClass], sources: tuple[str, ...]) -> list[VisionClass]:
    """Classes that have at least one public source among ``sources`` (the public-data baseline)."""
    return [c for c in classes if any(s in c.public_data for s in sources)]


def validate(classes: list[VisionClass]) -> list[str]:
    """Return a list of problems; empty when the table is consistent with ingredients and dish list."""
    problems: list[str] = []
    ing = {i["name_vi"] for i in yaml.safe_load(INGREDIENTS.read_text(encoding="utf-8"))["ingredients"]}
    dishes = yaml.safe_load(DISH_LIST.read_text(encoding="utf-8"))["dishes"]
    ids = [c.id for c in classes]
    if len(set(ids)) != len(ids):
        problems.append("duplicate class id")
    for c in classes:
        if c.instance_def not in INSTANCE_DEFS:
            problems.append(f"{c.id}: instance_def {c.instance_def!r}")
        if c.countable and c.instance_def != "item":
            problems.append(f"{c.id}: countable classes must have instance_def item")
        for n in c.ingredients:
            if n not in ing:
                problems.append(f"{c.id}: ingredient {n!r} not in ingredients.yaml")
        n_dish = sum(1 for d in dishes if set(d["main"]) & set(c.ingredients))
        if n_dish != c.dish_main_count:
            problems.append(f"{c.id}: dish_main_count {c.dish_main_count} != counted {n_dish}")
        if n_dish == 0:
            problems.append(f"{c.id}: not a main ingredient of any dish")
    for src in {s for c in classes for s in c.public_data}:
        try:
            source_label_map(classes, src)
        except ValueError as e:
            problems.append(str(e))
    return problems
