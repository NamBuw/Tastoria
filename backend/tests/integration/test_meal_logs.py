"""M4-3 P0-6: /meal-logs CRUD, timezone-aware dates, server nutrition derivation, journal rollups, and DSR export."""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from kb_helpers import API, accept, cook, ingredient_id, key, plan, q, recipe_id, stock_for, user

MAN, RAU, CANH = "Ba chỉ chiên nước mắm", "Bí ngòi xào tỏi", "Canh rau ngót thịt băm"


def test_meal_logs_crud_tz_derivation_idempotency_and_pagination(kb_client: TestClient, kb_db) -> None:
    h = user(kb_client, tz="America/New_York")
    h_other = user(kb_client, tz="Asia/Ho_Chi_Minh")
    rid = recipe_id(kb_db, MAN)
    ing = ingredient_id(kb_db, "thịt ba chỉ")

    # 1. Naive logged_at -> 422 timezone_required
    naive_res = kb_client.post(
        f"{API}/meal-logs",
        json={
            "logged_at": "2026-11-24T01:00:00",
            "meal_slot": "toi",
            "title": "Bữa tối",
            "source_type": "manual",
            "kcal": 300,
        },
        headers=h,
    )
    assert naive_res.status_code == 422 and naive_res.json()["errors"][0]["code"] == "timezone_required"

    # 2. Timezone-aware logged_date from user_settings.timezone: 01:00Z = 20:00 previous evening in America/New_York
    past_midnight_utc = (datetime.now(UTC) - timedelta(days=1)).replace(hour=1, minute=0, second=0, microsecond=0)
    expected_ny_date = past_midnight_utc.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    idem_k = key()
    create_payload = {
        "logged_at": past_midnight_utc.isoformat(),
        "meal_slot": "trua",
        "title": "Phở bò",
        "source_type": "calorie_scan",  # normalizes to scan_calorie
        "source_ref_id": "scan-123",
        "portion_label": "Tô lớn",
        "portion_scale": 1.25,
        "kcal": 620,
        "kcal_low": 540,
        "kcal_high": 700,
        "protein_g": 28,
        "carbs_g": 75,
        "fat_g": 18,
        "fiber_g": 3.5,
        "notes": "Ít hành",
    }
    r1 = kb_client.post(f"{API}/meal-logs", json=create_payload, headers=h | idem_k)
    assert r1.status_code == 201, r1.text
    log1 = r1.json()
    assert r1.headers["Location"] == f"/api/v1/meal-logs/{log1['id']}"
    assert log1["source_type"] == "scan_calorie"
    assert log1["logged_date"] == expected_ny_date
    assert len(log1["items"]) == 1 and log1["items"][0]["item_kind"] == "dish"

    # Idempotency replay preserves 201 + Location; mutated payload rejects 422 idempotency_key_reused
    replay = kb_client.post(f"{API}/meal-logs", json=create_payload, headers=h | idem_k)
    assert replay.status_code == 201 and replay.headers.get("Idempotent-Replayed") == "true"
    assert replay.headers["Location"] == f"/api/v1/meal-logs/{log1['id']}"
    assert replay.json()["id"] == log1["id"]
    mismatch = kb_client.post(f"{API}/meal-logs", json=create_payload | {"kcal": 650}, headers=h | idem_k)
    assert (mismatch.status_code, mismatch.json()["code"]) == (422, "idempotency_key_reused")

    # 3. Server-derived nutrition from catalog recipe_id + ingredient_id (grams)
    r2 = kb_client.post(
        f"{API}/meal-logs",
        json={
            "meal_slot": "toi",
            "title": "Mâm từ công thức",
            "source_type": "recipe",
            "portion_scale": 1.5,
            "items": [
                {"item_kind": "dish", "recipe_id": rid},
                {"item_kind": "manual_item", "ingredient_id": ing, "grams": 100},
            ],
        },
        headers=h,
    )
    assert r2.status_code == 201, r2.text
    log2 = r2.json()
    assert log2["kcal"] > 0 and log2["protein_g"] > 0
    assert log2["items"][0]["label_vi"] == MAN and log2["items"][0]["kcal"] > 0
    assert log2["items"][1]["label_vi"] == "thịt ba chỉ" and log2["items"][1]["kcal"] > 0

    # Unknown recipe / ingredient -> 422
    bad_rec = kb_client.post(
        f"{API}/meal-logs",
        json={
            "meal_slot": "phu",
            "title": "Món lạ",
            "source_type": "manual",
            "items": [{"item_kind": "dish", "recipe_id": str(uuid.uuid4())}],
        },
        headers=h,
    )
    assert bad_rec.status_code == 422

    # 4. Barcode log + extra manual logs for keyset pagination & filters
    extra_ids = []
    for idx in range(3):
        res = kb_client.post(
            f"{API}/meal-logs",
            json={
                "meal_slot": "sang",
                "title": f"Bữa sáng {idx}",
                "source_type": "barcode",
                "source_ref_id": f"89345631381{idx}",
                "kcal": 210 + idx * 10,
                "protein_g": 8,
                "carbs_g": 30,
                "fat_g": 6,
                "fiber_g": 2,
            },
            headers=h,
        )
        assert res.status_code == 201
        extra_ids.append(res.json()["id"])

    # Pagination: limit=2 across 5 logs
    seen: list[str] = []
    cursor: str | None = None
    while True:
        params = {"limit": 2} | ({"cursor": cursor} if cursor else {})
        pg = kb_client.get(f"{API}/meal-logs", params=params, headers=h)
        assert pg.status_code == 200
        body = pg.json()
        seen.extend(x["id"] for x in body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == 5 and len(set(seen)) == 5

    # Filters: meal_slot + date range + invalid cursor
    sang = kb_client.get(f"{API}/meal-logs", params={"meal_slot": "sang"}, headers=h).json()
    assert [x["id"] for x in sang["items"]] == extra_ids[::-1]
    assert kb_client.get(f"{API}/meal-logs", params={"cursor": "bad-cursor"}, headers=h).status_code == 400

    # 5. BOLA protection & DELETE cascade
    assert kb_client.get(f"{API}/meal-logs/{log1['id']}", headers=h_other).status_code == 404
    assert kb_client.delete(f"{API}/meal-logs/{log1['id']}", headers=h_other).status_code == 404
    assert kb_client.get(f"{API}/meal-logs/{log1['id']}", headers=h).json()["id"] == log1["id"]
    del_resp = kb_client.delete(f"{API}/meal-logs/{log1['id']}", headers=h)
    assert del_resp.status_code == 204
    assert kb_client.get(f"{API}/meal-logs/{log1['id']}", headers=h).status_code == 404
    assert q(kb_db, "SELECT count(*) FROM meal_log_items WHERE meal_log_id = :i", i=log1["id"]).scalar() == 0


def test_meal_logs_rate_limit(kb_client: TestClient) -> None:
    h = user(kb_client)
    body = {"meal_slot": "phu", "title": "Sữa chua", "source_type": "manual", "kcal": 110}
    for _ in range(60):
        assert kb_client.post(f"{API}/meal-logs", json=body, headers=h).status_code == 201
    limited = kb_client.post(f"{API}/meal-logs", json=body, headers=h)
    assert (limited.status_code, limited.json()["code"]) == (429, "rate_limited")


def test_meal_logs_integrate_into_journal_and_dsr_export(kb_client: TestClient, kb_db, kb_app) -> None:
    h = user(kb_client)
    tz = q(kb_db, "SELECT timezone FROM user_settings").scalar()
    stock_for(kb_client, h, kb_db, MAN, RAU, CANH)
    p = accept(kb_client, h, plan(kb_client, h)["id"])
    cs = cook(kb_client, h, p["id"])
    comp = kb_client.post(f"{API}/cook-sessions/{cs['id']}/complete", headers=h | key()).json()
    today_local = datetime.fromisoformat(comp["cook_session"]["completed_at"]).astimezone(ZoneInfo(tz)).date()

    log_resp = kb_client.post(
        f"{API}/meal-logs",
        json={
            "logged_date": today_local.isoformat(),
            "meal_slot": "sang",
            "title": "Xôi xéo",
            "source_type": "manual",
            "kcal": 400,
            "protein_g": 12,
            "carbs_g": 65,
            "fat_g": 10,
            "fiber_g": 3,
        },
        headers=h,
    )
    assert log_resp.status_code == 201
    log_id = log_resp.json()["id"]

    y, w, _ = today_local.isocalendar()
    wk = kb_client.get(f"{API}/journal", params={"week": f"{y}-W{w:02d}"}, headers=h).json()
    day = next(d for d in wk["days"] if d["date"] == today_local.isoformat())
    assert day["cooked_trays"] == 1
    assert day["meal_logs_count"] == 1
    assert day["meal_logs_kcal"] == 400.0
    dishes_kcal = sum(i["kcal_per_person"] for i in p["items"])
    assert day["kcal_per_person"] == pytest.approx(dishes_kcal + 400.0, abs=0.5)
    assert [m["id"] for m in wk["meal_logs"]] == [log_id]
    assert wk["macros"]["protein_g"] >= 12.0
    # Other empty days still preserve None for kcal_per_person
    others = [d for d in wk["days"] if d["date"] != today_local.isoformat()]
    assert all(d["kcal_per_person"] is None and d["meal_logs_count"] == 0 for d in others)

    # DSR export includes meal_logs.json and meal_log_items.json + clean filename header
    dsr = kb_client.post(f"{API}/me/data-requests", json={"type": "export"}, headers=h)
    assert dsr.status_code == 202
    rid = dsr.json()["id"]
    dl = kb_client.get(f"{API}/me/data-requests/{rid}/download", headers=h)
    assert dl.status_code == 200
    assert dl.headers["content-disposition"] == f'attachment; filename="my-vi-du-lieu-{rid}.zip"'
    storage = Path(kb_app.state.settings.storage_dir)
    zf = zipfile.ZipFile(io.BytesIO((storage / f"exports/{rid}.zip").read_bytes()))
    names = set(zf.namelist())
    assert {"meal_logs.json", "meal_log_items.json"} <= names
    exported_logs = json.loads(zf.read("meal_logs.json"))
    exported_items = json.loads(zf.read("meal_log_items.json"))
    assert len(exported_logs) == 1 and exported_logs[0]["id"] == log_id
    assert len(exported_items) == 1 and exported_items[0]["meal_log_id"] == log_id
    readme = json.loads(zf.read("README.json"))
    blob = json.dumps(readme, ensure_ascii=False).lower()
    assert "ứng dụng" not in blob and "tastoria" not in blob

    # Deleting the meal log removes it from the journal summary
    assert kb_client.delete(f"{API}/meal-logs/{log_id}", headers=h).status_code == 204
    wk_after = kb_client.get(f"{API}/journal", params={"week": f"{y}-W{w:02d}"}, headers=h).json()
    assert wk_after["meal_logs"] == []
    day_after = next(d for d in wk_after["days"] if d["date"] == today_local.isoformat())
    assert day_after["meal_logs_count"] == 0 and day_after["meal_logs_kcal"] == 0.0
