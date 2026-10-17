"""Reading and checking a catalog bundle (`data/kb` layout) — UC25 steps 2–5, FR-25-01 … FR-25-08.

The bundle is the curated knowledge base:

    ref/{food_groups,allergen_groups,diets,cooking_methods,tags,qty_levels,units}.yaml
    ingredients.yaml (+ ingredients_proposed*.yaml)       ingredients, synonyms, allergens, units, shelf life
    recipes/<slot>/<slug>.yaml                           one recipe per file
    make_ahead.yaml                                      make-ahead recipes and their made-ahead item

plus the processed composition tables `<processed>/fct2007/{foods,nutrients_long}.csv` and
`<processed>/usda/foods.csv` (D0). Every problem is collected (no stop at the first) as `file:line: code: message`.
Shapes are checked with strict pydantic models of this module; they mirror the KB format but do not import the ml
package, so the API image can import a bundle on its own.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, PositiveInt, ValidationError, model_validator

SLOTS = ("man", "rau", "canh")
LEVELS = ("it", "vua", "nhieu")
NUTRIENT_CODES = ("energy_kcal", "protein_g", "lipid_g", "glucid_g", "fiber_g", "sugar_g", "sodium_mg")
MIN_SOURCES_TO_PUBLISH = 2  # design v2 §5: every recipe needs ≥ 2 sources (FR-25-08)
MAKE_AHEAD_TAG = "lam_san"


def _nfc(v: str) -> str:
    if unicodedata.normalize("NFC", v) != v:
        raise ValueError(f"not NFC-normalised: {v!r}")
    if not v or v != v.strip():
        raise ValueError(f"empty or padded with whitespace: {v!r}")
    return v


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


Text = Annotated[str, Field(min_length=1)]
Code = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
Slug = Annotated[str, Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")]
Url = Annotated[str, Field(pattern=r"^https?://\S+$")]


# ---------------------------------------------------------------- file models


class FoodGroupIn(_Strict):
    code: Code
    name_vi: Text
    animal_origin: bool
    fct2007_groups: list[int] = []


class AllergenGroupIn(_Strict):
    code: Code
    name_vi: Text
    name_en: Text
    basis: Literal["codex_2024", "tastoria_extra"]


class DietIn(_Strict):
    code: Code
    name_vi: Text
    excluded_food_groups: list[Code] = Field(min_length=1)


class MethodIn(_Strict):
    code: Code
    name_vi: Text
    uses_burner: bool


class TagIn(_Strict):
    code: Code
    kind: Literal["flavor", "texture", "occasion"]
    name_vi: Text


class UnitIn(_Strict):
    code: Code
    name_vi: Text


class QtyLevelIn(_Strict):
    it: tuple[PositiveFloat, PositiveFloat]
    vua: tuple[PositiveFloat, PositiveFloat]
    nhieu: tuple[PositiveFloat, PositiveFloat]

    @model_validator(mode="after")
    def _ordered(self) -> QtyLevelIn:
        for lvl in LEVELS:
            lo, hi = getattr(self, lvl)
            if lo > hi:
                raise ValueError(f"{lvl}: g_min {lo} > g_max {hi}")
        return self


class CompSourceIn(_Strict):
    source: Literal["fct2007", "usda"] | None
    code: str | None = None
    source_name: str | None = None
    match: Literal["exact", "close", "proxy"] | None = None
    reason: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _complete(self) -> CompSourceIn:
        if self.source is None and not self.reason:
            raise ValueError("comp_source without source needs a reason")
        if self.source is not None and not (self.code and self.match and self.source_name):
            raise ValueError("comp_source with a source needs code, source_name and match")
        return self


class UnitConvIn(_Strict):
    unit_code: Code
    grams_per_unit: PositiveFloat
    source: Text


class SynonymsIn(_Strict):
    vi: list[Text] = []
    en: list[Text] = []


class ShelfLifeIn(_Strict):
    days: PositiveInt | None
    basis: Literal["foodkeeper", "estimate", "not_tracked"]
    foodkeeper_id: PositiveInt | None = None
    foodkeeper_name: str | None = None
    note: Text

    @model_validator(mode="after")
    def _complete(self) -> ShelfLifeIn:
        if self.basis == "not_tracked" and self.days is not None:
            raise ValueError("not_tracked shelf life has no days")
        if self.basis != "not_tracked" and self.days is None:
            raise ValueError(f"basis {self.basis} needs days")  # FR-25-07: days need a basis, a basis needs days
        if self.basis == "foodkeeper" and self.foodkeeper_id is None:
            raise ValueError("basis foodkeeper needs foodkeeper_id")
        return self


class IngredientIn(_Strict):
    name_vi: Text
    food_group: Code
    comp_source: CompSourceIn
    is_staple: bool = False
    countable: bool = False
    units: list[UnitConvIn] = []
    allergens: list[Code]  # required: an empty list is an explicit "no allergen" (FR-25-04)
    allergen_note: str | None = None
    synonyms: SynonymsIn = SynonymsIn()
    shelf_life: ShelfLifeIn

    @model_validator(mode="after")
    def _consistent(self) -> IngredientIn:
        if self.countable and not self.units:
            raise ValueError("countable ingredient needs at least one unit (FR-25-06)")
        if len({u.unit_code for u in self.units}) != len(self.units):
            raise ValueError("duplicate unit_code")
        if len(set(self.allergens)) != len(self.allergens):
            raise ValueError("duplicate allergen")
        return self


class RecipeIngredientIn(_Strict):
    name: Text
    grams: PositiveFloat
    role: Literal["main", "side", "seasoning"]
    optional: bool = False
    note: str | None = None


class RecipeStepIn(_Strict):
    step_no: PositiveInt
    text_vi: Text
    kind: Literal["active", "passive"]
    minutes: Annotated[int, Field(gt=0, le=32767)]
    uses_burner: bool = False


class RecipeSourceIn(_Strict):
    url: Url
    title: Text
    accessed_on: dt.date


class RecipeIn(_Strict):
    slug: Slug
    name_vi: Text
    slot: Literal["man", "rau", "canh"]
    servings: Annotated[int, Field(gt=0, le=32767)]
    method: Code
    tags: list[Code] = []
    ingredients: list[RecipeIngredientIn] = Field(min_length=1)
    steps: list[RecipeStepIn] = Field(min_length=1)
    sources: list[RecipeSourceIn] = Field(min_length=1)
    notes: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> RecipeIn:
        names = [i.name for i in self.ingredients]
        dup = sorted(n for n, c in Counter(names).items() if c > 1)
        if dup:
            raise ValueError(f"ingredient listed twice: {dup}")
        if [s.step_no for s in self.steps] != list(range(1, len(self.steps) + 1)):
            raise ValueError("steps must be numbered 1..n in order")
        if len(set(self.tags)) != len(self.tags):
            raise ValueError("duplicate tag")
        if len({s.url for s in self.sources}) != len(self.sources):
            raise ValueError("duplicate source url")
        return self


class MakeAheadIn(_Strict):
    recipe: Slug
    item: Text


class MakeAheadFile(_Strict):
    version: int
    passive_threshold_minutes: PositiveInt = 120
    make_ahead: list[MakeAheadIn] = []
    ingredients: list[IngredientIn] = []


# ---------------------------------------------------------------- loaded bundle


@dataclass(frozen=True)
class CompRow:
    """One composition row per 100 g edible portion; None = not analysed."""

    source: Literal["fct2007", "usda_sr_legacy", "usda_foundation"]
    code: str
    name: str
    name_en: str | None
    refuse_pct: float | None
    values: dict[str, float]  # nutrient code -> per 100 g


@dataclass(frozen=True)
class MakeAhead:
    item: str
    through_step: int
    whole: bool  # every step is done ahead: the dish is the made-ahead product itself


@dataclass
class Bundle:
    root: Path
    food_groups: list[FoodGroupIn] = field(default_factory=list)
    allergens: list[AllergenGroupIn] = field(default_factory=list)
    diets: list[DietIn] = field(default_factory=list)
    methods: list[MethodIn] = field(default_factory=list)
    tags: list[TagIn] = field(default_factory=list)
    units: list[UnitIn] = field(default_factory=list)
    qty_levels: dict[str, QtyLevelIn] = field(default_factory=dict)
    ingredients: dict[str, IngredientIn] = field(default_factory=dict)
    recipes: dict[str, RecipeIn] = field(default_factory=dict)  # slug -> recipe
    make_ahead: dict[str, MakeAhead] = field(default_factory=dict)  # slug -> make-ahead
    comp: dict[tuple[str, str], CompRow] = field(default_factory=dict)  # (fct2007|usda, code) -> row
    publishable: dict[str, bool] = field(default_factory=dict)  # slug -> FR-25-08
    vegetarian: dict[str, bool] = field(default_factory=dict)  # slug -> dish_list.yaml `vegetarian` (post-check)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    file_sha: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def content_sha(self) -> str:
        h = hashlib.sha256()
        for name in sorted(self.file_sha):
            h.update(f"{name}:{self.file_sha[name]}\n".encode())
        return h.hexdigest()


# ---------------------------------------------------------------- YAML with line numbers


def _lines(node: yaml.Node, path: tuple[Any, ...] = (), out: dict[tuple[Any, ...], int] | None = None) -> dict:
    out = {} if out is None else out
    out[path] = node.start_mark.line + 1
    if isinstance(node, yaml.MappingNode):
        for k, v in node.value:
            _lines(v, (*path, k.value), out)
            out[(*path, k.value)] = k.start_mark.line + 1
    elif isinstance(node, yaml.SequenceNode):
        for i, v in enumerate(node.value):
            _lines(v, (*path, i), out)
    return out


@dataclass
class _Doc:
    rel: str
    data: Any
    lines: dict[tuple[Any, ...], int]

    def line(self, *path: Any) -> int:
        p = tuple(path)
        while p and p not in self.lines:
            p = p[:-1]
        return self.lines.get(p, 1)


class _Reader:
    def __init__(self, bundle: Bundle) -> None:
        self.b = bundle

    def err(self, rel: str, line: int, code: str, msg: str) -> None:
        self.b.errors.append(f"{rel}:{line}: {code}: {msg}")

    def warn(self, rel: str, line: int, code: str, msg: str) -> None:
        self.b.warnings.append(f"{rel}:{line}: {code}: {msg}")

    def doc(self, path: Path) -> _Doc | None:
        rel = str(path.relative_to(self.b.root))
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8")
        except FileNotFoundError:
            self.err(rel, 1, "file_missing", "tệp không tồn tại")
            return None
        except UnicodeDecodeError as exc:
            self.err(rel, 1, "not_utf8", str(exc))
            return None
        self.b.file_sha[rel] = hashlib.sha256(raw).hexdigest()
        try:
            node = yaml.compose(text, Loader=yaml.SafeLoader)
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            mark = getattr(exc, "problem_mark", None)
            self.err(rel, (mark.line + 1) if mark else 1, "yaml_error", str(exc).splitlines()[0])
            return None
        return _Doc(rel, data, _lines(node) if node is not None else {})

    def model(self, doc: _Doc, model: type[BaseModel], data: Any, *path: Any) -> Any:
        try:
            return model.model_validate(data)
        except ValidationError as exc:
            for e in exc.errors():
                loc = (*path, *e["loc"])
                where = ".".join(str(p) for p in loc) or "/"
                self.err(doc.rel, doc.line(*loc), "schema", f"{where}: {e['msg']}")
            return None

    def nfc(self, doc: _Doc, value: str, *path: Any) -> None:
        try:
            _nfc(value)
        except ValueError as exc:
            self.err(doc.rel, doc.line(*path), "text", str(exc))


def _float(v: str | None) -> float | None:
    if v is None or v.strip() == "":
        return None
    return float(v)


def load_composition(processed: Path) -> dict[tuple[str, str], CompRow]:
    """FCT 2007 + USDA rows keyed by (fct2007|usda, code). USDA `carb_g` is by difference (includes fibre), so
    glucid = carb − fibre, matching FCT's available carbohydrate (same rule as tastoria_ml.kb.nutrition)."""
    out: dict[tuple[str, str], CompRow] = {}
    fct = processed / "fct2007"
    extra: dict[str, dict[str, float]] = {}
    with (fct / "nutrients_long.csv").open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row["nutrient"] in ("sodium", "sugar_total") and (v := _float(row["value"])) is not None:
                extra.setdefault(row["code"], {})["sodium_mg" if row["nutrient"] == "sodium" else "sugar_g"] = v
    with (fct / "foods.csv").open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            vals = {
                k: v
                for k, col in (
                    ("energy_kcal", "energy_kcal"),
                    ("protein_g", "protein_g"),
                    ("lipid_g", "lipid_g"),
                    ("glucid_g", "glucid_g"),
                    ("fiber_g", "fiber_g"),
                )
                if (v := _float(row[col])) is not None
            }
            vals.update(extra.get(row["code"], {}))
            out[("fct2007", row["code"])] = CompRow(
                "fct2007", row["code"], row["name_vi"], row["name_en"] or None, _float(row["refuse_pct"]), vals
            )
    with (processed / "usda" / "foods.csv").open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            carb, fib = _float(row["carb_g"]), _float(row["fiber_g"])
            vals = {
                k: v
                for k, v in (
                    ("energy_kcal", _float(row["energy_kcal"])),
                    ("protein_g", _float(row["protein_g"])),
                    ("lipid_g", _float(row["fat_g"])),
                    ("glucid_g", None if carb is None else max(carb - (fib or 0.0), 0.0)),
                    ("fiber_g", fib),
                    ("sugar_g", _float(row["sugars_g"])),
                    ("sodium_mg", _float(row["sodium_mg"])),
                )
                if v is not None
            }
            src = "usda_foundation" if row["data_type"] == "foundation_food" else "usda_sr_legacy"
            out[("usda", row["fdc_id"])] = CompRow(src, row["fdc_id"], row["description"], None, None, vals)  # type: ignore[arg-type]
    return out


def _norm(s: str) -> str:
    return unicodedata.normalize("NFC", s).casefold().strip()


# ---------------------------------------------------------------- load + check


def load_bundle(root: Path, processed: Path | None = None) -> Bundle:
    """Parse and check the whole bundle; `Bundle.errors` empty means it can be applied."""
    root = Path(root)
    processed = Path(processed) if processed else root.parent / "processed"
    b = Bundle(root=root)
    r = _Reader(b)
    if not root.is_dir():
        b.errors.append(f"{root}:1: bundle_missing: thư mục không tồn tại")
        return b

    def ref(name: str, key: str, model: type[BaseModel]) -> list[Any]:
        d = r.doc(root / "ref" / f"{name}.yaml")
        if d is None or not isinstance(d.data, dict):
            return []
        items = []
        for i, raw in enumerate(d.data.get(key) or []):
            m = r.model(d, model, raw, key, i)
            if m is not None:
                items.append(m)
        codes = Counter(m.code for m in items)
        for c, n in codes.items():
            if n > 1:
                r.err(d.rel, 1, "duplicate", f"{key}: mã {c} lặp {n} lần")
        return items

    b.food_groups = ref("food_groups", "food_groups", FoodGroupIn)
    b.allergens = ref("allergen_groups", "allergen_groups", AllergenGroupIn)
    b.diets = ref("diets", "diets", DietIn)
    b.methods = ref("cooking_methods", "cooking_methods", MethodIn)
    b.tags = ref("tags", "tags", TagIn)
    b.units = ref("units", "units", UnitIn)
    groups = {g.code for g in b.food_groups}
    allergen_codes = {a.code for a in b.allergens}
    method_codes = {m.code for m in b.methods}
    tag_codes = {t.code for t in b.tags} | {MAKE_AHEAD_TAG}
    unit_codes = {u.code for u in b.units}

    d = r.doc(root / "ref" / "diets.yaml")
    for i, diet in enumerate(b.diets):
        for g in diet.excluded_food_groups:
            if g not in groups and d is not None:
                r.err(d.rel, d.line("diets", i), "unknown_ref", f"diet {diet.code}: nhóm thực phẩm {g} không có")

    qd = r.doc(root / "ref" / "qty_levels.yaml")
    if qd is not None and isinstance(qd.data, dict):
        for g, raw in (qd.data.get("qty_levels") or {}).items():
            m = r.model(qd, QtyLevelIn, raw, "qty_levels", g)
            if g not in groups:
                r.err(qd.rel, qd.line("qty_levels", g), "unknown_ref", f"qty_levels: nhóm {g} không có")
            elif m is not None:
                b.qty_levels[g] = m

    # composition tables
    try:
        b.comp = load_composition(processed)
    except (FileNotFoundError, KeyError, ValueError) as exc:
        b.errors.append(f"{processed}:1: composition_unreadable: {exc}")
    for p in sorted(processed.glob("fct2007/*.csv")) + sorted(processed.glob("usda/*.csv")):
        b.file_sha[f"processed/{p.relative_to(processed)}"] = hashlib.sha256(p.read_bytes()).hexdigest()

    # ingredients (+ proposed files + make-ahead products)
    ing_docs = [root / "ingredients.yaml", *sorted(root.glob("ingredients_proposed*.yaml"))]
    ing_lines: dict[str, tuple[_Doc, int]] = {}
    for path in ing_docs:
        d = r.doc(path)
        if d is None or not isinstance(d.data, dict):
            continue
        for i, raw in enumerate(d.data.get("ingredients") or []):
            _ingredient(r, d, raw, ("ingredients", i), b, ing_lines)

    md = r.doc(root / "make_ahead.yaml") if (root / "make_ahead.yaml").exists() else None
    ma_file: MakeAheadFile | None = None
    if md is not None and isinstance(md.data, dict):
        for i, raw in enumerate(md.data.get("ingredients") or []):
            _ingredient(r, md, raw, ("ingredients", i), b, ing_lines)
        ma_file = r.model(md, MakeAheadFile, md.data)

    # reference checks of ingredients
    syn_owner: dict[str, str] = {}
    for name, ing in b.ingredients.items():
        dd, line = ing_lines[name]
        if ing.food_group not in groups:
            r.err(dd.rel, line, "unknown_ref", f"{name}: nhóm thực phẩm {ing.food_group} không có")
        for a in ing.allergens:
            if a not in allergen_codes:
                r.err(dd.rel, line, "unknown_ref", f"{name}: nhóm dị ứng {a} không có trong allergen_groups")
        for u in ing.units:
            if u.unit_code not in unit_codes:
                r.err(dd.rel, line, "unknown_ref", f"{name}: đơn vị {u.unit_code} không có trong ref/units.yaml")
        cs = ing.comp_source
        if cs.source is not None and b.comp:
            row = b.comp.get((cs.source, cs.code or ""))
            if row is None:
                r.err(dd.rel, line, "unknown_ref", f"{name}: {cs.source} mã {cs.code} không có trong bảng thành phần")
            elif cs.source_name and _norm(cs.source_name) != _norm(row.name):
                r.err(dd.rel, line, "source_name", f"{name}: source_name {cs.source_name!r} ≠ {row.name!r}")
            elif "energy_kcal" not in row.values:
                r.err(dd.rel, line, "no_energy", f"{name}: {cs.source} {cs.code} không có energy_kcal")
        for s in ing.synonyms.vi:
            key = _norm(s)
            owner = syn_owner.setdefault(key, name)
            if owner != name:
                r.err(dd.rel, line, "duplicate", f"từ đồng nghĩa {s!r} của {name} trùng với {owner}")
    names_norm = {_norm(n): n for n in b.ingredients}
    for key, owner in syn_owner.items():
        if key in names_norm and names_norm[key] != owner:
            dd, line = ing_lines[owner]
            r.err(dd.rel, line, "duplicate", f"từ đồng nghĩa {key!r} của {owner} trùng tên nguyên liệu khác")

    # recipes
    seen_names: dict[str, str] = {}
    for path in sorted((root / "recipes").glob("*/*.yaml")):
        d = r.doc(path)
        if d is None:
            continue
        rec = r.model(d, RecipeIn, d.data)
        if rec is None:
            continue
        r.nfc(d, rec.name_vi, "name_vi")
        if path.stem != rec.slug or path.parent.name != rec.slot:
            r.err(d.rel, d.line("slug"), "path", f"tệp phải là recipes/{rec.slot}/{rec.slug}.yaml")
        if rec.slug in b.recipes:
            r.err(d.rel, d.line("slug"), "duplicate", f"slug {rec.slug} lặp")
            continue
        if rec.name_vi in seen_names:
            r.err(d.rel, d.line("name_vi"), "duplicate", f"tên món {rec.name_vi!r} trùng {seen_names[rec.name_vi]}")
        seen_names[rec.name_vi] = rec.slug
        if rec.method not in method_codes:
            r.err(d.rel, d.line("method"), "unknown_ref", f"cách nấu {rec.method} không có")
        for i, t in enumerate(rec.tags):
            if t not in tag_codes:
                r.err(d.rel, d.line("tags", i), "unknown_ref", f"thẻ {t} không có")
        for i, it in enumerate(rec.ingredients):
            if it.name not in b.ingredients:
                r.err(d.rel, d.line("ingredients", i), "unknown_ref", f"nguyên liệu {it.name!r} không có")
        b.recipes[rec.slug] = rec
        # FR-25-08 / FR-25-12: publish only with ≥ 2 sources and composition for every non-seasoning ingredient
        # (energy must be computable); seasonings without a composition row carry an explicit reason instead.
        problems = []
        if len(rec.sources) < MIN_SOURCES_TO_PUBLISH:
            problems.append(f"{len(rec.sources)} nguồn (< {MIN_SOURCES_TO_PUBLISH})")
        unmapped = [
            it.name
            for it in rec.ingredients
            if it.name in b.ingredients
            and b.ingredients[it.name].comp_source.source is None
            and it.role != "seasoning"
            and not it.optional
        ]
        if unmapped:
            problems.append(f"nguyên liệu chưa có bảng thành phần: {', '.join(unmapped)}")
        b.publishable[rec.slug] = not problems
        if problems:
            r.warn(d.rel, 1, "draft", f"{rec.slug} nhập ở trạng thái draft: {'; '.join(problems)}")

    dl = r.doc(root / "dish_list.yaml") if (root / "dish_list.yaml").exists() else None
    if dl is not None and isinstance(dl.data, dict):
        for dish in dl.data.get("dishes") or []:
            if isinstance(dish, dict) and isinstance(dish.get("slug"), str):
                b.vegetarian[dish["slug"]] = bool(dish.get("vegetarian"))

    # make-ahead (passive step > threshold)
    threshold = ma_file.passive_threshold_minutes if ma_file else 120
    listed = {m.recipe: (i, m) for i, m in enumerate(ma_file.make_ahead)} if ma_file else {}
    diets_excl = {dt_.code: set(dt_.excluded_food_groups) for dt_ in b.diets}
    for slug, rec in b.recipes.items():
        long_steps = [s.step_no for s in rec.steps if s.kind == "passive" and s.minutes > threshold]
        entry = listed.get(slug)
        rel = f"recipes/{rec.slot}/{slug}.yaml"
        if long_steps and entry is None:
            r.err(
                rel,
                1,
                "make_ahead_missing",
                f"{slug} có bước chờ > {threshold} phút nhưng không có trong make_ahead.yaml",
            )
            continue
        if entry is None:
            continue
        i, m = entry
        assert md is not None
        if not long_steps:
            r.err(md.rel, md.line("make_ahead", i), "make_ahead_extra", f"{slug} không có bước chờ > {threshold} phút")
            continue
        item = b.ingredients.get(m.item)
        if item is None:
            r.err(md.rel, md.line("make_ahead", i), "unknown_ref", f"đồ làm sẵn {m.item!r} không có")
            continue
        through = max(long_steps)
        whole = through == len(rec.steps)
        names = [it.name for it in rec.ingredients]
        if not whole and m.item not in names:
            r.err(
                md.rel,
                md.line("make_ahead", i),
                "make_ahead_item",
                f"{slug}: {m.item!r} không phải nguyên liệu của món",
            )
        if whole:
            used = [b.ingredients[n] for n in names if n in b.ingredients]
            missing = sorted({a for ing in used for a in ing.allergens} - set(item.allergens))
            if missing:
                r.err(
                    md.rel,
                    md.line("make_ahead", i),
                    "make_ahead_allergen",
                    f"{slug}: {m.item!r} thiếu nhóm dị ứng {missing} mà nguyên liệu của món có",
                )
            for code, excl in diets_excl.items():
                if any(ing.food_group in excl for ing in used) and item.food_group not in excl:
                    r.err(
                        md.rel,
                        md.line("make_ahead", i),
                        "make_ahead_diet",
                        f"{slug}: món trái chế độ {code} nhưng {m.item!r} thì không",
                    )
        b.make_ahead[slug] = MakeAhead(m.item, through, whole)
    for slug, (i, _) in listed.items():
        if slug not in b.recipes and md is not None:
            r.err(md.rel, md.line("make_ahead", i), "unknown_ref", f"món {slug} không có trong recipes/")
    return b


def _ingredient(
    r: _Reader, d: _Doc, raw: Any, path: tuple[Any, ...], b: Bundle, lines: dict[str, tuple[_Doc, int]]
) -> None:
    m = r.model(d, IngredientIn, raw, *path)
    if m is None:
        return
    r.nfc(d, m.name_vi, *path, "name_vi")
    if m.name_vi in b.ingredients:
        prev, line = lines[m.name_vi]
        r.err(d.rel, d.line(*path), "duplicate", f"nguyên liệu {m.name_vi!r} đã có ở {prev.rel}:{line}")
        return
    b.ingredients[m.name_vi] = m
    lines[m.name_vi] = (d, d.line(*path))
