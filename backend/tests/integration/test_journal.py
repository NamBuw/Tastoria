"""UC22: GET /journal?week=YYYY-Www over v_journal_days in the user's time zone."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from kb_helpers import API, accept, add_lot, cook, key, plan, q, stock_for, user

from tastoria.core import clock

MAN, RAU, CANH = "Ba chỉ chiên nước mắm", "Bí ngòi xào tỏi", "Canh rau ngót thịt băm"


@pytest.fixture(autouse=True)
def _reset_clock():
    yield
    clock.shift_for_tests(0)


def _cooked_tray(client: TestClient, h: dict, db, *, urgent: bool = False) -> dict:
    stock_for(client, h, db, MAN, CANH)
    add_lot(client, h, db, "tỏi", 100)
    add_lot(client, h, db, "bí ngòi", 400, days_ago=4 if urgent else None)
    p = accept(client, h, plan(client, h)["id"])
    s = cook(client, h, p["id"])
    r = client.post(f"{API}/cook-sessions/{s['id']}/complete", headers=h | key())
    assert r.status_code == 200, r.text
    return {"plan": p, "session": r.json()["cook_session"]}


def _week_of(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def test_week_has_seven_days_and_the_cooked_tray(kb_client: TestClient, kb_db) -> None:
    h = user(kb_client)
    done = _cooked_tray(kb_client, h, kb_db, urgent=True)
    tz = q(kb_db, "SELECT timezone FROM user_settings").scalar()
    local = datetime.fromisoformat(done["session"]["completed_at"]).astimezone(ZoneInfo(tz)).date()
    r = kb_client.get(f"{API}/journal", params={"week": _week_of(local)}, headers=h)
    assert r.status_code == 200, r.text
    wk = r.json()
    assert wk["timezone"] == tz and wk["kcal_range_status"] == "calibrated"  # h from validation/nin_dishes.yaml
    assert len(wk["days"]) == 7 and date.fromisoformat(wk["days"][0]["date"]).isoweekday() == 1  # FR-22-01
    day = next(d for d in wk["days"] if d["date"] == local.isoformat())
    dishes = sum(i["kcal_per_person"] for i in done["plan"]["items"])
    assert day["cooked_trays"] == 1 and day["kcal_per_person"] == pytest.approx(dishes, abs=0.2)  # no target → no rice
    assert day["e_target_kcal"] is None  # FR-22-05
    assert day["urgent_lots_used"] == 1  # the bí ngòi lot at u ∈ [0.5, 1.0] (FR-22-07)
    others = [d for d in wk["days"] if d["date"] != local.isoformat()]
    assert all(d["cooked_trays"] == 0 and d["kcal_per_person"] is None for d in others)
    stranger = user(kb_client)
    assert all(d["cooked_trays"] == 0 for d in kb_client.get(f"{API}/journal", params={"week": _week_of(local)},
                                                             headers=stranger).json()["days"])  # FR-22-09  # fmt: skip


def test_rice_counts_in_kcal_and_target_is_the_snapshot(kb_client: TestClient, kb_db) -> None:
    h = user(kb_client, "health_profile")
    kb_client.put(f"{API}/me/energy-target", json={"kcal_target": 2000, "kcal_source": "user"}, headers=h)
    done = _cooked_tray(kb_client, h, kb_db)
    p = done["plan"]
    rice = q(
        kb_db, "SELECT per_100g FROM food_nutrients WHERE source_code = '1004' AND nutrient_code = 'energy_kcal'"
    ).scalar()
    e_bowl = round(float(rice) * 150 / 2.98 / 100, 1)
    week = kb_client.get(f"{API}/journal", headers=h).json()  # default = this week, user time zone
    day = next(d for d in week["days"] if d["cooked_trays"])
    expected = sum(i["kcal_per_person"] for i in p["items"]) + p["rice_bowls_per_person"] * e_bowl
    assert day["kcal_per_person"] == pytest.approx(expected, abs=0.2)  # FR-22-04
    assert day["e_target_kcal"] == p["e_target_kcal"] == 600  # FR-22-11: per person, not × persons


def test_reverted_session_does_not_count(kb_client: TestClient, kb_db) -> None:
    h = user(kb_client)
    done = _cooked_tray(kb_client, h, kb_db)
    assert kb_client.post(f"{API}/cook-sessions/{done['session']['id']}/undo", headers=h).status_code == 200
    week = kb_client.get(f"{API}/journal", headers=h).json()
    assert all(d["cooked_trays"] == 0 for d in week["days"])  # FR-22-03


def test_day_is_the_local_day_of_completion(kb_client: TestClient, kb_db) -> None:
    h = user(kb_client, tz="Asia/Ho_Chi_Minh")
    stock_for(kb_client, h, kb_db, MAN, RAU, CANH)
    p = accept(kb_client, h, plan(kb_client, h, meal="lunch")["id"])
    s = cook(kb_client, h, p["id"])
    kb_client.post(f"{API}/cook-sessions/{s['id']}/complete", headers=h | key())
    completed = q(kb_db, "SELECT completed_at FROM cook_sessions").scalar()
    local = completed.astimezone(ZoneInfo("Asia/Ho_Chi_Minh")).date()  # FR-22-02 (e.g. 17:30Z → next day in VN)
    week = kb_client.get(f"{API}/journal", params={"week": _week_of(local)}, headers=h).json()
    assert next(d for d in week["days"] if d["date"] == local.isoformat())["cooked_trays"] == 1
    assert completed.astimezone(UTC).date() in (local, local - timedelta(days=1))


@pytest.mark.parametrize("week", ["2026-W54", "abc", "2026-W00", "2021-W53"])
def test_invalid_iso_week(kb_client: TestClient, week: str) -> None:
    h = user(kb_client)
    r = kb_client.get(f"{API}/journal", params={"week": week}, headers=h)
    assert (r.status_code, r.json()["code"]) == (422, "invalid_iso_week")  # FR-22-08


def test_week_53_when_it_exists(kb_client: TestClient) -> None:
    h = user(kb_client)
    r = kb_client.get(f"{API}/journal", params={"week": "2026-W53"}, headers=h)
    assert r.status_code == 200 and r.json()["days"][0]["date"] == "2026-12-28"
