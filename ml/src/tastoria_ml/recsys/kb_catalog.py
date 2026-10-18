"""Vietnamese dish catalog (data/kb) as arrays for the survey models, the composer evaluation and substitution.

Content features of a dish follow the live backend ranker (backend/.../meal/ranker.py `features`): every
non-seasoning, non-staple ingredient 1.0, the cooking method 1.0, each tag 0.5.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml

from tastoria_ml.kb.models import Ingredient
from tastoria_ml.kb.recipes import Recipe, load_recipes
from tastoria_ml.kb.validate import load_kb

REPO = Path(__file__).resolve().parents[4]
KB_DIR = REPO / "data" / "kb"
NUTRITION = REPO / "data" / "processed" / "kb" / "recipe_nutrition.csv"
RICE = REPO / "data" / "processed" / "kb" / "rice_bowl.json"


@dataclass
class Catalog:
    recipes: list[Recipe]  # sorted by (slot, slug)
    ingredients: dict[str, Ingredient]  # name_vi -> Ingredient (ingredients.yaml + make_ahead.yaml extras)
    make_ahead: dict[str, str]  # recipe slug -> made-ahead item name
    kcal: dict[str, float]  # slug -> kcal per serving
    rice_kcal: float  # one 150 g bowl
    feature_names: list[str]
    X: np.ndarray  # recipes × features (content vector)

    @property
    def slugs(self) -> list[str]:
        return [r.slug for r in self.recipes]

    @property
    def slots(self) -> np.ndarray:
        return np.array([r.slot for r in self.recipes])

    def index(self) -> dict[str, int]:
        return {r.slug: i for i, r in enumerate(self.recipes)}

    def by_name(self) -> dict[tuple[str, str], int]:
        return {(r.name_vi, r.slot): i for i, r in enumerate(self.recipes)}


def features(r: Recipe, ingredients: dict[str, Ingredient]) -> dict[str, float]:
    f = {}
    for ln in r.ingredients:
        ing = ingredients.get(ln.name)
        if ln.role != "seasoning" and not (ing is not None and ing.is_staple):
            f[f"ing:{ln.name}"] = 1.0
    f[f"method:{r.method}"] = 1.0
    f.update({f"tag:{t}": 0.5 for t in r.tags})
    return f


def load(kb_dir: Path = KB_DIR, nutrition: Path = NUTRITION, rice: Path = RICE) -> Catalog:
    kb, errors = load_kb(kb_dir)
    if kb is None:
        raise ValueError(errors)
    ings = {i.name_vi: i for i in kb.ingredients.ingredients}
    ma_raw = yaml.safe_load((kb_dir / "make_ahead.yaml").read_text(encoding="utf-8"))
    for raw in ma_raw.get("ingredients") or []:
        ing = Ingredient.model_validate(raw)
        ings.setdefault(ing.name_vi, ing)
    make_ahead = {m["recipe"]: m["item"] for m in ma_raw.get("make_ahead") or []}
    rep = load_recipes(kb_dir)
    if rep.errors:
        raise ValueError(rep.errors)
    recipes = sorted(rep.recipes.values(), key=lambda r: (r.slot, r.slug))
    kcal = {}
    with open(nutrition, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            kcal[row["slug"]] = float(row["kcal_per_serving"])
    rice_kcal = float(json.loads(rice.read_text(encoding="utf-8"))["energy_kcal"])
    feats = [features(r, ings) for r in recipes]
    names = sorted({k for f in feats for k in f})
    col = {n: j for j, n in enumerate(names)}
    X = np.zeros((len(recipes), len(names)))
    for i, f in enumerate(feats):
        for k, v in f.items():
            X[i, col[k]] = v
    return Catalog(recipes, ings, make_ahead, kcal, rice_kcal, names, X)


def cosine_rows(A: np.ndarray, b: np.ndarray) -> np.ndarray:
    na = np.linalg.norm(A, axis=1)
    nb = np.linalg.norm(b)
    out = np.zeros(len(A))
    ok = (na > 0) & (nb > 0)
    out[ok] = (A[ok] @ b) / (na[ok] * nb)
    return out
