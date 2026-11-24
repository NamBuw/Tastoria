"""UC17 (Thiếu gì? / substitutions), UC18 (shopping list) and POST /events (consent gate, dedupe)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from kb_helpers import API, add_lot, ingredient_id, key, plan, q, stock_for, user

MAN, RAU, CANH = "Ba chỉ chiên nước mắm", "Bí ngòi xào tỏi", "Canh rau ngót thịt băm"


@pytest.fixture
def h(kb_client: TestClient) -> dict:
    return user(kb_client)


def _pair(
    db, original: str, substitute: str, *, ratio: float = 1.0, score: float = 0.9, slot: str | None = None
) -> None:
    q(db, "INSERT INTO substitution_pairs (ingredient_id, substitute_id, context_slot, ratio, score, source, curated) "
          "VALUES (:a, :b, :s, :r, :sc, 'test', true)", a=ingredient_id(db, original), b=ingredient_id(db, substitute),
      s=slot, r=ratio, sc=score)  # fmt: skip


def _item(p: dict, slot: str) -> dict:
    return next(i for i in p["items"] if i["slot"] == slot and i["status"] == "active")


def _tray_with_short_meat(client: TestClient, h: dict, db) -> dict:
    """A tray where thịt băm of the canh is short once the pantry is shared (stock is exactly the recipes' needs)."""
    stock_for(client, h, db, MAN, RAU, CANH, factor=1.0)  # 2 persons need half of a 4-serving recipe
    return plan(client, h)


# ---------------------------------------------------------------- substitutes


def test_missing_ingredient_with_lookup_candidates(kb_client: TestClient, kb_db, h: dict) -> None:
    p = _tray_with_short_meat(kb_client, h, kb_db)
    canh = _item(p, "canh")
    rid = canh["recipe_id"]
    meat = q(kb_db, "SELECT i.name_vi FROM recipe_ingredients ri JOIN ingredients i ON i.id = ri.ingredient_id "
                    "WHERE ri.recipe_id = :r AND i.food_group_code = 'thit'", r=rid).scalar()  # fmt: skip
    _pair(kb_db, meat, "thịt ba chỉ", score=0.8)
    _pair(kb_db, meat, "thịt bò", score=0.9, slot="canh")
    _pair(kb_db, meat, "tôm", score=0.99)  # other food group: never offered (FR-17-05)
    # use up the meat so it is really missing
    lot = q(kb_db, "SELECT l.id FROM pantry_lots l JOIN ingredients i ON i.id = l.ingredient_id WHERE i.name_vi = :n",
            n=meat).scalar()  # fmt: skip
    kb_client.patch(f"{API}/pantry/lots/{lot}", json={"status": "used_up"}, headers=h)
    add_lot(kb_client, h, kb_db, "thịt bò", 50)
    r = kb_client.get(f"{API}/meal-plans/{p['id']}/items/{canh['id']}/substitutes", headers=h)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    miss = next(m for m in items if m["name_vi"] == meat)
    assert miss["available_g_min"] == 0 and miss["need_g"] > 0  # FR-17-01
    cands = [c["name_vi"] for c in miss["candidates"]]
    assert cands == ["thịt bò", "thịt ba chỉ"]  # context match first, then score (FR-17-04)
    bo = miss["candidates"][0]
    assert bo["origin"] == "lookup" and bo["in_pantry"] is True and bo["available_g_min"] == 50
    assert bo["grams"] == pytest.approx(miss["need_g"] * bo["ratio"], abs=0.1)  # FR-17-08


def test_candidates_respect_allergens_of_user_and_coeaters(kb_client: TestClient, kb_db, h: dict) -> None:
    stock_for(kb_client, h, kb_db, MAN, RAU, CANH)
    p = plan(kb_client, h, coeater_allergen_codes=["trung"])
    rau = _item(p, "rau")
    _pair(kb_db, "bí ngòi", "trứng gà")  # nonsense pair, but proves the filter: other group + egg allergen
    _pair(kb_db, "bí ngòi", "su su", score=0.5)
    r = kb_client.get(
        f"{API}/meal-plans/{p['id']}/items/{rau['id']}/substitutes",
        params={"ingredient_id": ingredient_id(kb_db, "bí ngòi")},
        headers=h,
    )  # FR-17-02
    names = [c["name_vi"] for c in r.json()["items"][0]["candidates"]]
    assert "trứng gà" not in names
    bad = kb_client.get(f"{API}/meal-plans/{p['id']}/items/{rau['id']}/substitutes",
                        params={"ingredient_id": ingredient_id(kb_db, "trứng gà")}, headers=h)  # fmt: skip
    assert bad.status_code == 422  # not an ingredient of the dish


def test_apply_substitution_recomputes_energy(kb_client: TestClient, kb_db, h: dict) -> None:
    stock_for(kb_client, h, kb_db, MAN, RAU, CANH)
    p = plan(kb_client, h)
    man = _item(p, "man")
    body = {"original_ingredient_id": ingredient_id(kb_db, "thịt ba chỉ"),
            "substitute_ingredient_id": ingredient_id(kb_db, "thịt bò"), "origin": "user"}  # fmt: skip
    r = kb_client.post(f"{API}/meal-plans/{p['id']}/items/{man['id']}/substitutions", json=body, headers=h)
    assert r.status_code == 200, r.text
    item = r.json()
    assert len(item["substitutions"]) == 1 and item["substitutions"][0]["grams"] == 250  # 500 g × 2/4 × ratio 1
    assert item["kcal_per_person"] < man["kcal_per_person"]  # lean beef replaces pork belly (FR-17-12)
    again = kb_client.post(f"{API}/meal-plans/{p['id']}/items/{man['id']}/substitutions", json=body, headers=h)
    assert again.json() == item  # idempotent: still one row (FR-17-11)
    assert q(kb_db, "SELECT count(*) FROM meal_plan_item_substitutions").scalar() == 1
    plan_now = kb_client.get(f"{API}/meal-plans/{p['id']}", headers=h).json()
    assert _item(plan_now, "man")["substitutions"][0]["substitute_ingredient_id"] == body["substitute_ingredient_id"]


@pytest.mark.parametrize(
    ("substitute", "code"),
    [("tôm", "other_food_group"), ("thịt ba chỉ", "same_ingredient")],
)
def test_bad_substitution_writes_nothing(kb_client: TestClient, kb_db, h: dict, substitute: str, code: str) -> None:
    stock_for(kb_client, h, kb_db, MAN, RAU, CANH)
    p = plan(kb_client, h)
    man = _item(p, "man")
    body = {"original_ingredient_id": ingredient_id(kb_db, "thịt ba chỉ"),
            "substitute_ingredient_id": ingredient_id(kb_db, substitute), "origin": "user"}  # fmt: skip
    r = kb_client.post(f"{API}/meal-plans/{p['id']}/items/{man['id']}/substitutions", json=body, headers=h)
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == code
    assert q(kb_db, "SELECT count(*) FROM meal_plan_item_substitutions").scalar() == 0


def test_substitution_against_a_coeater_allergen_is_refused(kb_client: TestClient, kb_db, h: dict) -> None:
    stock_for(kb_client, h, kb_db, MAN, RAU, CANH)
    p = plan(kb_client, h, coeater_allergen_codes=["giap_xac"])
    fish_sauce = ingredient_id(kb_db, "nước mắm")
    with_sauce = [
        i
        for i in p["items"]
        if q(kb_db, "SELECT count(*) FROM recipe_ingredients WHERE recipe_id = :r AND ingredient_id = :i",
             r=i["recipe_id"], i=fish_sauce).scalar()
    ]  # fmt: skip
    assert with_sauce, p  # nước mắm → mắm tôm: the same food group, but crustacean
    body = {"original_ingredient_id": fish_sauce, "substitute_ingredient_id": ingredient_id(kb_db, "mắm tôm"),
            "origin": "user"}  # fmt: skip
    r = kb_client.post(f"{API}/meal-plans/{p['id']}/items/{with_sauce[0]['id']}/substitutions", json=body, headers=h)
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "allergen", r.text  # FR-17-10
    assert q(kb_db, "SELECT count(*) FROM meal_plan_item_substitutions").scalar() == 0


# ---------------------------------------------------------------- shopping items (UC18)


def test_shopping_items(kb_client: TestClient, kb_db, h: dict) -> None:
    stock_for(kb_client, h, kb_db, MAN, RAU, CANH)
    p = plan(kb_client, h)
    src = p["items"][0]["id"]
    egg = ingredient_id(kb_db, "trứng gà")
    r = kb_client.post(f"{API}/shopping-items", json={"ingredient_id": egg, "qty_g": 100, "source_meal_plan_item_id": src},
                       headers=h)  # fmt: skip
    assert r.status_code == 201 and r.headers["Location"].endswith(r.json()["id"])
    first = r.json()
    r = kb_client.post(f"{API}/shopping-items", json={"ingredient_id": egg, "qty_g": 150, "source_meal_plan_item_id": src},
                       headers=h)  # fmt: skip
    assert r.status_code == 200 and r.json()["id"] == first["id"] and r.json()["qty_g"] == 150  # FR-18-05
    loose = kb_client.post(f"{API}/shopping-items", json={"ingredient_id": egg}, headers=h)
    assert loose.status_code == 201 and loose.json()["id"] != first["id"]
    assert len(kb_client.get(f"{API}/shopping-items", headers=h).json()["items"]) == 2
    bought = kb_client.patch(f"{API}/shopping-items/{first['id']}", json={"status": "bought"}, headers=h).json()
    same = kb_client.patch(f"{API}/shopping-items/{first['id']}", json={"status": "bought"}, headers=h).json()
    assert bought["status"] == "bought" and same["updated_at"] == bought["updated_at"]  # FR-18-10
    r = kb_client.patch(f"{API}/shopping-items/{first['id']}", json={"status": "dropped"}, headers=h)
    assert (r.status_code, r.json()["code"]) == (409, "conflict_state")  # FR-18-07
    r = kb_client.patch(f"{API}/shopping-items/{first['id']}", json={"qty_g": 50}, headers=h)
    assert r.status_code == 409  # FR-18-08
    assert [
        x["id"] for x in kb_client.get(f"{API}/shopping-items", params={"status": "bought"}, headers=h).json()["items"]
    ] == [first["id"]]
    assert q(kb_db, "SELECT count(*) FROM pantry_transactions").scalar() == 0  # FR-18-11
    r = kb_client.post(f"{API}/shopping-items", json={"ingredient_id": egg, "qty_g": 0}, headers=h)
    assert r.status_code == 422  # FR-18-03
    other = user(kb_client)
    assert (
        kb_client.patch(f"{API}/shopping-items/{first['id']}", json={"status": "open"}, headers=other).status_code
        == 404
    )
    r = kb_client.post(
        f"{API}/shopping-items", json={"ingredient_id": egg, "source_meal_plan_item_id": src}, headers=other
    )
    assert r.status_code == 404  # FR-18-06


def test_shopping_item_to_pantry_ledger_and_errors(kb_client: TestClient, kb_db, h: dict) -> None:
    egg = ingredient_id(kb_db, "trứng gà")
    tomato = ingredient_id(kb_db, "cà chua")
    # 1. Bought item with qty_g -> creates lot with initial=0 + 1 manual_edit tx (+qty_g), no double counting
    bought_item = kb_client.post(f"{API}/shopping-items", json={"ingredient_id": egg, "qty_g": 200}, headers=h).json()
    kb_client.patch(f"{API}/shopping-items/{bought_item['id']}", json={"status": "bought"}, headers=h)
    res = kb_client.post(f"{API}/shopping-items/{bought_item['id']}/to-pantry", headers=h)
    assert res.status_code == 201, res.text
    body = res.json()
    lot = body["pantry_lot"]
    assert res.headers["Location"] == f"/api/v1/pantry/lots/{lot['id']}"
    assert lot["initial_g_min"] == 0.0 and lot["balance_g_min"] == 200.0
    assert body["shopping_item"]["pantry_lot_id"] == lot["id"]
    tx = q(
        kb_db,
        "SELECT delta_g_min, reason, ref_type FROM pantry_transactions WHERE lot_id = :l",
        l=lot["id"],
    ).one()
    assert (float(tx.delta_g_min), tx.reason, tx.ref_type) == (200.0, "manual_edit", "user")

    # Re-converting the same item -> 409 conflict_state
    again = kb_client.post(f"{API}/shopping-items/{bought_item['id']}/to-pantry", headers=h)
    assert (again.status_code, again.json()["code"]) == (409, "conflict_state")

    # 2. Open item without qty_g -> 422 qty_required; with body qty_g -> promotes to bought + creates lot
    loose = kb_client.post(f"{API}/shopping-items", json={"ingredient_id": tomato}, headers=h).json()
    miss = kb_client.post(f"{API}/shopping-items/{loose['id']}/to-pantry", headers=h)
    assert miss.status_code == 422 and miss.json()["errors"][0]["code"] == "qty_required"
    ok_loose = kb_client.post(
        f"{API}/shopping-items/{loose['id']}/to-pantry", json={"qty_g": 350}, headers=h
    )
    assert ok_loose.status_code == 201
    assert ok_loose.json()["shopping_item"]["status"] == "bought"
    assert ok_loose.json()["shopping_item"]["qty_g"] == 350.0
    assert ok_loose.json()["pantry_lot"]["balance_g_min"] == 350.0

    # 3. Dropped item -> 409 conflict_state; BOLA -> 404
    dropped = kb_client.post(f"{API}/shopping-items", json={"ingredient_id": egg, "qty_g": 100}, headers=h).json()
    kb_client.patch(f"{API}/shopping-items/{dropped['id']}", json={"status": "dropped"}, headers=h)
    drop_err = kb_client.post(f"{API}/shopping-items/{dropped['id']}/to-pantry", headers=h)
    assert (drop_err.status_code, drop_err.json()["code"]) == (409, "conflict_state")
    other = user(kb_client)
    assert kb_client.post(f"{API}/shopping-items/{dropped['id']}/to-pantry", headers=other).status_code == 404


# ---------------------------------------------------------------- events


def test_events_are_gated_by_consent_and_deduplicated(kb_client: TestClient, kb_db) -> None:
    from kb_helpers import grant, recipe_id

    h = user(kb_client)
    rid = recipe_id(kb_db, MAN)
    ev = {
        "event_id": str(uuid.uuid4()),
        "type": "viewed",
        "recipe_id": rid,
        "occurred_at": datetime.now(UTC).isoformat(),
    }
    r = kb_client.post(f"{API}/events", json={"events": [ev]}, headers=h)
    assert r.json() == {"accepted": 0, "duplicates": 0, "skipped_no_consent": 1}  # BR-CONSENT-03
    grant(kb_client, h, "personalization")
    assert kb_client.post(f"{API}/events", json={"events": [ev]}, headers=h).json()["accepted"] == 1
    assert kb_client.post(f"{API}/events", json={"events": [ev]}, headers=h).json()["duplicates"] == 1
    foreign = ev | {"event_id": str(uuid.uuid4()), "meal_plan_id": str(uuid.uuid4())}
    assert kb_client.post(f"{API}/events", json={"events": [foreign]}, headers=h).status_code == 422
    bad = ev | {"event_id": str(uuid.uuid4()), "swap_reason": "khac"}  # swap_reason only for swapped
    assert kb_client.post(f"{API}/events", json={"events": [bad]}, headers=h).status_code == 422
    assert q(kb_db, "SELECT count(*) FROM interactions").scalar() == 1
    _ = key


def test_withdrawing_personalization_erases_interactions(kb_client: TestClient, kb_db) -> None:
    from kb_helpers import grant, recipe_id

    h = user(kb_client)
    grant(kb_client, h, "personalization")
    ev = {"event_id": str(uuid.uuid4()), "type": "viewed", "recipe_id": recipe_id(kb_db, MAN),
          "occurred_at": datetime.now(UTC).isoformat()}  # fmt: skip
    kb_client.post(f"{API}/events", json={"events": [ev]}, headers=h)
    r = kb_client.post(f"{API}/me/consents/personalization/withdraw", json={"channel": "settings"}, headers=h)
    assert r.status_code == 200, r.text
    assert q(kb_db, "SELECT count(*) FROM interactions").scalar() == 0  # BR-CONSENT-04 (the job runs after commit)


def test_events_erase_purpose_works_under_tastoria_app_role(kb_client: TestClient, kb_db, kb_engine) -> None:
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    from kb_helpers import grant, recipe_id
    from tastoria.modules.events.service import EventsSubjectData

    h = user(kb_client)
    grant(kb_client, h, "personalization")
    ev = {"event_id": str(uuid.uuid4()), "type": "viewed", "recipe_id": recipe_id(kb_db, MAN),
          "occurred_at": datetime.now(UTC).isoformat()}  # fmt: skip
    assert kb_client.post(f"{API}/events", json={"events": [ev]}, headers=h).json()["accepted"] == 1
    uid = q(kb_db, "SELECT user_id FROM interactions LIMIT 1").scalar_one()

    with Session(kb_engine) as session, session.begin():
        session.execute(
            text(
                "INSERT INTO dsr_requests (user_id, subject_ref, type, status, received_at) "
                "VALUES (:u, '\\x01', 'withdraw', 'in_progress', now())"
            ),
            {"u": uid},
        )
        session.execute(text("SET LOCAL tastoria.erasure = 'on'"))
        session.execute(text("SET LOCAL ROLE tastoria_app"))
        EventsSubjectData().erase_purpose(session, uid, "personalization")

    assert q(kb_db, "SELECT count(*) FROM interactions").scalar() == 0


def test_events_rejects_server_only_types_and_enforces_rate_limit(kb_client: TestClient, kb_db) -> None:
    from kb_helpers import grant, recipe_id

    h = user(kb_client)
    grant(kb_client, h, "personalization")
    rid = recipe_id(kb_db, MAN)
    for bad_type in ("cooked", "served", "swapped", "undone"):
        ev = {
            "event_id": str(uuid.uuid4()),
            "type": bad_type,
            "recipe_id": rid,
            "occurred_at": datetime.now(UTC).isoformat(),
            **({"swap_reason": "khac"} if bad_type == "swapped" else {}),
        }
        r = kb_client.post(f"{API}/events", json={"events": [ev]}, headers=h)
        assert r.status_code == 422, bad_type

    for _ in range(60):
        ev = {"event_id": str(uuid.uuid4()), "type": "viewed", "recipe_id": rid, "occurred_at": datetime.now(UTC).isoformat()}
        assert kb_client.post(f"{API}/events", json={"events": [ev]}, headers=h).status_code == 200
    ev = {"event_id": str(uuid.uuid4()), "type": "viewed", "recipe_id": rid, "occurred_at": datetime.now(UTC).isoformat()}
    limited = kb_client.post(f"{API}/events", json={"events": [ev]}, headers=h)
    assert (limited.status_code, limited.json()["code"]) == (429, "rate_limited")


def test_concurrent_shopping_item_inserts_merge_without_500(kb_client: TestClient, kb_db, kb_engine) -> None:
    import concurrent.futures

    from sqlalchemy import text
    from sqlalchemy.orm import Session

    from tastoria.core.auth import AuthUser
    from tastoria.modules.substitute.schemas import ShoppingItemCreate
    from tastoria.modules.substitute.service import SubstituteDeps, create_item

    h = user(kb_client)
    # Create an open user and fetch UUID directly
    egg = ingredient_id(kb_db, "trứng gà")
    uid = q(kb_db, "SELECT id FROM users ORDER BY created_at DESC LIMIT 1").scalar_one()
    auth = AuthUser(id=uid, role="user", email="race@example.vn")
    deps = SubstituteDeps(item_owned=lambda *_a: False)

    def _run(qty: float) -> tuple[str, bool]:
        with Session(kb_engine) as s, s.begin():
            out, created = create_item(
                s,
                deps,
                auth,
                ShoppingItemCreate(ingredient_id=uuid.UUID(egg), qty_g=qty),
            )
            return str(out.id), created

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(_run, [100.0, 200.0]))

    ids = {r[0] for r in results}
    created_flags = sorted(r[1] for r in results)
    assert len(ids) == 1
    assert created_flags == [False, True]
    assert q(kb_db, "SELECT count(*) FROM shopping_items WHERE user_id = :u", u=uid).scalar() == 1
    _ = (h, text)
