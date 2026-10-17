"""Curated ingredient substitution table and the substitution evaluation queries.

Files (design v2 §6.3):

- ``data/kb/substitution_pairs.yaml``           -> table ``substitution_pairs`` (curated = true), candidate source (a);
- ``data/kb/substitution_eval/queries.yaml``    -> evaluation queries (dish, missing ingredient), no answers.

Run from the repo root::

    uv run --package tastoria-ml python -m tastoria_ml.kb.substitutes data/kb

Checks of the pair table:

- shape (:class:`SubstitutionPair`): NFC names, ratio > 0, 0 <= score <= 1, ``curated: true``, source is a URL or
  ``"kiến thức nấu ăn phổ biến: <lý do>"``;
- ``ingredient`` and ``substitute`` are canonical names of ``ingredients.yaml`` (or a proposed file), not synonyms;
- no self pair; unique by (ingredient, substitute, context_slot, context_method) — the DB unique key;
- ``context_method`` is a code of ``ref/cooking_methods.yaml``;
- same food group: the runtime hard filter (FR-17-05) drops cross-group pairs, so they would be dead data.

A substitute that carries an allergen group the original does not is allowed (the runtime BR-ALG-01 filter removes
it for affected users); :func:`added_allergens` lists those pairs for review.

Checks of the queries: unique ids and (slug, missing) pairs; the slug is a recipe; the missing ingredient is a line of
that recipe and not a staple; split is dev or test; no answer fields (answers come from two independent human
annotators, see ``substitution_eval/README.md``).
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, ValidationError, field_validator

from tastoria_ml.kb.models import Code, Ingredient, Slug, Text
from tastoria_ml.kb.recipes import load_proposed, load_recipes
from tastoria_ml.kb.validate import KB, load_kb

PAIRS_FILE = "substitution_pairs.yaml"
QUERIES_FILE = "substitution_eval/queries.yaml"
COMMON_KNOWLEDGE = "kiến thức nấu ăn phổ biến: "

Slot = Literal["man", "rau", "canh"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SubstitutionPair(_Strict):
    ingredient: Text
    substitute: Text
    context_slot: Slot | None
    context_method: Code | None
    ratio: PositiveFloat
    score: Annotated[float, Field(ge=0, le=1)]
    source: Text
    curated: Literal[True]

    @field_validator("source")
    @classmethod
    def _source(cls, v: str) -> str:
        if v.startswith(("https://", "http://")):
            return v
        if v.startswith(COMMON_KNOWLEDGE) and v[len(COMMON_KNOWLEDGE) :].strip():
            return v
        raise ValueError(f"source must be a URL or {COMMON_KNOWLEDGE!r} followed by the reasoning")

    @property
    def key(self) -> tuple[str, str, str | None, str | None]:
        return (self.ingredient, self.substitute, self.context_slot, self.context_method)


class SubstitutionPairsFile(_Strict):
    version: int
    pairs: list[SubstitutionPair] = Field(min_length=1)


class EvalQuery(_Strict):
    id: Annotated[str, Field(pattern=r"^q\d{3}$")]
    slug: Slug
    missing: Text
    split: Literal["dev", "test"]


class EvalQueriesFile(_Strict):
    version: int
    seed: int
    queries: list[EvalQuery] = Field(min_length=1)


@dataclass
class PairsReport:
    pairs: list[SubstitutionPair] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    added_allergens: list[tuple[SubstitutionPair, list[str]]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass
class QueriesReport:
    queries: list[EvalQuery] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _parse(path: Path, model: type[BaseModel], errors: list[str], rel: str) -> BaseModel | None:
    if not path.exists():
        errors.append(f"{rel}: missing")
        return None
    try:
        return model.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except yaml.YAMLError as exc:
        errors.append(f"{rel}: YAML error: {exc}")
    except ValidationError as exc:
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"])
            errors.append(f"{rel}: {loc}: {err['msg']}")
    return None


def _ingredients(kb_dir: Path, kb: KB, errors: list[str]) -> dict[str, Ingredient]:
    out = {i.name_vi: i for i in kb.ingredients.ingredients}
    proposed, perrs = load_proposed(kb_dir)
    errors.extend(perrs)
    for p in proposed:
        out.setdefault(p.name_vi, p)
    return out


def _kb(kb_dir: Path, kb: KB | None, errors: list[str]) -> KB | None:
    if kb is not None:
        return kb
    kb, errs = load_kb(kb_dir)
    errors.extend(errs)
    return kb


def added_allergens(pair: SubstitutionPair, ingredients: dict[str, Ingredient]) -> list[str]:
    """Allergen groups the substitute carries and the original does not."""
    a, b = ingredients[pair.ingredient], ingredients[pair.substitute]
    return sorted(set(b.allergens) - set(a.allergens))


def check_pairs(kb_dir: Path, kb: KB | None = None) -> PairsReport:
    kb_dir = Path(kb_dir)
    rep = PairsReport()
    err = rep.errors.append
    parsed = _parse(kb_dir / PAIRS_FILE, SubstitutionPairsFile, rep.errors, PAIRS_FILE)
    kb = _kb(kb_dir, kb, rep.errors)
    if parsed is None or kb is None:
        return rep
    assert isinstance(parsed, SubstitutionPairsFile)
    rep.pairs = list(parsed.pairs)
    ingredients = _ingredients(kb_dir, kb, rep.errors)
    methods = {m.code for m in kb.methods.cooking_methods}

    for key in sorted((k for k, n in Counter(p.key for p in rep.pairs).items() if n > 1), key=str):
        err(f"{PAIRS_FILE}: duplicate pair {key}")
    for i, p in enumerate(rep.pairs):
        where = f"{PAIRS_FILE}: pairs.{i} ({p.ingredient} -> {p.substitute})"
        unknown = [n for n in (p.ingredient, p.substitute) if n not in ingredients]
        for n in unknown:
            err(f"{where}: {n!r} is not a canonical name in ingredients.yaml")
        if p.ingredient == p.substitute:
            err(f"{where}: ingredient and substitute are the same")
        if p.context_method is not None and p.context_method not in methods:
            err(f"{where}: unknown cooking method {p.context_method}")
        if unknown:
            continue
        ga, gb = ingredients[p.ingredient].food_group, ingredients[p.substitute].food_group
        if ga != gb:
            err(f"{where}: food groups differ ({ga} vs {gb}); the runtime filter would never offer it")
        extra = added_allergens(p, ingredients)
        if extra:
            rep.added_allergens.append((p, extra))
    return rep


def check_queries(kb_dir: Path, kb: KB | None = None) -> QueriesReport:
    kb_dir = Path(kb_dir)
    rep = QueriesReport()
    err = rep.errors.append
    parsed = _parse(kb_dir / QUERIES_FILE, EvalQueriesFile, rep.errors, QUERIES_FILE)
    kb = _kb(kb_dir, kb, rep.errors)
    if parsed is None or kb is None:
        return rep
    assert isinstance(parsed, EvalQueriesFile)
    rep.queries = list(parsed.queries)
    ingredients = _ingredients(kb_dir, kb, rep.errors)
    recipes = {r.slug: r for r in load_recipes(kb_dir).recipes.values()}

    for d in sorted(k for k, n in Counter(q.id for q in rep.queries).items() if n > 1):
        err(f"{QUERIES_FILE}: duplicate id {d}")
    for d in sorted(k for k, n in Counter((q.slug, q.missing) for q in rep.queries).items() if n > 1):
        err(f"{QUERIES_FILE}: duplicate query {d}")
    for q in rep.queries:
        where = f"{QUERIES_FILE}: {q.id}"
        r = recipes.get(q.slug)
        if r is None:
            err(f"{where}: no recipe {q.slug}")
            continue
        if q.missing not in {i.name for i in r.ingredients}:
            err(f"{where}: {q.missing!r} is not an ingredient of {q.slug}")
        elif q.missing in ingredients and ingredients[q.missing].is_staple:
            err(f"{where}: {q.missing!r} is a staple (always in the kitchen, never missing)")
    return rep


def coverage(pairs: list[SubstitutionPair], queries: list[EvalQuery], kb_dir: Path) -> float:
    """Share of queries for which the table has at least one pair whose context fits the dish (FR-17-04 order)."""
    recipes = {r.slug: r for r in load_recipes(Path(kb_dir)).recipes.values()}
    hit = 0
    for q in queries:
        r = recipes[q.slug]
        if any(
            p.ingredient == q.missing and p.context_slot in (None, r.slot) and p.context_method in (None, r.method)
            for p in pairs
        ):
            hit += 1
    return hit / len(queries) if queries else 0.0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Validate data/kb/substitution_pairs.yaml and substitution_eval/")
    ap.add_argument("kb_dir", type=Path)
    args = ap.parse_args(argv)
    kb, errors = load_kb(args.kb_dir)
    if kb is None:
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    pr = check_pairs(args.kb_dir, kb)
    qr = check_queries(args.kb_dir, kb)
    web = sum(p.source.startswith("http") for p in pr.pairs)
    print(f"pairs: {len(pr.pairs)} (web source {web}, common knowledge {len(pr.pairs) - web})")
    print(f"  by slot: {dict(Counter(p.context_slot or 'any' for p in pr.pairs))}")
    print(f"  substitute adds allergen groups: {len(pr.added_allergens)}")
    for p, extra in pr.added_allergens:
        print(f"    {p.ingredient} -> {p.substitute}: {', '.join(extra)}")
    print(f"queries: {len(qr.queries)} ({dict(Counter(q.split for q in qr.queries))})")
    if pr.ok and qr.ok:
        print(f"  covered by the table: {coverage(pr.pairs, qr.queries, args.kb_dir):.0%}")
    errs = pr.errors + qr.errors
    if errs:
        print(f"\n{len(errs)} error(s):", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
