"""admin public interface (M15): staff operations run from the CLI: `tastoria catalog import` (UC25) and
`tastoria catalog substitutes import` (the curated substitution table, design v2 §6.3 (a)).

The import validates the whole bundle before opening a transaction, writes it in one Unit of Work together with
one audit_log row (action `catalog.import`, actor_role `curator`), and on any blocking problem writes nothing to the
catalog but still records the failed run in audit_log (UC25 2a, FR-25-15).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from tastoria.core.db import UnitOfWork, run_in_uow
from tastoria.modules.admin import substitutes as subs_file
from tastoria.modules.catalog import service as catalog
from tastoria.modules.privacy import service as privacy
from tastoria.modules.substitute import service as substitute


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
