"""admin public interface (M15): staff operations run from the CLI: `tastoria catalog import` (UC25),
`tastoria catalog substitutes import` (the curated substitution table, design v2 §6.3 (a)) and `tastoria survey ...`
(UC24), plus GET /admin/surveys.

The import validates the whole bundle before opening a transaction, writes it in one Unit of Work together with
one audit_log row (action `catalog.import`, actor_role `curator`), and on any blocking problem writes nothing to the
catalog but still records the failed run in audit_log (UC25 2a, FR-25-15).
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from tastoria.core.clock import utcnow
from tastoria.core.db import UnitOfWork, run_in_uow
from tastoria.modules.admin import substitutes as subs_file
from tastoria.modules.admin.schemas import ModelDeploymentOut, ModelVersionOut, ModelVersionPage
from tastoria.modules.catalog import service as catalog
from tastoria.modules.mlops import service as mlops
from tastoria.modules.privacy import schemas as privacy_schemas
from tastoria.modules.privacy import service as privacy
from tastoria.modules.substitute import service as substitute
from tastoria.modules.survey import schemas as survey_schemas
from tastoria.modules.survey import service as survey


@dataclass
class CatalogImportResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    report: dict[str, Any] = field(default_factory=dict)


def _audit(uow: UnitOfWork, outcome: str, entity_id: str | None) -> None:
    privacy.write_audit(
        uow.session,
        action="catalog.import",
        entity="catalog",
        entity_id=entity_id,
        purpose=outcome,
        actor_role="curator",
    )


def import_catalog(sm: sessionmaker[Session], bundle_dir: Path, processed: Path | None = None) -> CatalogImportResult:
    processed = Path(processed) if processed else Path(bundle_dir).parent / "processed"
    bundle = catalog.validate_bundle(Path(bundle_dir), processed)
    if not bundle.ok:
        run_in_uow(sm, lambda uow: _audit(uow, "failed: validation", bundle.content_sha()[:16]))
        return CatalogImportResult(False, errors=list(bundle.errors), report={"warnings": bundle.warnings})

    def work(uow: UnitOfWork) -> dict[str, Any]:
        rep = catalog.import_bundle(uow.session, bundle, processed).as_dict()
        _audit(uow, f"ok: {rep['changes']} changes", rep["data_version"][:64])
        return rep

    try:
        report = run_in_uow(sm, work)
    except ValueError as exc:
        run_in_uow(sm, lambda uow: _audit(uow, "failed: safety check", bundle.content_sha()[:16]))
        return CatalogImportResult(False, errors=str(exc).splitlines())
    return CatalogImportResult(True, report=report)  # type: ignore[arg-type]


# ---------------------------------------------------------------- curated substitution table


@dataclass
class SubstituteImportResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    report: dict[str, Any] = field(default_factory=dict)


def import_substitutes(sm: sessionmaker[Session], path: Path) -> SubstituteImportResult:
    """Validate `substitution_pairs.yaml` against the imported catalog and make the curated rows of
    substitution_pairs equal to it, in one Unit of Work with one audit_log row (action `catalog.substitutes.import`,
    actor_role `curator`). Re-running an unchanged file reports 0 changes. On any problem nothing is written to the
    table; the failed run is still audited."""
    path = Path(path)
    try:
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        sha = ""
    parsed = subs_file.parse(path)

    def audit(uow: UnitOfWork, outcome: str) -> None:
        privacy.write_audit(
            uow.session,
            action="catalog.substitutes.import",
            entity="substitution_pairs",
            entity_id=sha[:16] or None,
            purpose=outcome,
            actor_role="curator",
        )

    def work(uow: UnitOfWork) -> SubstituteImportResult:
        names = {v.name_vi: v for v in catalog.active_ingredients(uow.session).values()}
        pairs, errors = subs_file.resolve(parsed, names, catalog.cooking_method_codes(uow.session))
        if errors:
            audit(uow, "failed: validation")  # nothing else was written in this transaction
            return SubstituteImportResult(False, errors=errors)
        counts = substitute.sync_curated_pairs(uow.session, pairs)
        changes = counts["inserted"] + counts["updated"] + counts["removed"]
        audit(uow, f"ok: {changes} changes")
        return SubstituteImportResult(True, report={"pairs": len(pairs), **counts, "changes": changes, "sha256": sha})

    return run_in_uow(sm, work)  # type: ignore[return-value]


# ---------------------------------------------------------------- taste survey (UC24)
# Staff run these from the CLI inside the `api` container; access to the container is the ml_operator check, as
# for `tastoria catalog import` (actor_role recorded in audit_log). GET /admin/surveys checks the JWT role.

SURVEY_ROLE = "ml_operator"
PRIVILEGED_ROLES = frozenset({"admin", "curator", "ml_operator"})


def _write_coalesced_read_audit(
    session: Session,
    *,
    action: str,
    entity: str,
    actor_user_id: uuid.UUID,
    actor_role: str,
    cursor: str | None,
    cooldown_s: int = 60,
) -> None:
    if cursor is not None:
        return
    recent = privacy.list_audit_log(
        session,
        actor_user_id=actor_user_id,
        entity=entity,
        action=action,
        from_dt=utcnow() - timedelta(seconds=cooldown_s),
        to_dt=None,
        cursor=None,
        limit=1,
    )
    if recent.items:
        return
    privacy.write_audit(
        session,
        action=action,
        entity=entity,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
    )


@dataclass
class SurveyCommandResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    report: dict[str, Any] = field(default_factory=dict)


def _survey_audit(uow: UnitOfWork, action: str, entity_id: str | None, outcome: str) -> None:
    privacy.write_audit(
        uow.session, action=action, entity="survey_forms", entity_id=entity_id, purpose=outcome, actor_role=SURVEY_ROLE
    )


def survey_open_form(sm: sessionmaker[Session]) -> survey_schemas.SurveyFormSummary | None:
    return run_in_uow(sm, lambda uow: survey.open_form_summary(uow.session))  # type: ignore[return-value]


def create_survey_form(
    sm: sessionmaker[Session], *, n_anchor: int, n_random: int, seed: int | None, today: date
) -> SurveyCommandResult:
    """FR-24-01..04, FR-24-06: one transaction (close the open form, new form + anchors) and one audit_log row; a
    refused run writes only its audit_log row. The seed is printed and kept in audit_log.purpose."""

    def work(uow: UnitOfWork) -> SurveyCommandResult:
        try:
            with uow.session.begin_nested():
                made = survey.create_form(uow.session, n_anchor=n_anchor, n_random=n_random, seed=seed, today=today)
        except survey.SurveyFormError as exc:
            _survey_audit(uow, "survey.create_form", None, f"failed: {exc}"[:500])
            return SurveyCommandResult(False, errors=[str(exc)])
        _survey_audit(
            uow, "survey.create_form", str(made.form_id), f"ok: version={made.version} seed={made.seed} "
            f"anchors={n_anchor} random={n_random} closed={made.closed_version or '-'}"
        )  # fmt: skip
        return SurveyCommandResult(
            True,
            report={
                "version": made.version,
                "form_id": str(made.form_id),
                "n_anchor": n_anchor,
                "n_random": n_random,
                "seed": made.seed,
                "anchors": made.anchors,
                "closed": made.closed_version,
            },
        )

    return run_in_uow(sm, work)  # type: ignore[return-value]


def set_survey_open(sm: sessionmaker[Session], version: str | None, is_open: bool) -> SurveyCommandResult:
    action = "survey.open" if is_open else "survey.close"

    def work(uow: UnitOfWork) -> SurveyCommandResult:
        try:
            with uow.session.begin_nested():
                form, closed = survey.set_open(uow.session, version, is_open)
        except survey.SurveyFormError as exc:
            _survey_audit(uow, action, version, f"failed: {exc}"[:500])
            return SurveyCommandResult(False, errors=[str(exc)])
        _survey_audit(uow, action, str(form.id), f"ok: version={form.version} closed={','.join(closed) or '-'}")
        return SurveyCommandResult(True, report={"version": form.version, "is_open": form.is_open, "closed": closed})

    return run_in_uow(sm, work)  # type: ignore[return-value]


def export_survey(sm: sessionmaker[Session], version: str, out_base: Path) -> SurveyCommandResult:
    """FR-24-07..09, FR-24-06 (audit action survey.export, entity_id = form version)."""

    def work(uow: UnitOfWork) -> SurveyCommandResult:
        try:
            res = survey.export(uow.session, version, out_base)
        except survey.SurveyFormError as exc:
            _survey_audit(uow, "survey.export", version, f"failed: {exc}"[:500])
            return SurveyCommandResult(False, errors=[str(exc)])
        except OSError as exc:
            _survey_audit(uow, "survey.export", version, f"failed: {exc.__class__.__name__}")
            return SurveyCommandResult(False, errors=[f"ghi tệp xuất lỗi: {exc}"])
        _survey_audit(uow, "survey.export", version, f"ok: {res.respondents} respondents, {res.ratings} ratings")
        return SurveyCommandResult(
            True,
            report={
                "version": res.form_version,
                "directory": res.directory,
                "is_open": res.is_open,
                "respondents": res.respondents,
                "ratings": res.ratings,
                "files": res.files,
            },
        )

    return run_in_uow(sm, work)  # type: ignore[return-value]


def list_surveys(
    session: Session, *, actor_user_id: uuid.UUID, cursor: str | None, limit: int
) -> survey_schemas.SurveyFormSummaryPage:
    """GET /admin/surveys (FR-24-10); the role check is in the router. Coalesced audit (cursor=None + 60s cooldown)."""
    page = survey.list_forms(session, cursor=cursor, limit=limit)
    _write_coalesced_read_audit(
        session,
        action="survey.list",
        entity="survey_forms",
        actor_user_id=actor_user_id,
        actor_role=SURVEY_ROLE,
        cursor=cursor,
    )
    return page


# ---------------------------------------------------------------- admin HTTP API (UC27, UC29, UC30)


def list_data_requests(
    session: Session,
    *,
    actor_user_id: uuid.UUID,
    statuses: list[str],
    types: list[str],
    cursor: str | None,
    limit: int,
) -> privacy_schemas.AdminDataRequestPage:
    page = privacy.list_dsr_requests(session, statuses=statuses, types=types, cursor=cursor, limit=limit)
    _write_coalesced_read_audit(
        session,
        action="dsr.list",
        entity="dsr_requests",
        actor_user_id=actor_user_id,
        actor_role="admin",
        cursor=cursor,
    )
    return page


def resolve_data_request(
    session: Session,
    *,
    actor_user_id: uuid.UUID,
    request_id: uuid.UUID,
    body: privacy_schemas.DataRequestResolve,
) -> privacy_schemas.AdminDataRequestOut:
    return privacy.resolve_dsr_request(
        session,
        request_id=request_id,
        actor_user_id=actor_user_id,
        status=body.status,
        note=body.note,
    )


def list_audit_log(
    session: Session,
    *,
    actor_user_id: uuid.UUID,
    filter_actor_user_id: uuid.UUID | None,
    entity: str | None,
    action: str | None,
    from_dt: datetime | None,
    to_dt: datetime | None,
    cursor: str | None,
    limit: int,
) -> privacy_schemas.AuditLogEntryPage:
    return privacy.list_audit_log(
        session,
        actor_user_id=filter_actor_user_id,
        entity=entity,
        action=action,
        from_dt=from_dt,
        to_dt=to_dt,
        cursor=cursor,
        limit=limit,
    )


def list_models(
    session: Session,
    *,
    actor_user_id: uuid.UUID,
    name: str | None,
    status: str | None,
    cursor: str | None,
    limit: int,
) -> ModelVersionPage:
    versions, nxt, deployments = mlops.list_versions_page(
        session, name=name, status=status, cursor=cursor, limit=limit
    )
    return ModelVersionPage(
        items=[
            ModelVersionOut(
                id=v.id,
                name=v.name,  # type: ignore[arg-type]
                version=v.version,
                artifact_key=v.artifact_key,
                sha256=v.sha256,
                preprocess_version=v.preprocess_version,
                metrics=v.metrics,
                gate_report_key=v.gate_report_key,
                mlflow_run_id=v.mlflow_run_id,
                status=v.status,  # type: ignore[arg-type]
                is_active=v.is_active,
                created_at=v.created_at,
            )
            for v in versions
        ],
        next_cursor=nxt,
        deployments=[
            ModelDeploymentOut(
                name=d.name,  # type: ignore[arg-type]
                active_version_id=d.active_version_id,
                previous_version_id=d.previous_version_id,
                switched_at=d.switched_at,
                switched_by=d.switched_by,
            )
            for d in deployments
        ],
    )
