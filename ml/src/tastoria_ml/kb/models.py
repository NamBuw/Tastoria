"""Pydantic models for the recipe knowledge base in ``data/kb/``.

The files map onto the catalog tables of ``docs/sad/model.yaml``:

- ``ref/food_groups.yaml``      -> food_groups
- ``ref/allergen_groups.yaml``  -> allergen_groups
- ``ref/diets.yaml``            -> diets + diet_exclusions
- ``ref/cooking_methods.yaml``  -> cooking_methods
- ``ref/tags.yaml``             -> tags
- ``ref/qty_levels.yaml``       -> qty_levels
- ``ref/units.yaml``            -> allowed ingredient_units.unit_code values
- ``ingredients.yaml``          -> ingredients + ingredient_synonyms + ingredient_allergens + ingredient_units
- ``dish_list.yaml``            -> seed list for recipes (no quantities or steps yet)

Models check the shape of one record. Cross-file rules (references, uniqueness, codes that must
exist in the processed source tables) live in :mod:`tastoria_ml.kb.validate`.
"""

from __future__ import annotations

import unicodedata
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    PositiveFloat,
    PositiveInt,
    model_validator,
)


def _nfc(value: str) -> str:
    if unicodedata.normalize("NFC", value) != value:
        raise ValueError(f"not NFC-normalised: {value!r}")
    if value != value.strip() or not value:
        raise ValueError(f"empty or padded with whitespace: {value!r}")
    return value


Text = Annotated[str, AfterValidator(_nfc)]
Code = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
Slug = Annotated[str, Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---------------------------------------------------------------- reference tables


class FoodGroup(_Strict):
    code: Code
    name_vi: Text
    animal_origin: bool
    fct2007_groups: list[Annotated[int, Field(ge=1, le=14)]] = []


class FoodGroupsFile(_Strict):
    version: int
    food_groups: list[FoodGroup]


class AllergenGroup(_Strict):
    code: Code
    name_vi: Text
    name_en: Text
    basis: Literal["codex_2024", "tastoria_extra"]


class AllergenSource(_Strict):
    citation: Text
    note: Text | None = None


class AllergenGroupsFile(_Strict):
    version: int
    source: AllergenSource
    allergen_groups: list[AllergenGroup]


class Diet(_Strict):
    code: Code
    name_vi: Text
    excluded_food_groups: list[Code] = Field(min_length=1)


class DietsFile(_Strict):
    version: int
    diets: list[Diet]


class CookingMethod(_Strict):
    code: Code
    name_vi: Text
    uses_burner: bool


class CookingMethodsFile(_Strict):
    version: int
    cooking_methods: list[CookingMethod]


class Tag(_Strict):
    code: Code
    kind: Literal["flavor", "texture", "occasion"]
    name_vi: Text


class TagsFile(_Strict):
    version: int
    tags: list[Tag]


class Unit(_Strict):
    code: Code
    name_vi: Text


class UnitsFile(_Strict):
    version: int
    units: list[Unit]


GramRange = Annotated[tuple[PositiveFloat, PositiveFloat], Field()]


class QtyLevel(_Strict):
    """ít / vừa / nhiều as [g_min, g_max] grams as purchased (BR-QTY-02)."""

    it: GramRange
    vua: GramRange
    nhieu: GramRange

    @model_validator(mode="after")
    def _ordered(self) -> QtyLevel:
        for name in ("it", "vua", "nhieu"):
            lo, hi = getattr(self, name)
            if lo > hi:
                raise ValueError(f"{name}: g_min {lo} > g_max {hi}")
        if not (self.it[0] <= self.vua[0] <= self.nhieu[0] and self.it[1] <= self.vua[1] <= self.nhieu[1]):
            raise ValueError("levels must not decrease: ít <= vừa <= nhiều")
        return self


class QtyLevelsFile(_Strict):
    version: int
    status: Literal["team_estimate_uncalibrated", "calibrated"]
    qty_levels: dict[Code, QtyLevel]


# ---------------------------------------------------------------- ingredients


class CompSource(_Strict):
    """Pointer into a processed composition table, or an explicit reason why there is none."""

    source: Literal["fct2007", "usda"] | None
    code: str | None = None
    source_name: Text | None = None
    match: Literal["exact", "close", "proxy"] | None = None
    reason: Text | None = None
    note: Text | None = None

    @model_validator(mode="after")
    def _complete(self) -> CompSource:
        if self.source is None:
            if not self.reason:
                raise ValueError("comp_source without source needs a reason")
            if self.code or self.match:
                raise ValueError("comp_source without source must not carry code/match")
        else:
            if not self.code or not self.match or not self.source_name:
                raise ValueError("comp_source with a source needs code, source_name and match")
            if not self.code.isdigit():
                raise ValueError(f"source code must be numeric, got {self.code!r}")
            if self.reason:
                raise ValueError("comp_source with a source must not carry a reason")
        return self


class IngredientUnit(_Strict):
    unit_code: Code
    grams_per_unit: PositiveFloat
    source: Text


class Synonyms(_Strict):
    vi: list[Text] = []
    en: list[Text] = []


class ShelfLife(_Strict):
    days: PositiveInt | None
    basis: Literal["foodkeeper", "estimate", "not_tracked"]
    foodkeeper_id: PositiveInt | None = None
    foodkeeper_name: Text | None = None
    note: Text

    @model_validator(mode="after")
    def _complete(self) -> ShelfLife:
        if self.basis == "not_tracked":
            if self.days is not None or self.foodkeeper_id is not None:
                raise ValueError("not_tracked shelf life has no days and no FoodKeeper id")
        elif self.days is None:
            raise ValueError(f"basis {self.basis} needs days")
        if self.basis == "foodkeeper" and (self.foodkeeper_id is None or not self.foodkeeper_name):
            raise ValueError("basis foodkeeper needs foodkeeper_id and foodkeeper_name")
        if self.basis == "estimate" and self.foodkeeper_id is not None:
            raise ValueError("estimate must not claim a FoodKeeper id (cite it in the note instead)")
        return self


class Ingredient(_Strict):
    name_vi: Text
    food_group: Code
    comp_source: CompSource
    is_staple: bool = False
    countable: bool = False
    units: list[IngredientUnit] = []
    allergens: list[Code] = []
    allergen_note: Text | None = None
    synonyms: Synonyms = Synonyms()
    shelf_life: ShelfLife

    @model_validator(mode="after")
    def _consistent(self) -> Ingredient:
        codes = [u.unit_code for u in self.units]
        if len(codes) != len(set(codes)):
            raise ValueError(f"{self.name_vi}: duplicate unit_code")
        if self.countable and not self.units:
            raise ValueError(f"{self.name_vi}: countable but has no units")
        if len(self.allergens) != len(set(self.allergens)):
            raise ValueError(f"{self.name_vi}: duplicate allergen")
        if self.name_vi in self.synonyms.vi:
            raise ValueError(f"{self.name_vi}: name repeated as its own synonym")
        return self


class IngredientsFile(_Strict):
    version: int
    ingredients: list[Ingredient]


# ---------------------------------------------------------------- dishes


class Reference(_Strict):
    id: Code
    title: Text
    urls: list[Annotated[str, Field(pattern=r"^https?://")]] = Field(min_length=1)
    note: Text | None = None


class Dish(_Strict):
    slug: Slug
    name_vi: Text
    slot: Literal["man", "rau", "canh"]
    method: Code
    main: list[Text] = Field(min_length=1)
    seasonings: list[Text] = []
    region: Literal["bac", "trung", "nam", "chung"]
    vegetarian: bool
    minutes: PositiveInt
    seen_in: list[Annotated[str, Field(pattern=r"^https?://")]] = []

    @model_validator(mode="after")
    def _no_repeats(self) -> Dish:
        both = self.main + self.seasonings
        if len(both) != len(set(both)):
            raise ValueError(f"{self.slug}: ingredient listed twice in main/seasonings")
        return self


class DishListFile(_Strict):
    version: int
    references: list[Reference]
    dishes: list[Dish]
