"""Recipe nutrition per serving (BR-NUT-05) and the energy of one 150 g bowl of cooked rice (BR-TRAY-03).

The ML team's `tastoria_ml.kb.nutrition` is the reference implementation (EuroFIR ingredient method with its
documented refuse / moisture / sodium overrides). When that package is importable (development, CI, the import
container), the catalog import calls it, so the API stores exactly the numbers of the nutrition report. When it is
not installed, `compute_fallback` applies the same formula without the per-ingredient overrides:

    n_k(recipe) = Σ_i  w_i · EP_i / 100 · n_ik · RF_ik,   RF = 1 (v2),
    EP_i = 1 − refuse_pct/100 for FCT 2007 rows (per 100 g edible), 1 for USDA rows (already edible part);
    optional ingredients are left out; a deep-fried recipe (method `chien` whose notes cite BR-NUT-05) counts only
    the absorbed oil = 5 g per 100 g of the other ingredients (Bognár 2002, BFE-R--02-03), capped at the oil used.

The two engines write different `data_version` prefixes (`nut-r1+…` vs `catalog-nut-r1+…`), so stored values always
say which rules produced them.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from tastoria.modules.catalog.bundle import Bundle, CompRow

NUTRIENTS = ("energy_kcal", "protein_g", "lipid_g", "glucid_g", "fiber_g", "sodium_mg")
RICE_BOWL_G = 150.0  # BR-TRAY-03
RICE_FCT_CODE = "1004"  # gạo tẻ máy
RICE_YIELD = 2.98  # cooked/raw weight, Bognár (2002) Part 1 Table 29, boiled polished long-grain rice
DEEP_FRY_UPTAKE_G_PER_100G = 5.0
DEEP_FRY_MARKER = "BR-NUT-05"
FRYING_OILS = frozenset({"dầu ăn", "dầu lạc", "dầu vừng", "dầu ô liu", "mỡ lợn"})
FALLBACK_RULES = "catalog-nut-r1"


@dataclass(frozen=True)
class NutritionResult:
    per_serving: dict[str, dict[str, float]]  # slug -> nutrient code -> value per serving
    data_version: str
    rice_bowl_kcal: float
    engine: str  # "tastoria_ml" | "catalog"


def compute(bundle: Bundle, processed: Path) -> NutritionResult:
    try:
        from tastoria_ml.kb import nutrition as ml  # type: ignore[import-not-found]
    except ImportError:
        return compute_fallback(bundle)
    return _with_ml(ml, bundle, processed)


def _with_ml(ml: object, bundle: Bundle, processed: Path) -> NutritionResult:
    resolver = ml.Resolver.from_dirs(bundle.root, processed)  # type: ignore[attr-defined]
    rep = ml.load_recipes(bundle.root)  # type: ignore[attr-defined]
    if rep.errors:
        raise ValueError("tastoria_ml could not read the recipes: " + "; ".join(rep.errors[:5]))
    out: dict[str, dict[str, float]] = {}
    for recipe in rep.recipes.values():
        row = ml.recipe_row(recipe, resolver)  # type: ignore[attr-defined]
        vals = {
            "energy_kcal": row.kcal_per_serving,
            "protein_g": row.protein_g,
            "lipid_g": row.lipid_g,
            "glucid_g": row.glucid_g,
            "fiber_g": row.fiber_g,
        }
        if row.sodium_mg is not None:
            vals["sodium_mg"] = row.sodium_mg
        out[recipe.slug] = {k: float(v) for k, v in vals.items()}
    bowl = ml.rice_bowl(resolver.fct)  # type: ignore[attr-defined]
    return NutritionResult(out, str(resolver.data_version), float(bowl["energy_kcal"]), "tastoria_ml")


def _sha8(bundle: Bundle, prefix: str) -> str:
    h = hashlib.sha256()
    for name in sorted(k for k in bundle.file_sha if k.startswith(prefix)):
        h.update(bundle.file_sha[name].encode())
    return h.hexdigest()[:8]


def compute_fallback(bundle: Bundle) -> NutritionResult:
    def comp(name: str) -> CompRow | None:
        cs = bundle.ingredients[name].comp_source
        return bundle.comp.get((cs.source, cs.code or "")) if cs.source else None

    out = {
        slug: per_serving(
            [(i.name, i.grams) for i in r.ingredients if not i.optional],
            comp,
            servings=r.servings,
            deep_fried=r.method == "chien" and DEEP_FRY_MARKER in (r.notes or ""),
        )
        for slug, r in bundle.recipes.items()
    }
    version = (
        f"{FALLBACK_RULES}+kb:{_sha8(bundle, 'ingredients')}{_sha8(bundle, 'recipes/')}"
        f"+fct2007:{_sha8(bundle, 'processed/fct2007')}+usda:{_sha8(bundle, 'processed/usda')}"
    )
    rice = bundle.comp.get(("fct2007", RICE_FCT_CODE))
    kcal = rice.values["energy_kcal"] * RICE_BOWL_G / RICE_YIELD / 100 if rice else 0.0
    return NutritionResult(out, version, round(kcal, 1), "catalog")


def per_serving(
    items: list[tuple[str, float]],
    comp: Callable[[str], CompRow | None],
    *,
    servings: int,
    deep_fried: bool = False,
) -> dict[str, float]:
    """Σ w·EP/100·n per nutrient, divided by servings; nutrients no ingredient has are absent."""
    oil_g = sum(g for n, g in items if n in FRYING_OILS) if deep_fried else 0.0
    absorbed = 0.0
    if oil_g:
        food_g = sum(g for n, g in items if n not in FRYING_OILS)
        absorbed = min(oil_g, DEEP_FRY_UPTAKE_G_PER_100G * food_g / 100)
    totals: dict[str, float] = {}
    for name, grams in items:
        row = comp(name)
        if row is None:
            continue
        ep = 1 - (row.refuse_pct or 0.0) / 100 if row.source == "fct2007" else 1.0
        counted = grams * ep
        if deep_fried and name in FRYING_OILS and oil_g:
            counted *= absorbed / oil_g
        for k in NUTRIENTS:
            if (v := row.values.get(k)) is not None:
                totals[k] = totals.get(k, 0.0) + counted * v / 100
    return {k: round(v / servings, 2) for k, v in totals.items()}
