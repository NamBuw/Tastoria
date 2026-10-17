"""Recipe nutrition per serving (BR-NUT-05) and the energy of one bowl of rice (BR-TRAY-03).

EuroFIR recipe calculation, ingredient method::

    n_k(recipe) = Σ_i  w_i · EP_i / 100 · n_ik · RF_ik

- ``w_i``   grams as purchased, as written in ``data/kb/recipes/<slot>/<slug>.yaml`` for ``servings``.
- ``EP_i``  edible portion = 1 − refuse_pct/100 for FCT 2007 items (values are per 100 g edible portion);
            USDA SR/Foundation values are for the edible part already, so EP = 1 — except for the few
            ingredients bought with bone or shell, which take a refuse from an FCT item (``REFUSE_OVERRIDES``).
- ``n_ik``  per 100 g edible portion from ``data/processed/fct2007`` or ``data/processed/usda``.
- ``RF_ik`` = 1 for energy, protein, fat, carbohydrate, fibre and sodium in v2 (spec §4 BR-NUT-05).

Cooking fat:

- pan-fry, stir-fry, sauté: every gram of oil in the recipe is counted;
- deep-fry (recipe ``method: chien`` whose ``notes`` cite BR-NUT-05, i.e. the author flagged "chiên ngập
  dầu"): only the absorbed fat is counted. Absorbed fat = ``DEEP_FRY_UPTAKE_G_PER_100G`` g per 100 g of the
  other ingredients (as purchased) that go into the fryer, capped at the oil in the recipe. 5 g/100 g is the
  "deep fry" fat uptake of Bognár (2002), BFE-R--02-03, Part 2 (breaded dishes, deep fry column: pork
  Table 7 = 5, chicken Table 13 = 4, low-fat fish Table 21 = 6, breaded vegetables Table 27 = 5 g fat per
  100 g food ingredients). In our five deep-fried recipes this is 7–26 % of the oil put in the pan.

Ingredients without a composition source (``comp_source.source: null``) are skipped; the share of recipe
grams they represent is reported as ``uncovered_gram_share``. Optional ingredients are left out of the
totals (the cook may skip them).

Carbohydrate: FCT ``glucid`` is available carbohydrate (FCT energy is exactly 4·P + 9·L + 4·G). USDA ``carb_g``
is "by difference" and includes fibre, so ``glucid = carb_g − fiber_g`` for USDA items.

Run from the repo root::

    uv run --package tastoria-ml python -m tastoria_ml.kb.nutrition data/kb

It writes ``data/processed/kb/recipe_nutrition.csv``, ``recipe_nutrition_flags.csv`` (sanity checks) and
``rice_bowl.json``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from tastoria_ml.kb.models import Ingredient
from tastoria_ml.kb.recipes import Recipe, load_proposed, load_recipes

RULES_VERSION = "nut-r1"

NUTRIENTS = ("energy_kcal", "protein_g", "lipid_g", "glucid_g", "fiber_g", "sodium_mg")

# Bognár A. (2002) Tables on weight yield of food and retention factors of food constituents for the
# calculation of nutrient composition of cooked foods (dishes). Berichte der Bundesforschungsanstalt für
# Ernährung, BFE-R--02-03, Karlsruhe. Part 2: fat uptake "in gram related to 100 g food ingredients";
# deep fry column of the breaded tables ranges 4 (chicken, T13) – 6 (fish, T21); 5 = pork (T7), vegetables (T27).
DEEP_FRY_UPTAKE_G_PER_100G = 5.0
DEEP_FRY_MARKER = "BR-NUT-05"
FRYING_OILS = frozenset({"dầu ăn", "dầu lạc", "dầu vừng", "dầu ô liu", "mỡ lợn"})

# Ingredients bought with bone or shell whose composition row is for the edible part only (USDA) or whose
# FCT row has no refuse: borrow the refuse of an FCT item (code, refuse %, reason).
REFUSE_OVERRIDES: dict[str, tuple[str, float, str]] = {
    "cánh gà": ("7013", 52.0, "cân cả xương; USDA 172390 là phần thịt + da; lấy thải bỏ FCT 7013 'Thịt gà ta'"),
    "đùi gà": ("7013", 52.0, "cân cả xương; USDA 172385 là phần thịt + da; lấy thải bỏ FCT 7013 'Thịt gà ta'"),
    "chim cút": ("7013", 52.0, "mua cả con; USDA 172418 là phần thịt + da; lấy thải bỏ FCT 7013 'Thịt gà ta'"),
    "nghêu": ("8048", 80.0, "mua cả vỏ; USDA 174214 là phần thịt; lấy thải bỏ FCT 8048 'Sò' (hai mảnh vỏ)"),
    "cá nục": ("8026", 35.0, "FCT 8020 không ghi thải bỏ; mua nguyên con; lấy FCT 8026 'Cá thu' cùng nhóm cá biển"),
}

# Proxy rows that need a moisture correction: name -> (factor on every nutrient, reason).
# Vital wheat gluten (USDA 168147) is a dry powder with 8.2 % water; mì căn is sold wet. Assumed 68 % water
# (homemade seitan), so factor = (100 − 68) / (100 − 8.2) = 0.349.
SCALE_OVERRIDES: dict[str, tuple[float, str]] = {
    "mì căn": ((100 - 68) / (100 - 8.2), "USDA 168147 là bột gluten khô; mì căn ướt giả định 68 % nước"),
}

# Sodium-only values for ingredients without a composition row (energy contribution negligible).
SODIUM_ONLY: dict[str, tuple[float, str]] = {
    "bột ngọt": (12_300.0, "natri 12,3 g/100 g theo công thức mononatri glutamat ngậm 1 nước (ghi chú ingredients.yaml)"),
}

# kcal per serving considered plausible for one dish of a family tray, per slot; outside -> flagged.
PLAUSIBLE_KCAL: dict[str, tuple[float, float]] = {"man": (80, 650), "rau": (10, 250), "canh": (10, 300)}
ATWATER_TOLERANCE = 0.10

# Cooked rice (BR-TRAY-03). FCT 2007 has no "cơm" row; derive from gạo tẻ máy with the weight yield of
# boiled polished long-grain rice in Bognár (2002) Part 1, Table 29 (2.98 ± 0.05, n = 140).
RICE_BOWL_G = 150.0
RICE_CODE = "1004"
RICE_YIELD = 2.98


@dataclass(frozen=True)
class Comp:
    """Composition per 100 g edible portion; ``None`` = not analysed in the source table."""

    energy_kcal: float
    protein_g: float | None
    lipid_g: float | None
    glucid_g: float | None
    fiber_g: float | None
    sodium_mg: float | None
    refuse_pct: float | None = None

    def scaled(self, f: float) -> Comp:
        def s(v):
            return None if v is None else v * f

        return Comp(self.energy_kcal * f, s(self.protein_g), s(self.lipid_g), s(self.glucid_g),
                    s(self.fiber_g), s(self.sodium_mg), self.refuse_pct)


@dataclass(frozen=True)
class Resolved:
    """What one ingredient name maps to: composition per 100 g edible, edible fraction, provenance."""

    name: str
    comp: Comp | None
    ep: float
    source: str
    note: str = ""


def _f(v: str | None) -> float | None:
    if v is None or v == "":
        return None
    x = float(v)
    return None if math.isnan(x) else x


def _sha8(*paths: Path) -> str:
    h = hashlib.sha256()
    for p in paths:
        h.update(Path(p).read_bytes())
    return h.hexdigest()[:8]


def load_fct(processed_dir: Path) -> dict[str, Comp]:
    d = Path(processed_dir) / "fct2007"
    sodium: dict[str, float | None] = {}
    with (d / "nutrients_long.csv").open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row["nutrient"] == "sodium":
                sodium[row["code"]] = _f(row["value"])
    out: dict[str, Comp] = {}
    with (d / "foods.csv").open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            e = _f(row["energy_kcal"])
            if e is None:
                continue
            out[row["code"]] = Comp(e, _f(row["protein_g"]), _f(row["lipid_g"]), _f(row["glucid_g"]),
                                    _f(row["fiber_g"]), sodium.get(row["code"]), _f(row["refuse_pct"]))
    return out


def load_usda(processed_dir: Path) -> dict[str, Comp]:
    out: dict[str, Comp] = {}
    with (Path(processed_dir) / "usda" / "foods.csv").open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            e = _f(row["energy_kcal"])
            if e is None:
                continue
            carb, fib = _f(row["carb_g"]), _f(row["fiber_g"])
            glucid = None if carb is None else max(carb - (fib or 0.0), 0.0)
            out[row["fdc_id"]] = Comp(e, _f(row["protein_g"]), _f(row["fat_g"]), glucid, fib, _f(row["sodium_mg"]))
    return out


class Resolver:
    """Maps ingredient names to composition rows following ``comp_source`` and the overrides above."""

    def __init__(self, ingredients: Iterable[Ingredient], fct: Mapping[str, Comp], usda: Mapping[str, Comp],
                 data_version: str = "test"):
        self.ingredients = {i.name_vi: i for i in ingredients}
        self.fct, self.usda = fct, usda
        self.data_version = data_version

    @classmethod
    def from_dirs(cls, kb_dir: Path, processed_dir: Path | None = None) -> Resolver:
        kb_dir = Path(kb_dir)
        processed_dir = Path(processed_dir) if processed_dir else kb_dir.parent / "processed"
        from tastoria_ml.kb.models import IngredientsFile

        ing_path = kb_dir / "ingredients.yaml"
        ing = IngredientsFile.model_validate(yaml.safe_load(ing_path.read_text(encoding="utf-8")))
        proposed, errors = load_proposed(kb_dir)
        if errors:
            raise ValueError("; ".join(errors))
        fct_files = [processed_dir / "fct2007" / "foods.csv", processed_dir / "fct2007" / "nutrients_long.csv"]
        usda_file = processed_dir / "usda" / "foods.csv"
        version = (f"{RULES_VERSION}+kb{ing.version}:{_sha8(ing_path, *[p for p in sorted(kb_dir.glob('ingredients_proposed*.yaml'))])}"
                   f"+fct2007:{_sha8(*fct_files)}+usda:{_sha8(usda_file)}")
        return cls([*ing.ingredients, *proposed], load_fct(processed_dir), load_usda(processed_dir), version)

    def resolve(self, name: str) -> Resolved:
        ing = self.ingredients.get(name)
        if ing is None:
            raise KeyError(f"unknown ingredient {name!r}")
        cs = ing.comp_source
        if cs.source is None:
            if name in SODIUM_ONLY:
                na, why = SODIUM_ONLY[name]
                return Resolved(name, Comp(0.0, 0.0, 0.0, 0.0, 0.0, na), 1.0, "sodium_only", why)
            return Resolved(name, None, 1.0, "none", cs.reason or "")
        table = self.fct if cs.source == "fct2007" else self.usda
        comp = table.get(cs.code)
        if comp is None:
            raise KeyError(f"{name}: {cs.source} code {cs.code} not in processed table")
        note = ""
        if name in REFUSE_OVERRIDES:
            _, refuse, note = REFUSE_OVERRIDES[name]
            ep = 1 - refuse / 100
        elif cs.source == "fct2007":
            ep = 1 - (comp.refuse_pct or 0.0) / 100
        else:
            ep = 1.0
        if name in SCALE_OVERRIDES:
            f, why = SCALE_OVERRIDES[name]
            comp = comp.scaled(f)
            note = f"{note}; {why}" if note else why
        return Resolved(name, comp, ep, f"{cs.source}:{cs.code}", note)


@dataclass
class Line:
    name: str
    grams: float
    edible_g: float
    counted_g: float  # grams entering the sum (edible; for frying oil: absorbed fat only)
    source: str
    covered: bool
    nutrients: dict[str, float | None]


@dataclass
class DishNutrition:
    totals: dict[str, float]
    lines: list[Line]
    total_g: float
    uncovered_g: float
    sodium_known_g: float
    deep_fried: bool = False
    oil_g: float = 0.0
    oil_absorbed_g: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def uncovered_gram_share(self) -> float:
        return self.uncovered_g / self.total_g if self.total_g else 0.0

    @property
    def atwater_kcal(self) -> float:
        t = self.totals
        return 4 * t["protein_g"] + 9 * t["lipid_g"] + 4 * t["glucid_g"]


def compute(items: Iterable[tuple], resolver: Resolver, *, deep_fried: bool = False,
            edible_weights: bool = False) -> DishNutrition:
    """Sum nutrients over ``(ingredient name, grams)`` or ``(name, grams, as_purchased)``.

    ``edible_weights`` = grams are already edible portion (EP = 1), as in most NIN dish compositions;
    a third tuple element ``as_purchased=True`` overrides it for one item (e.g. "cua đồng (nguyên con)").
    ``deep_fried`` = count only the absorbed part of the frying oil.
    """
    items = [(it[0], it[1], it[2] if len(it) > 2 else not edible_weights) for it in items]
    resolved = [(resolver.resolve(n), g) for n, g, _ in items]
    as_purchased = [ap for _, _, ap in items]
    totals = {k: 0.0 for k in NUTRIENTS}
    lines: list[Line] = []
    oil_g = sum(g for r, g in resolved if r.name in FRYING_OILS) if deep_fried else 0.0
    absorbed = 0.0
    if deep_fried and oil_g:
        food_g = sum(g for r, g in resolved if r.name not in FRYING_OILS)
        absorbed = min(oil_g, DEEP_FRY_UPTAKE_G_PER_100G * food_g / 100)
    total_g = uncovered_g = sodium_known_g = 0.0
    for (r, g), ap in zip(resolved, as_purchased, strict=True):
        total_g += g
        ep = r.ep if ap else 1.0
        edible = g * ep
        counted = edible * (absorbed / oil_g) if (deep_fried and r.name in FRYING_OILS and oil_g) else edible
        nut: dict[str, float | None] = {}
        if r.comp is None:
            uncovered_g += g
        else:
            for k in NUTRIENTS:
                v = getattr(r.comp, k)
                nut[k] = None if v is None else counted * v / 100
                if nut[k] is not None:
                    totals[k] += nut[k]
            if r.comp.sodium_mg is not None:
                sodium_known_g += g
        lines.append(Line(r.name, g, edible, counted, r.source, r.comp is not None, nut))
    return DishNutrition(totals, lines, total_g, uncovered_g, sodium_known_g, deep_fried, oil_g, absorbed)


def is_deep_fried(recipe: Recipe) -> bool:
    return recipe.method == "chien" and DEEP_FRY_MARKER in (recipe.notes or "")


def recipe_items(recipe: Recipe) -> list[tuple[str, float]]:
    return [(i.name, i.grams) for i in recipe.ingredients if not i.optional]


@dataclass
class RecipeRow:
    slug: str
    slot: str
    servings: int
    kcal_per_serving: float
    protein_g: float
    lipid_g: float
    glucid_g: float
    fiber_g: float
    sodium_mg: float | None
    sodium_gram_share: float
    uncovered_gram_share: float
    deep_fried: bool
    oil_absorbed_g: float
    atwater_kcal_per_serving: float
    data_version: str


def recipe_row(recipe: Recipe, resolver: Resolver) -> RecipeRow:
    dn = compute(recipe_items(recipe), resolver, deep_fried=is_deep_fried(recipe))
    s = recipe.servings
    t = dn.totals
    covered_g = dn.total_g - dn.uncovered_g
    na_share = dn.sodium_known_g / covered_g if covered_g else 0.0
    return RecipeRow(
        slug=recipe.slug, slot=recipe.slot, servings=s,
        kcal_per_serving=round(t["energy_kcal"] / s, 1),
        protein_g=round(t["protein_g"] / s, 1), lipid_g=round(t["lipid_g"] / s, 1),
        glucid_g=round(t["glucid_g"] / s, 1), fiber_g=round(t["fiber_g"] / s, 1),
        sodium_mg=round(t["sodium_mg"] / s) if na_share > 0 else None,
        sodium_gram_share=round(na_share, 3),
        uncovered_gram_share=round(dn.uncovered_gram_share, 3),
        deep_fried=dn.deep_fried, oil_absorbed_g=round(dn.oil_absorbed_g, 1),
        atwater_kcal_per_serving=round(dn.atwater_kcal / s, 1),
        data_version=resolver.data_version,
    )


def flags(row: RecipeRow) -> list[str]:
    out = []
    lo, hi = PLAUSIBLE_KCAL[row.slot]
    if not lo <= row.kcal_per_serving <= hi:
        out.append(f"kcal/serving {row.kcal_per_serving} outside [{lo}, {hi}] for slot {row.slot}")
    if row.kcal_per_serving > 0:
        dev = row.atwater_kcal_per_serving / row.kcal_per_serving - 1
        if abs(dev) > ATWATER_TOLERANCE:
            out.append(f"Atwater 4P+9L+4G differs from table energy by {dev:+.1%}")
    if row.uncovered_gram_share > 0.2:
        out.append(f"{row.uncovered_gram_share:.0%} of recipe grams have no composition")
    return out


def rice_bowl(fct: Mapping[str, Comp], grams: float = RICE_BOWL_G, cooked_yield: float = RICE_YIELD) -> dict:
    """Energy of ``grams`` cooked rice derived from raw gạo tẻ máy and a cooked/raw weight yield."""
    raw = fct[RICE_CODE]
    raw_g = grams / cooked_yield
    out = {k: round(raw_g * getattr(raw, k) / 100, 1) for k in NUTRIENTS if getattr(raw, k) is not None}
    return {"cooked_g": grams, "raw_rice_g": round(raw_g, 1), "fct_code": RICE_CODE, "cooked_yield": cooked_yield,
            "yield_source": "Bognár 2002 BFE-R--02-03 Part 1 Table 29: rice, long corn, polished, boiled 2.98 ± 0.05 (n=140)",
            **out}


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def run(kb_dir: Path, out_dir: Path | None = None, processed_dir: Path | None = None) -> tuple[list[RecipeRow], dict]:
    kb_dir = Path(kb_dir)
    out_dir = Path(out_dir) if out_dir else kb_dir.parent / "processed" / "kb"
    resolver = Resolver.from_dirs(kb_dir, processed_dir)
    rep = load_recipes(kb_dir)
    if rep.errors:
        raise ValueError("\n".join(rep.errors))
    recipes = sorted(rep.recipes.values(), key=lambda r: (r.slot, r.slug))
    rows = [recipe_row(r, resolver) for r in recipes]
    write_csv(out_dir / "recipe_nutrition.csv", [asdict(r) for r in rows])
    flag_rows = [{"slug": r.slug, "slot": r.slot, "kcal_per_serving": r.kcal_per_serving, "flag": f}
                 for r in rows for f in flags(r)]
    write_csv(out_dir / "recipe_nutrition_flags.csv",
              flag_rows or [{"slug": "", "slot": "", "kcal_per_serving": "", "flag": ""}])
    bowl = {**rice_bowl(resolver.fct), "data_version": resolver.data_version}
    (out_dir / "rice_bowl.json").write_text(json.dumps(bowl, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return rows, bowl


# ---------------------------------------------------------------- validation against Viện Dinh dưỡng (BR-NUT-06)

NIN_HEADER = """\
# Kiểm định calo với công cụ "Giá trị dinh dưỡng món ăn" của Viện Dinh dưỡng (BR-NUT-06).
# Tra TỪNG MÓN bằng tay trên https://viendinhduong.vn/vi/cong-cu-va-tien-ich/gia-tri-dinh-duong-mon-an
# (không tải hàng loạt). Thành phần (gam) chép tay từ ảnh của món; nin_* chép từ trang.
# composition[].ingredient = tên nguyên liệu trong data/kb/ingredients.yaml (null = không có, tính là phần
# không phủ). Các trường our_* và rel_error do lệnh sau ghi lại, đừng sửa tay:
#   uv run --package tastoria-ml python -m tastoria_ml.kb.nutrition data/kb --nin data/kb/validation/nin_dishes.yaml
# Gam của Viện coi là phần ăn được (sống sạch), nên tính với EP = 1; our_kcal_ap là cùng thành phần nhưng
# coi gam là lúc mua (trừ thải bỏ như công thức của mình) để thấy độ nhạy.
"""


def quantile(xs: list[float], q: float) -> float:
    """Linear-interpolated quantile (numpy default, type 7)."""
    s = sorted(xs)
    if not s:
        raise ValueError("empty")
    pos = (len(s) - 1) * q
    lo = math.floor(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def validate_nin(path: Path, resolver: Resolver, *, write: bool = True, seed: int = 20261017) -> dict:
    import random

    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    errs = []
    for d in doc["dishes"]:
        items = [(c["ingredient"], c["grams"], bool(c.get("as_purchased", False)))
                 for c in d["composition"] if c.get("ingredient")]
        items_ap = [(n, g, True) for n, g, _ in items]
        fried = bool(d.get("deep_fried", False))
        dn = compute(items, resolver, edible_weights=True, deep_fried=fried)
        nut_ap = compute(items_ap, resolver, deep_fried=fried)
        total_g = sum(c["grams"] for c in d["composition"])
        uncovered = total_g - (dn.total_g - dn.uncovered_g)
        d["our_kcal"] = round(dn.totals["energy_kcal"], 1)
        d["our_protein_g"] = round(dn.totals["protein_g"], 1)
        d["our_lipid_g"] = round(dn.totals["lipid_g"], 1)
        d["our_glucid_g"] = round(dn.totals["glucid_g"], 1)
        d["our_kcal_ap"] = round(nut_ap.totals["energy_kcal"], 1)
        d["uncovered_gram_share"] = round(uncovered / total_g, 3) if total_g else 0.0
        d["rel_error"] = round(d["our_kcal"] / d["nin_kcal"] - 1, 4)
        errs.append(d["rel_error"])
    abs_errs = [abs(e) for e in errs]
    rng = random.Random(seed)
    boot = sorted(quantile([rng.choice(abs_errs) for _ in abs_errs], 0.8) for _ in range(2000))
    summary = {
        "n": len(errs),
        "p80_abs_rel_error": round(quantile(abs_errs, 0.8), 4),
        "p80_bootstrap_95ci": [round(quantile(boot, 0.025), 4), round(quantile(boot, 0.975), 4)],
        "median_abs_rel_error": round(quantile(abs_errs, 0.5), 4),
        "mean_rel_error": round(sum(errs) / len(errs), 4),
        "median_rel_error": round(quantile(errs, 0.5), 4),
        "within_10pct": sum(a <= 0.10 for a in abs_errs),
        "within_20pct": sum(a <= 0.20 for a in abs_errs),
        "data_version": resolver.data_version,
    }
    doc["summary"] = summary
    if write:
        body = yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=120)
        Path(path).write_text(NIN_HEADER + body, encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Per-serving nutrition of data/kb/recipes/** (BR-NUT-05)")
    ap.add_argument("kb_dir", type=Path)
    ap.add_argument("--out", type=Path, default=None, help="output dir (default: <kb_dir>/../processed/kb)")
    ap.add_argument("--processed", type=Path, default=None, help="data/processed (default: <kb_dir>/../processed)")
    ap.add_argument("--nin", type=Path, default=None,
                    help="also recompute the Viện Dinh dưỡng comparison file (data/kb/validation/nin_dishes.yaml)")
    args = ap.parse_args(argv)
    if args.nin:
        s = validate_nin(args.nin, Resolver.from_dirs(args.kb_dir, args.processed))
        print(json.dumps(s, ensure_ascii=False, indent=2))
    rows, bowl = run(args.kb_dir, args.out, args.processed)
    n_flag = sum(1 for r in rows if flags(r))
    print(f"recipes: {len(rows)}; flagged: {n_flag}; data_version: {rows[0].data_version if rows else '-'}")
    for slot in ("man", "rau", "canh"):
        ks = sorted(r.kcal_per_serving for r in rows if r.slot == slot)
        if ks:
            print(f"  {slot}: n={len(ks)} kcal/serving median {ks[len(ks) // 2]} range {ks[0]}–{ks[-1]}")
    print(f"E_bowl ({bowl['cooked_g']:.0f} g cooked rice = {bowl['raw_rice_g']} g gạo tẻ): {bowl['energy_kcal']} kcal")
    for r in rows:
        for f in flags(r):
            print(f"  FLAG {r.slug}: {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
