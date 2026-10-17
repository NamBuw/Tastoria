"""admin public interface (M15): staff operations run from the CLI. This slice: `tastoria catalog import` (UC25).

The import validates the whole bundle before opening a transaction, writes it in one Unit of Work together with
one audit_log row (action `catalog.import`, actor_role `curator`), and on any blocking problem writes nothing to the
catalog but still records the failed run in audit_log (UC25 2a, FR-25-15).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from tastoria.core.db import UnitOfWork, run_in_uow
from tastoria.modules.catalog import service as catalog
from tastoria.modules.privacy import service as privacy


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
