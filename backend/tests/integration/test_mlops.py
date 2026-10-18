"""UC29 / UC30 (SD10, ST07): register → gate → deploy → rollback, sha256 checks, and the real YOLO26n ONNX through
the whole scan pipeline (skipped when the gitignored model file is not on this machine)."""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import pytest
from conftest import REPO_ROOT
from fastapi.testclient import TestClient
from kb_helpers import API, key, q, user
from sqlalchemy.orm import Session

from tastoria.modules.admin import mlops as ops
from tastoria.modules.mlops import service as mlops
from tastoria.modules.mlops.schemas import MlopsError

ONNX = REPO_ROOT / "ml/runs/detect/yolo26n_640_none/weights/best.onnx"
SERVING = REPO_ROOT / "data/processed/cv/detector/yolo26n_640_none_serving.json"
TRAINING = REPO_ROOT / "data/processed/cv/detector/yolo26n_640_none.json"
TEST_IMAGES = REPO_ROOT / "data/processed/cv/yolo/images/test"
needs_onnx = pytest.mark.skipif(not ONNX.exists(), reason="detector ONNX not on this machine (gitignored)")


@pytest.fixture
def clean_models(kb_engine, kb_clean):
    """Each test starts with no model rows (the scan tests' scripted version is re-created by their fixture)."""

    def wipe() -> None:
        with kb_engine.begin() as c:
            c.exec_driver_sql("DELETE FROM model_deployments")
            c.exec_driver_sql("UPDATE scans SET detector_version_id = NULL, classifier_version_id = NULL")
            c.exec_driver_sql("UPDATE pantry_lots SET freshness_model_version_id = NULL")
            c.exec_driver_sql("DELETE FROM model_version_classes WHERE model_version_id IN "
                              "(SELECT id FROM model_versions WHERE version <> 'scripted-1')")  # fmt: skip
            c.exec_driver_sql("DELETE FROM model_versions WHERE version <> 'scripted-1'")

    wipe()
    yield
    wipe()


@pytest.fixture
def sm(kb_app):
    return kb_app.state.sessionmaker


def _artifact(tmp_path: Path, data: bytes = b"not really a model") -> Path:
    p = tmp_path / "model.bin"
    p.write_bytes(data)
    return p


def test_register_is_idempotent_and_refuses_other_bytes(sm, tmp_path, storage_dir, clean_models, kb_db) -> None:
    art = _artifact(tmp_path)
    v, created = ops.register(sm, storage_dir, name="ranker", version="r1", artifact=art, metrics={"a": 1},
                              preprocess_version=None, class_codes=None)  # fmt: skip
    assert created and v.status == "candidate" and v.artifact_key == "models/ranker/r1/model.bin"
    assert (storage_dir / v.artifact_key).read_bytes() == art.read_bytes()
    again, created2 = ops.register(sm, storage_dir, name="ranker", version="r1", artifact=art, metrics={},
                                   preprocess_version=None, class_codes=None)  # fmt: skip
    assert not created2 and again.id == v.id
    with pytest.raises(MlopsError, match="sha256"):
        ops.register(sm, storage_dir, name="ranker", version="r1", artifact=_artifact(tmp_path, b"other"),
                     metrics={}, preprocess_version=None, class_codes=None)  # fmt: skip
    assert q(kb_db, "SELECT count(*) FROM model_versions WHERE name = 'ranker'").scalar() == 1
    acts = [r.purpose for r in q(kb_db, "SELECT purpose FROM audit_log WHERE action = 'model_register' ORDER BY id")]
    assert acts[:2] == ["created", "unchanged"] and acts[2].startswith("refused")


def test_detector_needs_known_classes(sm, tmp_path, storage_dir, clean_models) -> None:
    with pytest.raises(MlopsError, match="bản đồ lớp"):
        ops.register(sm, storage_dir, name="detector", version="d0", artifact=_artifact(tmp_path), metrics={},
                     preprocess_version="none", class_codes=None)  # fmt: skip
    with pytest.raises(MlopsError, match="vision_classes"):
        ops.register(sm, storage_dir, name="detector", version="d0", artifact=_artifact(tmp_path), metrics={},
                     preprocess_version="none", class_codes=["trung", "rong"])  # fmt: skip


def test_gate_rejects_an_artifact_that_cannot_serve(sm, tmp_path, storage_dir, clean_models) -> None:
    ops.register(sm, storage_dir, name="detector", version="bad", artifact=_artifact(tmp_path), metrics={},
                 preprocess_version="none", class_codes=["trung"])  # fmt: skip
    ok, reasons = ops.gate(sm, storage_dir, name="detector", version="bad")
    assert not ok and any("onnxruntime" in r for r in reasons) and any("serving" in r for r in reasons)
    with pytest.raises(MlopsError, match="validated"):
        ops.deploy(sm, name="detector", version="bad")
    report = json.loads((storage_dir / "models/detector/bad/gate.json").read_text())
    assert report["passed"] is False


def test_deploy_rollback_and_retire_follow_st07(sm, tmp_path, storage_dir, clean_models, kb_db) -> None:
    for i in (1, 2, 3):
        ops.register(sm, storage_dir, name="ranker", version=f"r{i}", artifact=_artifact(tmp_path, bytes([i])),
                     metrics={}, preprocess_version=None, class_codes=None)  # fmt: skip
        q(kb_db, "UPDATE model_versions SET status = 'validated' WHERE version = :v", v=f"r{i}")
    ids = dict(q(kb_db, "SELECT version, id::text FROM model_versions WHERE name = 'ranker'").all())
    assert ops.deploy(sm, name="ranker", version="r1")["changed"]
    assert not ops.deploy(sm, name="ranker", version="r1")["changed"]  # already active
    assert not ops.deploy(sm, name="ranker", version="r2", only_if_none=True)["changed"]  # bootstrap only
    d = ops.deploy(sm, name="ranker", version="r2")
    assert (d["active_version_id"], d["previous_version_id"]) == (ids["r2"], ids["r1"])
    d = ops.rollback(sm, name="ranker")
    assert (d["active_version_id"], d["previous_version_id"]) == (ids["r1"], ids["r2"])
    ops.deploy(sm, name="ranker", version="r3")  # r2 leaves the rollback slot -> retired
    st = dict(q(kb_db, "SELECT version, status FROM model_versions WHERE name = 'ranker'").all())
    assert st == {"r1": "validated", "r2": "retired", "r3": "validated"}
    assert ops.rollback(sm, name="ranker")["active_version_id"] == ids["r1"]
    with pytest.raises(MlopsError):
        ops.rollback(sm, name="freshness")
    acts = [r.action for r in q(kb_db, "SELECT action FROM audit_log WHERE entity = 'model_deployments' ORDER BY id")]
    assert acts.count("model_deploy") == 3 and acts.count("model_rollback") == 3  # 2 done + 1 refused


def test_loader_refuses_a_changed_artifact(sm, tmp_path, storage_dir, clean_models) -> None:
    v, _ = ops.register(sm, storage_dir, name="freshness", version="f1", artifact=_artifact(tmp_path), metrics={},
                        preprocess_version=None, class_codes=None)  # fmt: skip
    (storage_dir / v.artifact_key).write_bytes(b"tampered")
    with pytest.raises(MlopsError, match="sha256"):
        mlops.load_onnx(storage_dir, v)


# ---------------------------------------------------------------- the real detector


@needs_onnx
def test_real_onnx_through_register_gate_deploy_worker_and_confirm(
    kb_client: TestClient, kb_app, kb_db, sm, storage_dir, clean_models, tmp_path
) -> None:
    from tastoria.core.config import Settings
    from tastoria.modules.scan import runner
    from tastoria.modules.scan import worker as job

    art = tmp_path / "best.onnx"
    shutil.copyfile(ONNX, art)
    metrics = json.loads(TRAINING.read_text())
    metrics["serving"] = json.loads(SERVING.read_text())
    v, created = ops.register(sm, storage_dir, name="detector", version="yolo26n_640_none", artifact=art,
                              metrics=metrics, preprocess_version="none", class_codes=None)  # names from ONNX metadata
    assert created and len(v.class_map) == 13
    codes = dict(q(kb_db, "SELECT id, code FROM vision_classes").all())
    assert [codes[v.class_map[i]] for i in range(3)] == ["ca", "tom", "trung"]
    ok, reasons = ops.gate(sm, storage_dir, name="detector", version="yolo26n_640_none")
    assert ok, reasons
    assert ops.deploy(sm, name="detector", version="yolo26n_640_none", only_if_none=True)["changed"]
    assert kb_client.get("/readyz").json()["checks"]["models"] == "ok"

    settings: Settings = kb_app.state.settings
    ctx = runner.build_context(settings, sm, kb_app.state.scan.queue)
    assert ctx.detector.size == 640 and ctx.detector.conf == metrics["serving"]["conf"]
    # a small real photo of the public test split that has labelled objects
    photo = next(p for p in sorted(TEST_IMAGES.glob("openimages_*.jpg"))
                 if p.stat().st_size < 200_000 and "trung" not in p.name)  # fmt: skip
    h = user(kb_client)
    r = kb_client.post(f"{API}/scans", data={"mode": "haul"},
                       files=[("images", (photo.name, photo.read_bytes(), "image/jpeg"))], headers=h | key())  # fmt: skip
    assert r.status_code == 202, r.text
    sid = r.json()["id"]
    job.install(ctx)
    try:
        assert job.run_job(ctx, uuid.UUID(sid)) == "done"
    finally:
        job.install(None)
    s = kb_client.get(f"{API}/scans/{sid}", headers=h).json()
    assert s["status"] == "done" and s["detector_version_id"] == str(v.id) and s["preprocess_version"] == "none"
    n_det = q(kb_db, "SELECT count(*) FROM detections d JOIN scan_images i ON i.id = d.scan_image_id "
                     "WHERE i.scan_id = :s", s=sid).scalar()  # fmt: skip
    assert n_det == sum(len(i["detections"]) for i in s["items"])  # every class of this model maps to an ingredient
    assert ctx.timings and ctx.timings[-1]["infer_ms"] < 5000
    for it in s["items"]:  # give every uncounted chip a level, then confirm into the pantry
        if it["final_count"] is None:
            kb_client.patch(f"{API}/scans/{sid}/items/{it['id']}", json={"qty_level": "vua"},
                            headers=h | {"Content-Type": "application/merge-patch+json"})  # fmt: skip
    res = kb_client.post(f"{API}/scans/{sid}/confirm", headers=h)
    assert res.status_code == 200, res.text
    assert len(res.json()["created_lot_ids"]) == len([i for i in s["items"] if i["final_count"] != 0])
    with Session(kb_app.state.engine) as sess:
        assert mlops.active_version(sess, "detector").version == "yolo26n_640_none"
