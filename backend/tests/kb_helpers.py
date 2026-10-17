"""Helpers for tests on the imported catalog (kb_client / kb_db fixtures): consents, stocking the pantry, plans."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from helpers import bearer, register
from sqlalchemy import text

API = "/api/v1"


def q(conn, sql: str, **params: object):
    return conn.execute(text(sql), params)


def morning_tz() -> str:
    """A fixed-offset zone where it is 08:00–10:59 now, so plans stay open whatever time the suite runs
    (a dinner plan made at 23:55 in Hà Nội would expire during the test)."""
    hour = datetime.now(UTC).hour
    for off in range(-12, 15):
        if 8 <= (hour + off) % 24 <= 10:
            return f"Etc/GMT{-off:+d}" if off else "Etc/GMT"
    raise AssertionError("unreachable")


def user(client: TestClient, *purposes: str, tz: str | None = None) -> dict[str, str]:
    h = bearer(register(client))
    for p in purposes:
        grant(client, h, p)
    r = client.put(f"{API}/me/settings", json={"timezone": tz or morning_tz()}, headers=h)
    assert r.status_code == 200, r.text
    return h


def grant(client: TestClient, h: dict[str, str], purpose: str) -> None:
    pv = client.get(f"{API}/policies/{purpose}/current").json()["id"]
    body = {"channel": "settings", "decisions": [{"policy_version_id": pv, "action": "grant"}]}
    r = client.post(f"{API}/me/consents", json=body, headers=h)
    assert r.status_code == 200, r.text


def ingredient_id(db, name: str) -> str:
    return str(q(db, "SELECT id FROM ingredients WHERE name_vi = :n AND is_active", n=name).scalar())


def recipe_id(db, name: str) -> str:
    return str(q(db, "SELECT id FROM recipes WHERE name_vi = :n AND status = 'published'", n=name).scalar())


def stock_needs(db, recipe: str) -> list[tuple[str, float, int]]:
    """(ingredient name, grams, servings) of the stock-checked lines (no staples, no optional lines)."""
    return [
        (r.name_vi, float(r.grams), r.servings)
        for r in q(
            db,
            "SELECT i.name_vi, ri.grams, r.servings FROM recipe_ingredients ri JOIN recipes r ON r.id = ri.recipe_id "
            "JOIN ingredients i ON i.id = ri.ingredient_id WHERE r.name_vi = :n AND r.status = 'published' "
            "AND NOT i.is_staple AND NOT ri.is_optional",
            n=recipe,
        )
    ]


def add_lot(client: TestClient, h: dict, db, name: str, grams: float, *, days_ago: float | None = None) -> dict:
    body: dict[str, Any] = {"ingredient_id": ingredient_id(db, name), "quantity": {"g_min": grams, "g_max": grams}}
    if days_ago is not None:
        body["acquired_at"] = (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()
    r = client.post(f"{API}/pantry/lots", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def stock_for(client: TestClient, h: dict, db, *recipes: str, factor: float = 3.0) -> dict[str, float]:
    """Lots covering `factor` × the recipes' stock-checked needs (one lot per ingredient)."""
    total: dict[str, float] = {}
    for r in recipes:
        for name, grams, _ in stock_needs(db, r):
            total[name] = total.get(name, 0.0) + grams * factor
    for name, g in total.items():
        add_lot(client, h, db, name, round(g, 1))
    return total


def key() -> dict[str, str]:
    return {"Idempotency-Key": uuid.uuid4().hex}


def plan(client: TestClient, h: dict, *, expect: int = 201, **body: Any) -> dict:
    payload = {"meal": "dinner", "max_minutes": 120} | body
    r = client.post(f"{API}/meal-plans", json=payload, headers=h | key())
    assert r.status_code == expect, r.text
    return r.json()


def accept(client: TestClient, h: dict, plan_id: str) -> dict:
    r = client.post(f"{API}/meal-plans/{plan_id}/accept", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def cook(client: TestClient, h: dict, plan_id: str, **body: Any) -> dict:
    payload = {"meal_plan_id": plan_id, "serve_at": (datetime.now(UTC) + timedelta(hours=3)).isoformat()} | body
    r = client.post(f"{API}/cook-sessions", json=payload, headers=h | key())
    assert r.status_code == 201, r.text
    return r.json()


def active_names(p: dict) -> dict[str, str]:
    return {i["slot"]: i["recipe_name_vi"] for i in p["items"] if i["status"] == "active"}
