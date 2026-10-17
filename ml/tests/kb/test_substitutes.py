"""Curated substitution table (data/kb/substitution_pairs.yaml) and evaluation queries (substitution_eval/)."""

import shutil
from pathlib import Path

import pytest
import yaml

from tastoria_ml.kb.substitutes import (
    PAIRS_FILE,
    QUERIES_FILE,
    SubstitutionPair,
    check_pairs,
    check_queries,
    coverage,
)
from tastoria_ml.kb.validate import load_kb

REPO = Path(__file__).resolve().parents[3]
KB = REPO / "data" / "kb"


@pytest.fixture(scope="module")
def kb():
    kb, errors = load_kb(KB)
    assert kb is not None, errors
    return kb


@pytest.fixture(scope="module")
def pairs_report(kb):
    return check_pairs(KB, kb)


@pytest.fixture(scope="module")
def queries_report(kb):
    return check_queries(KB, kb)


@pytest.fixture(scope="module")
def ingredients(kb):
    return {i.name_vi: i for i in kb.ingredients.ingredients}


@pytest.fixture
def kb_copy(tmp_path: Path) -> Path:
    dst = tmp_path / "kb"
    shutil.copytree(KB, dst)
    return dst


def _edit(path: Path, fn) -> None:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    fn(data)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _pair(**kw) -> dict:
    base = {
        "ingredient": "cải ngọt",
        "substitute": "cải thìa",
        "context_slot": "rau",
        "context_method": "xao",
        "ratio": 1,
        "score": 0.8,
        "source": "kiến thức nấu ăn phổ biến: thử",
        "curated": True,
    }
    return {**base, **kw}


# ---------------------------------------------------------------- the real table


def test_real_table_is_valid(pairs_report):
    assert pairs_report.ok, "\n".join(pairs_report.errors)


def test_table_size_and_contexts(pairs_report):
    pairs = pairs_report.pairs
    assert 120 <= len(pairs) <= 200
    slots = {p.context_slot for p in pairs}
    assert {"man", "rau", "canh", None} <= slots
    assert all(p.curated for p in pairs)


def test_examples_of_the_brief_are_present(pairs_report):
    keys = {(p.ingredient, p.substitute, p.context_slot, p.context_method) for p in pairs_report.pairs}
    assert ("cải ngọt", "cải thìa", "rau", "xao") in keys  # cải thìa = cải chíp
    assert ("thịt nạc vai", "thịt ba chỉ", "man", "kho") in keys
    assert ("thịt ba chỉ", "thịt nạc vai", "man", "kho") in keys
    assert ("me chua", "sấu", "canh", "nau_canh") in keys
    assert ("me chua", "chanh", "canh", "nau_canh") in keys


def test_every_pair_is_same_food_group(pairs_report, ingredients):
    for p in pairs_report.pairs:
        assert ingredients[p.ingredient].food_group == ingredients[p.substitute].food_group, p


def test_web_sources_are_urls_and_others_give_a_reason(pairs_report):
    web = [p for p in pairs_report.pairs if p.source.startswith("http")]
    assert web  # at least the pairs checked against cooking guides
    for p in pairs_report.pairs:
        assert p.source.startswith("https://") or len(p.source) > len("kiến thức nấu ăn phổ biến: ") + 10, p


def test_substitutes_that_add_allergens_carry_them_in_ingredients_yaml(pairs_report, ingredients):
    """The runtime filter reads allergens of the substitute from ingredients.yaml; animal groups must carry theirs."""
    added = {(p.ingredient, p.substitute): extra for p, extra in pairs_report.added_allergens}
    assert added[("lạc", "vừng")] == ["vung"]
    assert added[("tôm", "mực")] == ["nhuyen_the"]
    must = {"ca": "ca", "trung": "trung", "sua": "sua"}
    for p in pairs_report.pairs:
        sub = ingredients[p.substitute]
        if sub.food_group in must:
            assert must[sub.food_group] in sub.allergens, p
        if sub.food_group == "hai_san":
            assert set(sub.allergens) & {"giap_xac", "nhuyen_the"}, p


def test_dried_fresh_pairs_have_reciprocal_ratios(pairs_report):
    by = {(p.ingredient, p.substitute, p.context_slot, p.context_method): p.ratio for p in pairs_report.pairs}
    assert by[("nấm hương tươi", "nấm hương khô", None, None)] < 1 < by[("nấm hương khô", "nấm hương tươi", None, None)]
    assert by[("tôm", "tôm khô", "canh", "nau_canh")] < 1 < by[("tôm khô", "tôm", None, None)]


# ---------------------------------------------------------------- validator rules (on a copy)


@pytest.mark.parametrize(
    ("bad", "message"),
    [
        (_pair(substitute="cải chíp"), "not a canonical name"),  # synonym, not the canonical name
        (_pair(ingredient="cải không tồn tại"), "not a canonical name"),
        (_pair(substitute="cải ngọt"), "the same"),
        (_pair(context_method="nau_lau"), "unknown cooking method"),
        (_pair(ingredient="hành lá", substitute="hành tây"), "food groups differ"),
    ],
)
def test_rules_reject(kb_copy: Path, bad: dict, message: str):
    _edit(kb_copy / PAIRS_FILE, lambda d: d["pairs"].append(bad))
    rep = check_pairs(kb_copy)
    assert not rep.ok
    assert any(message in e for e in rep.errors), rep.errors


def test_duplicate_key_rejected(kb_copy: Path):
    _edit(kb_copy / PAIRS_FILE, lambda d: d["pairs"].extend([_pair(context_slot=None, context_method=None)] * 2))
    rep = check_pairs(kb_copy)
    assert any("duplicate pair" in e for e in rep.errors), rep.errors


def test_same_pair_in_other_context_is_not_a_duplicate(kb_copy: Path):
    _edit(kb_copy / PAIRS_FILE, lambda d: d["pairs"].append(_pair(context_slot="man", context_method="xao")))
    assert check_pairs(kb_copy).ok


@pytest.mark.parametrize(
    ("field", "value"),
    [("ratio", 0), ("ratio", -1), ("score", 1.2), ("score", -0.1), ("curated", False), ("source", "")],
)
def test_shape_rejects(field: str, value):
    with pytest.raises(ValueError):
        SubstitutionPair.model_validate(_pair(**{field: value}))


def test_source_must_be_url_or_reasoned_common_knowledge():
    with pytest.raises(ValueError):
        SubstitutionPair.model_validate(_pair(source="mẹ bảo thế"))
    with pytest.raises(ValueError):
        SubstitutionPair.model_validate(_pair(source="kiến thức nấu ăn phổ biến: "))
    SubstitutionPair.model_validate(_pair(source="https://example.org/canh"))


# ---------------------------------------------------------------- evaluation queries


def test_real_queries_are_valid(queries_report):
    assert queries_report.ok, "\n".join(queries_report.errors)


def test_queries_count_split_and_slots(queries_report):
    qs = queries_report.queries
    assert 80 <= len(qs) <= 100
    dev = sum(q.split == "dev" for q in qs) / len(qs)
    assert 0.25 <= dev <= 0.35
    slugs = {p.stem: p.parent.name for p in (KB / "recipes").glob("*/*.yaml")}
    assert {slugs[q.slug] for q in qs} == {"man", "rau", "canh"}


def test_queries_carry_no_answers():
    raw = yaml.safe_load((KB / QUERIES_FILE).read_text(encoding="utf-8"))
    for q in raw["queries"]:
        assert set(q) == {"id", "slug", "missing", "split"}
    assert (KB / "substitution_eval" / "README.md").exists()


def test_table_covers_part_but_not_all_queries(pairs_report, queries_report):
    c = coverage(pairs_report.pairs, queries_report.queries, KB)
    assert 0.3 < c < 1.0  # queries were sampled independently of the table


@pytest.mark.parametrize(
    ("bad", "message"),
    [
        ({"id": "q999", "slug": "khong-co-mon", "missing": "tôm", "split": "dev"}, "no recipe"),
        ({"id": "q999", "slug": "canh-chua-tom", "missing": "thịt bò", "split": "dev"}, "not an ingredient"),
        ({"id": "q999", "slug": "canh-chua-tom", "missing": "nước mắm", "split": "dev"}, "staple"),
        ({"id": "q001", "slug": "canh-chua-tom", "missing": "dứa", "split": "dev"}, "duplicate id"),
    ],
)
def test_query_rules_reject(kb_copy: Path, bad: dict, message: str):
    _edit(kb_copy / QUERIES_FILE, lambda d: d["queries"].append(bad))
    rep = check_queries(kb_copy)
    assert any(message in e for e in rep.errors), rep.errors


def test_query_with_answer_field_rejected(kb_copy: Path):
    _edit(
        kb_copy / QUERIES_FILE,
        lambda d: d["queries"].append(
            {"id": "q998", "slug": "canh-chua-tom", "missing": "dứa", "split": "dev", "answer": ["khế"]}
        ),
    )
    assert not check_queries(kb_copy).ok
