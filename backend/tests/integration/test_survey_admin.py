"""UC24 survey operations from the CLI: TC-SURV-06 (create-form), TC-SURV-07 (audit), TC-SURV-08 (export)."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path

import pytest
from conftest import q
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from tastoria.core.db import make_sessionmaker
from tastoria.modules.admin import service as admin

API = "/api/v1"
DAY = date(2026, 10, 18)


@pytest.fixture
def sm(kb_engine: Engine):
    return make_sessionmaker(kb_engine)


@pytest.fixture
def cli(kb_database_url: str, monkeypatch, capsys):
    from tastoria.cli import main
    from tastoria.core.config import get_settings

    monkeypatch.setenv("TASTORIA_DATABASE_URL", kb_database_url)
    get_settings.cache_clear()

    def run(*argv: str) -> tuple[int, dict | None, str]:
        capsys.readouterr()  # drop request logs of the API calls made in between
        code = main(list(argv))
        out = capsys.readouterr()
        try:
            body = json.loads(out.out)
        except json.JSONDecodeError:
            body = None
        return code, body, out.err

    yield run
    get_settings.cache_clear()


def _start(client: TestClient) -> dict:
    pid = client.get(f"{API}/policies/survey/current").json()["id"]
    r = client.post(f"{API}/survey/respondents", json={"policy_version_id": pid, "consent": True, "channel": "qr"})
    assert r.status_code == 201, r.text
    return r.json()


def _finish(client: TestClient, c: dict, favs: int = 2) -> None:
    h = {"X-Respondent-Token": c["respondent_token"]}
    rid = c["respondent"]["id"]
    items = c["respondent"]["assignments"]
    for i, a in enumerate(items):
        body = {"rating": None, "never_eaten": True} if i % 7 == 0 else {"rating": 1 + i % 5, "never_eaten": False}
        assert (
            client.put(f"{API}/survey/respondents/{rid}/ratings/{a['recipe_id']}", json=body, headers=h).status_code
            == 200
        )
    ids = [a["recipe_id"] for a in items[:favs]]
    assert (
        client.put(f"{API}/survey/respondents/{rid}/favorites", json={"recipe_ids": ids}, headers=h).status_code == 200
    )
    assert client.post(f"{API}/survey/respondents/{rid}/complete", headers=h).status_code == 200


def test_create_form_draws_stratified_published_anchors_and_closes_the_previous(cli, kb_db) -> None:
    code, first, _ = cli("survey", "create-form", "--anchors", "10", "--random", "35", "--seed", "42")
    assert code == 0 and first["ok"] and first["seed"] == 42 and first["closed"] is None
    rows = q(
        kb_db,
        "SELECT r.slot::text AS slot, r.status::text AS status FROM survey_form_anchors a JOIN recipes r ON r.id = a.recipe_id",
    ).all()
    assert len(rows) == 10 and {r.status for r in rows} == {"published"}
    kho = dict(q(kb_db, "SELECT slot::text, count(*) FROM recipes WHERE status = 'published' GROUP BY slot").all())
    per = Counter(r.slot for r in rows)
    for slot, n in kho.items():
        assert abs(per[slot] - 10 * n / sum(kho.values())) < 1, per  # FR-24-02
    assert sum(len(v) for v in first["anchors"].values()) == 10

    code, second, _ = cli("survey", "create-form", "--anchors", "10", "--random", "35", "--seed", "42")
    assert code == 0 and second["closed"] == first["version"]
    forms = q(kb_db, "SELECT version, is_open, n_anchor, n_random FROM survey_forms ORDER BY created_at").all()
    assert [(f.is_open, f.n_anchor, f.n_random) for f in forms] == [(False, 10, 35), (True, 10, 35)]
    same = q(
        kb_db,
        "SELECT f.version, array_agg(a.recipe_id ORDER BY a.recipe_id) FROM survey_form_anchors a "
        "JOIN survey_forms f ON f.id = a.form_id GROUP BY f.version",
    ).all()
    assert same[0][1] == same[1][1]  # same seed + same published catalog = same anchors (reproducible)
    audit = q(
        kb_db, "SELECT actor_role, action, entity_id, purpose FROM audit_log WHERE action LIKE 'survey.%' ORDER BY id"
    ).all()
    assert [(a.actor_role, a.action) for a in audit] == [("ml_operator", "survey.create_form")] * 2
    assert audit[0].entity_id == first["form_id"] and "seed=42" in audit[0].purpose


def test_create_form_refuses_infeasible_or_bad_arguments(cli, kb_db) -> None:
    code, body, err = cli("survey", "create-form", "--anchors", "100", "--random", "100")
    assert code == 1 and body["ok"] is False and "không đủ món published" in err
    assert q(kb_db, "SELECT count(*) FROM survey_forms").scalar() == 0
    assert (
        q(kb_db, "SELECT action, purpose FROM audit_log WHERE action LIKE 'survey.%'")
        .one()
        .purpose.startswith("failed:")
    )
    for bad in ("0", "-3", "x"):
        with pytest.raises(SystemExit) as e:
            cli("survey", "create-form", "--anchors", bad, "--random", "35")
        assert e.value.code == 2


def test_create_form_asks_before_replacing_a_form_with_respondents(cli, kb_client: TestClient, kb_db) -> None:
    assert cli("survey", "create-form", "--anchors", "10", "--random", "35")[0] == 0
    _start(kb_client)
    code, _, err = cli("survey", "create-form", "--anchors", "10", "--random", "35")  # stdin is not a tty in pytest
    assert code == 1 and "--yes" in err
    assert q(kb_db, "SELECT count(*) FROM survey_forms").scalar() == 1
    assert cli("survey", "create-form", "--anchors", "10", "--random", "35", "--yes")[0] == 0
    assert q(kb_db, "SELECT count(*) FROM survey_forms WHERE is_open").scalar() == 1


def test_open_close_and_list(cli, kb_client: TestClient, kb_db) -> None:
    _, f, _ = cli("survey", "create-form", "--anchors", "10", "--random", "35")
    code, closed, _ = cli("survey", "close")
    assert code == 0 and closed["is_open"] is False
    assert cli("survey", "close")[0] == 1  # nothing open
    pid = kb_client.get(f"{API}/policies/survey/current").json()["id"]
    r = kb_client.post(f"{API}/survey/respondents", json={"policy_version_id": pid, "consent": True, "channel": "qr"})
    assert r.json()["code"] == "survey_closed"
    assert cli("survey", "open", f["version"])[1]["is_open"] is True
    assert cli("survey", "open", "19990101-9")[0] == 1
    _start(kb_client)
    code, listed, _ = cli("survey", "list")
    assert code == 0 and listed[0]["respondents_total"] == 1 and listed[0]["is_open"] is True
    actions = [a for (a,) in q(kb_db, "SELECT action FROM audit_log WHERE action LIKE 'survey.%' ORDER BY id").all()]
    assert actions == ["survey.create_form", "survey.close", "survey.close", "survey.open", "survey.open"]


def test_export_has_completed_respondents_only_and_a_verifiable_manifest(
    cli, kb_client: TestClient, kb_db, tmp_path: Path
) -> None:
    _, f, _ = cli("survey", "create-form", "--anchors", "10", "--random", "35")
    done = [_start(kb_client) for _ in range(3)]
    for c in done:
        _finish(kb_client, c)
    abandoned = [_start(kb_client) for _ in range(2)]
    h = {"X-Respondent-Token": abandoned[0]["respondent_token"]}
    first = abandoned[0]["respondent"]["assignments"][0]["recipe_id"]
    kb_client.put(f"{API}/survey/respondents/{abandoned[0]['respondent']['id']}/ratings/{first}",
                  json={"rating": 5, "never_eaten": False}, headers=h)  # fmt: skip

    code, rep, err = cli("survey", "export", f["version"], "--out", str(tmp_path))
    assert code == 0 and rep["respondents"] == 3 and rep["ratings"] == 3 * 45 and rep["is_open"] is True
    assert "vẫn đang mở" in err
    d = Path(rep["directory"])
    assert d.parent == tmp_path and sorted(p.name for p in d.iterdir()) == sorted(
        [
            "respondents.csv",
            "assignments.csv",
            "ratings.csv",
            "favorites.csv",
            "anchors.csv",
            "recipes.csv",
            "manifest.json",
        ]
    )
    manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["form_version"] == f["version"] and manifest["is_open"] is True and manifest["respondents"] == 3
    assert manifest["ratings"] == 135 and manifest["exported_at"]
    for name, meta in manifest["files"].items():
        assert hashlib.sha256((d / name).read_bytes()).hexdigest() == meta["sha256"], name  # FR-24-09

    def read(name: str) -> list[dict[str, str]]:
        with (d / name).open(encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))

    keep = {c["respondent"]["id"] for c in done}
    respondents = read("respondents.csv")
    assert {r["respondent_id"] for r in respondents} == keep  # FR-24-07
    assert {r["policy_version"] for r in respondents} == {"2026-10-17"} and {r["channel"] for r in respondents} == {
        "qr"
    }
    ratings = read("ratings.csv")
    assert {r["respondent_id"] for r in ratings} == keep and len(ratings) == 135
    never = [r for r in ratings if r["never_eaten"] == "true"]
    assert never and all(r["rating"] == "" for r in never)
    assert len(read("assignments.csv")) == 135 and len(read("favorites.csv")) == 6
    assert len(read("anchors.csv")) == 10
    recipes = read("recipes.csv")
    assert {r["status"] for r in recipes} == {"published"} and all(r["name_vi"] for r in recipes)
    headers = set()
    for name in manifest["files"]:
        with (d / name).open(encoding="utf-8") as fh:
            headers |= set(next(csv.reader(fh)))
    assert not headers & {"email", "user_id", "name", "phone", "ip", "user_agent"}  # FR-24-08 (name_vi is the dish)

    code, again, _ = cli("survey", "export", f["version"], "--out", str(tmp_path))
    assert code == 0 and again["directory"] != rep["directory"]  # never overwrites an earlier export
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".partial")]
    assert cli("survey", "export", "19990101-1", "--out", str(tmp_path))[0] == 1
    audit = q(
        kb_db, "SELECT action, entity_id, purpose FROM audit_log WHERE action = 'survey.export' ORDER BY id"
    ).all()
    assert [a.entity_id for a in audit] == [f["version"], f["version"], "19990101-1"]
    assert audit[-1].purpose.startswith("failed:")


def test_export_of_a_form_without_completions_has_headers_only(sm, kb_db, tmp_path: Path) -> None:
    made = admin.create_survey_form(sm, n_anchor=3, n_random=5, seed=None, today=DAY)
    assert made.ok and isinstance(made.report["seed"], int)
    res = admin.export_survey(sm, made.report["version"], tmp_path)
    assert res.ok and res.report["respondents"] == 0
    d = Path(res.report["directory"])
    assert (d / "ratings.csv").read_text(encoding="utf-8") == "respondent_id,recipe_id,rating,never_eaten,answered_at\n"
