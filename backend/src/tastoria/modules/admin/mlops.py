"""Operator commands on model versions (UC29, UC30; SD10): `tastoria mlops register | gate | deploy | rollback | list`.

Each command runs in one Unit of Work with one audit_log row (actor_role `ml_operator`; the CLI has no logged-in
actor, so actor_user_id is NULL as for the catalog import). A refused command (MlopsError) writes nothing but an
audit row of the refusal.
"""

from __future__ import annotations

import ast
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from tastoria.core.db import UnitOfWork, run_in_uow
from tastoria.modules.mlops import service as mlops
from tastoria.modules.mlops.schemas import MlopsError, ModelVersionView
from tastoria.modules.privacy import service as privacy


def _audit(uow: UnitOfWork, action: str, entity: str, entity_id: str, outcome: str) -> None:
    privacy.write_audit(
        uow.session,
        action=action,
        entity=entity,
        entity_id=entity_id[:128],
        purpose=outcome[:256],
        actor_role="ml_operator",
    )


def _refused(sm: sessionmaker[Session], action: str, entity: str, entity_id: str, exc: Exception) -> None:
    run_in_uow(sm, lambda uow: _audit(uow, action, entity, entity_id, f"refused: {exc}"))


def view_dict(v: ModelVersionView) -> dict[str, Any]:
    d = asdict(v)
    d["id"] = str(v.id)
    d["created_at"] = v.created_at.isoformat()
    d["metrics"] = {k: v.metrics[k] for k in ("serving", "eval") if k in v.metrics}  # keep the CLI output short
    return d


def onnx_class_names(path: Path) -> list[str] | None:
    """Class codes from the `names` metadata ultralytics writes into an exported ONNX ({0: 'ca', 1: 'tom', …})."""
    import onnxruntime as ort

    meta = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"]).get_modelmeta().custom_metadata_map
    raw = meta.get("names")
    if not raw:
        return None
    names = ast.literal_eval(raw)
    return [names[i] for i in sorted(names)]


def register(
    sm: sessionmaker[Session],
    storage_dir: Path,
    *,
    name: str,
    version: str,
    artifact: Path,
    metrics: dict[str, Any],
    preprocess_version: str | None,
    class_codes: list[str] | None,
    mlflow_run_id: str | None = None,
) -> tuple[ModelVersionView, bool]:
    if class_codes is None and name == "detector" and Path(artifact).suffix == ".onnx":
        class_codes = onnx_class_names(Path(artifact))

    def work(uow: UnitOfWork) -> tuple[ModelVersionView, bool]:
        view, created = mlops.register(
            uow.session,
            storage_dir=storage_dir,
            name=name,
            version=version,
            artifact=Path(artifact),
            metrics=metrics,
            preprocess_version=preprocess_version,
            class_codes=class_codes,
            mlflow_run_id=mlflow_run_id,
        )
        _audit(uow, "model_register", "model_versions", str(view.id), "created" if created else "unchanged")
        return view, created

    try:
        return run_in_uow(sm, work)  # type: ignore[return-value]
    except MlopsError as exc:
        _refused(sm, "model_register", "model_versions", f"{name}:{version}", exc)
        raise


def gate(sm: sessionmaker[Session], storage_dir: Path, *, name: str, version: str) -> tuple[bool, list[str]]:
    def work(uow: UnitOfWork) -> tuple[bool, list[str]]:
        ok, reasons = mlops.gate(uow.session, storage_dir=storage_dir, name=name, version=version)
        _audit(uow, "model_gate", "model_versions", f"{name}:{version}", "passed" if ok else "; ".join(reasons))
        return ok, reasons

    try:
        return run_in_uow(sm, work)  # type: ignore[return-value]
    except MlopsError as exc:
        _refused(sm, "model_gate", "model_versions", f"{name}:{version}", exc)
        raise


def deploy(sm: sessionmaker[Session], *, name: str, version: str, only_if_none: bool = False) -> dict[str, Any]:
    def work(uow: UnitOfWork) -> dict[str, Any]:
        changed, d = mlops.deploy(uow.session, name=name, version=version, only_if_none=only_if_none)
        if changed:
            _audit(uow, "model_deploy", "model_deployments", name, f"{version}")
        return {
            "changed": changed,
            "name": name,
            "active_version_id": str(d.active_version_id) if d else None,
            "previous_version_id": str(d.previous_version_id) if d and d.previous_version_id else None,
        }

    try:
        return run_in_uow(sm, work)  # type: ignore[return-value]
    except MlopsError as exc:
        _refused(sm, "model_deploy", "model_deployments", name, exc)
        raise


def rollback(sm: sessionmaker[Session], *, name: str) -> dict[str, Any]:
    def work(uow: UnitOfWork) -> dict[str, Any]:
        d = mlops.rollback(uow.session, name=name)
        _audit(uow, "model_rollback", "model_deployments", name, str(d.active_version_id))
        return {"name": name, "active_version_id": str(d.active_version_id),
                "previous_version_id": str(d.previous_version_id)}  # fmt: skip

    try:
        return run_in_uow(sm, work)  # type: ignore[return-value]
    except MlopsError as exc:
        _refused(sm, "model_rollback", "model_deployments", name, exc)
        raise


def list_versions(sm: sessionmaker[Session], name: str | None) -> list[dict[str, Any]]:
    with sm() as s:
        return [view_dict(v) for v in mlops.list_versions(s, name)]


def load_json_arg(arg: str | None, what: str) -> dict[str, Any]:
    """A JSON object given inline, as @file or as a path to a JSON file."""
    if not arg:
        return {}
    p = Path(arg.removeprefix("@"))
    try:
        data = json.loads(p.read_text(encoding="utf-8")) if (arg.startswith("@") or p.is_file()) else json.loads(arg)
    except (OSError, ValueError) as exc:
        raise MlopsError(f"{what}: {exc}") from exc
    if not isinstance(data, dict):
        raise MlopsError(f"{what} phải là một object JSON")
    return data
