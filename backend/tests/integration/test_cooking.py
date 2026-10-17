"""UC19–UC21: cook sessions with the CP-SAT schedule, "nấu xong" in one transaction, undo within 10 minutes, abandon;
property tests: every schedule of the catalog is valid, and completing twice deducts once."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from kb_helpers import API, accept, add_lot, cook, grant, key, plan, q, stock_for, user
from sqlalchemy.orm import Session

from tastoria.core import clock
from tastoria.modules.catalog import service as catalog
from tastoria.modules.meal import schedule as sch
from tastoria.modules.meal.service import _sched_dish

MAN, RAU, CANH = "Ba chỉ chiên nước mắm", "Bí ngòi xào tỏi", "Canh rau ngót thịt băm"


@pytest.fixture(autouse=True)
def _reset_clock():
    yield
    clock.shift_for_tests(0)


@pytest.fixture
def h(kb_client: TestClient) -> dict:
    return user(kb_client, "personalization")


def _accepted(client: TestClient, h: dict, db, *recipes: str) -> dict:
    stock_for(client, h, db, *(recipes or (MAN, RAU, CANH)))
    p = plan(client, h)
    return accept(client, h, p["id"])


def _check_schedule(db, sess: dict) -> None:
    """BR-COOK-01 on what the API returned (FR-19-05 … FR-19-09)."""
    rows = sess["schedule"]
    active = [(e["start_offset_s"], e["end_offset_s"]) for e in rows if e["kind"] == "active"]
    for i, a in enumerate(active):
        for b in active[i + 1 :]:
            assert a[1] <= b[0] or b[1] <= a[0], "two active steps overlap"
    events = sorted({e["start_offset_s"] for e in rows})
    for t in events:
        assert (
            sum(1 for e in rows if e["uses_burner"] and e["start_offset_s"] <= t < e["end_offset_s"]) <= sess["burners"]
        )
    by_recipe: dict[str, list[dict]] = {}
    for e in rows:
        by_recipe.setdefault(e["recipe_id"], []).append(e)
    serve = int((datetime.fromisoformat(sess["serve_at"]) - datetime.fromisoformat(sess["started_at"])).total_seconds())
    for steps in by_recipe.values():
        steps.sort(key=lambda e: e["step_no"])
        for a, b in zip(steps, steps[1:], strict=False):
            assert a["end_offset_s"] <= b["start_offset_s"]
        assert serve - 300 - 1 <= steps[-1]["end_offset_s"] <= serve + 1  # within 5 min before serving


# ---------------------------------------------------------------- UC19


def test_start_cooking_builds_a_valid_schedule(kb_client: TestClient, kb_db, h: dict) -> None:
    p = _accepted(kb_client, h, kb_db)
    s = cook(kb_client, h, p["id"])
    assert s["status"] == "in_progress" and s["burners"] == 2 and s["undo_deadline"] is None
    assert len({e["recipe_id"] for e in s["schedule"]}) == 3
    _check_schedule(kb_db, s)
    xao = next(i["recipe_id"] for i in p["items"] if i["slot"] == "rau")  # Bí ngòi xào tỏi, method xao
    end = {
        r: max(e["end_offset_s"] for e in s["schedule"] if e["recipe_id"] == r)
        for r in {e["recipe_id"] for e in s["schedule"]}
    }
    assert end[xao] == max(end.values())  # FR-19-09: the stir-fry is last
    assert kb_client.get(f"{API}/cook-sessions/{s['id']}", headers=h).json() == s


def test_start_rules_and_idempotency(kb_client: TestClient, kb_db, h: dict) -> None:
    stock_for(kb_client, h, kb_db, MAN, RAU, CANH)
    p = plan(kb_client, h)
    body = {"meal_plan_id": p["id"], "serve_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat()}
    r = kb_client.post(f"{API}/cook-sessions", json=body, headers=h | key())
    assert (r.status_code, r.json()["code"]) == (409, "meal_plan_not_accepted")  # FR-19-01
    accept(kb_client, h, p["id"])
    k = key()
    first = kb_client.post(f"{API}/cook-sessions", json=body, headers=h | k)
    again = kb_client.post(f"{API}/cook-sessions", json=body, headers=h | k)
    assert first.status_code == again.status_code == 201 and first.json()["id"] == again.json()["id"]  # FR-19-03
    r = kb_client.post(f"{API}/cook-sessions", json=body, headers=h | key())
    assert (r.status_code, r.json()["code"]) == (409, "cook_session_in_progress")  # FR-19-02
    assert r.json()["cook_session_id"] == first.json()["id"]
    r = kb_client.post(f"{API}/cook-sessions", json=body | {"serve_at": datetime.now(UTC).isoformat()}, headers=h | k)
    assert (r.status_code, r.json()["code"]) == (422, "idempotency_key_reused")  # FR-19-04
    other = user(kb_client)
    assert kb_client.post(f"{API}/cook-sessions", json=body, headers=other | key()).status_code == 404
    assert kb_client.get(f"{API}/cook-sessions/{first.json()['id']}", headers=other).status_code == 404
    for action in ("complete", "undo", "abandon"):
        extra = key() if action == "complete" else {}
        assert (
            kb_client.post(f"{API}/cook-sessions/{first.json()['id']}/{action}", headers=other | extra).status_code
            == 404
        )


def test_serve_time_too_early_is_moved_to_the_earliest(kb_client: TestClient, kb_db, h: dict) -> None:
    p = _accepted(kb_client, h, kb_db)
    s = cook(kb_client, h, p["id"], serve_at=datetime.now(UTC).isoformat())
    lead = (datetime.fromisoformat(s["serve_at"]) - datetime.fromisoformat(s["started_at"])).total_seconds()
    assert abs(lead - s["makespan_s"]) < 2 and min(e["start_offset_s"] for e in s["schedule"]) == 0  # UC19 1a


def test_longer_than_max_minutes_needs_a_confirmation(kb_client: TestClient, kb_db, h: dict) -> None:
    p = _accepted(kb_client, h, kb_db)
    assert kb_client.put(f"{API}/me/settings", json={"burners": 1}, headers=h).status_code == 200
    plan_row = q(kb_db, "SELECT max_minutes FROM meal_plans WHERE id = :p", p=p["id"]).scalar()
    q(kb_db, "UPDATE meal_plans SET max_minutes = 10 WHERE id = :p", p=p["id"])  # the user picked 10 minutes
    body = {"meal_plan_id": p["id"], "serve_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat()}
    r = kb_client.post(f"{API}/cook-sessions", json=body, headers=h | key())
    assert (r.status_code, r.json()["code"]) == (409, "conflict_state") and r.json()["over_time_minutes"] > 0
    assert q(kb_db, "SELECT count(*) FROM cook_sessions").scalar() == 0
    r = kb_client.post(f"{API}/cook-sessions", json=body | {"confirm_over_time": True}, headers=h | key())
    assert r.status_code == 201 and r.json()["burners"] == 1  # FR-19-06: burners snapshot of the settings
    _check_schedule(kb_db, r.json())
    assert plan_row >= 10


def test_make_ahead_steps_are_not_scheduled(kb_client: TestClient, kb_db, h: dict) -> None:
    stock_for(kb_client, h, kb_db, MAN, "Canh măng nấu chân giò")
    add_lot(kb_client, h, kb_db, "dưa cải chua", 500)
    p = plan(kb_client, h, max_minutes=180)
    names = {i["recipe_name_vi"]: i["recipe_id"] for i in p["items"]}
    assert {"Dưa cải muối", "Canh măng nấu chân giò"} <= set(names)
    accept(kb_client, h, p["id"])
    s = cook(kb_client, h, p["id"])
    steps = {(e["recipe_id"], e["step_no"]) for e in s["schedule"]}
    assert not any(r == names["Dưa cải muối"] for r, _ in steps)  # the whole pickle is made ahead
    mang = sorted(n for r, n in steps if r == names["Canh măng nấu chân giò"])
    assert mang == list(range(3, 10))  # steps 1–2 (ngâm măng 8 giờ) are done the day before
    _check_schedule(kb_db, s)


def test_abandon(kb_client: TestClient, kb_db, h: dict) -> None:
    p = _accepted(kb_client, h, kb_db)
    s = cook(kb_client, h, p["id"])
    for _ in range(2):  # FR-19-12
        r = kb_client.post(f"{API}/cook-sessions/{s['id']}/abandon", headers=h)
        assert r.status_code == 200 and r.json()["status"] == "abandoned"
    assert kb_client.get(f"{API}/meal-plans/{p['id']}", headers=h).json()["status"] == "accepted"
    assert q(kb_db, "SELECT count(*) FROM pantry_transactions").scalar() == 0
    s2 = cook(kb_client, h, p["id"])  # the plan can be cooked again
    r = kb_client.post(f"{API}/cook-sessions/{s2['id']}/complete", headers=h | key())
    assert r.status_code == 200
    r = kb_client.post(f"{API}/cook-sessions/{s2['id']}/abandon", headers=h)
    assert (r.status_code, r.json()["code"]) == (409, "cook_session_not_in_progress")


# ---------------------------------------------------------------- UC20, UC21


def test_complete_deducts_records_and_closes_the_plan(kb_client: TestClient, kb_db, h: dict) -> None:
    p = _accepted(kb_client, h, kb_db)
    s = cook(kb_client, h, p["id"])
    rau = next(i for i in p["items"] if i["slot"] == "rau")
    canh = next(i for i in p["items"] if i["slot"] == "canh")
    fb = [{"meal_plan_item_id": rau["id"], "liked": True}, {"meal_plan_item_id": canh["id"], "liked": False}]
    k = key()
    r = kb_client.post(f"{API}/cook-sessions/{s['id']}/complete", json={"feedback": fb}, headers=h | k)
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["cook_session"]["status"] == "completed" and done["cook_session"]["undo_deadline"]
    assert done["interactions_recorded"] is True and done["deductions"]
    assert all(d["delta_g_min"] <= 0 and d["delta_g_max"] <= 0 for d in done["deductions"])  # FR-20-09
    tracked = set(q(kb_db, "SELECT id::text FROM ingredients WHERE shelf_life_days IS NOT NULL").scalars())
    # u is known only with a shelf life (FR-14-05): "chưa rõ hạn" lots record NULL rather than an invented number
    assert all((d["urgency_at_event"] is not None) == (d["ingredient_id"] in tracked) for d in done["deductions"])
    assert kb_client.get(f"{API}/meal-plans/{p['id']}", headers=h).json()["status"] == "cooked"  # FR-20-01
    types = sorted(r.type for r in q(kb_db, "SELECT type FROM interactions WHERE meal_plan_id = :p AND type <> 'served'",
                                     p=p["id"]))  # fmt: skip
    assert types == ["cooked", "cooked", "cooked", "disliked", "liked"]  # FR-20-11, FR-20-12
    # 2 persons, 4-serving recipe: 500 g pork belly × 2/4 = 250 g
    pork = q(kb_db, "SELECT sum(t.delta_g_min) FROM pantry_transactions t JOIN pantry_lots l ON l.id = t.lot_id "
                    "JOIN ingredients i ON i.id = l.ingredient_id WHERE i.name_vi = 'thịt ba chỉ'").scalar()  # fmt: skip
    assert float(pork) == -250  # FR-20-05
    again = kb_client.post(f"{API}/cook-sessions/{s['id']}/complete", json={"feedback": fb}, headers=h | k)
    assert again.json() == done and again.headers["Idempotent-Replayed"] == "true"  # FR-20-03
    other_key = kb_client.post(f"{API}/cook-sessions/{s['id']}/complete", headers=h | key())
    assert other_key.status_code == 200 and other_key.json()["deductions"] == done["deductions"]  # FR-20-04
    assert q(kb_db, "SELECT count(*) FROM pantry_transactions WHERE reason = 'cook_deduct'").scalar() == len(
        done["deductions"]
    )


def test_complete_without_consent_still_deducts(kb_client: TestClient, kb_db) -> None:
    h = user(kb_client)
    p = _accepted(kb_client, h, kb_db)
    s = cook(kb_client, h, p["id"])
    r = kb_client.post(f"{API}/cook-sessions/{s['id']}/complete", headers=h | key()).json()
    assert r["interactions_recorded"] is False and r["deductions"]  # FR-20-13
    assert q(kb_db, "SELECT count(*) FROM interactions").scalar() == 0


def test_shortage_is_reported_not_an_error(kb_client: TestClient, kb_db, h: dict) -> None:
    p = _accepted(kb_client, h, kb_db)
    pork = q(kb_db, "SELECT l.id FROM pantry_lots l JOIN ingredients i ON i.id = l.ingredient_id "
                    "WHERE i.name_vi = 'thịt ba chỉ'").scalar()  # fmt: skip
    kb_client.patch(f"{API}/pantry/lots/{pork}", json={"balance": {"g_min": 100, "g_max": 100}}, headers=h)
    s = cook(kb_client, h, p["id"])
    r = kb_client.post(f"{API}/cook-sessions/{s['id']}/complete", headers=h | key()).json()
    short = {x["short_g"] for x in r["shortfalls"]}
    assert short == {150} and q(kb_db, "SELECT status FROM pantry_lots WHERE id = :l", l=pork).scalar() == "used_up"


def test_undo_within_ten_minutes(kb_client: TestClient, kb_db, h: dict) -> None:
    p = _accepted(kb_client, h, kb_db)
    before = {
        r.lot_id: (float(r.g_min), float(r.g_max))
        for r in q(kb_db, "SELECT lot_id, g_min, g_max FROM v_pantry_lot_balance")
    }
    s = cook(kb_client, h, p["id"])
    r = kb_client.post(f"{API}/cook-sessions/{s['id']}/undo", headers=h)
    assert (r.status_code, r.json()["code"]) == (409, "cook_session_not_completed")
    kb_client.post(f"{API}/cook-sessions/{s['id']}/complete", headers=h | key())
    clock.shift_for_tests(599)
    r = kb_client.post(f"{API}/cook-sessions/{s['id']}/undo", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "reverted"  # FR-21-01
    after = {
        r.lot_id: (float(r.g_min), float(r.g_max))
        for r in q(kb_db, "SELECT lot_id, g_min, g_max FROM v_pantry_lot_balance")
    }
    assert after == before  # FR-21-04
    assert set(q(kb_db, "SELECT status FROM pantry_lots").scalars()) == {"in_stock"}  # FR-21-05
    assert kb_client.get(f"{API}/meal-plans/{p['id']}", headers=h).json()["status"] == "accepted"  # FR-21-07
    n_undo = q(kb_db, "SELECT count(*) FROM pantry_transactions WHERE reason = 'undo'").scalar()
    assert kb_client.post(f"{API}/cook-sessions/{s['id']}/undo", headers=h).status_code == 200  # FR-21-06
    assert q(kb_db, "SELECT count(*) FROM pantry_transactions WHERE reason = 'undo'").scalar() == n_undo
    undone = q(kb_db, "SELECT count(*) FROM interactions WHERE type = 'undone'").scalar()
    cooked = q(kb_db, "SELECT count(*) FROM interactions WHERE type = 'cooked'").scalar()
    assert undone == cooked == 3  # FR-21-08: cooked rows stay
    s2 = cook(kb_client, h, p["id"])  # cookable again
    assert s2["status"] == "in_progress"


def test_undo_after_ten_minutes_is_refused(kb_client: TestClient, kb_db, h: dict) -> None:
    p = _accepted(kb_client, h, kb_db)
    s = cook(kb_client, h, p["id"])
    kb_client.post(f"{API}/cook-sessions/{s['id']}/complete", headers=h | key())
    n = q(kb_db, "SELECT count(*) FROM pantry_transactions").scalar()
    clock.shift_for_tests(601)
    r = kb_client.post(f"{API}/cook-sessions/{s['id']}/undo", headers=h)
    assert (r.status_code, r.json()["code"]) == (409, "undo_window_expired")  # FR-21-02
    assert q(kb_db, "SELECT count(*) FROM pantry_transactions").scalar() == n
    assert kb_client.get(f"{API}/cook-sessions/{s['id']}", headers=h).json()["status"] == "completed"


# ---------------------------------------------------------------- property tests


@pytest.fixture(scope="module")
def all_recipes(kb_engine):
    with Session(kb_engine) as s:
        views = catalog.published_recipes(s)
    return {slot: [v for v in views if v.slot == slot] for slot in ("man", "rau", "canh")}


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(data=st.data(), burners=st.integers(1, 4))
def test_every_schedule_of_the_catalog_is_valid(all_recipes, data, burners: int) -> None:
    tray = [data.draw(st.sampled_from(all_recipes[s])) for s in ("man", "rau", "canh")]
    dishes = [_sched_dish(r) for r in tray]
    sched = sch.solve(dishes, burners)
    assert sch.violations(dishes, burners, sched) == []
    assert sched.makespan >= sch.lower_bound(dishes, burners)


@settings(max_examples=6, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(retries=st.lists(st.sampled_from(["same_key", "new_key"]), min_size=1, max_size=4))
def test_complete_applied_twice_deducts_once(kb_client: TestClient, kb_db, retries: list[str]) -> None:
    h = user(kb_client)
    grant(kb_client, h, "personalization")
    p = _accepted(kb_client, h, kb_db)
    s = cook(kb_client, h, p["id"])
    k = key()
    first = kb_client.post(f"{API}/cook-sessions/{s['id']}/complete", headers=h | k)
    assert first.status_code == 200
    for how in retries:
        r = kb_client.post(f"{API}/cook-sessions/{s['id']}/complete", headers=h | (k if how == "same_key" else key()))
        assert r.status_code == 200 and r.json()["deductions"] == first.json()["deductions"]
    rows = q(kb_db, "SELECT count(*) FROM pantry_transactions t WHERE t.ref_id = :s AND reason = 'cook_deduct'",
             s=s["id"]).scalar()  # fmt: skip
    assert rows == len(first.json()["deductions"])
    assert (
        q(kb_db, "SELECT count(*) FROM interactions WHERE type = 'cooked' AND meal_plan_id = :p", p=p["id"]).scalar()
        == 3
    )


def test_data_export_covers_pantry_plans_cooking_and_interactions(
    kb_client: TestClient, kb_db, kb_app, h: dict
) -> None:
    import io
    import json
    import zipfile
    from pathlib import Path

    p = _accepted(kb_client, h, kb_db)
    s = cook(kb_client, h, p["id"])
    kb_client.post(f"{API}/cook-sessions/{s['id']}/complete", headers=h | key())
    garlic = q(kb_db, "SELECT id::text FROM ingredients WHERE name_vi = 'tỏi'").scalar()
    kb_client.post(f"{API}/shopping-items", json={"ingredient_id": garlic}, headers=h)
    r = kb_client.post(f"{API}/me/data-requests", json={"type": "export"}, headers=h)
    assert r.status_code == 202, r.text
    storage = Path(kb_app.state.settings.storage_dir)
    archive = zipfile.ZipFile(io.BytesIO((storage / f"exports/{r.json()['id']}.zip").read_bytes()))
    files = {n: json.loads(archive.read(n)) for n in archive.namelist()}
    for name in ("pantry_lots", "pantry_transactions", "meal_plans", "meal_plan_items", "cook_sessions",
                 "interactions", "shopping_items"):  # fmt: skip
        assert files[f"{name}.json"], name
    readme = files["README.json"]["files"]
    assert all(f["description_vi"] != f["file"].removesuffix(".json") for f in readme)
