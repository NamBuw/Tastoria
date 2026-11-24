"""UC28: `tastoria mlops export-training-data --since YYYY-MM-DD` (pseudonymized training export).

ADR 0001: cross-module reads from identity, events, and scan are injected via `TrainingExportDeps` by `tastoria.cli`.
"""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import os
import shutil
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session, sessionmaker

from tastoria.core.clock import utcnow
from tastoria.core.db import UnitOfWork, run_in_uow
from tastoria.modules.catalog import service as catalog
from tastoria.modules.mlops import service as mlops
from tastoria.modules.privacy import service as privacy


@dataclass(frozen=True)
class TrainingExportDeps:
    active_user_ids: Callable[[Session, Iterable[uuid.UUID]], set[uuid.UUID]]
    export_interactions_since: Callable[..., Sequence[Any]]
    export_contributed_scans_since: Callable[..., Any]


@dataclass
class TrainingExportResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    report: dict[str, Any] = field(default_factory=dict)


def hmac_alias(key_bytes: bytes, raw_id: uuid.UUID) -> str:
    return hmac.new(key_bytes, raw_id.bytes, hashlib.sha256).hexdigest()


def _csv_bytes(header: list[str], rows: list[list[Any]]) -> bytes:
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue().encode("utf-8")


def _audit(uow: UnitOfWork, entity_id: str | None, outcome: str) -> None:
    privacy.write_audit(
        uow.session,
        action="training_export",
        entity="training_data",
        entity_id=entity_id[:128] if entity_id else None,
        purpose=outcome[:256],
        actor_role="ml_operator",
    )


def _record_failure(sm: sessionmaker[Session], since_str: str, reason: str) -> None:
    run_in_uow(sm, lambda uow: _audit(uow, since_str or None, f"failed: {reason}"))


def _coarsen(dt: datetime, tz: ZoneInfo) -> str:
    return dt.astimezone(tz).date().isoformat()


def export_training_data(
    sm: sessionmaker[Session],
    storage_dir: Path,
    *,
    since_str: str,
    out_base: Path,
    hmac_key: str | None,
    hmac_key_id: str,
    hmac_key_file: Path | None = None,
    dsr_hmac_key: str | None = None,
    tz_name: str = "Asia/Ho_Chi_Minh",
    deps: TrainingExportDeps,
) -> TrainingExportResult:
    tz = ZoneInfo(tz_name)
    now = utcnow()
    today_local = now.astimezone(tz).date()

    try:
        since_date = date.fromisoformat(since_str)
    except ValueError:
        msg = f"ngày --since không hợp lệ (cần YYYY-MM-DD): {since_str}"
        _record_failure(sm, since_str, "invalid_since")
        return TrainingExportResult(False, errors=[msg])

    if since_date > today_local:
        msg = f"--since {since_date.isoformat()} ở tương lai so với {today_local.isoformat()}"
        _record_failure(sm, since_str, "future_since")
        return TrainingExportResult(False, errors=[msg])

    out_base = Path(out_base)
    if hmac_key_file is not None:
        key_path = Path(hmac_key_file)
        if not key_path.is_file():
            msg = f"không tìm thấy tệp khoá HMAC: {key_path}"
            _record_failure(sm, since_str, "missing_hmac_key_file")
            return TrainingExportResult(False, errors=[msg])
        try:
            resolved_key = key_path.resolve()
            resolved_out = out_base.resolve()
            if resolved_key == resolved_out or resolved_key.is_relative_to(resolved_out):
                msg = "--hmac-key-file không được nằm bên trong thư mục --out (FR-28-12)"
                _record_failure(sm, since_str, "hmac_key_inside_out")
                return TrainingExportResult(False, errors=[msg])
            hmac_key = key_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            msg = f"không đọc được tệp khoá HMAC: {exc}"
            _record_failure(sm, since_str, "unreadable_hmac_key_file")
            return TrainingExportResult(False, errors=[msg])

    if not hmac_key:
        msg = "thiếu khoá HMAC xuất dữ liệu (TASTORIA_TRAINING_EXPORT_HMAC_KEY hoặc --hmac-key-file)"
        _record_failure(sm, since_str, "missing_hmac_key")
        return TrainingExportResult(False, errors=[msg])

    key_bytes = hmac_key.encode("utf-8")
    since_utc = datetime.combine(since_date, time(0, 0), tzinfo=tz)

    def read_and_export(uow: UnitOfWork) -> TrainingExportResult:
        sess = uow.session
        p_consented = privacy.consented_user_ids(sess, "personalization")
        c_consented = privacy.consented_user_ids(sess, "photo_contribution")
        p_users = deps.active_user_ids(sess, p_consented)
        c_users = deps.active_user_ids(sess, c_consented)

        interactions = deps.export_interactions_since(sess, user_ids=p_users, since_utc=since_utc)
        scans = deps.export_contributed_scans_since(sess, user_ids=c_users, since_utc=since_utc)
        revocations = privacy.revocations_since(sess, since_utc=since_utc)
        recipes = catalog.all_recipes_for_export(sess)
        ingredients = catalog.all_ingredients_for_export(sess)
        vclasses = catalog.vision_classes(sess)

        active_models: dict[str, dict[str, str]] = {}
        for mname in mlops.NAMES:
            mv = mlops.active_version(sess, mname)
            if mv is not None:
                active_models[mname] = {"id": str(mv.id), "version": mv.version, "sha256": mv.sha256}

        def alias(uid: uuid.UUID | None) -> str:
            return hmac_alias(key_bytes, uid) if uid is not None else ""

        int_rows = [
            [
                alias(r.user_id),
                str(r.recipe_id),
                alias(r.meal_plan_id),
                alias(r.meal_plan_item_id),
                r.type,
                "" if r.position is None else r.position,
                r.swap_reason or "",
                str(r.ranker_version_id) if r.ranker_version_id else "",
                "" if r.propensity is None else r.propensity,
                _coarsen(r.occurred_at, tz),
            ]
            for r in interactions
        ]

        img_rows: list[list[Any]] = []
        copied_images: list[tuple[Path, str]] = []
        for im in scans.images:
            s_alias = alias(im.scan_id)
            rel = f"images/{s_alias}_{im.ordinal}.jpg"
            src = Path(storage_dir) / im.storage_key
            copied = src.is_file()
            if copied:
                copied_images.append((src, rel))
            img_rows.append(
                [
                    alias(im.image_id),
                    s_alias,
                    alias(im.user_id),
                    im.ordinal,
                    im.shelf_group,
                    im.width,
                    im.height,
                    rel if copied else "",
                    im.mode,
                    str(im.detector_version_id) if im.detector_version_id else "",
                    str(im.classifier_version_id) if im.classifier_version_id else "",
                    im.preprocess_version or "",
                    _coarsen(im.created_at, tz),
                ]
            )

        item_rows = [
            [
                alias(it.item_id),
                alias(it.scan_id),
                alias(it.user_id),
                str(it.ingredient_id),
                it.origin,
                "" if it.model_count is None else it.model_count,
                "" if it.final_count is None else it.final_count,
                it.qty_level or "",
                it.user_action,
                str(it.original_ingredient_id) if it.original_ingredient_id else "",
                it.user_freshness or "",
                _coarsen(it.created_at, tz),
            ]
            for it in scans.items
        ]

        det_rows = [
            [
                d.detection_id,
                alias(d.scan_image_id),
                alias(d.scan_id),
                alias(d.user_id),
                alias(d.scan_item_id),
                d.vision_class_id,
                d.x1,
                d.y1,
                d.x2,
                d.y2,
                d.confidence,
                "" if d.p_tuoi is None else d.p_tuoi,
                "" if d.p_dung_som is None else d.p_dung_som,
                "" if d.p_dung_ngay is None else d.p_dung_ngay,
                "" if d.p_kiem_tra is None else d.p_kiem_tra,
            ]
            for d in scans.detections
        ]

        rev_rows: list[list[Any]] = []
        for rv in revocations:
            if rv.user_id is not None:
                u_alias = alias(rv.user_id)
            elif rv.export_alias:
                u_alias = rv.export_alias
            elif dsr_hmac_key and hmac_key == dsr_hmac_key and rv.subject_ref_hex:
                u_alias = rv.subject_ref_hex
            else:
                u_alias = rv.subject_ref_hex or ""
            rev_rows.append([u_alias, rv.reason, rv.purpose_code, _coarsen(rv.revoked_at, tz)])

        rec_rows = [[str(r.id), r.name_vi, r.slot, r.method_code, r.status] for r in recipes]
        ing_rows = [[str(i.id), i.name_vi, i.food_group_code, str(i.is_staple).lower()] for i in ingredients]
        vc_rows = [
            [
                vc.id,
                vc.code,
                vc.name_vi,
                str(vc.countable).lower(),
                str(vc.has_freshness_model).lower(),
                str(vc.default_ingredient_id) if vc.default_ingredient_id else "",
            ]
            for vc in sorted(vclasses.values(), key=lambda x: x.id)
        ]

        csv_specs: list[tuple[str, list[str], list[list[Any]]]] = [
            (
                "interactions.csv",
                [
                    "user_alias",
                    "recipe_id",
                    "meal_plan_alias",
                    "meal_plan_item_alias",
                    "type",
                    "position",
                    "swap_reason",
                    "ranker_version_id",
                    "propensity",
                    "occurred_date",
                ],
                int_rows,
            ),
            (
                "contributed_images.csv",
                [
                    "scan_image_alias",
                    "scan_alias",
                    "user_alias",
                    "ordinal",
                    "shelf_group",
                    "width",
                    "height",
                    "image_path",
                    "mode",
                    "detector_version_id",
                    "classifier_version_id",
                    "preprocess_version",
                    "created_date",
                ],
                img_rows,
            ),
            (
                "scan_items.csv",
                [
                    "scan_item_alias",
                    "scan_alias",
                    "user_alias",
                    "ingredient_id",
                    "origin",
                    "model_count",
                    "final_count",
                    "qty_level",
                    "user_action",
                    "original_ingredient_id",
                    "user_freshness",
                    "created_date",
                ],
                item_rows,
            ),
            (
                "detections.csv",
                [
                    "detection_id",
                    "scan_image_alias",
                    "scan_alias",
                    "user_alias",
                    "scan_item_alias",
                    "vision_class_id",
                    "x1",
                    "y1",
                    "x2",
                    "y2",
                    "confidence",
                    "p_tuoi",
                    "p_dung_som",
                    "p_dung_ngay",
                    "p_kiem_tra",
                ],
                det_rows,
            ),
            (
                "revoked_aliases.csv",
                ["user_alias", "reason", "purpose_code", "revoked_date"],
                rev_rows,
            ),
            (
                "recipes.csv",
                ["recipe_id", "name_vi", "slot", "method_code", "status"],
                rec_rows,
            ),
            (
                "ingredients.csv",
                ["ingredient_id", "name_vi", "food_group_code", "is_staple"],
                ing_rows,
            ),
            (
                "vision_classes.csv",
                ["vision_class_id", "code", "name_vi", "countable", "has_freshness_model", "default_ingredient_id"],
                vc_rows,
            ),
        ]

        out_base.mkdir(parents=True, exist_ok=True)
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        final = out_base / f"training-{since_date.isoformat()}-{stamp}"
        suffix = 1
        while final.exists():
            suffix += 1
            final = out_base / f"training-{since_date.isoformat()}-{stamp}-{suffix}"
        tmp = out_base / f".{final.name}.partial"

        files_meta: dict[str, dict[str, Any]] = {}
        try:
            tmp.mkdir()
            for fname, header, rows in csv_specs:
                data = _csv_bytes(header, rows)
                (tmp / fname).write_bytes(data)
                files_meta[fname] = {"sha256": hashlib.sha256(data).hexdigest(), "rows": len(rows)}
            if copied_images:
                (tmp / "images").mkdir(exist_ok=True)
                for src, rel in copied_images:
                    dst = tmp / rel
                    shutil.copyfile(src, dst)
                    files_meta[rel] = {"sha256": hashlib.sha256(dst.read_bytes()).hexdigest(), "rows": 1}
            manifest = {
                "schema_version": "training-export.v1",
                "since": since_date.isoformat(),
                "exported_at": now.isoformat(),
                "timezone": tz_name,
                "hmac_key_id": hmac_key_id,
                "active_models": active_models,
                "counts": {
                    "interactions": len(int_rows),
                    "contributed_images": len(img_rows),
                    "copied_images": len(copied_images),
                    "scan_items": len(item_rows),
                    "detections": len(det_rows),
                    "revoked_aliases": len(rev_rows),
                },
                "files": files_meta,
            }
            (tmp / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            os.rename(tmp, final)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise

        _audit(
            uow,
            final.name,
            f"ok: since={since_date.isoformat()} interactions={len(int_rows)} images={len(img_rows)}",
        )
        return TrainingExportResult(
            True,
            report={
                "directory": str(final),
                "since": since_date.isoformat(),
                "hmac_key_id": hmac_key_id,
                "counts": manifest["counts"],
                "files": files_meta,
            },
        )

    try:
        return run_in_uow(sm, read_and_export)  # type: ignore[return-value]
    except OSError as exc:
        _record_failure(sm, since_str, f"os_error:{exc.__class__.__name__}")
        return TrainingExportResult(False, errors=[f"ghi tệp xuất lỗi: {exc}"])
