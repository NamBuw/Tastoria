"""mlops public interface (M07): register, gate, deploy and roll back model versions; load the deployed ONNX model.

Lifecycle (ST07, SD10):
  register  copies the artifact into the file volume at models/<name>/<version>/<file> (artifact_key), stores its
            SHA-256, the preprocessing version, the metrics and — for the detector — the class map (output index →
            vision_classes.id); status candidate. Registering the same (name, version) again with the same bytes is a
            no-op; with other bytes it is refused.
  gate      re-checks the stored artifact (SHA-256, ONNX loads, detector output width = 4 + number of classes, every
            output index mapped, serving thresholds present) and writes models/<name>/<version>/gate.json;
            status validated or rejected. No metric threshold is enforced yet: there is no team-collected test set
            to set one on (docs/reports/xu-ly-anh/ket-qua-so-bo.md §8); the gate checks that the version can serve.
  deploy    moves the pointer model_deployments(name) to a validated version; the replaced version stays validated
            in previous_version_id (rollback target); the one pushed out of previous_version_id becomes retired.
  rollback  swaps active and previous.
Processes load the pointed version at start (`load_onnx` verifies the SHA-256 first); switching = pointer + restart.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tastoria.core.clock import utcnow
from tastoria.modules.catalog import service as catalog
from tastoria.modules.mlops.models import ModelDeployment, ModelVersion, ModelVersionClass
from tastoria.modules.mlops.schemas import DeploymentView, MlopsError, ModelVersionView

NAMES = ("detector", "freshness", "ranker", "substitution")
ONNX_NAMES = ("detector", "freshness")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _view(session: Session, v: ModelVersion, active_ids: set[uuid.UUID] | None = None) -> ModelVersionView:
    classes = {
        c.class_index: c.vision_class_id
        for c in session.scalars(select(ModelVersionClass).where(ModelVersionClass.model_version_id == v.id))
    }
    if active_ids is None:
        active_ids = set(session.scalars(select(ModelDeployment.active_version_id)))
    return ModelVersionView(
        id=v.id,
        name=v.name,
        version=v.version,
        artifact_key=v.artifact_key,
        sha256=bytes(v.sha256).hex(),
        preprocess_version=v.preprocess_version,
        metrics=dict(v.metrics or {}),
        status=v.status,
        created_at=v.created_at,
        class_map=classes,
        is_active=v.id in active_ids,
    )


def _get(session: Session, name: str, version: str, *, lock: bool = False) -> ModelVersion:
    q = select(ModelVersion).where(ModelVersion.name == name, ModelVersion.version == version)
    if lock:
        q = q.with_for_update()
    v = session.scalars(q).one_or_none()
    if v is None:
        raise MlopsError(f"{name} {version}: chưa đăng ký")
    return v


def _check_name(name: str) -> None:
    if name not in NAMES:
        raise MlopsError(f"tên mô hình {name!r} không hợp lệ (một trong {', '.join(NAMES)})")


# ---------------------------------------------------------------- register (UC29)


def register(
    session: Session,
    *,
    storage_dir: Path,
    name: str,
    version: str,
    artifact: Path,
    metrics: dict[str, Any],
    preprocess_version: str | None = None,
    class_codes: list[str] | None = None,
    mlflow_run_id: str | None = None,
) -> tuple[ModelVersionView, bool]:
    """(version, created). Idempotent for identical bytes; the file is copied before the row is written."""
    _check_name(name)
    artifact = Path(artifact)
    if not artifact.is_file():
        raise MlopsError(f"không có tệp {artifact}")
    digest = sha256_file(artifact)
    existing = session.scalars(
        select(ModelVersion).where(ModelVersion.name == name, ModelVersion.version == version)
    ).one_or_none()
    if existing is not None:
        if bytes(existing.sha256).hex() != digest:
            raise MlopsError(
                f"{name} {version} đã đăng ký với sha256 {bytes(existing.sha256).hex()[:12]}…, tệp mới {digest[:12]}…"
            )
        return _view(session, existing), False
    if name == "detector" and not class_codes:
        raise MlopsError("detector cần bản đồ lớp (--class-map hoặc metadata names trong ONNX)")
    class_ids: dict[int, int] = {}
    if class_codes:
        known = catalog.vision_class_ids_by_code(session)
        missing = [c for c in class_codes if c not in known]
        if missing:
            raise MlopsError(f"lớp không có trong vision_classes (chạy tastoria catalog import trước): {missing}")
        if len(set(class_codes)) != len(class_codes):
            raise MlopsError("bản đồ lớp có mã lặp")
        class_ids = {i: known[c] for i, c in enumerate(class_codes)}

    key = f"models/{name}/{version}/{artifact.name}"
    dst = Path(storage_dir) / key
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + f".{uuid.uuid4().hex}.part")
    shutil.copyfile(artifact, tmp)
    if sha256_file(tmp) != digest:
        tmp.unlink(missing_ok=True)
        raise MlopsError("tệp đổi trong lúc chép; thử lại")
    os.replace(tmp, dst)

    v = ModelVersion(
        id=uuid.uuid4(),
        name=name,
        version=version,
        artifact_key=key,
        sha256=bytes.fromhex(digest),
        preprocess_version=preprocess_version,
        metrics=metrics,
        mlflow_run_id=mlflow_run_id,
        status="candidate",
        created_at=utcnow(),
    )
    session.add(v)
    session.flush()
    for idx, vid in class_ids.items():
        session.add(ModelVersionClass(model_version_id=v.id, class_index=idx, vision_class_id=vid))
    session.flush()
    return _view(session, v), True


# ---------------------------------------------------------------- gate (UC29)


def _onnx_checks(path: Path, name: str, n_classes: int) -> list[str]:
    try:
        import onnxruntime as ort

        sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    except Exception as exc:  # noqa: BLE001 — any loader error rejects the version
        return [f"onnxruntime không nạp được: {exc}"]
    problems = []
    if name == "detector":
        out = sess.get_outputs()[0].shape
        if len(out) != 3 or out[1] != 4 + n_classes:
            problems.append(f"đầu ra {out} không khớp 4 + {n_classes} lớp")
        inp = sess.get_inputs()[0].shape
        if len(inp) != 4 or not isinstance(inp[2], int) or inp[2] != inp[3]:
            problems.append(f"đầu vào {inp} không phải ảnh vuông cố định")
    return problems


def gate(session: Session, *, storage_dir: Path, name: str, version: str) -> tuple[bool, list[str]]:
    """(passed, reasons). A validated version re-gates as passed without change; a rejected one stays rejected."""
    v = _get(session, name, version, lock=True)
    if v.status in ("validated", "retired"):
        return v.status == "validated", [] if v.status == "validated" else ["bản đã retired"]
    if v.status == "rejected":
        return False, ["bản đã bị từ chối ở lần gate trước"]
    view = _view(session, v)
    path = Path(storage_dir) / v.artifact_key
    reasons: list[str] = []
    if not path.is_file():
        reasons.append(f"thiếu tệp {v.artifact_key}")
    elif sha256_file(path) != view.sha256:
        reasons.append("sha256 của tệp không khớp model_versions.sha256")
    else:
        if name in ONNX_NAMES:
            reasons += _onnx_checks(path, name, len(view.class_map))
    if name == "detector":
        if sorted(view.class_map) != list(range(len(view.class_map))):
            reasons.append("bản đồ lớp không phủ liên tục 0..n-1")
        serving = view.metrics.get("serving") or {}
        for k in ("conf", "iou"):
            if not isinstance(serving.get(k), int | float) or not 0 < serving[k] < 1:
                reasons.append(f"metrics.serving.{k} thiếu hoặc ngoài (0, 1)")
    report_key = f"models/{name}/{version}/gate.json"
    report = {"name": name, "version": version, "passed": not reasons, "reasons": reasons, "at": utcnow().isoformat()}
    rp = Path(storage_dir) / report_key
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    v.gate_report_key = report_key
    v.status = "rejected" if reasons else "validated"
    session.flush()
    return not reasons, reasons


# ---------------------------------------------------------------- deploy / rollback (UC30)


def deploy(
    session: Session, *, name: str, version: str, switched_by: uuid.UUID | None = None, only_if_none: bool = False
) -> tuple[bool, DeploymentView | None]:
    """(changed, deployment). `only_if_none`: bootstrap the pointer only when the name has no deployment yet."""
    _check_name(name)
    v = _get(session, name, version)
    d = session.scalars(select(ModelDeployment).where(ModelDeployment.name == name).with_for_update()).one_or_none()
    if d is not None and (only_if_none or d.active_version_id == v.id):
        return False, _deployment(d)
    if v.status != "validated":
        raise MlopsError(f"{name} {version} ở trạng thái {v.status}; chỉ deploy bản validated (tastoria mlops gate)")
    now = utcnow()
    if d is None:
        d = ModelDeployment(name=name, active_version_id=v.id, previous_version_id=None, switched_at=now)
        d.switched_by = switched_by
        session.add(d)
    else:
        if d.previous_version_id is not None and d.previous_version_id != v.id:
            old = session.get(ModelVersion, d.previous_version_id)
            if old is not None and old.status == "validated":
                old.status = "retired"  # leaves the rollback slot (ST07)
        d.previous_version_id, d.active_version_id = d.active_version_id, v.id
        d.switched_at, d.switched_by = now, switched_by
    session.flush()
    return True, _deployment(d)


def rollback(session: Session, *, name: str, switched_by: uuid.UUID | None = None) -> DeploymentView:
    _check_name(name)
    d = session.scalars(select(ModelDeployment).where(ModelDeployment.name == name).with_for_update()).one_or_none()
    if d is None or d.previous_version_id is None:
        raise MlopsError(f"{name}: không có bản trước để quay lui")
    d.active_version_id, d.previous_version_id = d.previous_version_id, d.active_version_id
    d.switched_at, d.switched_by = utcnow(), switched_by
    session.flush()
    return _deployment(d)


def _deployment(d: ModelDeployment) -> DeploymentView:
    return DeploymentView(d.name, d.active_version_id, d.previous_version_id, d.switched_at)


# ---------------------------------------------------------------- reading


def active_version(session: Session, name: str) -> ModelVersionView | None:
    row = session.execute(
        select(ModelVersion)
        .join(ModelDeployment, ModelDeployment.active_version_id == ModelVersion.id)
        .where(ModelDeployment.name == name)
    ).scalar_one_or_none()
    return _view(session, row, {row.id}) if row is not None else None


def list_versions(session: Session, name: str | None = None) -> list[ModelVersionView]:
    q = select(ModelVersion).order_by(ModelVersion.name, ModelVersion.created_at)
    if name:
        q = q.where(ModelVersion.name == name)
    active = set(session.scalars(select(ModelDeployment.active_version_id)))
    return [_view(session, v, active) for v in session.scalars(q)]


def version_view(session: Session, version_id: uuid.UUID) -> ModelVersionView | None:
    v = session.get(ModelVersion, version_id)
    return _view(session, v) if v is not None else None


# ---------------------------------------------------------------- loading


def artifact_path(storage_dir: Path, view: ModelVersionView, *, verify: bool = True) -> Path:
    """Path of the stored artifact; with `verify`, refuses a missing file or a SHA-256 mismatch (SD10)."""
    path = Path(storage_dir) / view.artifact_key
    if not path.is_file():
        raise MlopsError(f"{view.name} {view.version}: thiếu tệp {view.artifact_key}")
    if verify and sha256_file(path) != view.sha256:
        raise MlopsError(f"{view.name} {view.version}: sha256 của {view.artifact_key} không khớp")
    return path


_sessions: dict[tuple[uuid.UUID, int], Any] = {}
_sessions_lock = threading.Lock()


def load_onnx(storage_dir: Path, view: ModelVersionView, *, intra_op_threads: int = 2) -> Any:
    """onnxruntime.InferenceSession of a registered version, created once per process (spec v2 §8: intra-op threads
    = 2, inter-op 1, sequential, no spinning) after the SHA-256 check."""
    key = (view.id, intra_op_threads)
    with _sessions_lock:
        if key in _sessions:
            return _sessions[key]
        import onnxruntime as ort

        path = artifact_path(storage_dir, view)
        so = ort.SessionOptions()
        so.intra_op_num_threads = intra_op_threads
        so.inter_op_num_threads = 1
        so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        so.add_session_config_entry("session.intra_op.allow_spinning", "0")
        so.add_session_config_entry("session.inter_op.allow_spinning", "0")
        sess = ort.InferenceSession(str(path), so, providers=["CPUExecutionProvider"])
        _sessions[key] = sess
        return sess
