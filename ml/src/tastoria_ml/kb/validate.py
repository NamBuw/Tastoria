"""Validate the recipe knowledge base in ``data/kb/``.

Run from the repo root::

    uv run --package tastoria-ml python -m tastoria_ml.kb.validate data/kb

Exit code 0 means no errors. The report also prints coverage counts (slots, vegetarian dishes,
composition-source mapping). Checks:

- every file parses into the pydantic models of :mod:`tastoria_ml.kb.models` (shape, NFC, units > 0);
- unique codes, ingredient names, Vietnamese synonyms (no synonym shadows another ingredient), dish
  slugs and dish names;
- every reference resolves: food groups, allergen groups, units, cooking methods, diet exclusions,
  qty_levels groups, dish ingredients (main + seasonings) -> ``ingredients.yaml``;
- ``comp_source`` codes exist in ``data/processed/fct2007/foods.csv`` / ``data/processed/usda/foods.csv``
  and ``source_name`` matches the table;
- FoodKeeper shelf lives point at a product with fridge days, and ``days`` lies in [min, max];
- staples are sane: the core seasonings are staples, staples are seasonings/oils only, and are not
  tracked for urgency;
- safety consistency: fish/seafood/egg/milk groups carry their allergen; a dish's ``vegetarian`` flag
  matches the "chay" diet exclusions over main + seasonings (BR-ALG-01: staples are checked too).
"""

from __future__ import annotations

import argparse
import csv
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import ValidationError

from tastoria_ml.kb.models import (
    AllergenGroupsFile,
    CookingMethodsFile,
    DietsFile,
    DishListFile,
    FoodGroupsFile,
    IngredientsFile,
    QtyLevelsFile,
    TagsFile,
    UnitsFile,
)

FILES = {
    "food_groups": ("ref/food_groups.yaml", FoodGroupsFile),
    "allergens": ("ref/allergen_groups.yaml", AllergenGroupsFile),
    "diets": ("ref/diets.yaml", DietsFile),
    "methods": ("ref/cooking_methods.yaml", CookingMethodsFile),
    "tags": ("ref/tags.yaml", TagsFile),
    "units": ("ref/units.yaml", UnitsFile),
    "qty": ("ref/qty_levels.yaml", QtyLevelsFile),
    "ingredients": ("ingredients.yaml", IngredientsFile),
    "dishes": ("dish_list.yaml", DishListFile),
}

# Seasonings every Vietnamese kitchen has; they must be staples (BR-TRAY-04 exempts them from stock checks).
CORE_STAPLES = frozenset({"muối", "đường", "nước mắm", "dầu ăn", "tiêu"})
STAPLE_GROUPS = frozenset({"gia_vi", "gia_vi_dong_vat", "dau_mo"})
MAX_STAPLES = 15
VEGETARIAN_DIET = "chay"
# Food group -> allergen codes of which at least one must be present.
GROUP_ALLERGENS = {
    "ca": {"ca"},
    "hai_san": {"giap_xac", "nhuyen_the"},
    "trung": {"trung"},
    "sua": {"sua"},
}


@dataclass
class KB:
    food_groups: FoodGroupsFile
    allergens: AllergenGroupsFile
    diets: DietsFile
    methods: CookingMethodsFile
    tags: TagsFile
    units: UnitsFile
    qty: QtyLevelsFile
    ingredients: IngredientsFile
    dishes: DishListFile


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    stats: dict[str, object] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


def _dupes(values) -> list:
    return sorted(v for v, n in Counter(values).items() if n > 1)


def load_kb(kb_dir: Path) -> tuple[KB | None, list[str]]:
    """Parse every KB file. Returns (kb, errors); kb is None when any file fails to parse."""
    errors: list[str] = []
    parsed: dict[str, object] = {}
    for key, (rel, model) in FILES.items():
        path = kb_dir / rel
        if not path.exists():
            errors.append(f"{rel}: missing")
            continue
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            parsed[key] = model.model_validate(raw)
        except yaml.YAMLError as exc:
            errors.append(f"{rel}: YAML error: {exc}")
        except ValidationError as exc:
            for err in exc.errors():
                loc = ".".join(str(p) for p in err["loc"])
                errors.append(f"{rel}: {loc}: {err['msg']}")
    if errors:
        return None, errors
    return KB(**parsed), errors


def _read_codes(path: Path, key: str, name_key: str) -> dict[str, str]:
    with path.open(encoding="utf-8") as fh:
        return {row[key]: row[name_key] for row in csv.DictReader(fh)}


def _read_foodkeeper(path: Path) -> dict[int, tuple[float | None, float | None]]:
    out: dict[int, tuple[float | None, float | None]] = {}
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            lo = float(row["fridge_min_days"]) if row["fridge_min_days"] else None
            hi = float(row["fridge_max_days"]) if row["fridge_max_days"] else None
            out[int(row["product_id"])] = (lo, hi)
    return out


def check(kb: KB, processed_dir: Path) -> Report:
    rep = Report()
    err = rep.errors.append

    group_codes = [g.code for g in kb.food_groups.food_groups]
    allergen_codes = [a.code for a in kb.allergens.allergen_groups]
    method_codes = [m.code for m in kb.methods.cooking_methods]
    unit_codes = [u.code for u in kb.units.units]
    for label, codes in [
        ("food_groups", group_codes),
        ("allergen_groups", allergen_codes),
        ("cooking_methods", method_codes),
        ("units", unit_codes),
        ("diets", [d.code for d in kb.diets.diets]),
        ("tags", [t.code for t in kb.tags.tags]),
    ]:
        for d in _dupes(codes):
            err(f"{label}: duplicate code {d}")
    groups, allergens, methods, units = set(group_codes), set(allergen_codes), set(method_codes), set(unit_codes)

    # diets
    diets = {d.code: d for d in kb.diets.diets}
    for d in kb.diets.diets:
        for g in d.excluded_food_groups:
            if g not in groups:
                err(f"diets: {d.code} excludes unknown food group {g}")
    if VEGETARIAN_DIET not in diets:
        err(f"diets: missing diet {VEGETARIAN_DIET}")
    animal = {g.code for g in kb.food_groups.food_groups if g.animal_origin}
    if VEGETARIAN_DIET in diets:
        missing = animal - set(diets[VEGETARIAN_DIET].excluded_food_groups) - {"sua"}
        if missing:
            err(f"diets: {VEGETARIAN_DIET} keeps animal-origin groups {sorted(missing)}")

    # qty levels
    for g in kb.qty.qty_levels:
        if g not in groups:
            err(f"qty_levels: unknown food group {g}")
    for g in sorted(groups - set(kb.qty.qty_levels)):
        err(f"qty_levels: no levels for food group {g}")

    # ingredients
    ings = kb.ingredients.ingredients
    names = [i.name_vi for i in ings]
    for d in _dupes(names):
        err(f"ingredients: duplicate name_vi {d}")
    by_name = {i.name_vi: i for i in ings}
    syn_owner: dict[str, str] = {}
    for i in ings:
        for s in i.synonyms.vi:
            if s in by_name:
                err(f"ingredients: synonym {s!r} of {i.name_vi} is itself an ingredient name")
            elif s in syn_owner and syn_owner[s] != i.name_vi:
                err(f"ingredients: synonym {s!r} shared by {syn_owner[s]} and {i.name_vi}")
            syn_owner.setdefault(s, i.name_vi)

    fct = _read_codes(processed_dir / "fct2007" / "foods.csv", "code", "name_vi")
    usda = _read_codes(processed_dir / "usda" / "foods.csv", "fdc_id", "description")
    fk = _read_foodkeeper(processed_dir / "foodkeeper" / "products.csv")

    for i in ings:
        where = f"ingredients: {i.name_vi}"
        if i.food_group not in groups:
            err(f"{where}: unknown food group {i.food_group}")
        for a in i.allergens:
            if a not in allergens:
                err(f"{where}: unknown allergen {a}")
        for u in i.units:
            if u.unit_code not in units:
                err(f"{where}: unknown unit {u.unit_code}")
        need = GROUP_ALLERGENS.get(i.food_group)
        if need and not need & set(i.allergens):
            err(f"{where}: group {i.food_group} needs one of allergens {sorted(need)}")
        cs = i.comp_source
        if cs.source is not None:
            table = fct if cs.source == "fct2007" else usda
            if cs.code not in table:
                err(f"{where}: {cs.source} code {cs.code} not in processed table")
            elif table[cs.code] != cs.source_name:
                err(f"{where}: source_name {cs.source_name!r} != table name {table[cs.code]!r}")
        sl = i.shelf_life
        if sl.basis == "foodkeeper":
            if sl.foodkeeper_id not in fk:
                err(f"{where}: FoodKeeper product {sl.foodkeeper_id} not found")
            else:
                lo, hi = fk[sl.foodkeeper_id]
                if lo is None or hi is None:
                    err(f"{where}: FoodKeeper product {sl.foodkeeper_id} has no fridge days")
                elif not lo <= sl.days <= hi:
                    err(f"{where}: shelf days {sl.days} outside FoodKeeper range [{lo:g}, {hi:g}]")

    # staples
    staples = {i.name_vi for i in ings if i.is_staple}
    for s in sorted(CORE_STAPLES - staples):
        err(f"staples: core seasoning {s!r} is not a staple" if s in by_name else f"staples: core seasoning {s!r} missing")
    for s in sorted(staples):
        i = by_name[s]
        if i.food_group not in STAPLE_GROUPS:
            err(f"staples: {s} is in group {i.food_group}; only seasonings and oils can be staples")
        if i.shelf_life.basis != "not_tracked":
            err(f"staples: {s} must have shelf_life basis not_tracked")
    if len(staples) > MAX_STAPLES:
        err(f"staples: {len(staples)} staples > {MAX_STAPLES}")

    # dishes
    dishes = kb.dishes.dishes
    for d in _dupes([x.slug for x in dishes]):
        err(f"dish_list: duplicate slug {d}")
    for d in _dupes([_fold(x.name_vi) for x in dishes]):
        err(f"dish_list: duplicate name {d}")
    ref_ids = [r.id for r in kb.dishes.references]
    for d in _dupes(ref_ids):
        err(f"dish_list: duplicate reference id {d}")
    excluded = set(diets[VEGETARIAN_DIET].excluded_food_groups) if VEGETARIAN_DIET in diets else set()
    for x in dishes:
        where = f"dish_list: {x.slug}"
        if x.method not in methods:
            err(f"{where}: unknown method {x.method}")
        unknown = [n for n in x.main + x.seasonings if n not in by_name]
        for n in unknown:
            err(f"{where}: ingredient {n!r} not in ingredients.yaml")
        if unknown:
            continue
        offending = sorted(n for n in x.main + x.seasonings if by_name[n].food_group in excluded)
        if x.vegetarian and offending:
            err(f"{where}: marked vegetarian but uses {offending}")
        if not x.vegetarian and not offending:
            err(f"{where}: no excluded ingredient, so it should be marked vegetarian")

    rep.stats = stats(kb)
    return rep


def _fold(s: str) -> str:
    return unicodedata.normalize("NFC", s).casefold()


def stats(kb: KB) -> dict[str, object]:
    dishes = kb.dishes.dishes
    ings = kb.ingredients.ingredients
    n = len(ings) or 1
    src = Counter(i.comp_source.source or "none" for i in ings)
    return {
        "dishes": len(dishes),
        "by_slot": dict(Counter(x.slot for x in dishes)),
        "vegetarian": sum(x.vegetarian for x in dishes),
        "vegetarian_by_slot": dict(Counter(x.slot for x in dishes if x.vegetarian)),
        "le_20_min": sum(x.minutes <= 20 for x in dishes),
        "by_region": dict(Counter(x.region for x in dishes)),
        "with_seen_in": sum(bool(x.seen_in) for x in dishes),
        "ingredients": len(ings),
        "staples": sorted(i.name_vi for i in ings if i.is_staple),
        "comp_source_pct": {k: round(100 * src.get(k, 0) / n, 1) for k in ("fct2007", "usda", "none")},
        "comp_match": dict(Counter(i.comp_source.match or "none" for i in ings)),
        "shelf_basis": dict(Counter(i.shelf_life.basis for i in ings)),
    }


def validate(kb_dir: Path, processed_dir: Path | None = None) -> Report:
    kb_dir = Path(kb_dir)
    processed_dir = Path(processed_dir) if processed_dir else kb_dir.parent / "processed"
    kb, errors = load_kb(kb_dir)
    if kb is None:
        return Report(errors=errors)
    return check(kb, processed_dir)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("kb_dir", type=Path, help="path to data/kb")
    ap.add_argument("--processed", type=Path, default=None, help="path to data/processed (default: <kb_dir>/../processed)")
    args = ap.parse_args(argv)
    rep = validate(args.kb_dir, args.processed)
    for k, v in rep.stats.items():
        print(f"{k}: {v}")
    if rep.errors:
        print(f"\n{len(rep.errors)} error(s):", file=sys.stderr)
        for e in rep.errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
