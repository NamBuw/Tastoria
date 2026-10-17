"""`tastoria catalog substitutes import data/kb/substitution_pairs.yaml`: validation against the catalog, idempotent
sync of the curated rows, audit, and the curated table answering GET /meal-plans/{id}/items/{itemId}/substitutes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from conftest import KB_DIR
from fastapi.testclient import TestClient
from kb_helpers import API, ingredient_id, plan, q, stock_for, user

from tastoria.core.db import make_engine, make_sessionmaker
from tastoria.modules.admin.service import import_substitutes

PAIRS = KB_DIR / "substitution_pairs.yaml"
N_PAIRS = len(yaml.safe_load(PAIRS.read_text(encoding="utf-8"))["pairs"])
MAN, RAU, CANH = "Ba chỉ chiên nước mắm", "Bí ngòi xào tỏi", "Canh rau ngót thịt băm"


def _run(url: str, path: Path = PAIRS):
    engine = make_engine(url, pool_size=1)
    try:
        return import_substitutes(make_sessionmaker(engine), path)
    finally:
        engine.dispose()


def _write(tmp_path: Path, fn) -> Path:
    data = yaml.safe_load(PAIRS.read_text(encoding="utf-8"))
    fn(data["pairs"])
    out = tmp_path / "substitution_pairs.yaml"
    out.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return out


def _count(db, where: str = "true") -> int:
    return q(db, f"SELECT count(*) FROM substitution_pairs WHERE {where}").scalar()


# ---------------------------------------------------------------- import


def test_import_is_idempotent_and_audited(kb_database_url: str, kb_db) -> None:
    res = _run(kb_database_url)
    assert res.ok, res.errors
    assert res.report["pairs"] == N_PAIRS and res.report["inserted"] == N_PAIRS and res.report["changes"] == N_PAIRS
    assert _count(kb_db) == N_PAIRS == _count(kb_db, "curated")
    again = _run(kb_database_url)
    assert again.ok and again.report["changes"] == 0 and again.report["unchanged"] == N_PAIRS
    assert _count(kb_db) == N_PAIRS
    audit = q(kb_db, "SELECT actor_role, entity, purpose FROM audit_log WHERE action = 'catalog.substitutes.import' "
                     "ORDER BY created_at").all()  # fmt: skip
    assert [tuple(a) for a in audit] == [
        ("curator", "substitution_pairs", f"ok: {N_PAIRS} changes"),
        ("curator", "substitution_pairs", "ok: 0 changes"),
    ]
    row = q(kb_db, "SELECT p.ratio, p.score, p.context_slot, p.context_method_code FROM substitution_pairs p "
                   "JOIN ingredients a ON a.id = p.ingredient_id JOIN ingredients b ON b.id = p.substitute_id "
                   "WHERE a.name_vi = 'nấm hương khô' AND b.name_vi = 'nấm hương tươi'").one()  # fmt: skip
    assert float(row.ratio) == 5 and row.score == pytest.approx(0.75) and row.context_slot is None


def test_changed_and_dropped_rows_are_synced_model_rows_kept(kb_database_url: str, kb_db, tmp_path: Path) -> None:
    assert _run(kb_database_url).ok
    q(kb_db, "INSERT INTO substitution_pairs (ingredient_id, substitute_id, ratio, score, source, curated) "
             "VALUES (:a, :b, 1, 0.3, 'word2vec', false)",
      a=ingredient_id(kb_db, "rau muống"), b=ingredient_id(kb_db, "cải ngọt"))  # fmt: skip

    def edit(pairs: list[dict]) -> None:
        pairs[0]["score"] = 0.5
        del pairs[1]

    res = _run(kb_database_url, _write(tmp_path, edit))
    assert res.ok, res.errors
    assert (res.report["updated"], res.report["removed"], res.report["inserted"]) == (1, 1, 0)
    assert _count(kb_db, "curated") == N_PAIRS - 1
    assert _count(kb_db, "NOT curated") == 1  # not the importer's to delete


@pytest.mark.parametrize(
    ("edit", "code"),
    [
        (lambda p: p.append(p[0] | {"substitute": "cải chíp"}), "unknown_ingredient"),  # a synonym, not canonical
        (lambda p: p.append(p[0] | {"substitute": p[0]["ingredient"], "context_slot": None}), "self_pair"),
        (lambda p: p.append(p[0] | {"substitute": "tôm"}), "food_group"),
        (lambda p: p.append(dict(p[0])), "duplicate"),
        (lambda p: p.append(p[0] | {"ratio": 0, "context_slot": None}), "range"),
        (lambda p: p.append(p[0] | {"context_method": "nau_lau", "context_slot": None}), "unknown_ref"),
    ],
)
def test_bad_file_writes_nothing(kb_database_url: str, kb_db, tmp_path: Path, edit, code: str) -> None:
    path = _write(tmp_path, edit)
    res = _run(kb_database_url, path)
    assert not res.ok
    assert any(e.startswith("substitution_pairs.yaml:") and f": {code}: " in e for e in res.errors), res.errors
    line = int(res.errors[0].split(":")[1])
    assert path.read_text(encoding="utf-8").splitlines()[line - 1].lstrip().startswith("- ingredient:")
    assert _count(kb_db) == 0
    assert q(kb_db, "SELECT purpose FROM audit_log WHERE action = 'catalog.substitutes.import'").scalar() == (
        "failed: validation"
    )


def test_cli_prints_a_json_report_and_exit_code(kb_database_url: str, kb_db, monkeypatch, capsys, tmp_path) -> None:
    from tastoria.cli import main
    from tastoria.core.config import get_settings

    monkeypatch.setenv("TASTORIA_DATABASE_URL", kb_database_url)
    get_settings.cache_clear()
    try:
        assert main(["catalog", "substitutes", "import", str(PAIRS)]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["ok"] is True and out["pairs"] == N_PAIRS and len(out["sha256"]) == 64
        assert main(["catalog", "substitutes", "import", str(PAIRS)]) == 0
        assert json.loads(capsys.readouterr().out)["changes"] == 0
        bad = _write(tmp_path, lambda p: p.append(p[0] | {"substitute": "không có"}))
        assert main(["catalog", "substitutes", "import", str(bad)]) == 1
        captured = capsys.readouterr()
        assert "unknown_ingredient" in captured.err and json.loads(captured.out)["ok"] is False
    finally:
        get_settings.cache_clear()


# ---------------------------------------------------------------- the table answers "Thiếu gì?" (UC17)


def test_missing_ingredient_gets_suggestions_from_the_curated_table(
    kb_client: TestClient, kb_database_url: str, kb_db
) -> None:
    h = user(kb_client)
    stock_for(kb_client, h, kb_db, MAN, RAU, CANH)
    p = plan(kb_client, h)
    canh = next(i for i in p["items"] if i["slot"] == "canh" and i["status"] == "active")
    assert canh["recipe_id"] == str(q(kb_db, "SELECT id FROM recipes WHERE name_vi = :n", n=CANH).scalar())
    url = f"{API}/meal-plans/{p['id']}/items/{canh['id']}/substitutes"
    params = {"ingredient_id": ingredient_id(kb_db, "rau ngót")}
    before = kb_client.get(url, params=params, headers=h)
    assert before.status_code == 200 and before.json()["items"][0]["candidates"] == []  # empty table: nothing

    assert _run(kb_database_url).ok
    # rau ngót runs out: the item lists it as missing, with the curated canh/nau_canh pairs
    lot = q(kb_db, "SELECT l.id FROM pantry_lots l JOIN ingredients i ON i.id = l.ingredient_id "
                   "WHERE i.name_vi = 'rau ngót'").scalar()  # fmt: skip
    assert kb_client.patch(f"{API}/pantry/lots/{lot}", json={"status": "used_up"}, headers=h).status_code == 200
    r = kb_client.get(url, headers=h)
    assert r.status_code == 200, r.text
    miss = next(m for m in r.json()["items"] if m["name_vi"] == "rau ngót")
    assert miss["available_g_min"] == 0 and miss["need_g"] > 0
    names = [c["name_vi"] for c in miss["candidates"]]
    assert set(names[:2]) == {"mồng tơi", "rau dền"} and names[2] == "rau đay"  # score 0.7, 0.7, then 0.6
    assert all(c["origin"] == "lookup" for c in miss["candidates"])

    # meat of the canh: thịt băm -> thịt nạc vai (any context) and thịt bò xay (canh/nau_canh) both apply
    meat = kb_client.get(url, params={"ingredient_id": ingredient_id(kb_db, "thịt băm")}, headers=h).json()
    assert [c["name_vi"] for c in meat["items"][0]["candidates"]] == ["thịt bò xay", "thịt nạc vai"]  # exact ctx first


def test_runtime_filter_drops_substitutes_with_a_coeater_allergen(
    kb_client: TestClient, kb_database_url: str, kb_db
) -> None:
    """thịt bò xay / thịt nạc vai carry no allergen; a fish co-eater does not change them — but the curated tôm ->
    mực pair (adds molluscs) is dropped for a co-eater allergic to molluscs."""
    assert _run(kb_database_url).ok
    h = user(kb_client)
    stock_for(kb_client, h, kb_db, "Ba chỉ chiên nước mắm", "Su su xào tôm", "Canh rau ngót thịt băm")
    p = plan(kb_client, h, coeater_allergen_codes=["nhuyen_the"])
    rau = next(i for i in p["items"] if i["slot"] == "rau" and i["status"] == "active")
    rid = q(kb_db, "SELECT id FROM recipes WHERE name_vi = 'Su su xào tôm'").scalar()
    assert rau["recipe_id"] == str(rid), p  # the stocked favourites lead their slot
    r = kb_client.get(f"{API}/meal-plans/{p['id']}/items/{rau['id']}/substitutes",
                      params={"ingredient_id": ingredient_id(kb_db, "tôm")}, headers=h)  # fmt: skip
    names = [c["name_vi"] for c in r.json()["items"][0]["candidates"]]
    assert "tép" in names and "mực" not in names
