"""UC23 taste survey on the imported data/kb catalog (171 published recipes): TC-SURV-01..05, TC-SEC-07."""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from datetime import date

import jwt
import pytest
from conftest import q
from fastapi.testclient import TestClient
from helpers import bearer, register
from sqlalchemy.engine import Engine

from tastoria.core.clock import shift_for_tests
from tastoria.core.db import make_sessionmaker
from tastoria.modules.admin import service as admin

API = "/api/v1"


@pytest.fixture
def sm(kb_engine: Engine):
    return make_sessionmaker(kb_engine)


@pytest.fixture
def form(sm, kb_db) -> dict:
    res = admin.create_survey_form(sm, n_anchor=10, n_random=35, seed=20261018, today=date(2026, 10, 18))
    assert res.ok, res.errors
    return res.report


def _policy_id(client: TestClient) -> str:
    return client.get(f"{API}/policies/survey/current").json()["id"]


def start(client: TestClient, **body) -> dict:
    payload = {"policy_version_id": _policy_id(client), "consent": True, "channel": "link"} | body
    r = client.post(f"{API}/survey/respondents", json=payload)
    assert r.status_code == 201, r.text
    out = r.json()
    assert r.headers["Location"] == f"/api/v1/survey/respondents/{out['respondent']['id']}"
    return out


def tok(created: dict) -> dict[str, str]:
    return {"X-Respondent-Token": created["respondent_token"]}


def rate(client: TestClient, created: dict, recipe_id: str, rating: int | None, never: bool = False, headers=None):
    rid = created["respondent"]["id"]
    return client.put(
        f"{API}/survey/respondents/{rid}/ratings/{recipe_id}",
        json={"rating": rating, "never_eaten": never},
        headers=headers if headers is not None else tok(created),
    )


def count(db, table: str) -> int:
    return q(db, f"SELECT count(*) FROM {table}").scalar()


# ---------------------------------------------------------------- TC-SURV-01 consent and form state


def test_no_open_form_is_survey_closed(kb_client: TestClient, kb_db) -> None:
    body = {"policy_version_id": _policy_id(kb_client), "consent": True, "channel": "qr"}
    r = kb_client.post(f"{API}/survey/respondents", json=body)
    assert (r.status_code, r.json()["code"]) == (409, "survey_closed")


def test_consent_is_required_and_bound_to_the_current_policy(kb_client: TestClient, kb_db, form) -> None:
    old = _policy_id(kb_client)
    r = kb_client.post(
        f"{API}/survey/respondents", json={"policy_version_id": old, "consent": False, "channel": "link"}
    )
    assert (r.status_code, r.json()["code"]) == (422, "consent_required")
    assert count(kb_db, "survey_respondents") == 0 and count(kb_db, "survey_assignments") == 0
    r = kb_client.post(f"{API}/survey/respondents", json={"policy_version_id": old, "channel": "link"})
    assert r.status_code == 422  # consent missing
    created = start(kb_client)
    row = q(kb_db, "SELECT policy_version_id, consented_at, channel FROM survey_respondents").one()
    assert str(row.policy_version_id) == old and row.consented_at is not None and row.channel == "link"
    assert created["respondent"]["form_version"] == form["version"]
    q(
        kb_db,
        "INSERT INTO policy_versions (purpose_code, version, text_sha256, effective_from) "
        "VALUES ('survey', 'test-v2', '\\x00', now() - interval '1 second')",
    )
    r = kb_client.post(f"{API}/survey/respondents", json={"policy_version_id": old, "consent": True, "channel": "link"})
    assert (r.status_code, r.json()["code"]) == (409, "policy_outdated")
    assert count(kb_db, "survey_respondents") == 1


def test_unknown_form_version_and_extra_fields(kb_client: TestClient, kb_db, form) -> None:
    pid = _policy_id(kb_client)
    r = kb_client.post(
        f"{API}/survey/respondents",
        json={"policy_version_id": pid, "consent": True, "channel": "link", "form_version": "19990101-1"},
    )
    assert (r.status_code, r.json()["code"]) == (409, "survey_closed")
    r = kb_client.post(
        f"{API}/survey/respondents",
        json={"policy_version_id": pid, "consent": True, "channel": "link", "email": "a@b.vn"},
    )
    assert r.status_code == 400
    assert start(kb_client, form_version=form["version"])["respondent"]["form_version"] == form["version"]


# ---------------------------------------------------------------- TC-SURV-02 incomplete block design


def test_each_respondent_gets_all_anchors_and_a_stratified_random_block(kb_client: TestClient, kb_db, form) -> None:
    anchors = {str(r[0]) for r in q(kb_db, "SELECT recipe_id FROM survey_form_anchors")}
    assert len(anchors) == 10
    kho = dict(q(kb_db, "SELECT slot::text, count(*) FROM recipes WHERE status = 'published' GROUP BY slot").all())
    total = sum(kho.values())
    published = {str(r[0]) for r in q(kb_db, "SELECT id FROM recipes WHERE status = 'published'")}
    created = start(kb_client)
    items = created["respondent"]["assignments"]
    assert len(items) == 45
    assert [a["display_order"] for a in items] == list(range(1, 46))
    assert {a["recipe_id"] for a in items if a["is_anchor"]} == anchors
    rnd = [a for a in items if not a["is_anchor"]]
    assert len(rnd) == 35 and len({a["recipe_id"] for a in rnd}) == 35
    assert {a["recipe_id"] for a in rnd} <= published - anchors
    per_slot = Counter(a["slot"] for a in rnd)
    for slot, n in kho.items():
        assert abs(per_slot[slot] - 35 * n / total) < 1, (slot, per_slot)
    assert all(a["rating"] is None and a["never_eaten"] is None for a in items)
    assert created["respondent"]["completed_at"] is None and created["respondent"]["favorite_recipe_ids"] == []


def test_assignment_balance_and_shuffled_order_over_many_respondents(kb_client: TestClient, kb_db, form) -> None:
    positions: dict[str, set[int]] = defaultdict(set)
    for _ in range(30):
        for a in start(kb_client)["respondent"]["assignments"]:
            if a["is_anchor"]:
                positions[a["recipe_id"]].add(a["display_order"])
    # FR-23-07: no anchor sits at a fixed place (30 shuffles of 45 positions)
    assert len(positions) == 10 and all(len(p) >= 10 for p in positions.values())
    shown = q(
        kb_db,
        "SELECT r.slot::text AS slot, r.id, count(a.recipe_id) AS n FROM recipes r "
        "LEFT JOIN survey_assignments a ON a.recipe_id = r.id AND NOT a.is_anchor "
        "WHERE r.status = 'published' AND r.id NOT IN (SELECT recipe_id FROM survey_form_anchors) GROUP BY r.slot, r.id",
    ).all()
    by_slot: dict[str, list[int]] = defaultdict(list)
    for row in shown:
        by_slot[row.slot].append(row.n)
    for slot, ns in by_slot.items():
        assert max(ns) - min(ns) <= 1, (slot, Counter(ns))  # every recipe of a slot rated about as often


# ---------------------------------------------------------------- TC-SURV-03 ratings


def test_ratings_validation_idempotence_and_overwrite(kb_client: TestClient, kb_db, form) -> None:
    c = start(kb_client)
    rid = c["respondent"]["id"]
    target = c["respondent"]["assignments"][0]["recipe_id"]
    for bad in ({"rating": 0, "never_eaten": False}, {"rating": 6, "never_eaten": False},
                {"rating": 3, "never_eaten": True}, {"rating": None, "never_eaten": False}):  # fmt: skip
        r = kb_client.put(f"{API}/survey/respondents/{rid}/ratings/{target}", json=bad, headers=tok(c))
        assert (r.status_code, r.json()["code"]) == (422, "invalid_rating"), bad
    assert count(kb_db, "survey_ratings") == 0
    first = rate(kb_client, c, target, 3).json()
    for _ in range(2):
        again = rate(kb_client, c, target, 3)
        assert again.status_code == 200 and again.json() == first  # answered_at unchanged too
    assert rate(kb_client, c, target, 4).json()["rating"] == 4
    rows = q(kb_db, "SELECT rating, never_eaten FROM survey_ratings").all()
    assert [(r.rating, r.never_eaten) for r in rows] == [(4, False)]
    never = rate(kb_client, c, target, None, True).json()
    assert never["rating"] is None and never["never_eaten"] is True
    assert q(kb_db, "SELECT rating FROM survey_ratings").scalar() is None
    got = kb_client.get(f"{API}/survey/respondents/{rid}", headers=tok(c)).json()
    assert got["assignments"][0]["never_eaten"] is True and got["assignments"][1]["never_eaten"] is None


def test_rating_a_recipe_not_assigned_is_404(kb_client: TestClient, kb_db, form) -> None:
    c = start(kb_client)
    mine = {a["recipe_id"] for a in c["respondent"]["assignments"]}
    other = next(
        str(r[0]) for r in q(kb_db, "SELECT id FROM recipes WHERE status = 'published'") if str(r[0]) not in mine
    )
    assert rate(kb_client, c, other, 3).status_code == 404
    assert rate(kb_client, c, str(uuid.uuid4()), 3).status_code == 404
    assert count(kb_db, "survey_ratings") == 0


# ---------------------------------------------------------------- TC-SEC-07 respondent token


def test_token_opens_only_its_own_respondent(kb_client: TestClient, kb_db, form, kb_app) -> None:
    r1, r2 = start(kb_client), start(kb_client)
    id2 = r2["respondent"]["id"]
    target = r2["respondent"]["assignments"][0]["recipe_id"]
    for call in (
        lambda h: kb_client.get(f"{API}/survey/respondents/{id2}", headers=h),
        lambda h: kb_client.put(
            f"{API}/survey/respondents/{id2}/ratings/{target}", json={"rating": 5, "never_eaten": False}, headers=h
        ),
        lambda h: kb_client.put(f"{API}/survey/respondents/{id2}/favorites", json={"recipe_ids": []}, headers=h),
        lambda h: kb_client.post(f"{API}/survey/respondents/{id2}/complete", headers=h),
    ):
        for h in ({}, tok(r1), {"X-Respondent-Token": "x.y.z"}):
            r = call(h)
            assert (r.status_code, r.json()["code"]) == (401, "respondent_token_invalid")
    assert count(kb_db, "survey_ratings") == 0 and count(kb_db, "survey_favorites") == 0
    assert kb_client.get(f"{API}/survey/respondents/{id2}", headers=tok(r2)).status_code == 200

    settings = kb_app.state.settings
    forged = jwt.encode({"sub": id2, "aud": "tastoria-survey", "iss": settings.jwt_issuer, "exp": 4102444800},
                        "another-secret-key-0123456789-abcdefghij", algorithm="HS256", headers={"kid": settings.jwt_active_kid})  # fmt: skip
    assert kb_client.get(f"{API}/survey/respondents/{id2}", headers={"X-Respondent-Token": forged}).status_code == 401
    # a user's access token is not a respondent token, and a respondent token is not a session
    s = register(kb_client)
    assert (
        kb_client.get(f"{API}/survey/respondents/{id2}", headers={"X-Respondent-Token": s["access_token"]}).status_code
        == 401
    )
    assert (
        kb_client.get(f"{API}/me/consents", headers={"Authorization": f"Bearer {r2['respondent_token']}"}).status_code
        == 401
    )


def test_expired_token_is_rejected(kb_client: TestClient, kb_db, form) -> None:
    shift_for_tests(-31 * 86400)
    try:
        c = start(kb_client)
    finally:
        shift_for_tests(0)
    r = kb_client.get(f"{API}/survey/respondents/{c['respondent']['id']}", headers=tok(c))
    assert (r.status_code, r.json()["code"]) == (401, "respondent_token_invalid")


# ---------------------------------------------------------------- TC-SURV-04 favourites and completion


def test_favorites_rules(kb_client: TestClient, kb_db, form) -> None:
    c = start(kb_client)
    rid = c["respondent"]["id"]
    pub = [str(r[0]) for r in q(kb_db, "SELECT id FROM recipes WHERE status = 'published' ORDER BY id LIMIT 6")]
    draft = q(kb_db, "SELECT id FROM recipes WHERE status <> 'published' LIMIT 1").scalar()
    url = f"{API}/survey/respondents/{rid}/favorites"
    ok = kb_client.put(url, json={"recipe_ids": pub[:5]}, headers=tok(c))
    assert ok.status_code == 200 and ok.json() == {"recipe_ids": pub[:5]}
    for bad in (pub, [pub[0], pub[0]], [pub[0], str(draft)], [str(uuid.uuid4())]):
        r = kb_client.put(url, json={"recipe_ids": bad}, headers=tok(c))
        assert (r.status_code, r.json()["code"]) == (422, "invalid_favorites"), bad
    assert count(kb_db, "survey_favorites") == 5  # the old list stays
    assert kb_client.put(url, json={"recipe_ids": []}, headers=tok(c)).status_code == 200
    assert count(kb_db, "survey_favorites") == 0


def test_complete_needs_every_answer_and_is_idempotent(kb_client: TestClient, kb_db, form) -> None:
    c = start(kb_client)
    rid = c["respondent"]["id"]
    items = c["respondent"]["assignments"]
    for a in items[:-2]:
        assert rate(kb_client, c, a["recipe_id"], 4 if a["is_anchor"] else None, not a["is_anchor"]).status_code == 200
    r = kb_client.post(f"{API}/survey/respondents/{rid}/complete", headers=tok(c))
    assert (r.status_code, r.json()["code"]) == (422, "survey_incomplete")
    assert r.json()["missing_recipe_ids"] == [a["recipe_id"] for a in items[-2:]]
    assert q(kb_db, "SELECT completed_at FROM survey_respondents").scalar() is None
    for a in items[-2:]:
        rate(kb_client, c, a["recipe_id"], 2)
    done = kb_client.post(f"{API}/survey/respondents/{rid}/complete", headers=tok(c))
    assert done.status_code == 200 and done.json()["completed_at"] is not None
    again = kb_client.post(f"{API}/survey/respondents/{rid}/complete", headers=tok(c))
    assert again.status_code == 200 and again.json()["completed_at"] == done.json()["completed_at"]
    r = rate(kb_client, c, items[0]["recipe_id"], 5)
    assert (r.status_code, r.json()["code"]) == (409, "survey_already_completed")
    r = kb_client.put(f"{API}/survey/respondents/{rid}/favorites", json={"recipe_ids": []}, headers=tok(c))
    assert (r.status_code, r.json()["code"]) == (409, "survey_already_completed")


def test_closing_the_form_stops_writes_but_keeps_answers(kb_client: TestClient, kb_db, form, sm) -> None:
    c = start(kb_client)
    rid = c["respondent"]["id"]
    first = c["respondent"]["assignments"][0]["recipe_id"]
    rate(kb_client, c, first, 5)
    assert admin.set_survey_open(sm, None, False).ok
    r = rate(kb_client, c, c["respondent"]["assignments"][1]["recipe_id"], 3)
    assert (r.status_code, r.json()["code"]) == (409, "survey_closed")
    r = kb_client.post(f"{API}/survey/respondents/{rid}/complete", headers=tok(c))
    assert (r.status_code, r.json()["code"]) == (409, "survey_closed")
    got = kb_client.get(f"{API}/survey/respondents/{rid}", headers=tok(c))
    assert got.status_code == 200 and got.json()["assignments"][0]["rating"] == 5
    body = {"policy_version_id": _policy_id(kb_client), "consent": True, "channel": "link"}
    assert kb_client.post(f"{API}/survey/respondents", json=body).json()["code"] == "survey_closed"
    assert admin.set_survey_open(sm, form["version"], True).ok
    assert rate(kb_client, c, c["respondent"]["assignments"][1]["recipe_id"], 3).status_code == 200


# ---------------------------------------------------------------- TC-SURV-05 no identifying data


def test_survey_tables_hold_no_identifying_columns(kb_client: TestClient, kb_db, form) -> None:
    c = start(kb_client)
    for a in c["respondent"]["assignments"]:
        rate(kb_client, c, a["recipe_id"], 3)
    kb_client.post(f"{API}/survey/respondents/{c['respondent']['id']}/complete", headers=tok(c) | {"User-Agent": "UA-test/1.0", "X-Forwarded-For": "203.0.113.9"})  # fmt: skip
    cols = q(
        kb_db,
        "SELECT table_name, column_name FROM information_schema.columns WHERE table_name LIKE 'survey\\_%'",
    ).all()
    # FR-23-13: the whole column list, so a new identifying column cannot slip in unnoticed
    assert {f"{t}.{c}" for t, c in cols} == {
        "survey_forms.id", "survey_forms.version", "survey_forms.n_anchor", "survey_forms.n_random",
        "survey_forms.is_open", "survey_forms.created_at",
        "survey_form_anchors.form_id", "survey_form_anchors.recipe_id",
        "survey_respondents.id", "survey_respondents.form_id", "survey_respondents.policy_version_id",
        "survey_respondents.consented_at", "survey_respondents.completed_at", "survey_respondents.channel",
        "survey_assignments.respondent_id", "survey_assignments.recipe_id", "survey_assignments.display_order",
        "survey_assignments.is_anchor",
        "survey_ratings.respondent_id", "survey_ratings.recipe_id", "survey_ratings.rating",
        "survey_ratings.never_eaten", "survey_ratings.answered_at",
        "survey_favorites.respondent_id", "survey_favorites.recipe_id",
    }  # fmt: skip
    dump = " ".join(str(r) for t in ("survey_respondents", "survey_assignments", "survey_ratings", "survey_favorites")
                    for r in q(kb_db, f"SELECT * FROM {t}").all())  # fmt: skip
    assert "UA-test" not in dump and "203.0.113.9" not in dump


# ---------------------------------------------------------------- TC-SURV-09 / TC-SEC-05 admin listing


def test_admin_surveys_lists_counts_for_ml_operator_only(kb_client: TestClient, kb_db, sm) -> None:
    f1 = admin.create_survey_form(sm, n_anchor=10, n_random=35, seed=1, today=date(2026, 10, 18)).report
    for _ in range(3):
        start(kb_client)
    f2 = admin.create_survey_form(sm, n_anchor=5, n_random=20, seed=2, today=date(2026, 10, 18)).report
    c = start(kb_client)
    for a in c["respondent"]["assignments"]:
        rate(kb_client, c, a["recipe_id"], 1)
    kb_client.post(f"{API}/survey/respondents/{c['respondent']['id']}/complete", headers=tok(c))
    assert (f1["version"], f2["version"]) == ("20261018-1", "20261018-2")

    u = register(kb_client)
    audits = count(kb_db, "audit_log")
    assert kb_client.get(f"{API}/admin/surveys", headers=bearer(u)).status_code == 403
    assert kb_client.get(f"{API}/admin/surveys").status_code == 401
    assert count(kb_db, "audit_log") == audits
    for role in ("curator", "admin"):
        q(kb_db, "UPDATE users SET role = :r WHERE id = :i", r=role, i=u["user"]["id"])
        s = kb_client.post(f"{API}/auth/login", json={"email": u["user"]["email"], "password": u["password"]}).json()
        assert kb_client.get(f"{API}/admin/surveys", headers=bearer(s)).status_code == 403, role
    q(kb_db, "UPDATE users SET role = 'ml_operator' WHERE id = :i", i=u["user"]["id"])
    s = kb_client.post(f"{API}/auth/login", json={"email": u["user"]["email"], "password": u["password"]}).json()
    r = kb_client.get(f"{API}/admin/surveys", headers=bearer(s))
    assert r.status_code == 200
    rows = {x["version"]: x for x in r.json()["items"]}
    assert (rows[f1["version"]]["respondents_total"], rows[f1["version"]]["respondents_completed"]) == (3, 0)
    assert (rows[f2["version"]]["respondents_total"], rows[f2["version"]]["respondents_completed"]) == (1, 1)
    assert [rows[v]["is_open"] for v in (f1["version"], f2["version"])] == [False, True]
    page = kb_client.get(f"{API}/admin/surveys", params={"limit": 1}, headers=bearer(s)).json()
    assert len(page["items"]) == 1 and page["next_cursor"]
    nxt = kb_client.get(f"{API}/admin/surveys", params={"limit": 1, "cursor": page["next_cursor"]}, headers=bearer(s))
    assert nxt.json()["items"][0]["version"] == f2["version"] and nxt.json()["next_cursor"] is None
    assert q(kb_db, "SELECT count(*) FROM audit_log WHERE action = 'survey.list'").scalar() == 3
