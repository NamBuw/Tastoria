"""GET /reference, /recipes, /recipes/{id}, /ingredients, /catalog/snapshot on the imported data/kb catalog."""

from __future__ import annotations

import uuid

from conftest import q
from fastapi.testclient import TestClient
from helpers import bearer, register

API = "/api/v1"


def test_reference_is_public_and_cached_by_etag(kb_client: TestClient) -> None:
    r = kb_client.get(f"{API}/reference")
    assert r.status_code == 200
    body = r.json()
    assert {a["code"] for a in body["allergen_groups"]} >= {"gluten", "giap_xac", "ca", "dau_nanh", "nhuyen_the"}
    chay = next(d for d in body["diets"] if d["code"] == "chay")
    assert set(chay["excluded_food_group_codes"]) == {"thit", "gia_cam", "ca", "hai_san", "trung", "gia_vi_dong_vat"}
    assert {p["code"] for p in body["consent_purposes"]} == {"health_profile", "personalization", "photo_contribution",
                                                             "survey"}  # fmt: skip
    assert any(t["code"] == "lam_san" for t in body["tags"])
    assert {n["code"] for n in body["nutrients"]} >= {"energy_kcal", "sodium_mg"}
    assert any(x["food_group_code"] == "rau_la" and x["level"] == "vua" for x in body["qty_levels"])
    etag = r.headers["ETag"]
    assert etag == f'"{body["data_version"]}"'
    again = kb_client.get(f"{API}/reference", headers={"If-None-Match": etag})
    assert again.status_code == 304 and again.headers["ETag"] == etag
    assert kb_client.get(f"{API}/reference", headers={"If-None-Match": '"other"'}).status_code == 200


def test_catalog_endpoints_need_a_session(kb_client: TestClient) -> None:
    for path in ("/recipes", f"/recipes/{uuid.uuid4()}", "/ingredients", "/catalog/snapshot"):
        assert kb_client.get(f"{API}{path}").status_code == 401, path


def test_recipe_search_filters_and_pages(kb_client: TestClient) -> None:
    s = bearer(register(kb_client))
    r = kb_client.get(f"{API}/recipes", params={"q": "dau dua"}, headers=s)  # no diacritics
    assert r.status_code == 200
    assert "Đậu đũa xào tỏi" in [x["name_vi"] for x in r.json()["items"]]
    canh = kb_client.get(f"{API}/recipes", params={"slot": "canh", "limit": 100}, headers=s).json()["items"]
    assert canh and all(x["slot"] == "canh" for x in canh)
    made = kb_client.get(f"{API}/recipes", params={"tag": "lam_san", "limit": 100}, headers=s).json()["items"]
    assert {x["name_vi"] for x in made} == {"Dưa cải muối", "Cà pháo muối", "Dưa giá", "Canh măng nấu chân giò"}
    seen, cursor = [], None
    while True:
        params = {"limit": 50} | ({"cursor": cursor} if cursor else {})
        page = kb_client.get(f"{API}/recipes", params=params, headers=s).json()
        seen += [x["id"] for x in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == len(set(seen)) == 171  # published only, no duplicates across pages
    x = page["items"][0]
    assert x["total_minutes"] > 0 and x["kcal_per_serving"] > 0
    bad = kb_client.get(f"{API}/recipes", params={"cursor": "%%%"}, headers=s)
    assert (bad.status_code, bad.json()["code"]) == (400, "validation_error")


def test_recipe_detail(kb_client: TestClient, kb_db) -> None:
    s = bearer(register(kb_client))
    rid = q(kb_db, "SELECT id FROM recipes WHERE name_vi = 'Dưa cải muối'").scalar()
    r = kb_client.get(f"{API}/recipes/{rid}", headers=s)
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "published" and d["slot"] == "rau" and len(d["sources"]) >= 2
    assert [st["step_no"] for st in d["steps"]] == [1, 2, 3, 4, 5]
    assert d["make_ahead"] == {"item_ingredient_id": d["make_ahead"]["item_ingredient_id"], "item_name_vi": "dưa cải chua",
                               "through_step_no": 5, "whole_dish": True}  # fmt: skip
    assert "lam_san" in d["tag_codes"]
    salt = next(i for i in d["ingredients"] if i["name_vi"] == "muối")
    assert salt["is_staple"] is True and salt["allergen_codes"] == []
    assert {n["nutrient_code"] for n in d["nutrition"]} >= {"energy_kcal", "protein_g", "lipid_g", "glucid_g"}
    assert d["nutrition_data_version"]
    draft = q(kb_db, "SELECT id FROM recipes WHERE status = 'draft' LIMIT 1").scalar()
    assert kb_client.get(f"{API}/recipes/{draft}", headers=s).status_code == 404
    assert kb_client.get(f"{API}/recipes/{uuid.uuid4()}", headers=s).status_code == 404


def test_ingredient_search_by_name_or_synonym(kb_client: TestClient) -> None:
    s = bearer(register(kb_client))
    r = kb_client.get(f"{API}/ingredients", params={"q": "hanh hoa"}, headers=s)  # synonym of hành lá, no diacritics
    names = [x["name_vi"] for x in r.json()["items"]]
    assert "hành lá" in names
    egg = next(x for x in kb_client.get(f"{API}/ingredients", params={"q": "trứng gà"}, headers=s).json()["items"]
               if x["name_vi"] == "trứng gà")  # fmt: skip
    assert egg["countable"] is True and egg["units"] and egg["allergen_codes"] == ["trung"]
    fish = kb_client.get(f"{API}/ingredients", params={"food_group_code": "ca", "limit": 100}, headers=s).json()
    assert fish["items"] and all(x["food_group_code"] == "ca" for x in fish["items"])
    first = kb_client.get(f"{API}/ingredients", params={"limit": 100}, headers=s).json()
    rest = kb_client.get(f"{API}/ingredients", params={"limit": 100, "cursor": first["next_cursor"]}, headers=s).json()
    ids = [x["id"] for x in first["items"] + rest["items"]]
    assert len(ids) == len(set(ids))


def test_snapshot_has_the_whole_catalog_and_an_etag(kb_client: TestClient) -> None:
    s = bearer(register(kb_client))
    r = kb_client.get(f"{API}/catalog/snapshot", headers=s)
    assert r.status_code == 200
    snap = r.json()
    assert len(snap["recipes"]) == 171 and len(snap["ingredients"]) == 225
    assert all(x["status"] == "published" for x in snap["recipes"])
    assert r.headers["ETag"] == f'"{snap["data_version"]}"'
    assert kb_client.get(f"{API}/catalog/snapshot", headers=s | {"If-None-Match": r.headers["ETag"]}).status_code == 304
