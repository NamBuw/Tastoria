"""NFR-PERF-02 smoke check: POST /meal-plans with the 171-recipe catalog and a 30-lot pantry."""

from __future__ import annotations

import statistics
import time

from fastapi.testclient import TestClient
from kb_helpers import API, add_lot, key, q, user


def test_meal_plan_latency_with_30_lots(kb_client: TestClient, kb_db) -> None:
    h = user(kb_client)
    names = [r.name_vi for r in q(kb_db, "SELECT name_vi FROM ingredients WHERE NOT is_staple AND is_active "
                                         "AND food_group_code NOT IN ('gia_vi', 'gia_vi_dong_vat') ORDER BY name_vi")]  # fmt: skip
    for n in names[:: max(1, len(names) // 30)][:30]:
        add_lot(kb_client, h, kb_db, n, 800)
    for n in ("thịt ba chỉ", "tỏi", "bí ngòi", "rau ngót", "thịt băm", "hành tím"):
        add_lot(kb_client, h, kb_db, n, 800)
    times = []
    for _ in range(8):
        t = time.perf_counter()
        r = kb_client.post(f"{API}/meal-plans", json={"meal": "dinner", "max_minutes": 90}, headers=h | key())
        times.append(time.perf_counter() - t)
        assert r.status_code == 201, r.text
    times.sort()
    print(f"POST /meal-plans: median {statistics.median(times):.3f}s, max {times[-1]:.3f}s")
    assert statistics.median(times) < 1.0  # NFR-PERF-02 target is p95 ≤ 1 s on the deployment machine
