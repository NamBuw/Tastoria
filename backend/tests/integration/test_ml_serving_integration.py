"""M3 ML Serving Integration: Ranker, pgvector Substitution, Calibrated Composer Params, Freshness ONNX."""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from conftest import REPO_ROOT
from fastapi.testclient import TestClient
from kb_helpers import API, grant, ingredient_id, key, plan, q, stock_for, user
from PIL import Image

from tastoria.modules.admin import mlops as ops
from tastoria.modules.meal import service as meal_service
from tastoria.modules.scan import runner
from tastoria.modules.scan import worker as job

RANKER_NPZ = REPO_ROOT / "deploy/models/ranker/model.npz"
RANKER_SERVING = REPO_ROOT / "deploy/models/ranker/serving.json"
EMB_NPZ = REPO_ROOT / "deploy/models/embeddings/ingredient_embeddings.npz"
DET_ONNX = REPO_ROOT / "deploy/models/detector/model.onnx"
DET_SERVING = REPO_ROOT / "deploy/models/detector/serving.json"

MAN, RAU, CANH = "Ba chỉ chiên nước mắm", "Bí ngòi xào tỏi", "Canh rau ngót thịt băm"


@pytest.fixture
def clean_m3_models(kb_engine, kb_clean):
    def wipe() -> None:
        with kb_engine.begin() as c:
            c.exec_driver_sql("SET LOCAL tastoria.erasure = 'on'")
            c.exec_driver_sql("DELETE FROM interactions")
            c.exec_driver_sql("DELETE FROM meal_plans")
            c.exec_driver_sql("DELETE FROM ingredient_embeddings")
            c.exec_driver_sql("DELETE FROM model_deployments")
            c.exec_driver_sql("UPDATE scans SET detector_version_id = NULL, classifier_version_id = NULL")
            c.exec_driver_sql("UPDATE pantry_lots SET freshness_model_version_id = NULL")
            c.exec_driver_sql(
                "DELETE FROM model_version_classes WHERE model_version_id IN "
                "(SELECT id FROM model_versions WHERE version <> 'scripted-1')"
            )
            c.exec_driver_sql("DELETE FROM model_versions WHERE version <> 'scripted-1'")
        meal_service._RANKER_CACHE.clear()

    wipe()
    yield
    wipe()


def test_calibrated_composer_params_and_ranker_serving(
    kb_client: TestClient, kb_db, kb_app, storage_dir: Path, clean_m3_models, tmp_path: Path
) -> None:
    sm = kb_app.state.sessionmaker
    art = tmp_path / "ranker.npz"
    shutil.copyfile(RANKER_NPZ, art)
    metrics = {"serving": json.loads(RANKER_SERVING.read_text(encoding="utf-8"))}
    v, _ = ops.register(
        sm,
        storage_dir,
        name="ranker",
        version="ranker_hybrid_v1",
        artifact=art,
        metrics=metrics,
        preprocess_version=None,
        class_codes=None,
    )
    ok, reasons = ops.gate(sm, storage_dir, name="ranker", version="ranker_hybrid_v1")
    assert ok, reasons
    ops.deploy(sm, name="ranker", version="ranker_hybrid_v1")
    assert kb_client.get("/readyz").json()["checks"]["models"] == "ok"

    h = user(kb_client, "personalization")
    stock_for(kb_client, h, kb_db, MAN, RAU, CANH)
    p = plan(kb_client, h)
    assert p["ranker_version_id"] == str(v.id)
    assert p["params_version"] == "tray-p1-knee-20261118"
    rv = q(kb_db, "SELECT ranker_version_id FROM interactions WHERE meal_plan_id = :p LIMIT 1", p=p["id"]).scalar()
    assert str(rv) == str(v.id)


def test_pgvector_embeddings_sync_and_substitute_fallback(
    kb_client: TestClient, kb_db, kb_app, storage_dir: Path, clean_m3_models, tmp_path: Path
) -> None:
    sm = kb_app.state.sessionmaker
    art = tmp_path / "ingredient_embeddings.npz"
    shutil.copyfile(EMB_NPZ, art)
    expected_emb_count = int(
        json.loads((REPO_ROOT / "deploy/models/embeddings/manifest.json").read_text(encoding="utf-8"))[
            "embedded_count"
        ]
    )
    v, _ = ops.register(
        sm,
        storage_dir,
        name="substitution",
        version="sub_hybrid_v1",
        artifact=art,
        metrics={},
        preprocess_version=None,
        class_codes=None,
    )
    ok, reasons = ops.gate(sm, storage_dir, name="substitution", version="sub_hybrid_v1")
    assert ok, reasons
    dep = ops.deploy(sm, name="substitution", version="sub_hybrid_v1", storage_dir=storage_dir)
    assert dep["changed"] is True and dep["embeddings"]["upserted"] == expected_emb_count
    assert q(kb_db, "SELECT count(*) FROM ingredient_embeddings WHERE model_version_id = :v", v=str(v.id)).scalar() == expected_emb_count
    assert kb_client.get("/readyz").json()["checks"]["models"] == "ok"

    h = user(kb_client)
    stock_for(kb_client, h, kb_db, MAN, RAU, CANH)
    p = plan(kb_client, h)
    canh = next(i for i in p["items"] if i["slot"] == "canh" and i["status"] == "active")
    # Curated substitution_pairs is empty in seeded test DB; deployed embeddings should return origin="embedding"
    r = kb_client.get(
        f"{API}/meal-plans/{p['id']}/items/{canh['id']}/substitutes",
        params={"ingredient_id": ingredient_id(kb_db, "rau ngót")},
        headers=h,
    )
    assert r.status_code == 200, r.text
    cands = r.json()["items"][0]["candidates"]
    assert 1 <= len(cands) <= 3
    assert all(c["origin"] == "embedding" for c in cands)
    assert all(0.0 <= c["score"] <= 1.0 for c in cands)


def test_freshness_onnx_worker_populates_detections_and_abstains(
    kb_client: TestClient, kb_db, kb_app, storage_dir: Path, clean_m3_models, tmp_path: Path
) -> None:
    import sys

    unit_dir = str(Path(__file__).resolve().parents[1] / "unit")
    if unit_dir not in sys.path:
        sys.path.insert(0, unit_dir)
    from test_m3_ml_serving import build_freshness_onnx

    if not DET_ONNX.exists():
        pytest.skip("detector model.onnx missing")

    sm = kb_app.state.sessionmaker
    det_art = tmp_path / "detector.onnx"
    shutil.copyfile(DET_ONNX, det_art)
    det_serving = json.loads(DET_SERVING.read_text(encoding="utf-8"))
    ops.register(
        sm,
        storage_dir,
        name="detector",
        version="det_m3_test",
        artifact=det_art,
        metrics={"serving": det_serving},
        preprocess_version="none",
        class_codes=None,
    )
    ok, reasons = ops.gate(sm, storage_dir, name="detector", version="det_m3_test")
    assert ok, reasons
    ops.deploy(sm, name="detector", version="det_m3_test")

    fresh_art = build_freshness_onnx(tmp_path / "freshness.onnx", two_outputs=True)
    fv, _ = ops.register(
        sm,
        storage_dir,
        name="freshness",
        version="fresh_m3_test",
        artifact=fresh_art,
        metrics={"serving": {"input": {"pad_value": 128}, "abstention": {"tau": 0.60}}},
        preprocess_version=None,
        class_codes=None,
    )
    f_ok, f_reasons = ops.gate(sm, storage_dir, name="freshness", version="fresh_m3_test")
    assert f_ok, f_reasons
    ops.deploy(sm, name="freshness", version="fresh_m3_test")
    assert kb_client.get("/readyz").json()["checks"]["models"] == "ok"

    ctx = runner.build_context(kb_app.state.settings, sm, kb_app.state.scan.queue)
    assert ctx.freshness is not None and ctx.freshness_version is not None and ctx.freshness_version.id == fv.id

    # Create a real scan using a test image from data/processed/cv/yolo/images/test or synthetic image
    test_imgs = list((REPO_ROOT / "data/processed/cv/yolo/images/test").glob("*.jpg"))
    if test_imgs:
        img_bytes = test_imgs[0].read_bytes()
    else:
        import io

        buf = io.BytesIO()
        Image.new("RGB", (320, 320), (240, 30, 30)).save(buf, format="JPEG")
        img_bytes = buf.getvalue()

    h = user(kb_client)
    r = kb_client.post(
        f"{API}/scans",
        data={"mode": "haul"},
        files=[("images", ("test.jpg", img_bytes, "image/jpeg"))],
        headers=h | key(),
    )
    assert r.status_code == 202, r.text
    sid = r.json()["id"]
    job.install(ctx)
    try:
        assert job.run_job(ctx, uuid.UUID(sid)) == "done"
    finally:
        job.install(None)

    s = kb_client.get(f"{API}/scans/{sid}", headers=h).json()
    assert s["status"] == "done" and s["classifier_version_id"] == str(fv.id)
    fresh_codes = {
        code
        for (code,) in kb_db.execute(
            sa.text("SELECT code FROM vision_classes WHERE has_freshness_model = true")
        ).all()
    }
    for it in s["items"]:
        for d in it["detections"]:
            probs = (d["p_tuoi"], d["p_dung_som"], d["p_dung_ngay"], d["p_kiem_tra"])
            if d["vision_class_code"] in fresh_codes:
                assert all(p is not None and 0.0 <= p <= 1.0 for p in probs)
                assert sum(probs) == pytest.approx(1.0, abs=0.01)
            else:
                assert all(p is None for p in probs)
