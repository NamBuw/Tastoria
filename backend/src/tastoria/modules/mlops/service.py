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
import re
import shutil
import threading
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from tastoria.core import pagination
from tastoria.core.clock import utcnow
from tastoria.modules.catalog import service as catalog
from tastoria.modules.mlops.models import ModelDeployment, ModelVersion, ModelVersionClass
from tastoria.modules.mlops.schemas import DeploymentView, MlopsError, ModelVersionView

NAMES = (
    "detector",
    "freshness",
    "ranker",
    "substitution",
    "meal_calorie",
    "dish_classifier",
    "mushroom_classifier",
)
ONNX_NAMES = ("detector", "freshness", "meal_calorie", "dish_classifier", "mushroom_classifier")
NPZ_NAMES = ("ranker", "substitution")


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
        gate_report_key=v.gate_report_key,
        mlflow_run_id=v.mlflow_run_id,
    )


def _get(session: Session, name: str, version: str, *, lock: bool = False) -> ModelVersion:
    q = select(ModelVersion).where(ModelVersion.name == name, ModelVersion.version == version)
    if lock:
        q = q.with_for_update()
    v = session.scalars(q).one_or_none()
    if v is None:
        raise MlopsError(f"{name} {version}: chưa đăng ký")
    return v


_VERSION_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def _check_name(name: str) -> None:
    if name not in NAMES:
        raise MlopsError(f"tên mô hình {name!r} không hợp lệ (một trong {', '.join(NAMES)})")


def _check_version(version: str) -> None:
    if not isinstance(version, str) or version in {".", ".."} or not _VERSION_RE.match(version):
        raise MlopsError(f"phiên bản {version!r} không hợp lệ (chỉ cho phép [A-Za-z0-9._-], 1..128 ký tự)")


def _safe_model_path(storage_dir: Path, name: str, rel_key: str) -> Path:
    _check_name(name)
    base = (Path(storage_dir) / "models" / name).resolve()
    target = (Path(storage_dir) / rel_key).resolve()
    if not target.is_relative_to(base):
        raise MlopsError(f"đường dẫn mô hình không hợp lệ: {rel_key!r}")
    return target


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
    _check_version(version)
    artifact = Path(artifact)
    if not artifact.is_file():
        raise MlopsError(f"không có tệp {artifact}")
    if artifact.name in {"", ".", ".."} or "/" in artifact.name or "\\" in artifact.name:
        raise MlopsError(f"tên tệp mô hình không hợp lệ: {artifact.name!r}")
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
    dst = _safe_model_path(Path(storage_dir), name, key)
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
    elif name == "freshness":
        inp = sess.get_inputs()[0].shape
        if len(inp) != 4 or inp[1] != 3 or not isinstance(inp[2], int) or inp[2] != inp[3]:
            problems.append(f"đầu vào {inp} không phải ảnh RGB vuông [N, 3, S, S]")
        outs = sess.get_outputs()
        if not outs or len(outs[0].shape) != 2 or outs[0].shape[1] != 3:
            problems.append(f"đầu ra {[o.shape for o in outs]} không khớp [N, 3]")
        elif len(outs) >= 2 and (len(outs[1].shape) != 2 or outs[1].shape[1] != 3):
            problems.append(f"đầu ra thứ 2 {outs[1].shape} không khớp [N, 3]")
    elif name == "meal_calorie":
        inp = sess.get_inputs()[0].shape
        if len(inp) != 4 or inp[1] != 3 or not isinstance(inp[2], int) or inp[2] != inp[3]:
            problems.append(f"đầu vào {inp} không phải ảnh RGB vuông [N, 3, S, S]")
        outs = sess.get_outputs()
        if not outs or len(outs[0].shape) != 2 or not isinstance(outs[0].shape[1], int) or outs[0].shape[1] < 5:
            problems.append(f"đầu ra {[o.shape for o in outs]} không khớp [N, D>=5]")
    elif name in ("dish_classifier", "mushroom_classifier"):
        inp = sess.get_inputs()[0].shape
        if len(inp) != 4 or inp[1] != 3 or not isinstance(inp[2], int) or inp[2] != inp[3]:
            problems.append(f"đầu vào {inp} không phải ảnh RGB vuông [N, 3, S, S]")
        outs = sess.get_outputs()
        if not outs or len(outs[0].shape) != 2 or not isinstance(outs[0].shape[1], int) or outs[0].shape[1] < 2:
            problems.append(f"đầu ra {[o.shape for o in outs]} không khớp [N, C>=2]")
    return problems


_RANKER_KEYS = frozenset(
    {
        "schema_version",
        "recipe_names",
        "recipe_slots",
        "feature_names",
        "X_content",
        "item_prior",
        "mf_mu",
        "mf_lam",
        "mf_bi",
        "mf_Q",
        "bpr_b",
        "bpr_Q",
        "norm_stats",
        "hybrid_weights",
    }
)


def _npz_checks(path: Path, name: str) -> list[str]:
    import numpy as np

    try:
        z = np.load(path, allow_pickle=False)
    except Exception as exc:  # noqa: BLE001
        return [f"numpy không nạp được: {exc}"]
    problems: list[str] = []
    with z:
        keys = set(z.files)
        if name == "ranker":
            missing = sorted(_RANKER_KEYS - keys)
            if missing:
                return [f"ranker thiếu mảng {missing}"]
            for k in _RANKER_KEYS:
                arr = z[k]
                if arr.dtype == object:
                    problems.append(f"mảng {k} có dtype object")
                elif np.issubdtype(arr.dtype, np.number) and not np.all(np.isfinite(arr)):
                    problems.append(f"mảng {k} có giá trị NaN/Inf")
            ns = np.asarray(z["norm_stats"], dtype=np.float64).ravel()
            if ns.shape != (8,) or np.any(ns[1::2] <= 0):
                problems.append("norm_stats phải có shape (8,) với std > 0")
            hw = np.asarray(z["hybrid_weights"], dtype=np.float64).ravel()
            if hw.shape != (4,):
                problems.append("hybrid_weights phải có shape (4,)")
        elif name == "substitution":
            missing = sorted({"vectors", "names_vi"} - keys)
            if missing:
                return [f"substitution thiếu mảng {missing}"]
            vecs = z["vectors"]
            names = z["names_vi"]
            if vecs.ndim != 2 or vecs.shape[1] != 100 or vecs.shape[0] == 0:
                problems.append(f"vectors {vecs.shape} phải có dạng (N, 100)")
            elif not np.all(np.isfinite(vecs)):
                problems.append("vectors có giá trị NaN/Inf")
            elif np.any(np.linalg.norm(vecs, axis=1) <= 0):
                problems.append("vectors có vector chuẩn 0")
            if len(names) != vecs.shape[0]:
                problems.append("độ dài names_vi không khớp số dòng vectors")
    return problems


def gate(session: Session, *, storage_dir: Path, name: str, version: str) -> tuple[bool, list[str]]:
    """(passed, reasons). A validated version re-gates as passed without change; a rejected one stays rejected."""
    _check_name(name)
    _check_version(version)
    v = _get(session, name, version, lock=True)
    if v.status in ("validated", "retired"):
        return v.status == "validated", [] if v.status == "validated" else ["bản đã retired"]
    if v.status == "rejected":
        return False, ["bản đã bị từ chối ở lần gate trước"]
    view = _view(session, v)
    path = _safe_model_path(Path(storage_dir), name, v.artifact_key)
    reasons: list[str] = []
    if not path.is_file():
        reasons.append(f"thiếu tệp {v.artifact_key}")
    elif sha256_file(path) != view.sha256:
        reasons.append("sha256 của tệp không khớp model_versions.sha256")
    else:
        if name in ONNX_NAMES:
            reasons += _onnx_checks(path, name, len(view.class_map))
        elif name in NPZ_NAMES:
            reasons += _npz_checks(path, name)
    if name == "detector":
        if sorted(view.class_map) != list(range(len(view.class_map))):
            reasons.append("bản đồ lớp không phủ liên tục 0..n-1")
        serving = view.metrics.get("serving") or {}
        for k in ("conf", "iou"):
            val = serving.get(k)
            if isinstance(val, bool) or not isinstance(val, int | float) or not 0 < val < 1:
                reasons.append(f"metrics.serving.{k} thiếu hoặc ngoài (0, 1)")
        ag = serving.get("agnostic_iou")
        if ag is not None and (isinstance(ag, bool) or not isinstance(ag, int | float) or not 0 < ag < 1):
            reasons.append("metrics.serving.agnostic_iou ngoài (0, 1)")
        cc = serving.get("class_conf")
        if cc is not None and (
            not isinstance(cc, dict)
            or any(isinstance(v, bool) or not isinstance(v, int | float) or not 0 < v <= 1 for v in cc.values())
        ):
            reasons.append("metrics.serving.class_conf phải là object {code: (0, 1]}")
    elif name == "freshness":
        serving = view.metrics.get("serving") or {}
        abst = serving.get("abstention")
        if isinstance(abst, dict) and "tau" in abst:
            tau = abst["tau"]
            if not isinstance(tau, int | float) or not 0 < tau <= 1:
                reasons.append("metrics.serving.abstention.tau ngoài (0, 1]")
        inp_cfg = serving.get("input")
        if isinstance(inp_cfg, dict) and "pad_value" in inp_cfg:
            pv = inp_cfg["pad_value"]
            if not isinstance(pv, int | float) or not 0 <= pv <= 255:
                reasons.append("metrics.serving.input.pad_value ngoài [0, 255]")
    elif name in ("dish_classifier", "mushroom_classifier"):
        serving = view.metrics.get("serving") or {}
        if "classes" in serving:
            classes = serving["classes"]
            if not isinstance(classes, list) or len(classes) < 2:
                reasons.append("metrics.serving.classes phải là danh sách >= 2 lớp")
            elif "n_classes" in serving and serving["n_classes"] != len(classes):
                reasons.append("metrics.serving.n_classes không khớp độ dài classes")
        if "conf_threshold" in serving:
            ct = serving["conf_threshold"]
            if isinstance(ct, bool) or not isinstance(ct, int | float) or not 0 < ct <= 1:
                reasons.append("metrics.serving.conf_threshold ngoài (0, 1]")
        if "temperature" in serving:
            temp = serving["temperature"]
            if isinstance(temp, bool) or not isinstance(temp, int | float) or temp <= 0:
                reasons.append("metrics.serving.temperature phải > 0")
    elif name == "meal_calorie":
        serving = view.metrics.get("serving") or {}
        if "outputs" in serving:
            outs_cfg = serving["outputs"]
            if not isinstance(outs_cfg, dict):
                reasons.append("metrics.serving.outputs phải là object")
            elif "columns" in outs_cfg:
                cols = outs_cfg["columns"]
                if not isinstance(cols, list) or len(cols) < 5:
                    reasons.append("metrics.serving.outputs.columns phải có >= 5 cột")
    report_key = f"models/{name}/{version}/gate.json"
    report = {"name": name, "version": version, "passed": not reasons, "reasons": reasons, "at": utcnow().isoformat()}
    rp = _safe_model_path(Path(storage_dir), name, report_key)
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
    return DeploymentView(d.name, d.active_version_id, d.previous_version_id, d.switched_at, d.switched_by)


# ---------------------------------------------------------------- reading


def active_version_id(session: Session, name: str) -> uuid.UUID | None:
    _check_name(name)
    return session.execute(
        select(ModelDeployment.active_version_id).where(ModelDeployment.name == name)
    ).scalar_one_or_none()


def active_version(session: Session, name: str) -> ModelVersionView | None:
    row = session.execute(
        select(ModelVersion)
        .join(ModelDeployment, ModelDeployment.active_version_id == ModelVersion.id)
        .where(ModelDeployment.name == name)
    ).scalar_one_or_none()
    return _view(session, row, {row.id}) if row is not None else None


def active_versions_map(session: Session) -> dict[str, ModelVersionView]:
    """Fetch every deployed ModelVersion + its ModelVersionClass map in a single SQL query."""
    rows = session.execute(
        select(ModelVersion, ModelVersionClass)
        .join(ModelDeployment, ModelDeployment.active_version_id == ModelVersion.id)
        .outerjoin(ModelVersionClass, ModelVersionClass.model_version_id == ModelVersion.id)
    ).all()
    versions: dict[str, ModelVersion] = {}
    class_maps: dict[uuid.UUID, dict[int, int]] = {}
    for mv, mvc in rows:
        versions.setdefault(mv.name, mv)
        if mvc is not None:
            class_maps.setdefault(mv.id, {})[mvc.class_index] = mvc.vision_class_id
    return {
        name: ModelVersionView(
            id=v.id,
            name=v.name,
            version=v.version,
            artifact_key=v.artifact_key,
            sha256=bytes(v.sha256).hex(),
            preprocess_version=v.preprocess_version,
            metrics=dict(v.metrics or {}),
            status=v.status,
            created_at=v.created_at,
            class_map=class_maps.get(v.id, {}),
            is_active=True,
            gate_report_key=v.gate_report_key,
            mlflow_run_id=v.mlflow_run_id,
        )
        for name, v in versions.items()
    }


def list_versions(session: Session, name: str | None = None) -> list[ModelVersionView]:
    q = select(ModelVersion).order_by(ModelVersion.name, ModelVersion.created_at)
    if name:
        q = q.where(ModelVersion.name == name)
    active = set(session.scalars(select(ModelDeployment.active_version_id)))
    return [_view(session, v, active) for v in session.scalars(q)]


def list_versions_page(
    session: Session,
    *,
    name: str | None,
    status: str | None,
    cursor: str | None,
    limit: int,
) -> tuple[list[ModelVersionView], str | None, list[DeploymentView]]:
    after = pagination.decode_created(cursor)
    q = select(ModelVersion).order_by(ModelVersion.created_at.desc(), ModelVersion.id.desc()).limit(limit + 1)
    if name:
        q = q.where(ModelVersion.name == name)
    if status:
        q = q.where(ModelVersion.status == status)
    if after is not None:
        q = q.where(tuple_(ModelVersion.created_at, ModelVersion.id) < after)
    rows = list(session.scalars(q))
    page = rows[:limit]
    active = set(session.scalars(select(ModelDeployment.active_version_id)))
    nxt = pagination.encode_created(page[-1].created_at, page[-1].id) if len(rows) > limit else None
    deployments = [_deployment(d) for d in session.scalars(select(ModelDeployment).order_by(ModelDeployment.name))]
    return [_view(session, v, active) for v in page], nxt, deployments


def version_view(session: Session, version_id: uuid.UUID) -> ModelVersionView | None:
    v = session.get(ModelVersion, version_id)
    return _view(session, v) if v is not None else None


# ---------------------------------------------------------------- loading


def artifact_path(storage_dir: Path, view: ModelVersionView, *, verify: bool = True) -> Path:
    """Path of the stored artifact; with `verify`, refuses a missing file or a SHA-256 mismatch (SD10)."""
    path = _safe_model_path(Path(storage_dir), view.name, view.artifact_key)
    if not path.is_file():
        raise MlopsError(f"{view.name} {view.version}: thiếu tệp {view.artifact_key}")
    if verify and sha256_file(path) != view.sha256:
        raise MlopsError(f"{view.name} {view.version}: sha256 của {view.artifact_key} không khớp")
    return path


_sessions: dict[tuple[uuid.UUID, int], Any] = {}
_session_names: dict[tuple[uuid.UUID, int], str] = {}
_sessions_lock = threading.Lock()


def evict_onnx_cache(name: str | None = None, *, keep_version_id: uuid.UUID | None = None) -> int:
    """Drop cached ONNX sessions (for a model name or all) except `keep_version_id`."""
    removed = 0
    with _sessions_lock:
        for key in list(_sessions):
            vid, _threads = key
            if name is not None and _session_names.get(key) != name:
                continue
            if keep_version_id is not None and vid == keep_version_id:
                continue
            _sessions.pop(key, None)
            _session_names.pop(key, None)
            removed += 1
    return removed


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
        _session_names[key] = view.name
        return sess
