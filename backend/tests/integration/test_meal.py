"""UC15/UC16: POST /meal-plans (hard filter, ranking, composer, fallbacks), read, accept, lifecycle, swap, BOLA."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from kb_helpers import (
    API,
    accept,
    active_names,
    add_lot,
    grant,
    ingredient_id,
    key,
    plan,
    q,
    stock_for,
    stock_needs,
    user,
)

from tastoria.core import clock

MAN, RAU, CANH = "Ba chỉ chiên nước mắm", "Bí ngòi xào tỏi", "Canh rau ngót thịt băm"


@pytest.fixture
def h(kb_client: TestClient) -> dict:
    return user(kb_client)


@pytest.fixture(autouse=True)
def _reset_clock():
    yield
    clock.shift_for_tests(0)


def _pooled_ok(db, p: dict) -> bool:
    """Σ need of every stock-checked ingredient over the active dishes ≤ Σ g_min of the user's usable lots."""
    need: dict[str, float] = {}
    for it in p["items"]:
        if it["status"] != "active":
            continue
        for name, grams, servings in stock_needs(db, it["recipe_name_vi"]):
            need[name] = need.get(name, 0.0) + grams * p["persons"] / servings
    have = {r.name_vi: float(r.g) for r in q(db, "SELECT i.name_vi, sum(b.g_min) AS g FROM v_pantry_lot_balance b "
                                                 "JOIN ingredients i ON i.id = b.ingredient_id GROUP BY 1")}  # fmt: skip
    return all(g <= have.get(n, 0) + 1e-6 for n, g in need.items())


# ---------------------------------------------------------------- create


def test_three_dish_tray_from_the_pantry(kb_client: TestClient, kb_db, h: dict) -> None:
    stock_for(kb_client, h, kb_db, MAN, RAU, CANH)
    r = kb_client.post(f"{API}/meal-plans", json={"meal": "dinner", "max_minutes": 120}, headers=h | key())
    assert r.status_code == 201, r.text
    p = r.json()
    assert r.headers["Location"] == f"/api/v1/meal-plans/{p['id']}"
    assert p["status"] == "proposed" and p["persons"] == 2  # default_persons (BR-TRAY-01)
    assert sorted(i["slot"] for i in p["items"]) == ["canh", "man", "rau"]
    assert all(i["kcal_per_person"] and i["servings_scale"] > 0 and 0 <= i["rank_score"] <= 1 for i in p["items"])
    assert p["e_target_kcal"] is None and p["rice_bowls_per_person"] is None  # no health consent (BR-CONSENT-02)
    h_ = float(q(kb_db, "SELECT current_setting('tastoria.kcal_half_width', true)").scalar() or "nan")
    dishes = sum(i["kcal_per_person"] for i in p["items"])
    assert p["kcal_low"] == pytest.approx(dishes * (1 - h_), abs=0.2)  # FR-15-22, h from validation (BR-NUT-06)
    assert p["kcal_high"] == pytest.approx(dishes * (1 + h_), abs=0.2)
    assert p["reason_vi"] and p["params_version"] and p["ranker_version_id"] is None
    assert _pooled_ok(kb_db, p)
    assert q(kb_db, "SELECT count(*) FROM interactions").scalar() == 0  # no personalization consent


def test_one_person_gets_two_dishes(kb_client: TestClient, kb_db, h: dict) -> None:
    stock_for(kb_client, h, kb_db, MAN, RAU, CANH)
    p = plan(kb_client, h, persons=1)
    slots = sorted(i["slot"] for i in p["items"])
    assert slots in (["man", "rau"], ["canh", "man"])  # BR-TRAY-01


def test_two_dish_fallback_when_one_slot_is_missing(kb_client: TestClient, kb_db, h: dict) -> None:
    stock_for(kb_client, h, kb_db, MAN, CANH)
    p = plan(kb_client, h, persons=2)
    assert len(p["items"]) == 2 and "man" in active_names(p)
    assert p["reason_vi"].startswith("Mâm 2 món vì thiếu nguyên liệu")  # FR-15-24


def test_empty_pantry_is_no_feasible_tray_and_stores_the_answer(kb_client: TestClient, kb_db, h: dict) -> None:
    k = key()
    body = {"meal": "dinner", "max_minutes": 60}
    r = kb_client.post(f"{API}/meal-plans", json=body, headers=h | k)
    assert r.status_code == 422 and r.headers["content-type"].startswith("application/problem+json")
    err = r.json()
    assert err["code"] == "no_feasible_tray" and len(err["shortfalls"]) == 3  # FR-15-31
    assert all(s["missing"] for s in err["shortfalls"]) and err["unmet_pinned_lot_ids"] == []
    m = err["shortfalls"][0]["missing"][0]
    assert m["need_g"] > 0 and m["available_g_min"] == 0 and m["name_vi"]
    assert q(kb_db, "SELECT count(*) FROM meal_plans").scalar() == 0
    again = kb_client.post(f"{API}/meal-plans", json=body, headers=h | k)  # SD03: the 422 is replayed verbatim
    assert again.status_code == 422 and again.json() == err and again.headers["Idempotent-Replayed"] == "true"


def test_idempotency_key(kb_client: TestClient, kb_db, h: dict) -> None:
    stock_for(kb_client, h, kb_db, MAN, RAU, CANH)
    k = key()
    body = {"meal": "lunch", "max_minutes": 120}
    first = kb_client.post(f"{API}/meal-plans", json=body, headers=h | k)
    again = kb_client.post(f"{API}/meal-plans", json=body, headers=h | k)
    assert first.status_code == again.status_code == 201 and again.json()["id"] == first.json()["id"]
    assert again.headers["Idempotent-Replayed"] == "true"
    assert q(kb_db, "SELECT count(*) FROM meal_plans").scalar() == 1  # FR-15-04
    other = kb_client.post(f"{API}/meal-plans", json=body | {"persons": 3}, headers=h | k)
    assert (other.status_code, other.json()["code"]) == (422, "idempotency_key_reused")  # FR-15-05
    missing = kb_client.post(f"{API}/meal-plans", json=body, headers=h)
    assert (missing.status_code, missing.json()["code"]) == (400, "idempotency_key_required")


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"meal": "dinner", "max_minutes": 60, "persons": 7}, "validation_error"),
        ({"meal": "dinner", "max_minutes": 5}, "validation_error"),
        ({"meal": "brunch", "max_minutes": 60}, "validation_error"),
        ({"meal": "dinner", "max_minutes": 60, "coeater_allergen_codes": ["abc"]}, "unknown_code"),
        ({"meal": "dinner", "max_minutes": 60, "pinned_lot_ids": [str(uuid.uuid4())]}, "validation_error"),
    ],
)
def test_bad_requests_store_nothing(kb_client: TestClient, kb_db, h: dict, body: dict, code: str) -> None:
    r = kb_client.post(f"{API}/meal-plans", json=body, headers=h | key())
    assert (r.status_code, r.json()["code"]) == (422, code), r.text
    assert q(kb_db, "SELECT count(*) FROM meal_plans").scalar() == 0


def test_more_than_two_pins_or_foreign_pins(kb_client: TestClient, kb_db, h: dict) -> None:
    lots = [add_lot(kb_client, h, kb_db, "thịt ba chỉ", 300)["id"] for _ in range(3)]
    r = kb_client.post(f"{API}/meal-plans", json={"meal": "dinner", "max_minutes": 60, "pinned_lot_ids": lots},
                       headers=h | key())  # fmt: skip
    assert r.status_code == 422  # FR-15-02
    other = user(kb_client)
    r = kb_client.post(f"{API}/meal-plans", json={"meal": "dinner", "max_minutes": 60, "pinned_lot_ids": lots[:1]},
                       headers=other | key())  # fmt: skip
    assert (r.status_code, r.json()["code"]) == (422, "validation_error")


# ---------------------------------------------------------------- hard filter (BR-ALG-01, BR-DIET-01)


def _ingredients_of(db, plan_id: str) -> set[tuple[str, str]]:
    """(allergen, food group) of every line of every dish of the plan — staples and optional lines included."""
    return {
        (r.allergen_code or "", r.food_group_code)
        for r in q(db, "SELECT ia.allergen_code, i.food_group_code FROM meal_plan_items it "
                       "JOIN recipe_ingredients ri ON ri.recipe_id = it.recipe_id "
                       "JOIN ingredients i ON i.id = ri.ingredient_id "
                       "LEFT JOIN ingredient_allergens ia ON ia.ingredient_id = i.id WHERE it.meal_plan_id = :p",
                   p=plan_id)
    }  # fmt: skip


def test_user_and_coeater_allergens_include_staples(kb_client: TestClient, kb_db, h: dict) -> None:
    stock_for(kb_client, h, kb_db, MAN, RAU, CANH, "Đậu phụ rán tẩm hành", "Giá xào hẹ", "Canh mồng tơi nấu mướp")
    assert kb_client.put(f"{API}/me/allergens", json={"allergen_codes": ["ca"]}, headers=h).status_code == 200
    p = plan(kb_client, h, coeater_allergen_codes=["gluten"])
    found = {a for a, _ in _ingredients_of(kb_db, p["id"])}
    assert "ca" not in found and "gluten" not in found  # nước mắm (a staple) carries fish: Ba chỉ chiên is out
    assert MAN not in active_names(p).values()
    assert p["coeater_allergen_codes"] == ["gluten"]
    assert q(kb_db, "SELECT allergen_code FROM meal_plan_coeater_allergens WHERE meal_plan_id = :p",
             p=p["id"]).scalars().all() == ["gluten"]  # fmt: skip


def test_vegetarian_diet(kb_client: TestClient, kb_db, h: dict) -> None:
    stock_for(kb_client, h, kb_db, MAN, RAU, CANH, "Đậu phụ rán tẩm hành", "Giá xào hẹ", "Canh mồng tơi nấu mướp")
    assert kb_client.put(f"{API}/me/diet", json={"diet_code": "chay"}, headers=h).status_code == 200
    p = plan(kb_client, h)
    groups = {g for _, g in _ingredients_of(kb_db, p["id"])}
    assert not groups & {"thit", "gia_cam", "ca", "hai_san", "trung", "gia_vi_dong_vat"}  # FR-15-07


# ---------------------------------------------------------------- pins, time, urgency, make-ahead


def test_pinned_lot_is_used_at_least_half(kb_client: TestClient, kb_db, h: dict) -> None:
    stock_for(kb_client, h, kb_db, MAN, RAU, CANH)
    pin = add_lot(kb_client, h, kb_db, "bí ngòi", 300)  # Bí ngòi xào tỏi uses 400 g × 2/4 = 200 g ≥ 150
    p = plan(kb_client, h, pinned_lot_ids=[pin["id"]])
    assert p["pinned_lot_ids"] == [pin["id"]] and active_names(p)["rau"] == RAU


def test_unusable_pin_is_reported(kb_client: TestClient, kb_db, h: dict) -> None:
    stock_for(kb_client, h, kb_db, MAN, RAU, CANH)
    pin = add_lot(kb_client, h, kb_db, "thịt ba chỉ", 5000)  # no tray uses 2.5 kg of pork belly
    r = kb_client.post(f"{API}/meal-plans", json={"meal": "dinner", "max_minutes": 120, "pinned_lot_ids": [pin["id"]]},
                       headers=h | key())  # fmt: skip
    assert (r.status_code, r.json()["code"]) == (422, "pin_unsatisfiable")  # FR-15-30
    assert r.json()["unmet_pinned_lot_ids"] == [pin["id"]]
    assert q(kb_db, "SELECT count(*) FROM meal_plans").scalar() == 0


def test_too_little_time_is_no_feasible_tray(kb_client: TestClient, kb_db, h: dict) -> None:
    stock_for(kb_client, h, kb_db, MAN, RAU, CANH)
    r = kb_client.post(f"{API}/meal-plans", json={"meal": "dinner", "max_minutes": 10}, headers=h | key())
    assert (r.status_code, r.json()["code"]) == (422, "no_feasible_tray")


def test_urgent_lot_drives_the_reason_line(kb_client: TestClient, kb_db, h: dict) -> None:
    stock_for(kb_client, h, kb_db, MAN, CANH, prefer=False)  # no favourites: taste ties, urgency decides
    add_lot(kb_client, h, kb_db, "tỏi", 100)
    add_lot(kb_client, h, kb_db, "bí ngòi", 400, days_ago=4)  # L ≈ 5–7 days → "nên dùng sớm" / "dùng ngay"
    add_lot(kb_client, h, kb_db, "cải cúc", 400)
    p = plan(kb_client, h)
    assert active_names(p)["rau"] == RAU
    assert "bí ngòi" in p["reason_vi"]  # FR-15-23


def test_make_ahead_dish_needs_its_item(kb_client: TestClient, kb_db, h: dict) -> None:
    stock_for(kb_client, h, kb_db, MAN, CANH)
    stock_for(kb_client, h, kb_db, "Dưa cải muối")  # the raw cải bẹ xanh … is not the pickle
    p = plan(kb_client, h)
    assert "Dưa cải muối" not in active_names(p).values()
    add_lot(kb_client, h, kb_db, "dưa cải chua", 500)
    p = plan(kb_client, h)
    assert active_names(p)["rau"] == "Dưa cải muối"


# ---------------------------------------------------------------- consent-gated interactions


def test_served_interactions_only_with_consent(kb_client: TestClient, kb_db) -> None:
    h = user(kb_client, "personalization")
    stock_for(kb_client, h, kb_db, MAN, RAU, CANH)
    p = plan(kb_client, h)
    rows = q(kb_db, "SELECT type, position, propensity FROM interactions WHERE meal_plan_id = :p ORDER BY position",
             p=p["id"]).all()  # fmt: skip
    assert [(r.type, r.position, r.propensity) for r in rows] == [("served", 0, 1.0), ("served", 1, 1.0),
                                                                  ("served", 2, 1.0)]  # fmt: skip


def test_energy_target_and_rice_bowls_with_health_consent(kb_client: TestClient, kb_db) -> None:
    h = user(kb_client, "health_profile")
    r = kb_client.put(f"{API}/me/energy-target", json={"kcal_target": 2000, "kcal_source": "user"}, headers=h)
    assert r.status_code == 200, r.text
    stock_for(kb_client, h, kb_db, MAN, RAU, CANH)
    p = plan(kb_client, h, meal="dinner", persons=3)
    assert p["e_target_kcal"] == 600 and p["persons"] == 3  # FR-15-19: per person, E × 0.30
    bowls = p["rice_bowls_per_person"]
    assert 0.5 <= bowls <= 3 and bowls * 2 == int(bowls * 2)  # BR-TRAY-03
    dishes = sum(i["kcal_per_person"] for i in p["items"])
    raw = q(kb_db, "SELECT per_100g FROM food_nutrients WHERE source_code = '1004' AND nutrient_code = 'energy_kcal'"
            ).scalar()  # fmt: skip
    rice = round(float(raw) * 150 / 2.98 / 100, 1)  # E_bát of 150 g cooked rice
    expected = min(3, max(0.5, int((600 - dishes) / rice * 2 + 0.5) / 2))
    assert bowls == expected


# ---------------------------------------------------------------- read, accept, lifecycle, BOLA


def test_read_accept_and_bola(kb_client: TestClient, kb_db, h: dict) -> None:
    stock_for(kb_client, h, kb_db, MAN, RAU, CANH)
    p = plan(kb_client, h)
    assert kb_client.get(f"{API}/meal-plans/{p['id']}", headers=h).json()["id"] == p["id"]
    first = accept(kb_client, h, p["id"])
    again = accept(kb_client, h, p["id"])
    assert first["status"] == again["status"] == "accepted" and again["updated_at"] == first["updated_at"]
    other = user(kb_client)
    item = p["items"][0]["id"]
    for method, path, body in [
        ("get", f"/meal-plans/{p['id']}", None),
        ("post", f"/meal-plans/{p['id']}/accept", None),
        ("post", f"/meal-plans/{p['id']}/items/{item}/swap", {"swap_reason": "khac"}),
        ("get", f"/meal-plans/{p['id']}/items/{item}/substitutes", None),
        ("post", f"/meal-plans/{p['id']}/items/{item}/substitutions",
         {"original_ingredient_id": str(uuid.uuid4()), "substitute_ingredient_id": str(uuid.uuid4()), "origin": "user"}),
    ]:  # fmt: skip
        r = kb_client.request(method.upper(), f"{API}{path}", json=body, headers=other | key())
        assert r.status_code == 404, (path, r.text)
    assert kb_client.get(f"{API}/meal-plans/latest", headers=other).status_code == 404


def test_new_plan_supersedes_the_open_one_of_the_same_meal(kb_client: TestClient, kb_db, h: dict) -> None:
    stock_for(kb_client, h, kb_db, MAN, RAU, CANH)
    m1 = plan(kb_client, h)
    m2 = plan(kb_client, h)
    assert kb_client.get(f"{API}/meal-plans/{m1['id']}", headers=h).json()["status"] == "expired"  # FR-15-37
    accept(kb_client, h, m2["id"])
    m3 = plan(kb_client, h)
    assert kb_client.get(f"{API}/meal-plans/{m2['id']}", headers=h).json()["status"] == "abandoned"  # FR-15-38
    lunch = plan(kb_client, h, meal="lunch")
    assert kb_client.get(f"{API}/meal-plans/{m3['id']}", headers=h).json()["status"] == "proposed"
    latest = kb_client.get(f"{API}/meal-plans/latest", params={"meal": "lunch"}, headers=h).json()
    assert latest["id"] == lunch["id"]
    r = kb_client.post(f"{API}/meal-plans/{m1['id']}/accept", headers=h)
    assert (r.status_code, r.json()["code"]) == (409, "conflict_state")  # FR-15-33


def test_plan_expires_after_the_meal(kb_client: TestClient, kb_db, h: dict) -> None:
    stock_for(kb_client, h, kb_db, MAN, RAU, CANH)
    p = plan(kb_client, h, meal="lunch")
    clock.shift_for_tests(36 * 3600)
    assert kb_client.get(f"{API}/meal-plans/{p['id']}", headers=h).json()["status"] == "expired"  # FR-15-39
    assert kb_client.post(f"{API}/meal-plans/{p['id']}/accept", headers=h).status_code == 409


def test_list_plans_newest_first_with_filters(kb_client: TestClient, kb_db, h: dict) -> None:
    stock_for(kb_client, h, kb_db, MAN, RAU, CANH)
    ids = [plan(kb_client, h, meal=m)["id"] for m in ("lunch", "dinner", "lunch")]
    page = kb_client.get(f"{API}/meal-plans", params={"limit": 2}, headers=h).json()
    rest = kb_client.get(f"{API}/meal-plans", params={"limit": 2, "cursor": page["next_cursor"]}, headers=h).json()
    assert [x["id"] for x in page["items"] + rest["items"]] == ids[::-1]
    assert all(len(x["recipe_names_vi"]) == 3 for x in page["items"])
    expired = kb_client.get(f"{API}/meal-plans", params={"status": "expired"}, headers=h).json()["items"]
    assert [x["id"] for x in expired] == [ids[0]]


# ---------------------------------------------------------------- swap (BR-SWAP-01)


def test_swap_keeps_other_slots_and_never_brings_a_dish_back(kb_client: TestClient, kb_db, h: dict) -> None:
    stock_for(kb_client, h, kb_db, MAN, RAU, CANH, "Giá xào hẹ", "Cải cúc xào tỏi")
    grant(kb_client, h, "personalization")
    p = plan(kb_client, h)
    before = active_names(p)
    rau = next(i for i in p["items"] if i["slot"] == "rau")
    k = key()
    r = kb_client.post(f"{API}/meal-plans/{p['id']}/items/{rau['id']}/swap", json={"swap_reason": "moi_an"},
                       headers=h | k)  # fmt: skip
    assert r.status_code == 200, r.text
    after = r.json()
    names = active_names(after)
    assert names["man"] == before["man"] and names["canh"] == before["canh"]  # FR-16-05
    assert names["rau"] != before["rau"]
    old = next(i for i in after["items"] if i["id"] == rau["id"])
    new = next(i for i in after["items"] if i["status"] == "active" and i["slot"] == "rau")
    assert old["status"] == "swapped_out" and old["swap_reason"] == "moi_an" and new["replaced_item_id"] == rau["id"]
    again = kb_client.post(f"{API}/meal-plans/{p['id']}/items/{rau['id']}/swap", json={"swap_reason": "moi_an"},
                           headers=h | k)  # fmt: skip
    assert again.json() == after and again.headers["Idempotent-Replayed"] == "true"  # FR-16-04
    r = kb_client.post(f"{API}/meal-plans/{p['id']}/items/{rau['id']}/swap", json={"swap_reason": "moi_an"},
                       headers=h | key())  # fmt: skip
    assert (r.status_code, r.json()["code"]) == (409, "conflict_state")  # swapped_out already
    second = kb_client.post(f"{API}/meal-plans/{p['id']}/items/{new['id']}/swap", json={"swap_reason": "khong_hop_gu"},
                            headers=h | key()).json()  # fmt: skip
    assert active_names(second)["rau"] not in {before["rau"], names["rau"]}  # FR-16-06
    types = q(kb_db, "SELECT type, swap_reason FROM interactions WHERE meal_plan_id = :p AND type <> 'served'",
              p=p["id"]).all()  # fmt: skip
    assert sorted((t.type, t.swap_reason) for t in types) == [("swapped", "khong_hop_gu"), ("swapped", "moi_an")]
    assert q(kb_db, "SELECT count(*) FROM interactions WHERE type = 'disliked'").scalar() == 0  # FR-16-13


def test_swap_without_alternative(kb_client: TestClient, kb_db, h: dict) -> None:
    stock_for(kb_client, h, kb_db, MAN, RAU, CANH)
    p = plan(kb_client, h)
    item = next(i for i in p["items"] if i["slot"] == "canh")
    r = kb_client.post(f"{API}/meal-plans/{p['id']}/items/{item['id']}/swap", json={"swap_reason": "khac"},
                       headers=h | key())  # fmt: skip
    if r.status_code == 200:  # another canh fitted the stock; the next one cannot
        item = next(i for i in r.json()["items"] if i["slot"] == "canh" and i["status"] == "active")
        r = kb_client.post(f"{API}/meal-plans/{p['id']}/items/{item['id']}/swap", json={"swap_reason": "khac"},
                           headers=h | key())  # fmt: skip
    assert (r.status_code, r.json()["code"]) == (422, "no_alternative")  # FR-16-14
    bad = kb_client.post(f"{API}/meal-plans/{p['id']}/items/{item['id']}/swap", json={"swap_reason": "chan"},
                         headers=h | key())  # fmt: skip
    assert bad.status_code == 422  # FR-16-01


def test_ingredient_id_helper_resolves(kb_db) -> None:
    assert uuid.UUID(ingredient_id(kb_db, "tỏi"))
