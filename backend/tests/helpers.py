from __future__ import annotations

import uuid
from typing import Any

from fastapi.testclient import TestClient

PASSWORD = "dung-mat-khau-10"


def register(client: TestClient, email: str | None = None, password: str = PASSWORD) -> dict[str, Any]:
    email = email or f"u{uuid.uuid4().hex[:8]}@example.vn"
    r = client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert r.status_code == 201, r.text
    body = r.json()
    body["password"] = password
    return body


def login(client: TestClient, email: str, password: str = PASSWORD) -> dict[str, Any]:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def bearer(session: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {session['access_token']}"}
