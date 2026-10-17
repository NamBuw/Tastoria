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
    man = _item(p, "man")  # Ba chỉ chiên nước mắm: nước mắm → mắm tôm is the same food group, but crustacean
    body = {"original_ingredient_id": ingredient_id(kb_db, "nước mắm"),
            "substitute_ingredient_id": ingredient_id(kb_db, "mắm tôm"), "origin": "user"}  # fmt: skip
    r = kb_client.post(f"{API}/meal-plans/{p['id']}/items/{man['id']}/substitutions", json=body, headers=h)
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "allergen"  # FR-17-10
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
