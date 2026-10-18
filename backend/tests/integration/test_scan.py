"""UC12 / UC13: POST /scans (upload checks, Idempotency-Key, 202), the inference job (claim, BR-SCAN-01 chips,
retries, RQ timeout), long-poll, chips, confirm (BR-SCAN-02, BR-PANTRY-03), discard, BOLA, sweeper, photo purge.

A scripted detector stands in for the ONNX model here, so counts are exact; test_scan_real_model.py runs the real
detector end to end. The scan module, the database, Valkey and RQ are real.
"""

from __future__ import annotations

import hashlib
import io
import threading
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from kb_helpers import API, grant, ingredient_id, key, q, user
from PIL import Image
from rq import SimpleWorker

from tastoria.modules.scan import queue as scan_queue
from tastoria.modules.scan import worker as job
from tastoria.modules.scan.detector import Box

CLASSES = ["trung", "ca_chua", "rau_muong", "thit_lon"]  # fake detector output index -> vision class code
EGG, TOMATO, SPINACH, PORK = range(4)


def jpeg(w: int = 320, h: int = 240, color=(120, 80, 40), exif: bytes | None = None) -> bytes:  # noqa: ANN001
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "JPEG", quality=85, **({"exif": exif} if exif else {}))
    return buf.getvalue()


def gps_exif() -> bytes:
    ex = Image.Exif()
    ex[0x0112] = 6
    ex[0x8825] = {1: "N", 2: (21.0, 1.0, 30.0), 3: "E", 4: (105.0, 51.0, 0.0)}
    return ex.tobytes()


def box(cls: int, i: int = 0, conf: float = 0.8) -> Box:
    x = 0.02 + 0.05 * i
    return Box(cls, conf, x, 0.1, x + 0.04, 0.2)


class ScriptedDetector:
    """detect() returns the next scripted list of boxes (one list per photo, in order); `fail`/`sleep` simulate
    a broken or hanging model."""

    def __init__(self) -> None:
        self.script: list[list[Box]] = []
        self.calls = 0
        self.fail = False
        self.sleep = 0.0
        self.conf, self.iou = 0.18, 0.7

    def detect(self, img: Image.Image) -> list[Box]:
        self.calls += 1
        if self.sleep:
            time.sleep(self.sleep)
        if self.fail:
            raise RuntimeError("model exploded")
        return self.script.pop(0) if self.script else []


@pytest.fixture(scope="session")
def fake_model(kb_engine, storage_dir: Path) -> dict:
    """A deployed detector version whose artifact is a placeholder file (the worker gets ScriptedDetector)."""
    from tastoria.modules.mlops import service as mlops

    key_ = "models/detector/scripted-1/scripted.bin"
    path = storage_dir / key_
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"scripted detector for tests")
    sha = hashlib.sha256(path.read_bytes()).digest()
    with kb_engine.begin() as c:
        ids = {code: vid for vid, code in c.exec_driver_sql("SELECT id, code FROM vision_classes")}
        vid = c.exec_driver_sql(
            "INSERT INTO model_versions (name, version, artifact_key, sha256, preprocess_version, metrics, status) "
            "VALUES ('detector', 'scripted-1', %s, %s, 'none', '{\"serving\": {\"conf\": 0.18, \"iou\": 0.7}}', "
            "'validated') RETURNING id",
            (key_, sha),
        ).scalar()
        for i, code in enumerate(CLASSES):
            c.exec_driver_sql(
                "INSERT INTO model_version_classes (model_version_id, class_index, vision_class_id) VALUES (%s, %s, %s)",
                (vid, i, ids[code]),
            )
        c.exec_driver_sql(
            "INSERT INTO model_deployments (name, active_version_id, switched_at) VALUES ('detector', %s, now())", (vid,)
        )
    with kb_engine.connect() as c:
        from sqlalchemy.orm import Session

        with Session(bind=c) as s:
            view = mlops.active_version(s, "detector")
    return {"version_id": vid, "view": view}


@pytest.fixture
def deployed(kb_engine, fake_model) -> dict:
    """kb_clean's TRUNCATE users … CASCADE also empties model_deployments (FK switched_by): put the pointer back."""
    with kb_engine.begin() as c:
        c.exec_driver_sql(
            "INSERT INTO model_deployments (name, active_version_id, switched_at) VALUES ('detector', %s, now()) "
            "ON CONFLICT (name) DO UPDATE SET active_version_id = EXCLUDED.active_version_id, previous_version_id = NULL",
            (fake_model["version_id"],),
        )
    return fake_model


@pytest.fixture
def detector() -> ScriptedDetector:
    return ScriptedDetector()


@pytest.fixture
def ctx(kb_app, deployed, detector: ScriptedDetector, storage_dir: Path):
    c = job.WorkerContext(
        kb_app.state.sessionmaker, storage_dir, kb_app.state.scan.queue, detector, deployed["view"], None  # type: ignore[arg-type]
    )
    job.install(c)
    yield c
    job.install(None)


@pytest.fixture
def h(kb_client: TestClient, deployed) -> dict[str, str]:
    return user(kb_client)


def post_scan(client: TestClient, h: dict, photos: list[bytes] | None = None, *, mode: str = "fridge",
              k: dict | None = None, **form) -> object:  # fmt: skip
    photos = photos if photos is not None else [jpeg()]
    files = [("images", (f"anh-{i}.jpg", p, "image/jpeg")) for i, p in enumerate(photos)]
    data: dict = {"mode": mode, **form}
    return client.post(f"{API}/scans", data=data, files=files, headers=h | (k or key()))


def scan_done(client: TestClient, h: dict, ctx, script: list[list[Box]], photos: list[bytes] | None = None,  # noqa: ANN001
              **kw) -> dict:  # fmt: skip
    ctx.detector.script = list(script)
    r = post_scan(client, h, photos or [jpeg() for _ in script], **kw)
    assert r.status_code == 202, r.text
    sid = r.json()["id"]
    assert job.run_job(ctx, uuid.UUID(sid)) == "done"
    g = client.get(f"{API}/scans/{sid}", headers=h)
    assert g.status_code == 200 and g.json()["status"] == "done", g.text
    return g.json()


def chip(scan: dict, name: str) -> dict:
    return next(i for i in scan["items"] if i["ingredient_name_vi"] == name)


# ---------------------------------------------------------------- UC12: upload


def test_post_scan_202_with_location_and_stored_sanitised_photo(kb_client, kb_db, h, storage_dir: Path) -> None:
    r = post_scan(kb_client, h, [jpeg(64, 48, exif=gps_exif())], mode="haul")
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "queued" and set(body) == {"id", "status", "created_at"}
    assert r.headers["location"] == f"/api/v1/scans/{body['id']}"
    assert r.headers["retry-after"] == "1"
    row = q(kb_db, "SELECT mode, status, attempts, enqueued_at FROM scans WHERE id = :i", i=body["id"]).one()
    assert (row.mode, row.status, row.attempts) == ("haul", "queued", 0)
    assert row.enqueued_at is not None  # FR-12-08: enqueued after COMMIT
    im = q(kb_db, "SELECT storage_key, width, height, contributed, shelf_group FROM scan_images WHERE scan_id = :i",
           i=body["id"]).one()  # fmt: skip
    assert (im.width, im.height, im.contributed, im.shelf_group) == (48, 64, False, 1)  # rotated by EXIF (FR-12-05)
    assert im.storage_key.startswith("tmp/scans/")
    stored = (storage_dir / im.storage_key).read_bytes()
    assert b"Exif" not in stored and b"\xff\xe1" not in stored
    with Image.open(io.BytesIO(stored)) as pic:
        assert not pic.getexif()
    # the RQ job is on the queue
    assert kb_client.app.state.scan.queue.length() >= 1


@pytest.mark.parametrize(
    ("photos", "form", "status", "code"),
    [
        ([b"%PDF-1.7 fake jpg\n%%EOF"], {}, 415, "unsupported_media_type"),
        ([jpeg() + b"\0" * (3 * 1024 * 1024)], {}, 413, "image_too_large"),
        ([jpeg(4097, 4096, color=(0, 0, 0))], {}, 422, "image_too_many_pixels"),
        ([jpeg(), jpeg(), jpeg()], {}, 422, "validation_error"),
        ([jpeg()], {"mode": "freezer"}, 422, "validation_error"),
        ([jpeg(), jpeg()], {"shelf_groups": ["1", "3"]}, 422, "validation_error"),
    ],
)
def test_upload_rejections_create_nothing(kb_client, kb_db, h, photos, form, status, code) -> None:  # noqa: ANN001
    r = post_scan(kb_client, h, photos, **form)
    assert r.status_code == status, r.text
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["code"] == code
    assert q(kb_db, "SELECT count(*) FROM scans").scalar() == 0
    assert q(kb_db, "SELECT count(*) FROM idempotency_keys").scalar() == 0


def test_idempotency_key_required_replayed_and_reused(kb_client, kb_db, h) -> None:
    photo = jpeg()
    r = kb_client.post(f"{API}/scans", data={"mode": "fridge"}, files=[("images", ("a.jpg", photo, "image/jpeg"))],
                       headers=h)  # fmt: skip
    assert r.status_code == 400 and r.json()["code"] == "idempotency_key_required"
    k = key()
    first = post_scan(kb_client, h, [photo], k=k)
    again = post_scan(kb_client, h, [photo], k=k)  # another multipart boundary, same logical request
    assert first.status_code == again.status_code == 202
    assert again.json() == first.json() and again.headers["idempotent-replayed"] == "true"
    assert again.headers["location"] == first.headers["location"]
    other = post_scan(kb_client, h, [jpeg(color=(1, 2, 3))], k=k)
    assert other.status_code == 422 and other.json()["code"] == "idempotency_key_reused"
    assert q(kb_db, "SELECT count(*) FROM scans").scalar() == 1


def test_no_deployed_detector_is_503(kb_client, kb_db, h, fake_model) -> None:
    q(kb_db, "DELETE FROM model_deployments WHERE name = 'detector'")
    try:
        r = post_scan(kb_client, h)
        assert r.status_code == 503 and r.json()["code"] == "model_unavailable" and "retry-after" in r.headers
    finally:
        q(kb_db, "INSERT INTO model_deployments (name, active_version_id, switched_at) VALUES ('detector', :v, now())",
          v=fake_model["version_id"])  # fmt: skip
    assert q(kb_db, "SELECT count(*) FROM scans").scalar() == 0


def test_contribution_needs_consent(kb_client, kb_db, h) -> None:
    r = post_scan(kb_client, h, contribute="true")
    assert r.status_code == 403 and r.json()["code"] == "consent_required"
    grant(kb_client, h, "photo_contribution")
    r = post_scan(kb_client, h)  # consent given and no opt-out: contributed (FR-12-17)
    assert r.status_code == 202
    im = q(kb_db, "SELECT contributed, storage_key FROM scan_images WHERE scan_id = :i", i=r.json()["id"]).one()
    assert im.contributed and im.storage_key.startswith("contrib/")
    r = post_scan(kb_client, h, contribute="false")
    assert q(kb_db, "SELECT contributed FROM scan_images WHERE scan_id = :i", i=r.json()["id"]).scalar() is False


# ---------------------------------------------------------------- the job


def test_same_shelf_max_other_shelf_sum_and_one_chip_per_ingredient(kb_client, kb_db, h, ctx) -> None:
    photo1 = [box(EGG, i) for i in range(4)] + [box(TOMATO, 9), box(SPINACH, 12, 0.6)]
    photo2 = [box(EGG, i) for i in range(3)] + [box(PORK, 10, 0.3)]
    s = scan_done(kb_client, h, ctx, [photo1, photo2])
    assert s["detector_version_id"] == str(ctx.detector_version.id) and s["preprocess_version"] == "none"
    assert s["attempts"] == 1 and s["classifier_version_id"] is None
    egg = chip(s, "trứng gà")
    assert egg["model_count"] == 4 and egg["final_count"] == 4 and egg["origin"] == "model"  # max (FR-12-13)
    assert len(egg["detections"]) == 7 and {d["image_ordinal"] for d in egg["detections"]} == {1, 2}
    spinach = chip(s, "rau muống")
    assert spinach["model_count"] is None and spinach["final_count"] is None and spinach["qty_level"] is None
    assert spinach["predicted_freshness"] is None and spinach["needs_check"] is False  # no freshness model
    assert all(d["p_tuoi"] is None for i in s["items"] for d in i["detections"])
    assert {i["ingredient_name_vi"] for i in s["items"]} == {"trứng gà", "cà chua", "rau muống", "thịt ba chỉ"}
    assert q(kb_db, "SELECT count(*) FROM detections").scalar() == 4 + 1 + 1 + 3 + 1

    s2 = scan_done(kb_client, h, ctx, [[box(EGG, i) for i in range(4)], [box(EGG, i) for i in range(3)]],
                   shelf_groups=["1", "2"])  # fmt: skip
    assert chip(s2, "trứng gà")["model_count"] == 7  # "ngăn khác" adds


def test_no_boxes_is_done_with_no_chips(kb_client, h, ctx) -> None:
    s = scan_done(kb_client, h, ctx, [[]])
    assert s["items"] == [] and s["status"] == "done"


def test_inference_error_retried_then_failed(kb_client, kb_db, h, ctx) -> None:  # FR-12-19
    ctx.detector.fail = True
    sid = uuid.UUID(post_scan(kb_client, h).json()["id"])
    assert job.run_job(ctx, sid) == "requeued"
    assert job.run_job(ctx, sid) == "requeued"
    assert job.run_job(ctx, sid) == "failed"
    assert job.run_job(ctx, sid) == "skipped"  # a late duplicate job does nothing
    row = q(kb_db, "SELECT status, attempts, error_code FROM scans WHERE id = :i", i=sid).one()
    assert (row.status, row.attempts) == ("failed", 3)
    assert row.error_code and row.error_code != "timeout"
    assert ctx.detector.calls == 3
    g = kb_client.get(f"{API}/scans/{sid}", headers=h).json()
    assert g["status"] == "failed" and g["items"] == [] and g["error_code"].startswith("inference_error")


def test_rq_worker_runs_the_job_and_times_out_hanging_runs(kb_client, kb_db, h, ctx, monkeypatch) -> None:
    queue = kb_client.app.state.scan.queue
    ctx.detector.script = [[box(EGG)]]
    sid = post_scan(kb_client, h).json()["id"]
    SimpleWorker([queue.queue], connection=queue.redis).work(burst=True)
    assert q(kb_db, "SELECT status FROM scans WHERE id = :i", i=sid).scalar() == "done"

    monkeypatch.setattr(scan_queue, "JOB_TIMEOUT_S", 1)  # FR-12-10 with a 1 s limit instead of 30 s
    ctx.detector.sleep = 2.5
    sid = post_scan(kb_client, h).json()["id"]
    t0 = time.monotonic()
    SimpleWorker([queue.queue], connection=queue.redis).work(burst=True)  # 3 attempts, each cut at 1 s
    assert time.monotonic() - t0 < 8
    row = q(kb_db, "SELECT status, attempts, error_code FROM scans WHERE id = :i", i=sid).one()
    assert (row.status, row.attempts, row.error_code) == ("failed", 3, "timeout")
    assert q(kb_db, "SELECT count(*) FROM scan_items WHERE scan_id = :i", i=sid).scalar() == 0


def test_long_poll_waits_then_wakes_on_done(kb_client, h, ctx) -> None:  # FR-12-09
    sid = post_scan(kb_client, h).json()["id"]
    t0 = time.monotonic()
    r = kb_client.get(f"{API}/scans/{sid}?wait=2", headers=h)
    assert 1.8 <= time.monotonic() - t0 < 3.5
    assert r.json()["status"] == "queued" and r.headers["retry-after"] == "1"

    ctx.detector.script = [[box(EGG)]]
    threading.Timer(0.5, lambda: job.run_job(ctx, uuid.UUID(sid))).start()
    t0 = time.monotonic()
    r = kb_client.get(f"{API}/scans/{sid}?wait=10", headers=h)
    assert time.monotonic() - t0 < 3
    assert r.json()["status"] == "done" and "retry-after" not in r.headers
    assert kb_client.get(f"{API}/scans/{sid}?wait=11", headers=h).status_code == 422


# ---------------------------------------------------------------- BOLA


def test_other_users_scan_is_404_everywhere(kb_client, h, ctx) -> None:  # FR-12-14
    s = scan_done(kb_client, h, ctx, [[box(EGG)]])
    other = user(kb_client)
    item = s["items"][0]["id"]
    sid = s["id"]
    for method, path, body in [
        ("GET", f"/scans/{sid}", None),
        ("GET", f"/scans/{sid}/images/1", None),
        ("POST", f"/scans/{sid}/items", {"ingredient_id": item}),
        ("PATCH", f"/scans/{sid}/items/{item}", {"final_count": 9}),
        ("DELETE", f"/scans/{sid}/items/{item}", None),
        ("POST", f"/scans/{sid}/confirm", None),
        ("POST", f"/scans/{sid}/discard", None),
    ]:
        r = kb_client.request(method, f"{API}{path}", json=body, headers=other)
        assert r.status_code == 404, (method, path, r.text)
        assert r.json()["code"] == "not_found" and "trứng" not in r.text
    assert chip(kb_client.get(f"{API}/scans/{sid}", headers=h).json(), "trứng gà")["final_count"] == 1


def test_image_is_served_through_x_accel_and_purged_after_30_days(kb_client, kb_db, h, ctx, storage_dir) -> None:
    s = scan_done(kb_client, h, ctx, [[]])
    r = kb_client.get(f"{API}/scans/{s['id']}/images/1", headers=h)
    key_ = q(kb_db, "SELECT storage_key FROM scan_images WHERE scan_id = :i", i=s["id"]).scalar()
    assert r.status_code == 200 and r.headers["x-accel-redirect"] == f"/_protected/{key_}"
    assert kb_client.get(f"{API}/scans/{s['id']}/images/2", headers=h).status_code == 404

    from tastoria.jobs.purge_images import purge

    grant(kb_client, h, "photo_contribution")
    kept = scan_done(kb_client, h, ctx, [[]])
    q(kb_db, "UPDATE scans SET created_at = now() - interval '31 days'")
    counts = purge(kb_client.app.state.sessionmaker, storage_dir)
    assert counts["images_purged"] == 1
    assert not (storage_dir / key_).exists()
    r = kb_client.get(f"{API}/scans/{s['id']}/images/1", headers=h)
    assert r.status_code == 410 and r.json()["code"] == "image_purged"
    assert kb_client.get(f"{API}/scans/{s['id']}", headers=h).json()["images"][0]["purged"] is True
    assert kb_client.get(f"{API}/scans/{kept['id']}/images/1", headers=h).status_code == 200  # contributed


# ---------------------------------------------------------------- UC13: chips


def test_edit_chips_never_touch_the_pantry(kb_client, kb_db, h, ctx) -> None:  # FR-13-03..08
    r = kb_client.post(f"{API}/pantry/lots", json={"ingredient_id": ingredient_id(kb_db, "cà rốt"),
                                                   "quantity": {"g_min": 300, "g_max": 300}}, headers=h)  # fmt: skip
    assert r.status_code == 201
    before = q(kb_db, "SELECT count(*), max(updated_at) FROM pantry_lots").one()
    s = scan_done(kb_client, h, ctx, [[box(EGG), box(EGG, 1), box(SPINACH, 3)]])
    sid, egg, spin = s["id"], chip(s, "trứng gà"), chip(s, "rau muống")
    url = f"{API}/scans/{sid}/items"
    mp = {"Content-Type": "application/merge-patch+json"}

    r = kb_client.patch(f"{url}/{egg['id']}", json={"final_count": 6}, headers=h | mp)
    assert r.status_code == 200, r.text
    assert (r.json()["final_count"], r.json()["model_count"], r.json()["user_action"]) == (6, 2, "edited")
    r = kb_client.patch(f"{url}/{egg['id']}", json={"qty_level": "vua"}, headers=h | mp)
    assert r.status_code == 422 and r.json()["code"] == "qty_kind_mismatch"
    r = kb_client.patch(f"{url}/{spin['id']}", json={"final_count": 2}, headers=h | mp)
    assert r.status_code == 422 and r.json()["code"] == "qty_kind_mismatch"
    r = kb_client.patch(f"{url}/{egg['id']}", json={"final_count": 100}, headers=h | mp)
    assert r.status_code == 422 and r.json()["code"] == "validation_error"
    duck = ingredient_id(kb_db, "trứng vịt")
    r = kb_client.patch(f"{url}/{egg['id']}", json={"ingredient_id": duck}, headers=h | mp)
    assert r.status_code == 200
    j = r.json()
    assert (j["ingredient_id"], j["original_ingredient_id"], j["user_action"]) == (duck, egg["ingredient_id"], "relabeled")
    r = kb_client.patch(f"{url}/{spin['id']}", json={"ingredient_id": str(uuid.uuid4())}, headers=h | mp)
    assert r.status_code == 422 and r.json()["code"] == "unknown_ingredient"

    onion = ingredient_id(kb_db, "hành lá")
    r = kb_client.post(url, json={"ingredient_id": onion, "qty_level": "it"}, headers=h)
    assert r.status_code == 201 and r.headers["location"].endswith(r.json()["id"])
    assert r.json()["origin"] == "user_added" and r.json()["model_count"] is None
    added = r.json()["id"]
    assert kb_client.post(url, json={"ingredient_id": onion}, headers=h).json()["code"] == "duplicate_item"
    r = kb_client.patch(f"{url}/{spin['id']}", json={"ingredient_id": duck}, headers=h | mp)
    assert r.status_code == 409 and r.json()["code"] == "duplicate_item"

    for _ in range(2):  # idempotent
        assert kb_client.delete(f"{url}/{spin['id']}", headers=h).status_code == 204
        assert kb_client.delete(f"{url}/{added}", headers=h).status_code == 204
    assert q(kb_db, "SELECT user_action FROM scan_items WHERE id = :i", i=spin["id"]).scalar() == "deleted"
    assert q(kb_db, "SELECT count(*) FROM scan_items WHERE id = :i", i=added).scalar() == 0
    names = [i["ingredient_name_vi"] for i in kb_client.get(f"{API}/scans/{sid}", headers=h).json()["items"]]
    assert names == ["trứng vịt"]
    assert q(kb_db, "SELECT count(*), max(updated_at) FROM pantry_lots").one() == before  # FR-13-08
    assert q(kb_db, "SELECT count(*) FROM pantry_transactions").scalar() == 0


# ---------------------------------------------------------------- UC13: confirm


def test_haul_confirm_creates_lots_and_is_idempotent(kb_client, kb_db, h, ctx) -> None:
    s = scan_done(kb_client, h, ctx, [[box(EGG, i) for i in range(4)] + [box(SPINACH, 9)]], mode="haul")
    assert "unseen_lots" not in s
    sid = s["id"]
    r = kb_client.post(f"{API}/scans/{sid}/confirm", headers=h)
    assert r.status_code == 422 and r.json()["code"] == "qty_level_required"
    assert r.json()["item_ids"] == [chip(s, "rau muống")["id"]]
    assert q(kb_db, "SELECT count(*) FROM pantry_lots").scalar() == 0
    kb_client.patch(f"{API}/scans/{sid}/items/{chip(s, 'rau muống')['id']}", json={"qty_level": "vua"},
                    headers=h | {"Content-Type": "application/merge-patch+json"})  # fmt: skip
    results = [kb_client.post(f"{API}/scans/{sid}/confirm", headers=h) for _ in range(3)]
    assert all(r.status_code == 200 for r in results), results[0].text
    assert results[0].json() == results[1].json() == results[2].json()  # FR-13-17
    res = results[0].json()
    assert res["status"] == "confirmed" and len(res["created_lot_ids"]) == 2 and res["not_seen_lot_ids"] == []
    lots = q(kb_db, "SELECT i.name_vi, l.initial_g_min, l.initial_g_max, l.acquired_basis, l.source_scan_item_id "
                    "FROM pantry_lots l JOIN ingredients i ON i.id = l.ingredient_id ORDER BY i.name_vi").all()  # fmt: skip
    assert len(lots) == 2
    egg = next(lt for lt in lots if lt.name_vi == "trứng gà")
    assert float(egg.initial_g_min) == float(egg.initial_g_max) == 200  # 4 × 50 g (FR-13-10)
    assert {lt.acquired_basis for lt in lots} == {"purchase_date_entered"}  # FR-13-13
    lvl = q(kb_db, "SELECT g_min, g_max FROM qty_levels WHERE food_group_code = 'rau_la' AND level = 'vua'").one()
    spin = next(lt for lt in lots if lt.name_vi == "rau muống")
    assert (float(spin.initial_g_min), float(spin.initial_g_max)) == (float(lvl.g_min), float(lvl.g_max))
    assert q(kb_db, "SELECT count(*) FROM pantry_transactions").scalar() == 0
    assert q(kb_db, "SELECT status, confirmed_at IS NOT NULL FROM scans WHERE id = :i", i=sid).one() == ("confirmed", True)
    # a confirmed scan is closed
    r = kb_client.patch(f"{API}/scans/{sid}/items/{chip(s, 'trứng gà')['id']}", json={"final_count": 1},
                        headers=h | {"Content-Type": "application/merge-patch+json"})  # fmt: skip
    assert r.status_code == 409 and r.json()["code"] == "scan_not_editable"
    r = kb_client.post(f"{API}/scans/{sid}/discard", headers=h)
    assert r.status_code == 409 and r.json()["code"] == "invalid_scan_state"
    lots = kb_client.get(f"{API}/pantry/lots", headers=h).json()["items"]
    assert {lt["ingredient_name_vi"] for lt in lots} == {"trứng gà", "rau muống"}


def test_fridge_confirm_updates_seen_lots_and_marks_unseen(kb_client, kb_db, h, ctx) -> None:  # BR-PANTRY-03
    def lot(name: str, grams: float) -> str:
        r = kb_client.post(f"{API}/pantry/lots", json={"ingredient_id": ingredient_id(kb_db, name),
                                                       "quantity": {"g_min": grams, "g_max": grams}}, headers=h)  # fmt: skip
        assert r.status_code == 201, r.text
        return r.json()["id"]

    tomato_lot, carrot_lot, salt_lot = lot("cà chua", 500), lot("cà rốt", 300), lot("muối", 200)
    s = scan_done(kb_client, h, ctx, [[box(TOMATO), box(EGG), box(EGG, 1)]])
    assert [u["lot_id"] for u in s["unseen_lots"]] == [carrot_lot]  # staples are not asked about (FR-12-18)
    res = kb_client.post(f"{API}/scans/{s['id']}/confirm", headers=h)
    assert res.status_code == 200, res.text
    res = res.json()
    assert res["not_seen_lot_ids"] == [carrot_lot]
    assert len(res["created_lot_ids"]) == 1  # eggs: new lot; tomatoes: the existing lot is updated (FR-13-15)
    rows = dict(q(kb_db, "SELECT id::text, status FROM pantry_lots").all())
    assert rows[tomato_lot] == "in_stock" and rows[carrot_lot] == "not_seen" and rows[salt_lot] == "in_stock"
    egg = q(kb_db, "SELECT acquired_basis, acquired_at FROM pantry_lots WHERE id = :i", i=res["created_lot_ids"][0]).one()
    created = q(kb_db, "SELECT created_at FROM scans WHERE id = :i", i=s["id"]).scalar()
    assert egg.acquired_basis == "first_seen" and egg.acquired_at == created  # FR-13-14
    assert q(kb_db, "SELECT count(*) FROM pantry_lots WHERE ingredient_id = :i",
             i=ingredient_id(kb_db, "cà chua")).scalar() == 1  # fmt: skip
    assert kb_client.post(f"{API}/scans/{s['id']}/confirm", headers=h).json() == res  # replay keeps not_seen ids

    # the next fridge scan sees the carrots again: not_seen -> in_stock, no new lot
    s2 = scan_done(kb_client, h, ctx, [[box(TOMATO), box(EGG)]])
    kb_client.patch(f"{API}/scans/{s2['id']}/items/{chip(s2, 'cà chua')['id']}",
                    json={"ingredient_id": ingredient_id(kb_db, "cà rốt")},
                    headers=h | {"Content-Type": "application/merge-patch+json"})  # fmt: skip
    res2 = kb_client.post(f"{API}/scans/{s2['id']}/confirm", headers=h).json()
    assert res2["created_lot_ids"] == [] and tomato_lot in res2["not_seen_lot_ids"]
    assert q(kb_db, "SELECT status FROM pantry_lots WHERE id = :i", i=carrot_lot).scalar() == "in_stock"


def test_confirm_from_wrong_states_and_discard(kb_client, kb_db, h, ctx) -> None:  # FR-13-18
    sid = post_scan(kb_client, h).json()["id"]
    r = kb_client.post(f"{API}/scans/{sid}/confirm", headers=h)
    assert r.status_code == 409 and r.json()["code"] == "invalid_scan_state"
    r = kb_client.post(f"{API}/scans/{sid}/items", json={"ingredient_id": ingredient_id(kb_db, "muối")}, headers=h)
    assert r.status_code == 409 and r.json()["code"] == "scan_not_editable"
    s = scan_done(kb_client, h, ctx, [[box(EGG)]])
    for _ in range(2):
        r = kb_client.post(f"{API}/scans/{s['id']}/discard", headers=h)
        assert r.status_code == 200 and r.json()["status"] == "discarded"
    r = kb_client.post(f"{API}/scans/{s['id']}/confirm", headers=h)
    assert r.status_code == 409 and r.json()["code"] == "invalid_scan_state"
    assert q(kb_db, "SELECT count(*) FROM pantry_lots").scalar() == 0


def test_two_confirms_at_once_write_once(kb_client, kb_db, h, ctx) -> None:  # UC13 11b
    s = scan_done(kb_client, h, ctx, [[box(EGG, i) for i in range(3)]], mode="haul")
    out: list = []
    ts = [threading.Thread(target=lambda: out.append(kb_client.post(f"{API}/scans/{s['id']}/confirm", headers=h)))
          for _ in range(4)]  # fmt: skip
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert [r.status_code for r in out] == [200] * 4
    assert len({tuple(r.json()["created_lot_ids"]) for r in out}) == 1
    assert q(kb_db, "SELECT count(*) FROM pantry_lots").scalar() == 1


# ---------------------------------------------------------------- UC34 sweeper, data-subject requests


def test_sweeper_enqueues_lost_scans_and_expires_stuck_ones(kb_client, kb_db, h, ctx) -> None:
    from tastoria.jobs.sweep import sweep

    lost = post_scan(kb_client, h).json()["id"]
    stuck = post_scan(kb_client, h).json()["id"]
    q(kb_db, "UPDATE scans SET enqueued_at = NULL, created_at = now() - interval '2 minutes' WHERE id = :i", i=lost)
    q(kb_db, "UPDATE scans SET status = 'processing', started_at = now() - interval '2 minutes', attempts = 1 "
             "WHERE id = :i", i=stuck)  # fmt: skip
    counts = sweep(kb_client.app.state.sessionmaker, kb_client.app.state.scan.queue)
    assert counts["scans_requeued"] == 1 and counts["scans_expired"] == 1
    assert q(kb_db, "SELECT enqueued_at IS NOT NULL FROM scans WHERE id = :i", i=lost).scalar()
    assert q(kb_db, "SELECT status, error_code FROM scans WHERE id = :i", i=stuck).one() == ("expired", "stuck")
    assert job.run_job(ctx, uuid.UUID(stuck)) == "skipped"


def test_account_deletion_removes_photos(kb_client, kb_db, h, ctx, storage_dir: Path) -> None:
    from tastoria.modules.scan.service import ScanSubjectData

    s = scan_done(kb_client, h, ctx, [[box(EGG)]])
    key_ = q(kb_db, "SELECT storage_key FROM scan_images WHERE scan_id = :i", i=s["id"]).scalar()
    uid = q(kb_db, "SELECT user_id FROM scans WHERE id = :i", i=s["id"]).scalar()
    handler = ScanSubjectData(storage_dir)
    from sqlalchemy.orm import Session

    with Session(kb_client.app.state.engine) as sess:
        exported = handler.export(sess, uid)
    assert exported["scans"][0]["id"] == s["id"] and exported["scan_items"]
    handler.erase_files(uid)
    assert not (storage_dir / key_).exists()


def test_withdrawing_photo_contribution_returns_photos_to_the_30_day_rule(kb_client, kb_db, h, ctx, storage_dir) -> None:
    grant(kb_client, h, "photo_contribution")
    s = scan_done(kb_client, h, ctx, [[]])
    old = q(kb_db, "SELECT storage_key FROM scan_images WHERE scan_id = :i", i=s["id"]).scalar()
    assert old.startswith("contrib/")
    r = kb_client.post(f"{API}/me/consents/photo_contribution/withdraw", json={}, headers=h)
    assert r.status_code in (200, 202), r.text
    row = q(kb_db, "SELECT storage_key, contributed FROM scan_images WHERE scan_id = :i", i=s["id"]).one()
    if row.contributed:  # the purpose data is erased by the DSR job (≤ 24 h); run it now
        from tastoria.modules.privacy.service import process_pending

        process_pending(kb_client.app.state.privacy)
        row = q(kb_db, "SELECT storage_key, contributed FROM scan_images WHERE scan_id = :i", i=s["id"]).one()
    assert row.contributed is False and row.storage_key.startswith("tmp/scans/")
    assert (storage_dir / row.storage_key).exists() and not (storage_dir / old).exists()


def test_purge_cutoff_is_30_days(kb_client, kb_db, h, ctx, storage_dir) -> None:
    from tastoria.jobs.purge_images import purge

    s = scan_done(kb_client, h, ctx, [[]])
    q(kb_db, "UPDATE scans SET created_at = now() - interval '29 days 23 hours'")
    assert purge(kb_client.app.state.sessionmaker, storage_dir)["images_purged"] == 0
    assert kb_client.get(f"{API}/scans/{s['id']}/images/1", headers=h).status_code == 200
