"""Parse and check data/kb/substitution_pairs.yaml against the loaded catalog (private to admin).

Same rules as `tastoria_ml.kb.substitutes` (the authoring-side validator), re-checked here against the database:
names resolve to active ingredients (canonical name_vi, not synonyms), no self pair, cooking method exists, same food
group (FR-17-05 would drop the pair at runtime anyway), unique by (ingredient, substitute, slot, method), ratio > 0,
0 <= score <= 1, curated true, a non-empty source. Problems are `file:line: code: message`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from tastoria.modules.catalog.schemas import IngredientView
from tastoria.modules.substitute.schemas import CuratedPair

FIELDS = {"ingredient", "substitute", "context_slot", "context_method", "ratio", "score", "source", "curated"}
SLOTS = {"man", "rau", "canh"}


@dataclass
class ParsedFile:
    rel: str
    items: list[tuple[int, dict[str, Any]]] = field(default_factory=list)  # (line, mapping)
    errors: list[str] = field(default_factory=list)


def parse(path: Path) -> ParsedFile:
    out = ParsedFile(rel=path.name)
    try:
        text = path.read_text(encoding="utf-8")
        node = yaml.compose(text)
        data = yaml.safe_load(text)
    except OSError as exc:
        out.errors.append(f"{out.rel}:1: io_error: {exc}")
        return out
    except yaml.YAMLError as exc:
        line = getattr(getattr(exc, "problem_mark", None), "line", 0) + 1
        out.errors.append(f"{out.rel}:{line}: yaml_error: {exc}")
        return out
    if not isinstance(data, dict) or not isinstance(data.get("pairs"), list) or not data["pairs"]:
        out.errors.append(f"{out.rel}:1: shape: cần khoá 'pairs' là danh sách không rỗng")
        return out
    seq = next(v for k, v in node.value if k.value == "pairs")  # type: ignore[union-attr]
    for item_node, item in zip(seq.value, data["pairs"], strict=True):
        out.items.append((item_node.start_mark.line + 1, item))
    return out


def _decimal(v: Any) -> Decimal | None:
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


def resolve(
    parsed: ParsedFile, ingredients: dict[str, IngredientView], methods: frozenset[str]
) -> tuple[list[CuratedPair], list[str]]:
    errors = list(parsed.errors)
    pairs: list[CuratedPair] = []
    seen: dict[tuple[Any, ...], int] = {}

    def err(line: int, code: str, msg: str) -> None:
        errors.append(f"{parsed.rel}:{line}: {code}: {msg}")

    for line, it in parsed.items:
        if not isinstance(it, dict):
            err(line, "shape", "mỗi cặp là một mapping")
            continue
        if set(it) != FIELDS:
            err(line, "shape", f"thiếu {sorted(FIELDS - set(it))}, thừa {sorted(set(it) - FIELDS)}")
            continue
        a, b = ingredients.get(it["ingredient"]), ingredients.get(it["substitute"])
        ok = True
        for name, ing in ((it["ingredient"], a), (it["substitute"], b)):
            if ing is None:
                err(line, "unknown_ingredient", f"{name!r} không phải tên chuẩn của nguyên liệu đang dùng")
                ok = False
        slot, method = it["context_slot"], it["context_method"]
        if slot is not None and slot not in SLOTS:
            err(line, "unknown_ref", f"context_slot {slot!r} không thuộc man/rau/canh")
            ok = False
        if method is not None and method not in methods:
            err(line, "unknown_ref", f"context_method {method!r} không có trong cooking_methods")
            ok = False
        ratio, score = _decimal(it["ratio"]), it["score"]
        if ratio is None or ratio <= 0:
            err(line, "range", f"ratio phải > 0, có {it['ratio']!r}")
            ok = False
        if isinstance(score, bool) or not isinstance(score, int | float) or not (0 <= score <= 1) or math.isnan(score):
            err(line, "range", f"score phải trong [0, 1], có {score!r}")
            ok = False
        if it["curated"] is not True:
            err(line, "shape", "curated phải là true (bảng do nhóm soạn)")
            ok = False
        if not isinstance(it["source"], str) or not it["source"].strip():
            err(line, "shape", "source không được rỗng")
            ok = False
        if a is not None and b is not None:
            if a.id == b.id:
                err(line, "self_pair", f"{a.name_vi} thay chính nó")
                ok = False
            elif a.food_group_code != b.food_group_code:
                err(
                    line,
                    "food_group",
                    f"{a.name_vi} ({a.food_group_code}) và {b.name_vi} ({b.food_group_code}) khác nhóm thực phẩm",
                )
                ok = False
        key = (it["ingredient"], it["substitute"], slot, method)
        if key in seen:
            err(line, "duplicate", f"trùng cặp ở dòng {seen[key]}")
            ok = False
        else:
            seen[key] = line
        if ok:
            assert a is not None and b is not None and ratio is not None
            pairs.append(CuratedPair(a.id, b.id, slot, method, ratio, float(score), it["source"].strip()))
    return pairs, errors
