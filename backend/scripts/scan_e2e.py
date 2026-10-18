"""End-to-end check and server-side latency of scans on a running deployment (public URL or 127.0.0.1:6880).

    uv run --package tastoria-backend python backend/scripts/scan_e2e.py https://safework.ctslab.net \
        --images data/processed/cv/yolo/images/test --runs 30 --out data/processed/cv/detector/scan_latency_live.json

Creates a fresh account (e2e+<time>@example.com), sends one real photo per scan (sequential, one user), waits with
GET /scans/{id}?wait=10 and reads the server timestamps of each scan:
  queue→done   = finished_at − enqueued_at   (NFR-PERF-01 "enqueue → done")
  create→done  = finished_at − created_at    (includes the after-commit enqueue)
  run          = finished_at − started_at    (worker: claim, read photo, detect, write chips)
The first scan is confirmed into the pantry (levels chosen for uncounted chips) and the pantry is read back; the
others are discarded. Client round trips over the network are reported separately (they include Cloudflare).
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import time
import uuid
from datetime import datetime
from pathlib import Path

import httpx


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _pct(v: list[float], p: float) -> float:
    v = sorted(v)
    k = (len(v) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("--images", required=True)
    ap.add_argument("--runs", type=int, default=30)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    api = a.base.rstrip("/") + "/api/v1"
    files = sorted(Path(a.images).glob("*.jpg"))
    rng = random.Random(a.seed)
    picks = rng.sample(files, min(a.runs, len(files)))
    c = httpx.Client(timeout=30)
    email = f"e2e+{int(time.time())}@example.com"
    r = c.post(f"{api}/auth/register", json={"email": email, "password": "e2e-mat-khau-dai-123"})
    r.raise_for_status()
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    rows, first = [], None
    for i, p in enumerate(picks):
        t0 = time.perf_counter()
        r = c.post(f"{api}/scans", data={"mode": "haul" if i == 0 else "fridge"},
                   files=[("images", (p.name, p.read_bytes(), "image/jpeg"))],
                   headers=h | {"Idempotency-Key": uuid.uuid4().hex})  # fmt: skip
        assert r.status_code == 202, r.text
        t_upload = time.perf_counter() - t0
        sid = r.json()["id"]
        while True:
            g = c.get(f"{api}/scans/{sid}", params={"wait": 10}, headers=h)
            g.raise_for_status()
            s = g.json()
            if s["status"] not in ("queued", "processing"):
                break
        t_total = time.perf_counter() - t0
        assert s["status"] == "done", s
        rows.append({
            "image": p.name,
            "bytes": p.stat().st_size,
            "width": s["images"][0]["width"],
            "height": s["images"][0]["height"],
            "chips": len(s["items"]),
            "boxes": sum(len(it["detections"]) for it in s["items"]),
            "queue_to_done_ms": (_ts(s["finished_at"]) - _ts(s["enqueued_at"])).total_seconds() * 1e3,
            "create_to_done_ms": (_ts(s["finished_at"]) - _ts(s["created_at"])).total_seconds() * 1e3,
            "run_ms": (_ts(s["finished_at"]) - _ts(s["started_at"])).total_seconds() * 1e3,
            "client_upload_ms": t_upload * 1e3,
            "client_total_ms": t_total * 1e3,
        })  # fmt: skip
        if first is None:
            first = s
        else:
            c.post(f"{api}/scans/{sid}/discard", headers=h).raise_for_status()

    # confirm the first scan into the pantry
    assert first is not None
    for it in first["items"]:
        if it["final_count"] is None:
            r = c.patch(f"{api}/scans/{first['id']}/items/{it['id']}", json={"qty_level": "vua"},
                        headers=h | {"Content-Type": "application/merge-patch+json"})  # fmt: skip
            r.raise_for_status()
    conf = c.post(f"{api}/scans/{first['id']}/confirm", headers=h)
    conf.raise_for_status()
    again = c.post(f"{api}/scans/{first['id']}/confirm", headers=h)
    lots = c.get(f"{api}/pantry/lots", headers=h).json()["items"]

    def summary(k: str) -> dict[str, float]:
        v = [r[k] for r in rows]
        return {"p50": round(_pct(v, 50), 1), "p95": round(_pct(v, 95), 1), "max": round(max(v), 1),
                "mean": round(statistics.mean(v), 1)}  # fmt: skip

    out = {
        "base": a.base,
        "account": email,
        "runs": len(rows),
        "concurrency": 1,
        "measured_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "server": {k: summary(k) for k in ("queue_to_done_ms", "create_to_done_ms", "run_ms")},
        "client": {k: summary(k) for k in ("client_upload_ms", "client_total_ms")},
        "first_scan": {
            "id": first["id"],
            "image": rows[0]["image"],
            "detector_version_id": first["detector_version_id"],
            "chips": [(it["ingredient_name_vi"], it["model_count"], len(it["detections"])) for it in first["items"]],
            "confirm": conf.json(),
            "confirm_again_same": again.json() == conf.json(),
            "pantry": [(lt["ingredient_name_vi"], lt["initial_g_min"], lt["initial_g_max"], lt["acquired_basis"])
                       for lt in lots],  # fmt: skip
        },
        "rows": rows,
    }
    text = json.dumps(out, ensure_ascii=False, indent=2)
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("runs", "server", "client")}, indent=2))
    print(json.dumps(out["first_scan"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
