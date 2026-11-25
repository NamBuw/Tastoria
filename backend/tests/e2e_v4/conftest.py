"""Fixtures, env parameterization, ONNX/Detector builders, and M3 probe helpers for backend/tests/e2e_v4."""

from __future__ import annotations

import ast
import hashlib
import importlib
import json
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import onnxruntime as ort
import pytest
import yaml

from tastoria.modules.scan import worker as job
from tastoria.modules.scan.detector import Detector
from tastoria.modules.scan.runner import resolve_class_conf

REPO_ROOT = Path(__file__).resolve().parents[3]
KB_DIR = REPO_ROOT / "data/kb"
PROCESSED_DIR = REPO_ROOT / "data/processed"
FOOD_ASSETS_DIR = REPO_ROOT / "app/assets/food"


def pytest_configure(config: pytest.Config) -> None:
    for marker in (
        "tier1: Tier 1 contract and feature-coverage E2E tests",
        "tier2: Tier 2 boundary, edge-case, and negative/rejection E2E tests",
        "tier3: Tier 3 cross-feature and isolation E2E tests",
        "tier4: Tier 4 real-world E2E scenarios and latency SLA tests",
    ):
        config.addinivalue_line("markers", marker)


def _env_bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class BackendE2EConfig:
    strict: bool
    model_dir: Path
    serving_file: str | None
    meal_calorie_dir: Path
    latency_sla_ms: float
    threads: int
    min_nin_dishes: int


@dataclass(frozen=True)
class DetectorBundle:
    detector: Detector
    session: ort.InferenceSession
    onnx_path: Path
    serving_path: Path
    manifest_path: Path
    serving: dict[str, Any]
    manifest: dict[str, Any]
    classes: list[str]
    class_map: dict[int, int]
    code_by_vid: dict[int, str]


def load_vision_classes_yaml() -> list[dict[str, Any]]:
    raw = yaml.safe_load((KB_DIR / "vision_classes.yaml").read_text(encoding="utf-8"))
    return list(raw["classes"]) + list(raw.get("proposed_classes") or [])


def make_ort_session(onnx_path: Path, threads: int = 2) -> ort.InferenceSession:
    so = ort.SessionOptions()
    so.intra_op_num_threads = threads
    so.inter_op_num_threads = 1
    so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    so.add_session_config_entry("session.intra_op.allow_spinning", "0")
    so.add_session_config_entry("session.inter_op.allow_spinning", "0")
    return ort.InferenceSession(str(onnx_path), so, providers=["CPUExecutionProvider"])


@pytest.fixture(scope="session")
def e2e_cfg() -> BackendE2EConfig:
    strict = _env_bool("TASTORIA_E2E_STRICT_V4", False)
    default_model = REPO_ROOT / ("deploy/models/detector_v3" if strict else "deploy/models/detector_v2")
    model_dir = Path(os.environ.get("TASTORIA_E2E_MODEL_DIR") or default_model)
    serving_file = os.environ.get("TASTORIA_E2E_SERVING_FILE") or None
    meal_dir = Path(os.environ.get("TASTORIA_E2E_MEAL_CALORIE_DIR") or (REPO_ROOT / "deploy/models/meal_calorie"))
    sla_ms = float(os.environ.get("TASTORIA_E2E_LATENCY_SLA_MS") or "3000.0")
    threads = int(os.environ.get("TASTORIA_E2E_THREADS") or "2")
    min_nin = int(os.environ.get("TASTORIA_E2E_MIN_NIN_DISHES") or ("46" if strict else "45"))
    return BackendE2EConfig(
        strict=strict,
        model_dir=model_dir,
        serving_file=serving_file,
        meal_calorie_dir=meal_dir,
        latency_sla_ms=sla_ms,
        threads=threads,
        min_nin_dishes=min_nin,
    )


@pytest.fixture(scope="session")
def e2e_detector(e2e_cfg: BackendE2EConfig) -> DetectorBundle:
    onnx_path = e2e_cfg.model_dir / "model.onnx"
    if not onnx_path.is_file():
        pytest.fail(f"Missing detector ONNX at {onnx_path}")

    manifest_path = e2e_cfg.model_dir / "serving.json"
    if not manifest_path.is_file():
        pytest.fail(f"Missing detector serving.json at {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    if e2e_cfg.serving_file:
        serving_path = e2e_cfg.model_dir / e2e_cfg.serving_file
    elif (e2e_cfg.model_dir / "serving_f05.json").is_file():
        serving_path = e2e_cfg.model_dir / "serving_f05.json"
    else:
        serving_path = manifest_path
    if not serving_path.is_file():
        pytest.fail(f"Missing serving file at {serving_path}")
    serving = json.loads(serving_path.read_text(encoding="utf-8"))

    sess = make_ort_session(onnx_path, threads=e2e_cfg.threads)
    meta = sess.get_modelmeta().custom_metadata_map
    raw_names = meta.get("names")
    assert raw_names, f"ONNX names metadata missing in {onnx_path}"
    parsed = ast.literal_eval(raw_names)
    classes = [str(parsed[i]) for i in sorted(parsed)]

    class_map = {i: 1000 + i for i in range(len(classes))}
    code_by_vid = {1000 + i: code for i, code in enumerate(classes)}
    cc = resolve_class_conf(serving.get("class_conf"), class_map, code_by_vid)
    ccc = resolve_class_conf(serving.get("class_count_conf"), class_map, code_by_vid)
    zoom_rescue = serving.get("zoom_rescue") if isinstance(serving.get("zoom_rescue"), dict) else None
    raw_ag = serving.get("agnostic_iou")
    agnostic_iou = float(raw_ag) if raw_ag is not None else None

    det = Detector(
        sess,
        conf=float(serving["conf"]),
        iou=float(serving["iou"]),
        preprocess_version=serving.get("preprocess_version") or manifest.get("preprocess_version"),
        agnostic_iou=agnostic_iou,
        class_conf=cc,
        class_count_conf=ccc,
        zoom_rescue=zoom_rescue,
    )
    return DetectorBundle(
        detector=det,
        session=sess,
        onnx_path=onnx_path,
        serving_path=serving_path,
        manifest_path=manifest_path,
        serving=serving,
        manifest=manifest,
        classes=classes,
        class_map=class_map,
        code_by_vid=code_by_vid,
    )


@pytest.fixture(scope="session")
def meal_calorie_probe(e2e_cfg: BackendE2EConfig) -> dict[str, Any] | None:
    """Discover M3 meal_calorie service/artifacts (mandatory under STRICT_V4=1)."""
    svc_mod = None
    try:
        svc_mod = importlib.import_module("tastoria.modules.meal_calorie.service")
    except ImportError:
        svc_mod = None

    has_dir = (e2e_cfg.meal_calorie_dir / "serving.json").is_file()
    if e2e_cfg.strict:
        if svc_mod is None:
            pytest.fail("TASTORIA_E2E_STRICT_V4=1 requires tastoria.modules.meal_calorie.service")
        if not has_dir:
            pytest.fail(f"TASTORIA_E2E_STRICT_V4=1 requires {e2e_cfg.meal_calorie_dir}/serving.json")
    if svc_mod is None:
        return None

    deps = svc_mod.MealCalorieDeps.from_paths(
        model_dir=e2e_cfg.meal_calorie_dir,
        kb_dir=KB_DIR,
        kb_processed_dir=PROCESSED_DIR / "kb",
    )
    return {
        "service": svc_mod,
        "deps": deps,
        "has_onnx": has_dir,
        "model_dir": e2e_cfg.meal_calorie_dir if has_dir else None,
    }


@pytest.fixture(scope="session")
def real_produce_images() -> list[Path]:
    paths: list[Path] = []
    v2_test = PROCESSED_DIR / "cv/yolo_v2/images/test"
    if v2_test.is_dir():
        paths.extend(sorted(v2_test.glob("*.jpg"))[:20])
    for held_dir in (
        PROCESSED_DIR / "cv/yolo_v4/images/heldout",
        PROCESSED_DIR / "cv/yolo_v3/images/heldout",
        PROCESSED_DIR / "cv/yolo_v2/images/heldout",
    ):
        if held_dir.is_dir():
            omorros = sorted(held_dir.glob("omorros_kitchen__*.jpg"))[:5]
            if omorros:
                paths.extend(omorros)
                break
    assert len(paths) > 0, "Expected real produce images under data/processed/cv/"
    return paths


@pytest.fixture
def e2e_worker_ctx(
    kb_engine, kb_app, kb_clean, storage_dir: Path, e2e_detector: DetectorBundle
) -> Iterator[job.WorkerContext]:
    """Install a real ONNX WorkerContext wired to a matching DB model_versions + model_deployments row."""
    from sqlalchemy.orm import Session

    from tastoria.modules.mlops import service as mlops

    version_name = "e2e-v4-detector"
    key_ = f"models/detector/{version_name}/model.onnx"
    dst = storage_dir / key_
    dst.parent.mkdir(parents=True, exist_ok=True)
    onnx_bytes = e2e_detector.onnx_path.read_bytes()
    if not dst.exists() or dst.read_bytes() != onnx_bytes:
        dst.write_bytes(onnx_bytes)
    sha = hashlib.sha256(onnx_bytes).digest()

    serving_payload = json.dumps({"serving": e2e_detector.serving})
    preprocess_ver = e2e_detector.manifest.get("preprocess_version") or "none"

    with kb_engine.begin() as c:
        existing_id = c.exec_driver_sql(
            "SELECT id FROM model_versions WHERE name = 'detector' AND version = %s",
            (version_name,),
        ).scalar()
        ids = {code: vid for vid, code in c.exec_driver_sql("SELECT id, code FROM vision_classes")}
        if existing_id is None:
            vid = c.exec_driver_sql(
                "INSERT INTO model_versions (name, version, artifact_key, sha256, preprocess_version, metrics, status) "
                "VALUES ('detector', %s, %s, %s, %s, %s::jsonb, 'validated') RETURNING id",
                (version_name, key_, sha, preprocess_ver, serving_payload),
            ).scalar()
        else:
            vid = existing_id
            c.exec_driver_sql("DELETE FROM model_version_classes WHERE model_version_id = %s", (vid,))
        for i, code in enumerate(e2e_detector.classes):
            c.exec_driver_sql(
                "INSERT INTO model_version_classes (model_version_id, class_index, vision_class_id) VALUES (%s, %s, %s)",
                (vid, i, ids[code]),
            )
        c.exec_driver_sql(
            "INSERT INTO model_deployments (name, active_version_id, switched_at) VALUES ('detector', %s, now()) "
            "ON CONFLICT (name) DO UPDATE SET active_version_id = EXCLUDED.active_version_id, previous_version_id = NULL",
            (vid,),
        )

    with kb_engine.connect() as c, Session(bind=c) as s:
        view = mlops.active_version(s, "detector")
    assert view is not None

    ctx = job.WorkerContext(
        kb_app.state.sessionmaker,
        storage_dir,
        kb_app.state.scan.queue,
        e2e_detector.detector,
        view,
        None,
    )
    job.install(ctx)
    try:
        yield ctx
    finally:
        job.install(None)
        with kb_engine.begin() as c:
            c.exec_driver_sql("DELETE FROM model_deployments WHERE name = 'detector'")
