"""Recipe files of the knowledge base: ``data/kb/recipes/<slot>/<slug>.yaml``.

One file = one recipe (tables ``recipes``, ``recipe_ingredients``, ``recipe_steps``, ``recipe_tags``,
``recipe_sources`` of ``docs/sad/model.yaml``). Grams are as-purchased weight for ``servings`` portions
(BR-QTY-01); seasonings are listed explicitly so allergen and diet checks cover them (BR-ALG-01).

Run from the repo root::

    uv run --package tastoria-ml python -m tastoria_ml.kb.recipes data/kb

Checks on top of the per-file shape (:class:`Recipe`):

- file sits at ``recipes/<slot>/<slug>.yaml`` matching its own ``slot`` and ``slug``; slugs are unique;
- the slug is in ``dish_list.yaml`` with the same name, slot and method;
- every ingredient name resolves to ``ingredients.yaml`` or an ``ingredients_proposed*.yaml`` file
  (canonical names only, not synonyms); method and tag codes exist in ``ref/``;
- a recipe whose dish is marked vegetarian uses nothing from the groups the "chay" diet excludes.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, PositiveInt, ValidationError, model_validator

from tastoria_ml.kb.models import Code, IngredientsFile, Slug, Text
from tastoria_ml.kb.validate import VEGETARIAN_DIET, KB, load_kb

Url = Annotated[str, Field(pattern=r"^https?://\S+$")]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RecipeIngredient(_Strict):
    name: Text
    grams: PositiveFloat
    role: Literal["main", "side", "seasoning"]
    optional: bool = False
    note: Text | None = None


class RecipeStep(_Strict):
    # step_no, not `no`: YAML 1.1 (PyYAML) reads a bare `no` key as the boolean False.
    step_no: PositiveInt
    text_vi: Text
    kind: Literal["active", "passive"]
    minutes: PositiveInt
    uses_burner: bool = False


class RecipeSource(_Strict):
    url: Url
    title: Text
    accessed_on: dt.date


class Recipe(_Strict):
    slug: Slug
    name_vi: Text
    slot: Literal["man", "rau", "canh"]
    servings: PositiveInt
    method: Code
    tags: list[Code] = []
    ingredients: list[RecipeIngredient] = Field(min_length=1)
    steps: list[RecipeStep] = Field(min_length=2)
    sources: list[RecipeSource] = Field(min_length=1)
    notes: Text | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Recipe:
        names = [i.name for i in self.ingredients]
        dup = sorted(n for n, c in Counter(names).items() if c > 1)
        if dup:
            raise ValueError(f"ingredient listed twice: {dup}")
        if not any(i.role == "main" and not i.optional for i in self.ingredients):
            raise ValueError("needs at least one non-optional main ingredient")
        if [s.step_no for s in self.steps] != list(range(1, len(self.steps) + 1)):
            raise ValueError("steps must be numbered 1..n in order")
        if len(self.tags) != len(set(self.tags)):
            raise ValueError("duplicate tag")
        urls = [s.url for s in self.sources]
        if len(urls) != len(set(urls)):
            raise ValueError("duplicate source url")
        return self

    @property
    def total_minutes(self) -> int:
        return sum(s.minutes for s in self.steps)


@dataclass
class RecipeReport:
    recipes: dict[Path, Recipe] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def proposed_files(kb_dir: Path) -> list[Path]:
    return sorted(Path(kb_dir).glob("ingredients_proposed*.yaml"))


def load_proposed(kb_dir: Path) -> tuple[list, list[str]]:
    """Ingredients proposed by recipe authors, same shape as ``ingredients.yaml``."""
    out, errors = [], []
    for path in proposed_files(kb_dir):
        try:
            out.extend(IngredientsFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8"))).ingredients)
        except (yaml.YAMLError, ValidationError) as exc:
            errors.append(f"{path.name}: {exc}")
    return out, errors


def load_recipes(kb_dir: Path) -> RecipeReport:
    rep = RecipeReport()
    for path in sorted((Path(kb_dir) / "recipes").glob("*/*.yaml")):
        rel = path.relative_to(kb_dir)
        try:
            rep.recipes[path] = Recipe.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        except yaml.YAMLError as exc:
            rep.errors.append(f"{rel}: YAML error: {exc}")
        except ValidationError as exc:
            for err in exc.errors():
                loc = ".".join(str(p) for p in err["loc"])
                rep.errors.append(f"{rel}: {loc}: {err['msg']}")
    return rep


def check_recipes(kb_dir: Path, kb: KB | None = None) -> RecipeReport:
    kb_dir = Path(kb_dir)
    rep = load_recipes(kb_dir)
    err = rep.errors.append
    if kb is None:
        kb, errors = load_kb(kb_dir)
        if kb is None:
            rep.errors.extend(errors)
            return rep
    proposed, perrs = load_proposed(kb_dir)
    rep.errors.extend(perrs)

    ingredients = {i.name_vi: i for i in kb.ingredients.ingredients}
    for p in proposed:
        if p.name_vi in ingredients:
            err(f"proposed ingredient {p.name_vi!r} already exists")
        ingredients.setdefault(p.name_vi, p)
    methods = {m.code for m in kb.methods.cooking_methods}
    tags = {t.code for t in kb.tags.tags}
    dishes = {d.slug: d for d in kb.dishes.dishes}
    diets = {d.code: d for d in kb.diets.diets}
    excluded = set(diets[VEGETARIAN_DIET].excluded_food_groups) if VEGETARIAN_DIET in diets else set()

    for d in sorted(s for s, n in Counter(r.slug for r in rep.recipes.values()).items() if n > 1):
        err(f"recipes: duplicate slug {d}")
    for path, r in rep.recipes.items():
        where = str(path.relative_to(kb_dir))
        if path.stem != r.slug or path.parent.name != r.slot:
            err(f"{where}: file must be recipes/{r.slot}/{r.slug}.yaml")
        dish = dishes.get(r.slug)
        if dish is None:
            err(f"{where}: slug not in dish_list.yaml")
        else:
            for attr, mine in (("name_vi", r.name_vi), ("slot", r.slot), ("method", r.method)):
                if getattr(dish, attr) != mine:
                    err(f"{where}: {attr} {mine!r} != dish_list {getattr(dish, attr)!r}")
        if r.method not in methods:
            err(f"{where}: unknown method {r.method}")
        for t in r.tags:
            if t not in tags:
                err(f"{where}: unknown tag {t}")
        unknown = [i.name for i in r.ingredients if i.name not in ingredients]
        for n in unknown:
            err(f"{where}: ingredient {n!r} not in ingredients.yaml or a proposed file")
        if dish is not None and dish.vegetarian and not unknown:
            bad = sorted(i.name for i in r.ingredients if ingredients[i.name].food_group in excluded)
            if bad:
                err(f"{where}: dish is vegetarian but recipe uses {bad}")
    return rep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Validate data/kb/recipes/**")
    ap.add_argument("kb_dir", type=Path)
    args = ap.parse_args(argv)
    rep = check_recipes(args.kb_dir)
    print(f"recipes: {len(rep.recipes)} ({dict(Counter(r.slot for r in rep.recipes.values()))})")
    if rep.errors:
        print(f"\n{len(rep.errors)} error(s):", file=sys.stderr)
        for e in rep.errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
