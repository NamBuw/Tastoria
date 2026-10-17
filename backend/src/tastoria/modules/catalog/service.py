"""catalog public interface (M04): reference data, recipes, ingredients, the offline snapshot, the bundle import
(UC25) and the read-only views other modules plan with (meal, pantry, substitute, cooking).

The hard filter primitive `recipe_allowed` lives here because every module that proposes food (meal, substitute)
must apply the same rule: a recipe is excluded when any of its lines — staples and optional lines included — or its
made-ahead item belongs to an excluded allergen group or food group (BR-ALG-01, BR-DIET-01).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, text, tuple_
from sqlalchemy.orm import Session

from tastoria.core import pagination
from tastoria.core.clock import utcnow
from tastoria.core.errors import ApiError, ProblemCode
from tastoria.core.text import fold
from tastoria.modules.catalog import importer
from tastoria.modules.catalog import nutrition as nut
from tastoria.modules.catalog.bundle import Bundle, load_bundle
from tastoria.modules.catalog.models import (
    AllergenGroup,
    CookingMethod,
    Diet,
    DietExclusion,
    FoodGroup,
    FoodItem,
    FoodNutrient,
    Ingredient,
    IngredientAllergen,
    IngredientSynonym,
    IngredientUnit,
    Nutrient,
    QtyLevel,
    Recipe,
    RecipeIngredient,
    RecipeMakeAhead,
    RecipeNutrition,
    RecipeSource,
    RecipeStep,
    RecipeTag,
    Tag,
)
from tastoria.modules.catalog.schemas import (
    AllergenGroupOut,
    CatalogSnapshot,
    CodeName,
    ConsentPurposeRef,
    DietOut,
    FoodNutrition,
    IngredientOut,
    IngredientPage,
    IngredientUnitOut,
    IngredientView,
    MakeAheadOut,
    MakeAheadView,
    NutrientOut,
    QtyLevelOut,
    RecipeIngredientOut,
    RecipeLine,
    RecipeNutrientOut,
    RecipeOut,
    RecipeSourceOut,
    RecipeStepOut,
    RecipeSummary,
    RecipeSummaryPage,
    RecipeView,
    ReferenceData,
    StepView,
    TagOut,
)

RICE_FCT_CODE = nut.RICE_FCT_CODE
STIR_FRY_METHOD = "xao"  # BR-COOK-01: "món xào xong cuối"


@dataclass(frozen=True)
class CatalogDeps:
    """Installed by tastoria.app: /reference lists consent purposes, owned by privacy (no import from here)."""

    consent_purposes: Callable[[Session], Sequence[object]]


def catalog_deps(request: Request) -> CatalogDeps:
    return request.app.state.catalog


# ---------------------------------------------------------------- small lookups (also used by profile)


def unknown_allergen_codes(session: Session, codes: Iterable[str]) -> list[str]:
    wanted = set(codes)
    if not wanted:
        return []
    known = set(session.scalars(select(AllergenGroup.code).where(AllergenGroup.code.in_(wanted))).all())
    return sorted(wanted - known)


def diet_exists(session: Session, code: str) -> bool:
    return session.get(Diet, code) is not None


def cooking_method_codes(session: Session) -> frozenset[str]:
    return frozenset(session.scalars(select(CookingMethod.code)).all())


def not_published_recipe_ids(session: Session, recipe_ids: Iterable[uuid.UUID]) -> list[uuid.UUID]:
    """Ids that do not exist or are not `published` (draft, retired)."""
    wanted = list(dict.fromkeys(recipe_ids))
    if not wanted:
        return []
    ok = set(session.scalars(select(Recipe.id).where(Recipe.id.in_(wanted), Recipe.status == "published")).all())
    return [r for r in wanted if r not in ok]


def excluded_food_groups(session: Session, diet_code: str | None) -> frozenset[str]:
    """Food groups a diet excludes (BR-DIET-01); none without a diet."""
    if diet_code is None:
        return frozenset()
    return frozenset(
        session.scalars(select(DietExclusion.food_group_code).where(DietExclusion.diet_code == diet_code)).all()
    )


def qty_level_grams(session: Session, food_group_code: str, level: str) -> tuple[float, float] | None:
    """[g_min, g_max] of ít/vừa/nhiều for a food group (BR-QTY-02)."""
    row = session.get(QtyLevel, (food_group_code, level))
    return (float(row.g_min), float(row.g_max)) if row else None


def recipe_allowed(recipe: RecipeView, allergens: Iterable[str], excluded_groups: Iterable[str]) -> bool:
    """Hard filter (BR-ALG-01, BR-DIET-01): False when any line (staples and optional lines too) or the make-ahead item
    is in one of `allergens` or in one of `excluded_groups`."""
    return not (recipe.allergen_codes & set(allergens)) and not (recipe.food_group_codes & set(excluded_groups))


def ingredient_allowed(ing: IngredientView, allergens: Iterable[str], excluded_groups: Iterable[str]) -> bool:
    return not (ing.allergen_codes & set(allergens)) and ing.food_group_code not in set(excluded_groups)


# ---------------------------------------------------------------- views


def ingredients_by_ids(session: Session, ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, IngredientView]:
    wanted = list(set(ids))
    if not wanted:
        return {}
    return _ingredient_views(session, select(Ingredient).where(Ingredient.id.in_(wanted)))


def active_ingredients(session: Session, food_group_code: str | None = None) -> dict[uuid.UUID, IngredientView]:
    q = select(Ingredient).where(Ingredient.is_active)
    if food_group_code is not None:
        q = q.where(Ingredient.food_group_code == food_group_code)
    return _ingredient_views(session, q)


def _ingredient_views(session: Session, query) -> dict[uuid.UUID, IngredientView]:  # noqa: ANN001
    rows = list(session.scalars(query))
    ids = [r.id for r in rows]
    if not ids:
        return {}
    allergens: dict[uuid.UUID, set[str]] = defaultdict(set)
    for iid, code in session.execute(
        select(IngredientAllergen.ingredient_id, IngredientAllergen.allergen_code).where(
            IngredientAllergen.ingredient_id.in_(ids)
        )
    ):
        allergens[iid].add(code)
    units: dict[uuid.UUID, dict[str, float]] = defaultdict(dict)
    for u in session.scalars(select(IngredientUnit).where(IngredientUnit.ingredient_id.in_(ids))):
        units[u.ingredient_id][u.unit_code] = float(u.grams_per_unit)
    return {
        r.id: IngredientView(
            id=r.id,
            name_vi=r.name_vi,
            food_group_code=r.food_group_code,
            is_staple=r.is_staple,
            countable=r.countable,
            shelf_life_days=float(r.shelf_life_days) if r.shelf_life_days is not None else None,
            is_active=r.is_active,
            allergen_codes=frozenset(allergens.get(r.id, ())),
            units=dict(units.get(r.id, {})),
        )
        for r in rows
    }


def _recipe_views(session: Session, recipes: list[Recipe]) -> list[RecipeView]:
    ids = [r.id for r in recipes]
    if not ids:
        return []
    lines = list(session.scalars(select(RecipeIngredient).where(RecipeIngredient.recipe_id.in_(ids))))
    makes = {m.recipe_id: m for m in session.scalars(select(RecipeMakeAhead).where(RecipeMakeAhead.recipe_id.in_(ids)))}
    ing = ingredients_by_ids(
        session, [ln.ingredient_id for ln in lines] + [m.item_ingredient_id for m in makes.values()]
    )
    steps: dict[uuid.UUID, list[StepView]] = defaultdict(list)
    for s in session.scalars(select(RecipeStep).where(RecipeStep.recipe_id.in_(ids)).order_by(RecipeStep.step_no)):
        steps[s.recipe_id].append(StepView(s.step_no, s.text_vi, s.kind, s.minutes, s.uses_burner))
    tags: dict[uuid.UUID, set[str]] = defaultdict(set)
    for rid, code in session.execute(
        select(RecipeTag.recipe_id, RecipeTag.tag_code).where(RecipeTag.recipe_id.in_(ids))
    ):
        tags[rid].add(code)
    kcal = dict(
        session.execute(
            select(RecipeNutrition.recipe_id, RecipeNutrition.per_serving).where(
                RecipeNutrition.recipe_id.in_(ids), RecipeNutrition.nutrient_code == "energy_kcal"
            )
        ).all()
    )
    by_recipe: dict[uuid.UUID, list[RecipeLine]] = defaultdict(list)
    for ln in sorted(lines, key=lambda x: (x.role != "main", x.role != "side", -float(x.grams))):
        by_recipe[ln.recipe_id].append(RecipeLine(ing[ln.ingredient_id], float(ln.grams), ln.role, ln.is_optional))
    out = []
    for r in recipes:
        m = makes.get(r.id)
        st = tuple(steps.get(r.id, ()))
        out.append(
            RecipeView(
                id=r.id,
                name_vi=r.name_vi,
                slot=r.slot,
                servings=r.servings,
                method_code=r.method_code,
                status=r.status,
                lines=tuple(by_recipe.get(r.id, ())),
                steps=st,
                tag_codes=frozenset(tags.get(r.id, ())),
                kcal_per_serving=float(kcal[r.id]) if r.id in kcal else None,
                make_ahead=MakeAheadView(ing[m.item_ingredient_id], m.through_step_no, m.through_step_no >= len(st))
                if m
                else None,
                created_at=r.created_at,
            )
        )
    return out


def published_recipes(session: Session, slot: str | None = None) -> list[RecipeView]:
    q = select(Recipe).where(Recipe.status == "published")
    if slot is not None:
        q = q.where(Recipe.slot == slot)
    return _recipe_views(session, list(session.scalars(q.order_by(Recipe.created_at, Recipe.id))))


def recipes_by_ids(session: Session, ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, RecipeView]:
    """Any status: plans and cook sessions keep using the version they were made with (BR-CATALOG-01)."""
    wanted = list(set(ids))
    if not wanted:
        return {}
    return {v.id: v for v in _recipe_views(session, list(session.scalars(select(Recipe).where(Recipe.id.in_(wanted)))))}


def ingredient_nutrition(session: Session, ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, FoodNutrition]:
    """Per 100 g as purchased (EP = 1 − refuse for FCT rows) — for recomputing a dish after a substitution
    (BR-NUT-05) and for the nutrition-vector neighbours of substitute (design v2 §6.3 c)."""
    wanted = list(set(ids))
    rows = session.execute(
        select(Ingredient.id, Ingredient.comp_source_id, Ingredient.comp_source_code, FoodItem.refuse_pct)
        .join(
            FoodItem,
            (FoodItem.source_id == Ingredient.comp_source_id) & (FoodItem.source_code == Ingredient.comp_source_code),
        )
        .where(Ingredient.id.in_(wanted))
    ).all()
    keys = {(r.comp_source_id, r.comp_source_code): r for r in rows}
    vals: dict[tuple[int, str], dict[str, float]] = defaultdict(dict)
    if keys:
        for fn in session.scalars(
            select(FoodNutrient).where(tuple_(FoodNutrient.source_id, FoodNutrient.source_code).in_(list(keys)))
        ):
            vals[(fn.source_id, fn.source_code)][fn.nutrient_code] = float(fn.per_100g)
    out = {i: FoodNutrition(i) for i in wanted}
    for k, r in keys.items():
        ep = 1 - float(r.refuse_pct or 0) / 100 if r.comp_source_id == importer.SOURCE_ID["fct2007"] else 1.0
        out[r.id] = FoodNutrition(r.id, {n: v * ep for n, v in vals[k].items()})
    return out


def rice_bowl_kcal(session: Session) -> float | None:
    """E_bát = energy of 150 g cooked rice from FCT 1004 gạo tẻ máy (BR-TRAY-03); None before the first import."""
    v = session.scalar(
        select(FoodNutrient.per_100g).where(
            FoodNutrient.source_id == importer.SOURCE_ID["fct2007"],
            FoodNutrient.source_code == RICE_FCT_CODE,
            FoodNutrient.nutrient_code == "energy_kcal",
        )
    )
    return round(float(v) * nut.RICE_BOWL_G / nut.RICE_YIELD / 100, 1) if v is not None else None


_DB_PARAM = text(
    "SELECT split_part(c, '=', 2) FROM pg_db_role_setting s CROSS JOIN LATERAL unnest(s.setconfig) c "
    "WHERE s.setdatabase = (SELECT oid FROM pg_database WHERE datname = current_database()) AND s.setrole = 0 "
    "AND split_part(c, '=', 1) = :k"
)


def db_param(session: Session, key: str) -> float | None:
    """A database-level parameter tastoria.<key> as stored now (pg_db_role_setting), not the value the pooled
    connection saw when it opened — so a catalog import takes effect without restarting the API."""
    v = session.scalar(_DB_PARAM, {"k": f"tastoria.{key}"})
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def kcal_half_width(session: Session) -> float | None:
    """BR-NUT-06 half width h of the calorie range; None = still calibrating (no range shown)."""
    return db_param(session, "kcal_half_width")


# ---------------------------------------------------------------- API: reference (public, ETag)


def _etag(payload: object) -> str:
    raw = json.dumps(jsonable_encoder(payload), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def get_reference(session: Session, deps: CatalogDeps) -> ReferenceData:
    excl: dict[str, list[str]] = defaultdict(list)
    for d in session.scalars(select(DietExclusion).order_by(DietExclusion.food_group_code)):
        excl[d.diet_code].append(d.food_group_code)
    body = {
        "allergen_groups": [
            AllergenGroupOut(code=a.code, name_vi=a.name_vi, name_en=a.name_en, basis=a.basis)  # type: ignore[arg-type]
            for a in session.scalars(select(AllergenGroup).order_by(AllergenGroup.code))
        ],
        "diets": [
            DietOut(code=d.code, name_vi=d.name_vi, excluded_food_group_codes=excl.get(d.code, []))
            for d in session.scalars(select(Diet).order_by(Diet.code))
        ],
        "food_groups": [
            CodeName(code=g.code, name_vi=g.name_vi)
            for g in session.scalars(select(FoodGroup).order_by(FoodGroup.code))
        ],
        "cooking_methods": [
            CodeName(code=m.code, name_vi=m.name_vi)
            for m in session.scalars(select(CookingMethod).order_by(CookingMethod.code))
        ],
        "tags": [
            TagOut(code=t.code, kind=t.kind, name_vi=t.name_vi) for t in session.scalars(select(Tag).order_by(Tag.code))
        ],  # type: ignore[arg-type]
        "nutrients": [
            NutrientOut(code=n.code, name_vi=n.name_vi, unit=n.unit)
            for n in session.scalars(select(Nutrient).order_by(Nutrient.code))
        ],
        "qty_levels": [
            QtyLevelOut(food_group_code=q.food_group_code, level=q.level, g_min=float(q.g_min), g_max=float(q.g_max))  # type: ignore[arg-type]
            for q in session.scalars(select(QtyLevel).order_by(QtyLevel.food_group_code, QtyLevel.level))
        ],
        "consent_purposes": [
            ConsentPurposeRef.model_validate(p, from_attributes=True) for p in deps.consent_purposes(session)
        ],
    }
    return ReferenceData(data_version=_etag(body), **body)


# ---------------------------------------------------------------- API: recipes, ingredients, snapshot


def _summary(v: RecipeView) -> RecipeSummary:
    return RecipeSummary(
        id=v.id,
        name_vi=v.name_vi,
        slot=v.slot,  # type: ignore[arg-type]
        servings=v.servings,
        method_code=v.method_code,
        total_minutes=sum(s.minutes for s in v.steps),
        kcal_per_serving=v.kcal_per_serving,
        tag_codes=sorted(v.tag_codes),
    )


def list_recipes(
    session: Session, *, q: str | None, slot: str | None, tag: str | None, cursor: str | None, limit: int
) -> RecipeSummaryPage:
    after = pagination.decode_created(cursor)
    views = published_recipes(session, slot)
    if tag:
        views = [v for v in views if tag in v.tag_codes]
    if q:
        needle = fold(q)
        views = [v for v in views if needle in fold(v.name_vi)]
    if after is not None:
        views = [v for v in views if (v.created_at, v.id) > after]  # type: ignore[operator]
    page = views[:limit]
    nxt = pagination.encode_created(page[-1].created_at, page[-1].id) if len(views) > limit else None  # type: ignore[arg-type]
    return RecipeSummaryPage(items=[_summary(v) for v in page], next_cursor=nxt)


def _recipe_out(session: Session, v: RecipeView, r: Recipe) -> RecipeOut:
    sources = session.scalars(select(RecipeSource).where(RecipeSource.recipe_id == v.id).order_by(RecipeSource.url))
    nutrients = list(
        session.scalars(
            select(RecipeNutrition).where(RecipeNutrition.recipe_id == v.id).order_by(RecipeNutrition.nutrient_code)
        )
    )
    return _recipe_out_from(v, r.notes, list(sources), nutrients)


def _recipe_out_from(
    v: RecipeView, notes: str | None, sources: list[RecipeSource], nutrients: list[RecipeNutrition]
) -> RecipeOut:
    m = v.make_ahead
    return RecipeOut(
        **_summary(v).model_dump(),
        status=v.status,  # type: ignore[arg-type]
        notes=notes,
        ingredients=[
            RecipeIngredientOut(
                ingredient_id=ln.ingredient.id,
                name_vi=ln.ingredient.name_vi,
                grams=ln.grams,
                role=ln.role,  # type: ignore[arg-type]
                is_optional=ln.is_optional,
                is_staple=ln.ingredient.is_staple,
                allergen_codes=sorted(ln.ingredient.allergen_codes),
            )
            for ln in v.lines
        ],
        steps=[
            RecipeStepOut(
                step_no=s.step_no, text_vi=s.text_vi, kind=s.kind, minutes=s.minutes, uses_burner=s.uses_burner
            )
            for s in v.steps
        ],  # type: ignore[arg-type]
        sources=[RecipeSourceOut(url=s.url, title=s.title, accessed_on=s.accessed_on) for s in sources],
        nutrition=[
            RecipeNutrientOut(nutrient_code=n.nutrient_code, per_serving=float(n.per_serving)) for n in nutrients
        ],
        nutrition_data_version=nutrients[0].data_version if nutrients else None,
        make_ahead=MakeAheadOut(
            item_ingredient_id=m.item.id,
            item_name_vi=m.item.name_vi,
            through_step_no=m.through_step_no,
            whole_dish=m.whole_dish,
        )
        if m
        else None,
    )


def get_recipe(session: Session, recipe_id: uuid.UUID) -> RecipeOut:
    """Published and retired recipes are readable (old plans show the version they used); drafts are not."""
    r = session.get(Recipe, recipe_id)
    if r is None or r.status == "draft":
        raise ApiError(404, ProblemCode.not_found)
    return _recipe_out(session, _recipe_views(session, [r])[0], r)


def _ingredient_out(v: IngredientView, units: list[IngredientUnit], synonyms: list[str]) -> IngredientOut:
    return IngredientOut(
        id=v.id,
        name_vi=v.name_vi,
        food_group_code=v.food_group_code,
        is_staple=v.is_staple,
        countable=v.countable,
        shelf_life_days=v.shelf_life_days,
        allergen_codes=sorted(v.allergen_codes),
        units=[
            IngredientUnitOut(unit_code=u.unit_code, grams_per_unit=float(u.grams_per_unit), source=u.source)
            for u in units
        ],
        synonyms=synonyms,
    )


def _ingredients_out(session: Session, rows: list[Ingredient]) -> list[IngredientOut]:
    ids = [r.id for r in rows]
    views = ingredients_by_ids(session, ids)
    units: dict[uuid.UUID, list[IngredientUnit]] = defaultdict(list)
    for u in session.scalars(
        select(IngredientUnit).where(IngredientUnit.ingredient_id.in_(ids)).order_by(IngredientUnit.unit_code)
    ):
        units[u.ingredient_id].append(u)
    syn: dict[uuid.UUID, list[str]] = defaultdict(list)
    for s in session.scalars(
        select(IngredientSynonym)
        .where(IngredientSynonym.ingredient_id.in_(ids))
        .order_by(IngredientSynonym.lang.desc(), IngredientSynonym.synonym)
    ):
        syn[s.ingredient_id].append(s.synonym)
    return [_ingredient_out(views[r.id], units.get(r.id, []), syn.get(r.id, [])) for r in rows]


def list_ingredients(
    session: Session, *, q: str | None, food_group_code: str | None, cursor: str | None, limit: int
) -> IngredientPage:
    """Active ingredients matching the name or a synonym (no diacritics needed), keyset by (created_at, id)."""
    after = pagination.decode_created(cursor)
    query = select(Ingredient).where(Ingredient.is_active).order_by(Ingredient.created_at, Ingredient.id)
    if food_group_code:
        query = query.where(Ingredient.food_group_code == food_group_code)
    if after is not None:
        query = query.where(tuple_(Ingredient.created_at, Ingredient.id) > after)
    rows = list(session.scalars(query))
    if q:
        needle = fold(q)
        syn: dict[uuid.UUID, list[str]] = defaultdict(list)
        for iid, s in session.execute(select(IngredientSynonym.ingredient_id, IngredientSynonym.synonym)):
            syn[iid].append(s)
        rows = [r for r in rows if needle in fold(r.name_vi) or any(needle in fold(s) for s in syn.get(r.id, []))]
    page = rows[:limit]
    nxt = pagination.encode_created(page[-1].created_at, page[-1].id) if len(rows) > limit else None
    return IngredientPage(items=_ingredients_out(session, page), next_cursor=nxt)


def snapshot(session: Session) -> CatalogSnapshot:
    """Every published recipe and active ingredient for offline cooking (UC19); data_version = content hash."""
    recipes = list(
        session.scalars(select(Recipe).where(Recipe.status == "published").order_by(Recipe.created_at, Recipe.id))
    )
    views = {v.id: v for v in _recipe_views(session, recipes)}
    ids = [r.id for r in recipes]
    sources: dict[uuid.UUID, list[RecipeSource]] = defaultdict(list)
    for s in session.scalars(select(RecipeSource).where(RecipeSource.recipe_id.in_(ids)).order_by(RecipeSource.url)):
        sources[s.recipe_id].append(s)
    nutrients: dict[uuid.UUID, list[RecipeNutrition]] = defaultdict(list)
    for n in session.scalars(
        select(RecipeNutrition).where(RecipeNutrition.recipe_id.in_(ids)).order_by(RecipeNutrition.nutrient_code)
    ):
        nutrients[n.recipe_id].append(n)
    out_recipes = [
        _recipe_out_from(views[r.id], r.notes, sources.get(r.id, []), nutrients.get(r.id, [])) for r in recipes
    ]
    ingredients = _ingredients_out(
        session,
        list(
            session.scalars(
                select(Ingredient).where(Ingredient.is_active).order_by(Ingredient.created_at, Ingredient.id)
            )
        ),
    )
    version = _etag({"recipes": out_recipes, "ingredients": ingredients})
    return CatalogSnapshot(data_version=version, generated_at=utcnow(), recipes=out_recipes, ingredients=ingredients)


# ---------------------------------------------------------------- import (UC25)


def validate_bundle(root: Path, processed: Path | None = None) -> Bundle:
    return load_bundle(root, processed)


def import_bundle(session: Session, bundle: Bundle, processed: Path) -> importer.ImportReport:
    """Write a checked bundle in the caller's transaction, then re-check BR-ALG-01/BR-DIET-01 on what was written
    (FR-25-15); any violation raises ValueError so the caller rolls everything back."""
    result = nut.compute(bundle, processed)
    report = importer.apply(session, bundle, result, utcnow())
    problems = check_catalog_safety(session, bundle)
    if problems:
        raise ValueError("catalog safety check failed:\n" + "\n".join(problems))
    return report


def check_catalog_safety(session: Session, bundle: Bundle | None = None) -> list[str]:
    """Hard filter vs raw SQL for every published recipe × every allergen group and diet, plus the `vegetarian`
    flags of dish_list.yaml against the diet `chay`."""
    views = published_recipes(session)
    allergen_rows = session.execute(
        text(
            "SELECT ri.recipe_id, ia.allergen_code FROM recipe_ingredients ri "
            "JOIN ingredient_allergens ia ON ia.ingredient_id = ri.ingredient_id "
            "UNION SELECT ma.recipe_id, ia.allergen_code FROM recipe_make_ahead ma "
            "JOIN ingredient_allergens ia ON ia.ingredient_id = ma.item_ingredient_id"
        )
    ).all()
    group_rows = session.execute(
        text(
            "SELECT ri.recipe_id, i.food_group_code FROM recipe_ingredients ri "
            "JOIN ingredients i ON i.id = ri.ingredient_id "
            "UNION SELECT ma.recipe_id, i.food_group_code FROM recipe_make_ahead ma "
            "JOIN ingredients i ON i.id = ma.item_ingredient_id"
        )
    ).all()
    has_allergen = {(r, a) for r, a in allergen_rows}
    has_group = {(r, g) for r, g in group_rows}
    problems = []
    for code in session.scalars(select(AllergenGroup.code)):
        for v in views:
            if recipe_allowed(v, {code}, ()) == ((v.id, code) in has_allergen):
                problems.append(f"{v.name_vi}: lọc cứng dị ứng {code} sai")
    for diet in session.scalars(select(Diet.code)):
        excl = excluded_food_groups(session, diet)
        for v in views:
            if recipe_allowed(v, (), excl) == any((v.id, g) in has_group for g in excl):
                problems.append(f"{v.name_vi}: lọc cứng chế độ ăn {diet} sai")
    if bundle is not None and diet_exists(session, "chay"):
        excl = excluded_food_groups(session, "chay")
        names = {r.name_vi: slug for slug, r in bundle.recipes.items()}
        for v in views:
            slug = names.get(v.name_vi)
            if slug and bundle.vegetarian.get(slug) and not recipe_allowed(v, (), excl):
                bad = sorted(ln.ingredient.name_vi for ln in v.lines if ln.ingredient.food_group_code in excl)
                problems.append(f"{v.name_vi}: dish_list ghi chay nhưng có {bad}")
    return problems
