"""UC14: lots, append-only transactions, quantity conversion, urgency computed at read (BR-PANTRY-01, BR-QTY-01/02,
BR-FRESH-01..05), BOLA; plus the deduct / reverse primitives cooking uses (BR-PANTRY-02)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from conftest import q
from fastapi.testclient import TestClient
from helpers import bearer, register
from sqlalchemy.orm import Session

from tastoria.modules.pantry import service as pantry
from tastoria.modules.pantry.schemas import Need

API = "/api/v1"


def _ing(db, name: str) -> str:
    return str(q(db, "SELECT id FROM ingredients WHERE name_vi = :n AND is_active", n=name).scalar())


def _ago(days: float) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def _lot(client: TestClient, s: dict, ingredient_id: str, quantity: dict, **kw) -> dict:
    r = client.post(f"{API}/pantry/lots", json={"ingredient_id": ingredient_id, "quantity": quantity, **kw}, headers=s)
    assert r.status_code == 201, r.text
    return r.json()


def _txs(db, lot_id: str):
    return q(db, "SELECT reason, delta_g_min, delta_g_max, urgency_at_event, ref_type FROM pantry_transactions "
                 "WHERE lot_id = :l ORDER BY id", l=lot_id).all()  # fmt: skip


@pytest.fixture
def s(kb_client: TestClient) -> dict:
    return bearer(register(kb_client))


# ---------------------------------------------------------------- create (BR-PANTRY-01, BR-QTY-02)


def test_create_by_grams_count_and_level(kb_client: TestClient, kb_db, s: dict) -> None:
    egg = _lot(kb_client, s, _ing(kb_db, "trứng gà"), {"count": 10, "unit_code": "qua"}, acquired_at=_ago(1))
    assert (egg["initial_g_min"], egg["initial_g_max"]) == (500, 500)  # FR-14-09: 10 × 50 g
    assert egg["acquired_basis"] == "purchase_date_entered" and egg["status"] == "in_stock"
    assert (egg["balance_g_min"], egg["balance_g_max"]) == (500, 500)
    leafy = _lot(kb_client, s, _ing(kb_db, "rau muống"), {"qty_level": "vua"})
    assert (leafy["initial_g_min"], leafy["initial_g_max"]) == (250, 500)  # qty_levels rau_la / vừa
    assert leafy["acquired_basis"] == "first_seen"
    bunch = _lot(kb_client, s, _ing(kb_db, "rau muống"), {"count": 2, "unit_code": "bo"})
    assert bunch["initial_g_min"] == 800
    meat = _lot(kb_client, s, _ing(kb_db, "thịt ba chỉ"), {"g_min": 300, "g_max": 350})
    assert meat["ingredient_name_vi"] == "thịt ba chỉ" and meat["urgency"] == pytest.approx(0, abs=0.01)
    again = _lot(kb_client, s, _ing(kb_db, "trứng gà"), {"count": 10, "unit_code": "qua"}, acquired_at=_ago(1))
    assert again["id"] != egg["id"]  # every add is its own lot
    assert q(kb_db, "SELECT count(*) FROM pantry_transactions").scalar() == 0  # the amount is the lot's initial


@pytest.mark.parametrize(
    ("name", "quantity", "status", "code"),
    [
        ("thịt ba chỉ", {"count": 2, "unit_code": "qua"}, 422, "qty_kind_mismatch"),
        ("trứng gà", {"count": 2, "unit_code": "hop"}, 422, "unit_conversion_missing"),
        ("trứng gà", {"qty_level": "it"}, 422, "qty_kind_mismatch"),
        ("thịt ba chỉ", {"g_min": -10, "g_max": 50}, 422, "validation_error"),
        ("thịt ba chỉ", {"g_min": 60, "g_max": 50}, 422, "validation_error"),
        ("thịt ba chỉ", {"g_min": 60, "count": 1}, 400, "validation_error"),  # mixed shapes: unknown key
    ],
)
def test_create_rejects_bad_quantities(kb_client: TestClient, kb_db, s: dict, name, quantity, status, code) -> None:
    r = kb_client.post(f"{API}/pantry/lots", json={"ingredient_id": _ing(kb_db, name), "quantity": quantity}, headers=s)
    assert (r.status_code, r.json()["code"]) == (status, code), r.text


def test_create_rejects_future_date_and_unknown_ingredient(kb_client: TestClient, kb_db, s: dict) -> None:
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    body = {"ingredient_id": _ing(kb_db, "trứng gà"), "quantity": {"g_min": 1, "g_max": 1}, "acquired_at": future}
    r = kb_client.post(f"{API}/pantry/lots", json=body, headers=s)
    assert (r.status_code, r.json()["code"]) == (422, "acquired_at_in_future")
    r = kb_client.post(f"{API}/pantry/lots", json=body | {"ingredient_id": str(uuid.uuid4()), "acquired_at": None},
                       headers=s)  # fmt: skip
    assert (r.status_code, r.json()["code"]) == (422, "unknown_ingredient")
    assert q(kb_db, "SELECT count(*) FROM pantry_lots").scalar() == 0


# ---------------------------------------------------------------- urgency at read (BR-FRESH-01..05)


def test_urgency_and_labels_sorted(kb_client: TestClient, kb_db, s: dict) -> None:
    leafy = _ing(kb_db, "cải ngọt")  # L = 4 days
    a = _lot(kb_client, s, leafy, {"g_min": 100, "g_max": 100}, acquired_at=_ago(1.2))  # 0.3
    b = _lot(kb_client, s, leafy, {"g_min": 100, "g_max": 100}, acquired_at=_ago(3.6))  # 0.9
    c = _lot(kb_client, s, leafy, {"g_min": 100, "g_max": 100}, acquired_at=_ago(2.4))  # 0.6
    d = _lot(kb_client, s, leafy, {"g_min": 100, "g_max": 100}, acquired_at=_ago(4.4))  # 1.1
    salt = _lot(kb_client, s, _ing(kb_db, "muối"), {"g_min": 500, "g_max": 500})  # not tracked
    items = kb_client.get(f"{API}/pantry/lots", headers=s).json()["items"]
    assert [x["id"] for x in items] == [d["id"], b["id"], c["id"], a["id"], salt["id"]]
    got = {x["id"]: (round(x["urgency"], 2) if x["urgency"] is not None else None, x["freshness_label"],
                     x["available"]) for x in items}  # fmt: skip
    assert got[a["id"]] == (0.3, "tuoi", True)
    assert got[c["id"]] == (0.6, "dung_som", True)
    assert got[b["id"]] == (0.9, "dung_ngay", True)
    assert got[d["id"]] == (1.1, "kiem_tra", False)  # BR-FRESH-04: not available
    assert got[salt["id"]] == (None, "chua_ro", True)  # FR-14-05
    assert (
        q(
            kb_db,
            "SELECT count(*) FROM information_schema.columns WHERE table_name = 'pantry_lots' "
            "AND column_name IN ('u', 'urgency')",
        ).scalar()
        == 0
    )  # u is never stored (FR-14-06)


def test_image_probabilities_combine_per_br_fresh_03(kb_client: TestClient, kb_db, s: dict) -> None:
    leafy = _ing(kb_db, "cải ngọt")
    lot = _lot(kb_client, s, leafy, {"g_min": 100, "g_max": 100})  # first_seen
    q(kb_db, "UPDATE pantry_lots SET acquired_at = now() - interval '3.6 days', p_tuoi = 0.7, p_dung_som = 0.2, "
             "p_dung_ngay = 0.1, p_kiem_tra = 0, freshness_observed_at = now() WHERE id = :l", l=lot["id"])  # fmt: skip

    def one() -> dict:
        return next(x for x in kb_client.get(f"{API}/pantry/lots", headers=s).json()["items"] if x["id"] == lot["id"])

    assert one()["urgency"] == pytest.approx(0.395, abs=1e-3)  # first_seen and max P ≥ 0.6 → u = u_img
    q(kb_db, "UPDATE pantry_lots SET p_tuoi = 0.5, p_dung_som = 0.3, p_dung_ngay = 0.2 WHERE id = :l", l=lot["id"])
    assert one()["urgency"] == pytest.approx(0.9, abs=1e-3)  # max P < 0.6 → max(u_time, u_img)
    q(kb_db, "UPDATE pantry_lots SET acquired_basis = 'purchase_date_entered', p_tuoi = 0.7, p_dung_som = 0.2, "
             "p_dung_ngay = 0.1 WHERE id = :l", l=lot["id"])  # fmt: skip
    assert one()["urgency"] == pytest.approx(0.9, abs=1e-3)  # a real purchase date → max
    q(kb_db, "UPDATE pantry_lots SET acquired_at = now(), p_tuoi = 0.2, p_dung_som = 0.2, p_dung_ngay = 0.1, "
             "p_kiem_tra = 0.5 WHERE id = :l", l=lot["id"])  # fmt: skip
    x = one()
    assert x["freshness_label"] == "kiem_tra" and x["available"] is False  # the check class is the most likely


def test_confirming_a_check_level_lot(kb_client: TestClient, kb_db, s: dict) -> None:
    leafy = _ing(kb_db, "cải ngọt")
    old = _lot(kb_client, s, leafy, {"g_min": 100, "g_max": 100}, acquired_at=_ago(4.4))
    fresh_ = _lot(kb_client, s, leafy, {"g_min": 100, "g_max": 100})
    r = kb_client.patch(f"{API}/pantry/lots/{fresh_['id']}", json={"user_checked": True}, headers=s)
    assert (r.status_code, r.json()["code"]) == (409, "lot_not_check_level")
    r = kb_client.patch(f"{API}/pantry/lots/{old['id']}", json={"user_checked": True}, headers=s)
    assert r.status_code == 200
    assert (r.json()["freshness_label"], r.json()["available"]) == ("dung_ngay", True)  # FR-14-15
    assert r.json()["user_checked_at"] is not None
    # a newer freshness observation puts it back at "kiểm tra"
    q(kb_db, "UPDATE pantry_lots SET p_tuoi = 0, p_dung_som = 0, p_dung_ngay = 0.1, p_kiem_tra = 0.9, "
             "freshness_observed_at = now() + interval '1 second' WHERE id = :l", l=old["id"])  # fmt: skip
    x = next(i for i in kb_client.get(f"{API}/pantry/lots", headers=s).json()["items"] if i["id"] == old["id"])
    assert (x["freshness_label"], x["available"]) == ("kiem_tra", False)


def test_list_filters_and_pages(kb_client: TestClient, kb_db, s: dict) -> None:
    leafy = _ing(kb_db, "cải ngọt")
    ids = [_lot(kb_client, s, leafy, {"g_min": 10, "g_max": 10}, acquired_at=_ago(i * 0.1))["id"] for i in range(5)]
    q(kb_db, "UPDATE pantry_lots SET status = 'not_seen' WHERE id = :l", l=ids[0])
    first = kb_client.get(f"{API}/pantry/lots", params={"limit": 2}, headers=s).json()
    second = kb_client.get(f"{API}/pantry/lots", params={"limit": 2, "cursor": first["next_cursor"]}, headers=s).json()
    third = kb_client.get(f"{API}/pantry/lots", params={"limit": 2, "cursor": second["next_cursor"]}, headers=s).json()
    seen = [x["id"] for x in first["items"] + second["items"] + third["items"]]
    assert sorted(seen) == sorted(ids) and third["next_cursor"] is None
    ns = next(x for x in first["items"] + second["items"] + third["items"] if x["id"] == ids[0])
    assert ns["status"] == "not_seen" and ns["available"] is False  # FR-14-07
    only = kb_client.get(f"{API}/pantry/lots", params={"status": "not_seen"}, headers=s).json()["items"]
    assert [x["id"] for x in only] == [ids[0]]
    by_created = kb_client.get(f"{API}/pantry/lots", params={"sort": "created_at"}, headers=s).json()["items"]
    assert [x["id"] for x in by_created] == ids


# ---------------------------------------------------------------- edits are transactions (FR-14-10 … FR-14-13)


def test_patch_balance_writes_the_difference_once(kb_client: TestClient, kb_db, s: dict) -> None:
    lot = _lot(kb_client, s, _ing(kb_db, "thịt ba chỉ"), {"g_min": 300, "g_max": 300})
    r = kb_client.patch(
        f"{API}/pantry/lots/{lot['id']}",
        json={"balance": {"g_min": 200, "g_max": 250}},
        headers=s,
    )
    assert r.status_code == 200 and (r.json()["balance_g_min"], r.json()["balance_g_max"]) == (200, 250)
    assert r.json()["initial_g_min"] == 300  # initial is never rewritten
    kb_client.patch(f"{API}/pantry/lots/{lot['id']}", json={"balance": {"g_min": 200, "g_max": 250}}, headers=s)
    assert [(t.reason, float(t.delta_g_min), float(t.delta_g_max), t.ref_type) for t in _txs(kb_db, lot["id"])] == [
        ("manual_edit", -100, -50, "user")
    ]
    r = kb_client.patch(f"{API}/pantry/lots/{lot['id']}", json={"balance": {"g_min": -1, "g_max": 50}}, headers=s)
    assert (r.status_code, r.json()["code"]) == (422, "validation_error")
    with pytest.raises(Exception, match="chỉ ghi thêm"):  # the ledger is append-only in the database
        q(kb_db, "UPDATE pantry_transactions SET delta_g_min = 0")


def test_patch_purchase_date(kb_client: TestClient, kb_db, s: dict) -> None:
    lot = _lot(kb_client, s, _ing(kb_db, "thịt ba chỉ"), {"g_min": 300, "g_max": 300})
    r = kb_client.patch(f"{API}/pantry/lots/{lot['id']}", json={"acquired_at": _ago(1)}, headers=s)
    assert r.json()["acquired_basis"] == "purchase_date_entered"
    assert r.json()["urgency"] == pytest.approx(0.2, abs=0.01)  # L = 5
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    r = kb_client.patch(f"{API}/pantry/lots/{lot['id']}", json={"acquired_at": future}, headers=s)
    assert (r.status_code, r.json()["code"]) == (422, "acquired_at_in_future")


def test_status_transitions(kb_client: TestClient, kb_db, s: dict) -> None:
    carrot = _ing(kb_db, "cà rốt")
    a = _lot(kb_client, s, carrot, {"g_min": 100, "g_max": 150})
    b = _lot(kb_client, s, carrot, {"g_min": 100, "g_max": 150})
    q(kb_db, "UPDATE pantry_lots SET status = 'not_seen' WHERE id IN (:a, :b)", a=a["id"], b=b["id"])
    r = kb_client.patch(f"{API}/pantry/lots/{a['id']}", json={"status": "in_stock"}, headers=s)
    assert r.json()["status"] == "in_stock" and _txs(kb_db, a["id"]) == []
    r = kb_client.patch(f"{API}/pantry/lots/{b['id']}", json={"status": "used_up"}, headers=s)
    assert r.json()["status"] == "used_up" and (r.json()["balance_g_min"], r.json()["balance_g_max"]) == (0, 0)
    assert [(float(t.delta_g_min), float(t.delta_g_max)) for t in _txs(kb_db, b["id"])] == [(-100, -150)]
    r = kb_client.patch(f"{API}/pantry/lots/{b['id']}", json={"status": "in_stock"}, headers=s)
    assert (r.status_code, r.json()["code"]) == (409, "invalid_lot_transition")
    r = kb_client.patch(f"{API}/pantry/lots/{b['id']}", json={"balance": {"g_min": 5, "g_max": 5}}, headers=s)
    assert (r.status_code, r.json()["code"]) == (409, "lot_closed")
    r = kb_client.patch(f"{API}/pantry/lots/{a['id']}", json={"status": "not_seen"}, headers=s)
    assert r.status_code == 422  # in_stock → not_seen by hand is not offered


def test_discard_is_idempotent(kb_client: TestClient, kb_db, s: dict) -> None:
    lot = _lot(kb_client, s, _ing(kb_db, "cải ngọt"), {"g_min": 200, "g_max": 250}, acquired_at=_ago(3.8))
    r = kb_client.post(f"{API}/pantry/lots/{lot['id']}/discard", headers=s)
    assert r.status_code == 200 and r.json()["status"] == "discarded" and r.json()["balance_g_max"] == 0
    assert kb_client.post(f"{API}/pantry/lots/{lot['id']}/discard", headers=s).status_code == 200
    txs = _txs(kb_db, lot["id"])
    assert len(txs) == 1 and txs[0].reason == "discard" and (float(txs[0].delta_g_min), float(txs[0].delta_g_max)) == (
        -200, -250)  # fmt: skip
    assert txs[0].urgency_at_event == pytest.approx(0.95, abs=0.01)  # FR-14-11
    used = _lot(kb_client, s, _ing(kb_db, "cải ngọt"), {"g_min": 1, "g_max": 1})
    kb_client.patch(f"{API}/pantry/lots/{used['id']}", json={"status": "used_up"}, headers=s)
    r = kb_client.post(f"{API}/pantry/lots/{used['id']}/discard", headers=s)
    assert (r.status_code, r.json()["code"]) == (409, "invalid_lot_transition")


def test_lots_of_another_user_are_not_found(kb_client: TestClient, kb_db, s: dict) -> None:
    lot = _lot(kb_client, s, _ing(kb_db, "thịt ba chỉ"), {"g_min": 300, "g_max": 300})
    other = bearer(register(kb_client))
    assert (
        kb_client.patch(f"{API}/pantry/lots/{lot['id']}", json={"status": "used_up"}, headers=other).status_code == 404
    )
    assert kb_client.post(f"{API}/pantry/lots/{lot['id']}/discard", headers=other).status_code == 404
    assert kb_client.get(f"{API}/pantry/lots", headers=other).json()["items"] == []
    assert q(kb_db, "SELECT status FROM pantry_lots WHERE id = :l", l=lot["id"]).scalar() == "in_stock"
    assert kb_client.get(f"{API}/pantry/lots").status_code == 401


# ---------------------------------------------------------------- deduct / reverse (used by cooking)


def test_deduct_takes_the_most_urgent_lot_first_and_reverse_restores(kb_client: TestClient, kb_db, kb_engine,
                                                                    s: dict) -> None:  # fmt: skip
    leafy = _ing(kb_db, "rau muống")  # L = 4
    urgent = _lot(kb_client, s, leafy, {"g_min": 100, "g_max": 100}, acquired_at=_ago(3.4))  # u = 0.85
    calm = _lot(kb_client, s, leafy, {"g_min": 200, "g_max": 200}, acquired_at=_ago(1.2))  # u = 0.3
    check = _lot(kb_client, s, leafy, {"g_min": 500, "g_max": 500}, acquired_at=_ago(4.4))  # kiểm tra: skipped
    uid = q(kb_db, "SELECT user_id FROM pantry_lots WHERE id = :l", l=urgent["id"]).scalar()
    with Session(kb_engine) as session:
        cs = _fake_cook_session(session, uid)
        deds, short = pantry.deduct(session, uid, cs, [Need(uuid.UUID(leafy), 150)])
        session.commit()
    got = {str(d.lot_id): (d.delta_g_min, d.delta_g_max, round(d.urgency_at_event, 2)) for d in deds}
    assert got == {urgent["id"]: (-100, -100, 0.85), calm["id"]: (-50, -50, 0.3)} and short == []  # FR-20-07
    assert q(kb_db, "SELECT status FROM pantry_lots WHERE id = :l", l=urgent["id"]).scalar() == "used_up"
    assert _txs(kb_db, check["id"]) == []  # FR-20-08
    with Session(kb_engine) as session:
        undone = pantry.reverse(session, uid, cs)
        again = pantry.reverse(session, uid, cs)
        session.commit()
    assert len(undone) == 2 and again == []  # one undo per deduction, never twice (FR-21-03, FR-21-06)
    bal = {r.lot_id: float(r.g_min) for r in q(kb_db, "SELECT lot_id::text, g_min FROM v_pantry_lot_balance")}
    assert bal[urgent["id"]] == 100 and bal[calm["id"]] == 200  # FR-21-04
    assert q(kb_db, "SELECT status FROM pantry_lots WHERE id = :l", l=urgent["id"]).scalar() == "in_stock"


def test_deduct_reports_a_shortage_and_empties_the_lots(kb_client: TestClient, kb_db, kb_engine, s: dict) -> None:
    meat = _ing(kb_db, "thịt ba chỉ")
    lot = _lot(kb_client, s, meat, {"g_min": 120, "g_max": 120})
    uid = q(kb_db, "SELECT user_id FROM pantry_lots WHERE id = :l", l=lot["id"]).scalar()
    with Session(kb_engine) as session:
        deds, short = pantry.deduct(session, uid, _fake_cook_session(session, uid), [Need(uuid.UUID(meat), 200)])
        session.commit()
    assert [(s_.need_g, s_.available_g_min, s_.short_g) for s_ in short] == [(200, 120, 80)]  # FR-20-10
    assert q(kb_db, "SELECT status FROM pantry_lots WHERE id = :l", l=lot["id"]).scalar() == "used_up"


def _fake_cook_session(session: Session, user_id) -> uuid.UUID:
    """A completed-looking cook session row so pantry_transactions.ref_id passes trg_pantry_transactions_ref."""
    from sqlalchemy import text

    plan = session.execute(text("INSERT INTO meal_plans (user_id, meal, persons, max_minutes, status, reason_vi, "
                                "params_version) VALUES (:u, 'dinner', 2, 45, 'accepted', 'x', 'p') RETURNING id"),
                           {"u": user_id}).scalar()  # fmt: skip
    return session.execute(text("INSERT INTO cook_sessions (meal_plan_id, serve_at, burners, started_at) "
                                "VALUES (:p, now(), 2, now()) RETURNING id"), {"p": plan}).scalar()  # fmt: skip
