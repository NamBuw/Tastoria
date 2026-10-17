"""Applying a checked bundle to the catalog tables in one transaction (UC25 steps 6–9, FR-25-09 … FR-25-15).

Identity across imports: ingredients and live recipes are matched by `name_vi` (unique among active ingredients /
non-retired recipes); reference rows by their code. Re-importing an unchanged bundle writes nothing (FR-25-09).

Recipes (BR-CATALOG-01): a draft is edited in place; a published recipe whose content changed (ingredients, grams,
steps, tags, sources, notes, servings, method, make-ahead) is retired and a new published version is inserted, so
meal plans and cook sessions keep pointing at the version they used. Recipes and ingredients missing from the bundle
are retired / deactivated, never deleted (FR-25-11; the bundle is a full sync of the catalog).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select, text, update
from sqlalchemy.orm import Session

from tastoria.modules.catalog.bundle import MAKE_AHEAD_TAG, NUTRIENT_CODES, Bundle, IngredientIn, RecipeIn
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
    NutrientSource,
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
from tastoria.modules.catalog.nutrition import RICE_FCT_CODE, NutritionResult

NUTRIENT_ROWS = [
    ("energy_kcal", "Năng lượng", "kcal"),
    ("protein_g", "Chất đạm", "g"),
    ("lipid_g", "Chất béo", "g"),
    ("glucid_g", "Chất bột đường", "g"),
    ("fiber_g", "Chất xơ", "g"),
    ("sugar_g", "Đường", "g"),
    ("sodium_mg", "Natri", "mg"),
]
assert tuple(c for c, _, _ in NUTRIENT_ROWS) == NUTRIENT_CODES

SOURCES = [
    {
        "id": 1,
        "code": "fct2007",
        "name": "Bảng thành phần thực phẩm Việt Nam (Viện Dinh dưỡng – Bộ Y tế)",
        "version": "2007",
        "license": "Viện Dinh dưỡng giữ bản quyền; dùng cho nghiên cứu, ghi nguồn, không phát hành lại PDF",
        "url": "https://www.fao.org/fileadmin/templates/food_composition/documents/pdf/VTN_FCT_2007.pdf",
    },
    {
        "id": 2,
        "code": "usda_sr_legacy",
        "name": "USDA FoodData Central — SR Legacy",
        "version": "2018-04",
        "license": "CC0 1.0",
        "url": "https://fdc.nal.usda.gov/",
    },
    {
        "id": 3,
        "code": "usda_foundation",
        "name": "USDA FoodData Central — Foundation Foods",
        "version": "2026-04-30",
        "license": "CC0 1.0",
        "url": "https://fdc.nal.usda.gov/",
    },
]
SOURCE_ID = {s["code"]: s["id"] for s in SOURCES}
SYSTEM_TAGS = {MAKE_AHEAD_TAG: ("occasion", "Làm sẵn từ trước (muối, ngâm, ủ hơn 2 giờ)")}


@dataclass
class ImportReport:
    tables: dict[str, dict[str, int]] = field(default_factory=lambda: defaultdict(lambda: defaultdict(int)))
    new_versions: list[dict[str, str]] = field(default_factory=list)  # {name_vi, old_id, new_id}
    drafts: list[str] = field(default_factory=list)
    nutrition_recomputed: int = 0
    data_version: str = ""
    rice_bowl_kcal: float = 0.0
    kcal_half_width: float | None = None
    nutrition_engine: str = ""
    warnings: list[str] = field(default_factory=list)

    def count(self, table: str, what: str, n: int = 1) -> None:
        if n:
            self.tables[table][what] += n

    @property
    def changes(self) -> int:
        return sum(sum(v.values()) for v in self.tables.values())

    def as_dict(self) -> dict[str, Any]:
        return {
            "changes": self.changes,
            "tables": {t: dict(v) for t, v in sorted(self.tables.items())},
            "new_versions": self.new_versions,
            "drafts": self.drafts,
            "nutrition_recomputed": self.nutrition_recomputed,
            "nutrition_engine": self.nutrition_engine,
            "data_version": self.data_version,
            "rice_bowl_kcal": self.rice_bowl_kcal,
            "kcal_half_width": self.kcal_half_width,
            "warnings": self.warnings,
        }


def _dec(v: Any) -> Decimal | None:
    if v is None:
        return None
    d = Decimal(str(v)).normalize()
    return d + 0  # drop "-0"


def _sync(
    session: Session,
    model: type,
    key: tuple[str, ...],
    rows: list[dict[str, Any]],
    report: ImportReport,
    *,
    delete_missing: bool = False,
    scope: dict[str, Any] | None = None,
) -> None:
    """Insert new rows, update changed columns, optionally delete rows of `scope` missing from `rows`."""
    q = select(model)
    for col, val in (scope or {}).items():
        q = q.where(getattr(model, col) == val)
    existing = {tuple(getattr(o, k) for k in key): o for o in session.scalars(q)}
    wanted = {tuple(r[k] for k in key): r for r in rows}
    name = model.__tablename__  # type: ignore[attr-defined]
    for k, r in wanted.items():
        obj = existing.get(k)
        if obj is None:
            session.add(model(**r))
            report.count(name, "inserted")
            continue
        changed = False
        for col, val in r.items():
            cur = getattr(obj, col)
            if isinstance(val, Decimal) or isinstance(cur, Decimal):
                same = _dec(cur) == _dec(val)
            else:
                same = cur == val
            if not same:
                setattr(obj, col, val)
                changed = True
        if changed:
            report.count(name, "updated")
    if delete_missing:
        for k, obj in existing.items():
            if k not in wanted:
                session.delete(obj)
                report.count(name, "deleted")
    session.flush()


# ---------------------------------------------------------------- reference + composition


def _reference(session: Session, b: Bundle, report: ImportReport) -> None:
    _sync(session, NutrientSource, ("id",), [dict(s) for s in SOURCES], report)
    _sync(session, Nutrient, ("code",), [{"code": c, "name_vi": n, "unit": u} for c, n, u in NUTRIENT_ROWS], report)
    _sync(session, FoodGroup, ("code",), [{"code": g.code, "name_vi": g.name_vi} for g in b.food_groups], report)
    _sync(
        session,
        AllergenGroup,
        ("code",),
        [{"code": a.code, "name_vi": a.name_vi, "name_en": a.name_en, "basis": a.basis} for a in b.allergens],
        report,
    )
    _sync(session, Diet, ("code",), [{"code": d.code, "name_vi": d.name_vi} for d in b.diets], report)
    for d in b.diets:
        _sync(
            session,
            DietExclusion,
            ("diet_code", "food_group_code"),
            [{"diet_code": d.code, "food_group_code": g} for g in d.excluded_food_groups],
            report,
            delete_missing=True,
            scope={"diet_code": d.code},
        )
    _sync(session, CookingMethod, ("code",), [{"code": m.code, "name_vi": m.name_vi} for m in b.methods], report)
    tags = {t.code: {"code": t.code, "kind": t.kind, "name_vi": t.name_vi} for t in b.tags}
    for code, (kind, name) in SYSTEM_TAGS.items():
        tags.setdefault(code, {"code": code, "kind": kind, "name_vi": name})
    _sync(session, Tag, ("code",), list(tags.values()), report)
    _sync(
        session,
        QtyLevel,
        ("food_group_code", "level"),
        [
            {"food_group_code": g, "level": lvl, "g_min": _dec(getattr(q, lvl)[0]), "g_max": _dec(getattr(q, lvl)[1])}
            for g, q in b.qty_levels.items()
            for lvl in ("it", "vua", "nhieu")
        ],
        report,
    )


def _comp_key(ing: IngredientIn) -> tuple[str, str] | None:
    cs = ing.comp_source
    return (cs.source, cs.code) if cs.source and cs.code else None


def _composition(session: Session, b: Bundle, report: ImportReport) -> dict[tuple[str, str], tuple[int, str]]:
    """food_items + food_nutrients for the codes the ingredients use, plus rice for E_bát (BR-TRAY-03)."""
    used = {k for ing in b.ingredients.values() if (k := _comp_key(ing))}
    used.add(("fct2007", RICE_FCT_CODE))
    ids: dict[tuple[str, str], tuple[int, str]] = {}
    items, nutrients = [], []
    for key in sorted(used):
        row = b.comp.get(key)
        if row is None:
            continue
        sid = SOURCE_ID[row.source]
        ids[key] = (sid, row.code)
        refuse = _dec(row.refuse_pct) if row.source == "fct2007" else None
        items.append(
            {"source_id": sid, "source_code": row.code, "name": row.name, "name_en": row.name_en, "refuse_pct": refuse}
        )
        for code, val in row.values.items():
            if val >= 0:
                nutrients.append(
                    {"source_id": sid, "source_code": row.code, "nutrient_code": code, "per_100g": _dec(val)}
                )
    _sync(session, FoodItem, ("source_id", "source_code"), items, report)
    by_item: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for n in nutrients:
        by_item[(n["source_id"], n["source_code"])].append(n)
    existing = defaultdict(dict)
    for fn in session.scalars(select(FoodNutrient)):
        existing[(fn.source_id, fn.source_code)][fn.nutrient_code] = fn
    for k, rows in by_item.items():
        cur = existing.get(k, {})
        want = {r["nutrient_code"]: r for r in rows}
        for code, r in want.items():
            obj = cur.get(code)
            if obj is None:
                session.add(FoodNutrient(**r))
                report.count("food_nutrients", "inserted")
            elif _dec(obj.per_100g) != r["per_100g"]:
                obj.per_100g = r["per_100g"]
                report.count("food_nutrients", "updated")
        for code, obj in cur.items():
            if code not in want:
                session.delete(obj)
                report.count("food_nutrients", "deleted")
    session.flush()
    return ids


# ---------------------------------------------------------------- ingredients


def _basis(ing: IngredientIn) -> str:
    sl = ing.shelf_life
    return f"foodkeeper:{sl.foodkeeper_id}" if sl.basis == "foodkeeper" else sl.basis


def _ingredients(
    session: Session, b: Bundle, comp_ids: dict[tuple[str, str], tuple[int, str]], now: datetime, report: ImportReport
) -> dict[str, uuid.UUID]:
    rows = list(session.scalars(select(Ingredient).order_by(Ingredient.is_active.desc(), Ingredient.updated_at.desc())))
    by_name: dict[str, Ingredient] = {}
    for r in rows:
        by_name.setdefault(r.name_vi, r)
    ids: dict[str, uuid.UUID] = {}
    for name, ing in b.ingredients.items():
        key = _comp_key(ing)
        sid, scode = comp_ids[key] if key in comp_ids else (None, None)
        values = {
            "food_group_code": ing.food_group,
            "comp_source_id": sid,
            "comp_source_code": scode,
            "is_staple": ing.is_staple,
            "countable": ing.countable,
            "shelf_life_days": _dec(ing.shelf_life.days),
            "shelf_life_basis": _basis(ing),
            "is_active": True,
        }
        obj = by_name.get(name)
        if obj is None:
            obj = Ingredient(id=uuid.uuid4(), name_vi=name, created_at=now, updated_at=now, **values)
            session.add(obj)
            report.count("ingredients", "inserted")
        else:
            diff = {
                k: v
                for k, v in values.items()
                if (_dec(getattr(obj, k)) if k == "shelf_life_days" else getattr(obj, k)) != v
            }
            if diff:
                for k, v in diff.items():
                    setattr(obj, k, v)
                obj.updated_at = now
                report.count("ingredients", "reactivated" if "is_active" in diff else "updated")
        ids[name] = obj.id
    session.flush()
    for name, obj in by_name.items():
        if name not in b.ingredients and obj.is_active:
            obj.is_active = False
            obj.updated_at = now
            report.count("ingredients", "deactivated")
    session.flush()
    for name, ing in b.ingredients.items():
        iid = ids[name]
        syn = [
            {"ingredient_id": iid, "synonym": s, "lang": "vi", "source": "kb"} for s in dict.fromkeys(ing.synonyms.vi)
        ]
        syn += [
            {"ingredient_id": iid, "synonym": s, "lang": "en", "source": "kb"} for s in dict.fromkeys(ing.synonyms.en)
        ]
        _sync(
            session,
            IngredientSynonym,
            ("ingredient_id", "synonym", "lang"),
            syn,
            report,
            delete_missing=True,
            scope={"ingredient_id": iid},
        )
        _sync(
            session,
            IngredientAllergen,
            ("ingredient_id", "allergen_code"),
            [{"ingredient_id": iid, "allergen_code": a} for a in ing.allergens],
            report,
            delete_missing=True,
            scope={"ingredient_id": iid},
        )
        _sync(
            session,
            IngredientUnit,
            ("ingredient_id", "unit_code"),
            [
                {
                    "ingredient_id": iid,
                    "unit_code": u.unit_code,
                    "grams_per_unit": _dec(u.grams_per_unit),
                    "source": u.source,
                }
                for u in ing.units
            ],
            report,
            delete_missing=True,
            scope={"ingredient_id": iid},
        )
    return ids


# ---------------------------------------------------------------- recipes


def _tags(b: Bundle, slug: str, rec: RecipeIn) -> list[str]:
    tags = list(rec.tags)
    if slug in b.make_ahead and MAKE_AHEAD_TAG not in tags:
        tags.append(MAKE_AHEAD_TAG)
    return tags


def _canon_bundle(b: Bundle, slug: str, rec: RecipeIn) -> dict[str, Any]:
    ma = b.make_ahead.get(slug)
    return {
        "slot": rec.slot,
        "servings": rec.servings,
        "method": rec.method,
        "notes": rec.notes,
        "ingredients": sorted((i.name, str(_dec(i.grams)), i.role, i.optional) for i in rec.ingredients),
        "steps": [(s.step_no, s.text_vi, s.kind, s.minutes, s.uses_burner) for s in rec.steps],
        "tags": sorted(_tags(b, slug, rec)),
        "sources": sorted((s.url, s.title, s.accessed_on.isoformat()) for s in rec.sources),
        "make_ahead": (ma.item, ma.through_step) if ma else None,
    }


def _canon_db(session: Session, r: Recipe, names: dict[uuid.UUID, str]) -> dict[str, Any]:
    rid = r.id
    ings = session.scalars(select(RecipeIngredient).where(RecipeIngredient.recipe_id == rid)).all()
    steps = session.scalars(select(RecipeStep).where(RecipeStep.recipe_id == rid).order_by(RecipeStep.step_no)).all()
    tags = session.scalars(select(RecipeTag.tag_code).where(RecipeTag.recipe_id == rid)).all()
    srcs = session.scalars(select(RecipeSource).where(RecipeSource.recipe_id == rid)).all()
    ma = session.get(RecipeMakeAhead, rid)
    return {
        "slot": r.slot,
        "servings": r.servings,
        "method": r.method_code,
        "notes": r.notes,
        "ingredients": sorted(
            (names.get(i.ingredient_id, str(i.ingredient_id)), str(_dec(i.grams)), i.role, i.is_optional) for i in ings
        ),
        "steps": [(s.step_no, s.text_vi, s.kind, s.minutes, s.uses_burner) for s in steps],
        "tags": sorted(tags),
        "sources": sorted((s.url, s.title, s.accessed_on.isoformat()) for s in srcs),
        "make_ahead": (names.get(ma.item_ingredient_id), ma.through_step_no) if ma else None,
    }


def _write_children(
    session: Session, b: Bundle, slug: str, rec: RecipeIn, rid: uuid.UUID, ing_ids: dict[str, uuid.UUID]
) -> None:
    session.add_all(
        RecipeIngredient(
            recipe_id=rid, ingredient_id=ing_ids[i.name], grams=_dec(i.grams), role=i.role, is_optional=i.optional
        )
        for i in rec.ingredients
    )
    session.add_all(
        RecipeStep(
            recipe_id=rid,
            step_no=s.step_no,
            text_vi=s.text_vi,
            kind=s.kind,
            minutes=s.minutes,
            uses_burner=s.uses_burner,
        )
        for s in rec.steps
    )
    session.flush()
    session.add_all(RecipeTag(recipe_id=rid, tag_code=t) for t in _tags(b, slug, rec))
    session.add_all(
        RecipeSource(recipe_id=rid, url=s.url, title=s.title, accessed_on=s.accessed_on) for s in rec.sources
    )
    if (ma := b.make_ahead.get(slug)) is not None:
        session.add(
            RecipeMakeAhead(recipe_id=rid, item_ingredient_id=ing_ids[ma.item], through_step_no=ma.through_step)
        )
    session.flush()


def _clear_children(session: Session, rid: uuid.UUID) -> None:
    for model in (RecipeMakeAhead, RecipeTag, RecipeSource, RecipeIngredient, RecipeStep):
        session.execute(delete(model).where(model.recipe_id == rid))  # type: ignore[attr-defined]
    session.flush()


def _insert_recipe(
    session: Session, b: Bundle, slug: str, rec: RecipeIn, status: str, ing_ids: dict[str, uuid.UUID], now: datetime
) -> uuid.UUID:
    rid = uuid.uuid4()
    session.add(
        Recipe(
            id=rid,
            name_vi=rec.name_vi,
            slot=rec.slot,
            servings=rec.servings,
            method_code=rec.method,
            status="draft",
            notes=rec.notes,
            created_at=now,
            updated_at=now,
        )
    )
    session.flush()
    _write_children(session, b, slug, rec, rid, ing_ids)
    if status != "draft":  # children are writable only while draft (trg_recipe_children_guard)
        session.execute(update(Recipe).where(Recipe.id == rid).values(status=status, updated_at=now))
    return rid


def _recipes(
    session: Session, b: Bundle, ing_ids: dict[str, uuid.UUID], now: datetime, report: ImportReport
) -> dict[str, uuid.UUID]:
    names = {i: n for n, i in ing_ids.items()}
    names.update({r.id: r.name_vi for r in session.scalars(select(Ingredient))})
    live = {r.name_vi: r for r in session.scalars(select(Recipe).where(Recipe.status != "retired"))}
    ids: dict[str, uuid.UUID] = {}
    wanted_names = {rec.name_vi for rec in b.recipes.values()}
    for name, r in live.items():  # retire first: the new version reuses the name (ux_recipes_name_vi_live)
        if name not in wanted_names:
            r.status, r.updated_at = "retired", now
            report.count("recipes", "retired")
    session.flush()
    for slug, rec in sorted(b.recipes.items()):
        status = "published" if b.publishable.get(slug) else "draft"
        if status == "draft":
            report.drafts.append(slug)
        cur = live.get(rec.name_vi)
        if cur is None:
            ids[slug] = _insert_recipe(session, b, slug, rec, status, ing_ids, now)
            report.count("recipes", "inserted")
            continue
        same = _canon_db(session, cur, names) == _canon_bundle(b, slug, rec)
        if same and cur.status == status:
            ids[slug] = cur.id
            continue
        if cur.status == "draft":
            _clear_children(session, cur.id)
            cur.slot, cur.servings, cur.method_code, cur.notes = rec.slot, rec.servings, rec.method, rec.notes
            cur.updated_at = now
            session.flush()
            _write_children(session, b, slug, rec, cur.id, ing_ids)
            cur.status = status
            session.flush()
            ids[slug] = cur.id
            report.count("recipes", "updated")
            continue
        # published and changed (or no longer publishable): new version, old one retired (BR-CATALOG-01)
        cur.status, cur.updated_at = "retired", now
        session.flush()
        new_id = _insert_recipe(session, b, slug, rec, status, ing_ids, now)
        ids[slug] = new_id
        report.new_versions.append({"name_vi": rec.name_vi, "old_id": str(cur.id), "new_id": str(new_id)})
        report.count("recipes", "new_version")
    session.flush()
    return ids


def _nutrition(
    session: Session, recipe_ids: dict[str, uuid.UUID], nut: NutritionResult, now: datetime, report: ImportReport
) -> None:
    existing: dict[uuid.UUID, dict[str, RecipeNutrition]] = defaultdict(dict)
    for row in session.scalars(select(RecipeNutrition).where(RecipeNutrition.recipe_id.in_(list(recipe_ids.values())))):
        existing[row.recipe_id][row.nutrient_code] = row
    for slug, rid in recipe_ids.items():
        vals = {k: _dec(v) for k, v in nut.per_serving.get(slug, {}).items() if v is not None and v >= 0}
        cur = existing.get(rid, {})
        same = set(cur) == set(vals) and all(
            _dec(cur[k].per_serving) == v and cur[k].data_version == nut.data_version for k, v in vals.items()
        )
        if same:
            continue
        session.execute(delete(RecipeNutrition).where(RecipeNutrition.recipe_id == rid))
        session.add_all(
            RecipeNutrition(
                recipe_id=rid, nutrient_code=k, per_serving=v, computed_at=now, data_version=nut.data_version
            )
            for k, v in vals.items()
        )
        report.nutrition_recomputed += 1
    session.flush()


MIN_CALIBRATION_DISHES = 30  # BR-NUT-06


def _set_db_param(session: Session, key: str, value: float | None, report: ImportReport) -> None:
    """Database-level parameter tastoria.<key> (app_param() in views; catalog.service.db_param() reads it fresh).
    None resets it. Needs the database owner; otherwise a warning (the API then falls back to "not calibrated")."""
    assert key.isidentifier()
    action = f"SET tastoria.{key} = %L" if value is not None else f"RESET tastoria.{key}"
    arg = f", '{float(value)}'" if value is not None else ""
    try:
        with session.begin_nested():
            session.execute(
                text(f"DO $$ BEGIN EXECUTE format('ALTER DATABASE %I {action}', current_database(){arg}); END $$")
            )
    except Exception as exc:  # noqa: BLE001
        report.warnings.append(f"ALTER DATABASE {action.split(' ')[0]} tastoria.{key} failed: {exc.__class__.__name__}")


def _calibration(b: Bundle, nut: NutritionResult, report: ImportReport) -> float | None:
    """Half width h of the calorie range (BR-NUT-06): p80 of |relative error| against Viện Dinh dưỡng, used only
    when ≥ 30 dishes were compared with the same nutrition rules and data that computed recipe_nutrition."""
    c = b.calorie_check
    if not c:
        return None
    n, h, version = c.get("n"), c.get("p80_abs_rel_error"), c.get("data_version")
    if not isinstance(n, int) or n < MIN_CALIBRATION_DISHES or not isinstance(h, int | float):
        report.warnings.append(f"validation/nin_dishes.yaml: {n} dishes, BR-NUT-06 needs ≥ {MIN_CALIBRATION_DISHES}")
        return None
    if version != nut.data_version:
        report.warnings.append(
            f"validation/nin_dishes.yaml was computed with {version}, recipe_nutrition with {nut.data_version}: "
            "calorie range left uncalibrated"
        )
        return None
    return float(h)


def apply(session: Session, b: Bundle, nut: NutritionResult, now: datetime) -> ImportReport:
    if not b.ok:
        raise ValueError("bundle has errors; validate first")
    report = ImportReport(
        data_version=nut.data_version,
        rice_bowl_kcal=nut.rice_bowl_kcal,
        nutrition_engine=nut.engine,
        warnings=list(b.warnings),
    )
    _reference(session, b, report)
    comp_ids = _composition(session, b, report)
    ing_ids = _ingredients(session, b, comp_ids, now, report)
    recipe_ids = _recipes(session, b, ing_ids, now, report)
    _nutrition(session, recipe_ids, nut, now, report)
    _set_db_param(session, "rice_bowl_kcal", nut.rice_bowl_kcal, report)
    report.kcal_half_width = _calibration(b, nut, report)
    _set_db_param(session, "kcal_half_width", report.kcal_half_width, report)
    return report
