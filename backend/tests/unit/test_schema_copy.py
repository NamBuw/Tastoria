from __future__ import annotations

from conftest import REPO_ROOT

from tastoria.migrations import MIGRATIONS_DIR


def test_migration_0001_is_a_byte_copy_of_db_schema_sql() -> None:
    """db/schema.sql is the design source; 0001 must execute exactly that file.

    If this fails, db/schema.sql changed after 0001 was frozen: write a new migration for the difference
    (and only then refresh the documents), do not edit 0001.
    """
    assert (MIGRATIONS_DIR / "sql/0001_schema.sql").read_bytes() == (REPO_ROOT / "db/schema.sql").read_bytes()
