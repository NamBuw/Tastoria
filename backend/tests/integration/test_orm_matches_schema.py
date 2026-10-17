"""Every ORM-mapped table matches the migrated catalog: columns, types, nullability, PK, FK, unique, indexes."""

from __future__ import annotations

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.engine import Engine

from tastoria.models_registry import target_metadata


def _is_comment_diff(diff: object) -> bool:
    ops = diff if isinstance(diff, list) else [diff]
    return all(
        isinstance(op, tuple) and str(op[0]) in {"modify_comment", "add_table_comment", "remove_table_comment"}
        for op in ops
    )


@pytest.mark.filterwarnings("ignore:Did not recognize type 'vector'")
def test_orm_models_match_database(engine: Engine) -> None:
    mapped = set(target_metadata.tables)

    def include_object(obj, name, type_, reflected, compare_to):  # noqa: ANN001
        if type_ == "table":
            return name in mapped
        table = getattr(obj, "table", None)
        return table is None or table.name in mapped

    with engine.connect() as conn:
        ctx = MigrationContext.configure(
            conn, opts={"compare_type": True, "include_object": include_object, "compare_server_default": False}
        )
        diffs = compare_metadata(ctx, target_metadata)
    # COMMENT ON ... text lives in db/schema.sql only (data dictionary); the ORM does not repeat it.
    diffs = [d for d in diffs if not _is_comment_diff(d)]
    assert diffs == []
    assert {"users", "refresh_tokens", "password_resets", "idempotency_keys", "consent_events", "profiles"} <= mapped
