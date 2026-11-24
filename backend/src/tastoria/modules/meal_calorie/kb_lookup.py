"""Private KB dish lookup & NIN-calibrated uncertainty loader (stdlib + PyYAML only)."""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import yaml

PORTION_MULTIPLIERS: dict[str, float] = {"nho": 0.75, "vua": 1.0, "lon": 1.35}
DEFAULT_HALF_WIDTH = 0.25
_SERVING_MASS_RE = re.compile(r"~?(\d+(?:\.\d+)?)\s*(?:g|ml)(?=[\s,)\]/]|$)")


def _parse_serving_g(raw_val: object, serving_desc_vi: str) -> float | None:
    if isinstance(raw_val, int | float) and not isinstance(raw_val, bool) and float(raw_val) > 0:
        return round(float(raw_val), 1)
    m = _SERVING_MASS_RE.search(serving_desc_vi or "")
    if m:
        val = float(m.group(1))
        if val > 0:
            return round(val, 1)
    return None


def _fold_vi(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text.strip().casefold())
    stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
    return stripped.replace("đ", "d")


def _nfc_cf(text: str) -> str:
    return unicodedata.normalize("NFC", text.strip()).casefold()


def _word_boundary_match(folded_query: str, folded_target: str) -> bool:
    return bool(re.search(rf"(?<!\w){re.escape(folded_query)}(?!\w)", folded_target))


def _words_diacritic_compatible(q_words: list[str], c_words: list[str]) -> bool:
    if len(q_words) != len(c_words):
        return False
    for qw, cw in zip(q_words, c_words):
        if _fold_vi(qw) != _fold_vi(cw):
            return False
        if len(qw) != len(cw):
            continue
        for qc, cc in zip(qw, cw):
            if qc != _fold_vi(qc) and qc != cc:
                return False
    return True


def _diacritic_compatible(query_nfc_cf: str, cand_nfc_cf: str, *, mode: str) -> bool:
    """Allow unaccented ASCII queries to match accented Vietnamese, while rejecting conflicting accents (e.g. Cơm vs Cốm)."""
    if query_nfc_cf == _fold_vi(query_nfc_cf):
        return True
    q_words = re.findall(r"\w+", query_nfc_cf)
    c_words = re.findall(r"\w+", cand_nfc_cf)
    if not q_words or not c_words:
        return True
    if mode == "exact":
        return _words_diacritic_compatible(q_words, c_words)
    if mode == "word_start":
        return len(c_words) >= len(q_words) and _words_diacritic_compatible(q_words, c_words[: len(q_words)])
    if mode == "word_boundary":
        n = len(q_words)
        return any(_words_diacritic_compatible(q_words, c_words[i : i + n]) for i in range(max(0, len(c_words) - n + 1)))
    if mode == "prefix":
        return len(q_words) >= len(c_words) and _words_diacritic_compatible(q_words[: len(c_words)], c_words)
    return True


@dataclass(frozen=True)
class KBDishNutrition:
    slug: str
    name_vi: str
    slot: str
    servings: int
    kcal_per_serving: float
    protein_g: float
    lipid_g: float
    glucid_g: float
    fiber_g: float
    data_version: str


@dataclass(frozen=True)
class RecognizedDishNutrition:
    dish_id: str
    name_vi: str
    name_en: str
    category: str
    kb_slug: str | None
    slot: str
    kcal_per_serving: float
    protein_g: float
    lipid_g: float
    glucid_g: float
    fiber_g: float
    serving_desc_vi: str
    source_ref: str
    serving_g: float | None = None


@dataclass(frozen=True)
class KBPortionEstimate:
    slug: str
    name_vi: str
    slot: str
    portion: str
    portion_multiplier: float
    estimated_kcal: float
    kcal_low: float
    kcal_high: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float
    half_width_rel: float
    calibrated: bool
    serving_g: float | None = None


class KBDishCatalog:
    """In-memory index of Tastoria's calibrated KB dish nutrition + extended recognized dish table."""

    def __init__(
        self,
        dishes: list[KBDishNutrition],
        *,
        half_width_rel: float,
        calibrated: bool,
        data_version: str,
        recognized: list[RecognizedDishNutrition] | None = None,
    ) -> None:
        self.dishes = sorted(dishes, key=lambda d: (d.slot, d.slug))
        self.by_slug = {d.slug: d for d in self.dishes}
        self._by_exact_name = {_nfc_cf(d.name_vi): d for d in self.dishes}
        self._by_folded_name = {_fold_vi(d.name_vi): d for d in self.dishes}
        self._dl_entries: list[tuple[str, str, KBDishNutrition]] = [
            (_fold_vi(d.name_vi), _nfc_cf(d.name_vi), d) for d in self.dishes
        ]
        self.recognized = list(recognized or [])
        self.recognized_by_id = {d.dish_id: d for d in self.recognized}
        self._rec_by_exact: dict[str, RecognizedDishNutrition] = {}
        self._rec_by_folded: dict[str, RecognizedDishNutrition] = {}
        self._rec_entries: list[tuple[str, str, RecognizedDishNutrition]] = []
        for d in self.recognized:
            vi_cf = _nfc_cf(d.name_vi)
            vi_f = _fold_vi(d.name_vi)
            self._rec_by_exact[vi_cf] = d
            self._rec_by_folded[vi_f] = d
            self._rec_entries.append((vi_f, vi_cf, d))
        for d in self.recognized:
            en_cf = _nfc_cf(d.name_en)
            en_f = _fold_vi(d.name_en)
            self._rec_by_exact.setdefault(en_cf, d)
            self._rec_by_folded.setdefault(en_f, d)
            self._rec_entries.append((en_f, en_cf, d))
        self.half_width_rel = half_width_rel
        self.calibrated = calibrated
        self.data_version = data_version

    @classmethod
    def from_dirs(cls, kb_dir: Path, kb_processed_dir: Path) -> KBDishCatalog:
        kb_dir = Path(kb_dir)
        kb_processed_dir = Path(kb_processed_dir)
        dish_list_path = kb_dir / "dish_list.yaml"
        csv_path = kb_processed_dir / "recipe_nutrition.csv"
        if not dish_list_path.exists() or not csv_path.exists():
            raise FileNotFoundError(f"KB nutrition files not found in {kb_dir} / {kb_processed_dir}")

        dish_list = yaml.safe_load(dish_list_path.read_text(encoding="utf-8"))["dishes"]
        name_by_slug = {d["slug"]: d["name_vi"] for d in dish_list}

        dishes: list[KBDishNutrition] = []
        versions: set[str] = set()
        with csv_path.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                slug = row["slug"]
                versions.add(row["data_version"])
                dishes.append(
                    KBDishNutrition(
                        slug=slug,
                        name_vi=name_by_slug.get(slug, slug),
                        slot=row["slot"],
                        servings=int(row["servings"]),
                        kcal_per_serving=float(row["kcal_per_serving"]),
                        protein_g=float(row["protein_g"]),
                        lipid_g=float(row["lipid_g"]),
                        glucid_g=float(row["glucid_g"]),
                        fiber_g=float(row["fiber_g"]),
                        data_version=row["data_version"],
                    )
                )

        recognized: list[RecognizedDishNutrition] = []
        seen_rec_ids: set[str] = set()
        rec_path = kb_dir / "recognized_dishes_nutrition.yaml"
        if rec_path.exists():
            rec_doc = yaml.safe_load(rec_path.read_text(encoding="utf-8")) or {}
            for r in rec_doc.get("dishes") or []:
                did = str(r["dish_id"])
                seen_rec_ids.add(did)
                sdesc = str(r.get("serving_desc_vi") or "")
                recognized.append(
                    RecognizedDishNutrition(
                        dish_id=did,
                        name_vi=str(r["name_vi"]),
                        name_en=str(r["name_en"]),
                        category=str(r["category"]),
                        kb_slug=r.get("kb_slug"),
                        slot=str(r["slot"]),
                        kcal_per_serving=float(r["kcal_per_serving"]),
                        protein_g=float(r["protein_g"]),
                        lipid_g=float(r["lipid_g"]),
                        glucid_g=float(r["glucid_g"]),
                        fiber_g=float(r["fiber_g"]),
                        serving_desc_vi=sdesc,
                        source_ref=str(r.get("source_ref") or ""),
                        serving_g=_parse_serving_g(r.get("serving_g"), sdesc),
                    )
                )
        open_path = kb_dir / "dish_taxonomy_expanded.json"
        if open_path.exists():
            open_doc = json.loads(open_path.read_text(encoding="utf-8")) or {}
            for r in open_doc.get("dishes") or []:
                did = str(r.get("dish_id") or "")
                if not did or did in seen_rec_ids:
                    continue
                seen_rec_ids.add(did)
                p = float(r.get("protein_g") or 0.0)
                c = float(r.get("glucid_g") or 0.0)
                f = float(r.get("lipid_g") or 0.0)
                kcal = float(r.get("kcal_per_serving") or round(4.0 * p + 4.0 * c + 9.0 * f, 1))
                sdesc = str(r.get("serving_desc_vi") or "")
                recognized.append(
                    RecognizedDishNutrition(
                        dish_id=did,
                        name_vi=str(r.get("name_vi") or did),
                        name_en=str(r.get("name_en") or did),
                        category=str(r.get("category") or "global"),
                        kb_slug=r.get("kb_slug"),
                        slot=str(r.get("slot") or "man"),
                        kcal_per_serving=kcal,
                        protein_g=p,
                        lipid_g=f,
                        glucid_g=c,
                        fiber_g=float(r.get("fiber_g") or 0.0),
                        serving_desc_vi=sdesc,
                        source_ref=str(r.get("source_ref") or "M7 Expanded Open-Vocab Taxonomy"),
                        serving_g=_parse_serving_g(r.get("serving_g"), sdesc),
                    )
                )
        pkg_path = kb_dir / "everyday_packaged_foods.yaml"
        if pkg_path.exists():
            pkg_doc = yaml.safe_load(pkg_path.read_text(encoding="utf-8")) or {}
            for r in pkg_doc.get("items") or []:
                did = str(r["id"])
                if did in seen_rec_ids:
                    continue
                seen_rec_ids.add(did)
                p = float(r["protein_g"])
                c = float(r["glucid_g"])
                f = float(r["lipid_g"])
                kcal = float(r.get("kcal_per_serving") or round(4.0 * p + 4.0 * c + 9.0 * f, 1))
                sdesc = str(r.get("serving_desc_vi") or "")
                recognized.append(
                    RecognizedDishNutrition(
                        dish_id=did,
                        name_vi=str(r["name_vi"]),
                        name_en=str(r["name_en"]),
                        category="packaged",
                        kb_slug=None,
                        slot=str(r.get("slot") or "man"),
                        kcal_per_serving=kcal,
                        protein_g=p,
                        lipid_g=f,
                        glucid_g=c,
                        fiber_g=float(r.get("fiber_g") or 0.0),
                        serving_desc_vi=sdesc,
                        source_ref=str(r.get("source_ref") or ""),
                        serving_g=_parse_serving_g(r.get("serving_g"), sdesc),
                    )
                )
        open_path = kb_dir / "dish_taxonomy_expanded.json"
        if open_path.exists():
            open_doc = json.loads(open_path.read_text(encoding="utf-8")) or {}
            for r in open_doc.get("dishes") or []:
                did = str(r.get("dish_id") or "")
                if not did or did in seen_rec_ids:
                    continue
                seen_rec_ids.add(did)
                p = float(r.get("protein_g") or 0.0)
                c = float(r.get("glucid_g") or 0.0)
                f = float(r.get("lipid_g") or 0.0)
                kcal = float(r.get("kcal_per_serving") or round(4.0 * p + 4.0 * c + 9.0 * f, 1))
                sdesc = str(r.get("serving_desc_vi") or "")
                recognized.append(
                    RecognizedDishNutrition(
                        dish_id=did,
                        name_vi=str(r.get("name_vi") or did),
                        name_en=str(r.get("name_en") or did),
                        category=str(r.get("category") or "global"),
                        kb_slug=r.get("kb_slug"),
                        slot=str(r.get("slot") or "man"),
                        kcal_per_serving=kcal,
                        protein_g=p,
                        lipid_g=f,
                        glucid_g=c,
                        fiber_g=float(r.get("fiber_g") or 0.0),
                        serving_desc_vi=sdesc,
                        source_ref=str(r.get("source_ref") or "M7 Expanded Open-Vocab Taxonomy"),
                        serving_g=_parse_serving_g(r.get("serving_g"), sdesc),
                    )
                )

        data_version = next(iter(versions)) if len(versions) == 1 else "mixed"
        half_width = DEFAULT_HALF_WIDTH
        calibrated = False
        nin_path = kb_dir / "validation" / "nin_dishes.yaml"
        if nin_path.exists():
            nin_doc = yaml.safe_load(nin_path.read_text(encoding="utf-8"))
            summary = nin_doc.get("summary") or {}
            if (
                isinstance(summary.get("n"), int)
                and summary["n"] >= 30
                and summary.get("data_version") == data_version
                and isinstance(summary.get("p80_abs_rel_error"), int | float)
            ):
                half_width = float(summary["p80_abs_rel_error"])
                calibrated = True

        return cls(
            dishes,
            half_width_rel=half_width,
            calibrated=calibrated,
            data_version=data_version,
            recognized=recognized,
        )

    @staticmethod
    def _match_entries_by_tier(
        entries: list[tuple[str, str, Any]],
        exact_map: dict[str, Any],
        dish_name: str,
        *,
        tier: str,
    ) -> Any | None:
        query_cf = _nfc_cf(dish_name)
        folded = _fold_vi(dish_name)
        if not folded:
            return None
        if tier == "exact":
            if query_cf in exact_map:
                return exact_map[query_cf]
            exact_folded = [
                d
                for k, orig_cf, d in entries
                if k == folded and _diacritic_compatible(query_cf, orig_cf, mode="exact")
            ]
            return exact_folded[0] if exact_folded else None
        if len(folded) < 3:
            return None
        if tier == "word_start":
            matches = [
                d
                for k, orig_cf, d in entries
                if k.startswith(folded + " ") and _diacritic_compatible(query_cf, orig_cf, mode="word_start")
            ]
            return min(matches, key=lambda d: len(d.name_vi)) if matches else None
        if tier == "word_boundary":
            matches = [
                d
                for k, orig_cf, d in entries
                if _word_boundary_match(folded, k) and _diacritic_compatible(query_cf, orig_cf, mode="word_boundary")
            ]
            return min(matches, key=lambda d: len(d.name_vi)) if matches else None
        if tier == "prefix":
            prefix_matches = [
                (k, d)
                for k, orig_cf, d in entries
                if len(k) >= 3 and folded.startswith(k + " ") and _diacritic_compatible(query_cf, orig_cf, mode="prefix")
            ]
            return max(prefix_matches, key=lambda kd: len(kd[0]))[1] if prefix_matches else None
        raise ValueError(f"Unknown lookup tier: {tier!r}")

    def lookup(
        self,
        *,
        dish_slug: str | None = None,
        dish_name: str | None = None,
        exact_only: bool = False,
    ) -> KBDishNutrition | None:
        if dish_slug and dish_slug.strip():
            key = dish_slug.strip().lower()
            return self.by_slug.get(key)
        if dish_name:
            tiers = ("exact",) if exact_only else ("exact", "word_start", "word_boundary", "prefix")
            for tier in tiers:
                hit = self._match_entries_by_tier(self._dl_entries, self._by_exact_name, dish_name, tier=tier)
                if hit is not None:
                    return hit
        return None

    def lookup_recognized(
        self,
        *,
        dish_id: str | None = None,
        dish_name: str | None = None,
        exact_only: bool = False,
    ) -> RecognizedDishNutrition | None:
        if dish_id and dish_id.strip():
            key = dish_id.strip().lower()
            if key in self.recognized_by_id:
                return self.recognized_by_id[key]
        if dish_name:
            tiers = ("exact",) if exact_only else ("exact", "word_start", "word_boundary", "prefix")
            for tier in tiers:
                hit = self._match_entries_by_tier(self._rec_entries, self._rec_by_exact, dish_name, tier=tier)
                if hit is not None:
                    return hit
        return None

    def _build_recognized_estimate(
        self,
        rec: RecognizedDishNutrition,
        *,
        portion: str = "vua",
    ) -> KBPortionEstimate:
        mult = PORTION_MULTIPLIERS[portion]
        scaled_g = round(rec.serving_g * mult, 1) if rec.serving_g is not None else None
        if rec.kb_slug and rec.kb_slug in self.by_slug:
            est = self.estimate(dish_slug=rec.kb_slug, portion=portion)
            if est is not None:
                if est.serving_g is None and scaled_g is not None:
                    return replace(est, serving_g=scaled_g)
                return est
        kcal = round(rec.kcal_per_serving * mult, 1)
        hw = 0.20
        return KBPortionEstimate(
            slug=rec.dish_id,
            name_vi=rec.name_vi,
            slot=rec.slot,
            portion=portion,
            portion_multiplier=mult,
            estimated_kcal=kcal,
            kcal_low=round(max(0.0, kcal * (1.0 - hw)), 1),
            kcal_high=round(kcal * (1.0 + hw), 1),
            protein_g=round(rec.protein_g * mult, 1),
            carbs_g=round(rec.glucid_g * mult, 1),
            fat_g=round(rec.lipid_g * mult, 1),
            fiber_g=round(rec.fiber_g * mult, 1),
            half_width_rel=hw,
            calibrated=False,
            serving_g=scaled_g,
        )

    def _build_dish_estimate(self, entry: KBDishNutrition, *, portion: str = "vua") -> KBPortionEstimate:
        mult = PORTION_MULTIPLIERS[portion]
        kcal = round(entry.kcal_per_serving * mult, 1)
        return KBPortionEstimate(
            slug=entry.slug,
            name_vi=entry.name_vi,
            slot=entry.slot,
            portion=portion,
            portion_multiplier=mult,
            estimated_kcal=kcal,
            kcal_low=round(max(0.0, kcal * (1.0 - self.half_width_rel)), 1),
            kcal_high=round(kcal * (1.0 + self.half_width_rel), 1),
            protein_g=round(entry.protein_g * mult, 1),
            carbs_g=round(entry.glucid_g * mult, 1),
            fat_g=round(entry.lipid_g * mult, 1),
            fiber_g=round(entry.fiber_g * mult, 1),
            half_width_rel=round(self.half_width_rel, 4),
            calibrated=self.calibrated,
        )

    def estimate_recognized(
        self,
        *,
        dish_id: str | None = None,
        dish_name: str | None = None,
        portion: str = "vua",
        exact_only: bool = False,
    ) -> KBPortionEstimate | None:
        if portion not in PORTION_MULTIPLIERS:
            raise ValueError(f"Unsupported portion {portion!r}")
        rec = self.lookup_recognized(dish_id=dish_id, dish_name=dish_name, exact_only=exact_only)
        if rec is None:
            return None
        return self._build_recognized_estimate(rec, portion=portion)

    def estimate(
        self,
        *,
        dish_slug: str | None = None,
        dish_name: str | None = None,
        portion: str = "vua",
        exact_only: bool = False,
    ) -> KBPortionEstimate | None:
        if portion not in PORTION_MULTIPLIERS:
            raise ValueError(f"Unsupported portion {portion!r}")
        entry = self.lookup(dish_slug=dish_slug, dish_name=dish_name, exact_only=exact_only)
        if entry is None:
            return None
        return self._build_dish_estimate(entry, portion=portion)

    def estimate_query(
        self,
        *,
        dish_slug: str | None = None,
        dish_name: str | None = None,
        portion: str = "vua",
    ) -> tuple[KBPortionEstimate | None, bool]:
        """Resolve slug/id or dish_name across both dish_list and recognized dishes by match specificity."""
        if portion not in PORTION_MULTIPLIERS:
            raise ValueError(f"Unsupported portion {portion!r}")
        if dish_slug and dish_slug.strip():
            entry = self.lookup(dish_slug=dish_slug)
            if entry is not None:
                return self._build_dish_estimate(entry, portion=portion), False
            rec = self.lookup_recognized(dish_id=dish_slug)
            if rec is not None:
                return self._build_recognized_estimate(rec, portion=portion), True
            return None, False
        if dish_name and dish_name.strip():
            for tier in ("exact", "word_start", "word_boundary", "prefix"):
                entry = self._match_entries_by_tier(self._dl_entries, self._by_exact_name, dish_name, tier=tier)
                if entry is not None:
                    return self._build_dish_estimate(entry, portion=portion), False
                rec = self._match_entries_by_tier(self._rec_entries, self._rec_by_exact, dish_name, tier=tier)
                if rec is not None:
                    return self._build_recognized_estimate(rec, portion=portion), True
        return None, False
