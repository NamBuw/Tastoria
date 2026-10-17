"""Initial schema: execute db/schema.sql (vendored as migrations/sql/0001_schema.sql).

Revision ID: 0001
Revises:
Create Date: 2026-10-17
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from alembic import op

from tastoria.migrations import MIGRATIONS_DIR

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SQL_FILE = MIGRATIONS_DIR / "sql" / "0001_schema.sql"


def schema_sql() -> str:
    """The schema file without its own BEGIN/COMMIT: Alembic already runs the migration in a transaction."""
    text = SQL_FILE.read_text(encoding="utf-8")
    text = re.sub(r"^BEGIN;\s*$", "", text, count=1, flags=re.MULTILINE)
    text = re.sub(r"^COMMIT;\s*$", "", text, count=1, flags=re.MULTILINE)
    return text


def upgrade() -> None:
    # Raw DB-API cursor: with no parameters psycopg sends the whole multi-statement script as one simple query,
    # and `%` in format('%I') is not treated as a placeholder.
    dbapi = op.get_bind().connection.dbapi_connection
    with dbapi.cursor() as cur:
        cur.execute(schema_sql())


_DROP_ALL = """
DO $$
DECLARE r record;
BEGIN
    FOR r IN SELECT viewname FROM pg_views WHERE schemaname = 'public' LOOP
        EXECUTE format('DROP VIEW IF EXISTS public.%I CASCADE', r.viewname);
    END LOOP;
    FOR r IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version' LOOP
        EXECUTE format('DROP TABLE IF EXISTS public.%I CASCADE', r.tablename);
    END LOOP;
    FOR r IN SELECT p.oid::regprocedure AS sig FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
              LEFT JOIN pg_depend d ON d.objid = p.oid AND d.deptype = 'e'
             WHERE n.nspname = 'public' AND d.objid IS NULL LOOP
        EXECUTE format('DROP FUNCTION IF EXISTS %s CASCADE', r.sig);
    END LOOP;
    FOR r IN SELECT t.typname FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
             WHERE n.nspname = 'public' AND t.typtype = 'e' LOOP
        EXECUTE format('DROP TYPE IF EXISTS public.%I CASCADE', r.typname);
    END LOOP;
    EXECUTE format('ALTER DATABASE %I RESET tastoria.fresh_u_soon', current_database());
    EXECUTE format('ALTER DATABASE %I RESET tastoria.fresh_u_check', current_database());
END $$;
"""


def downgrade() -> None:
    # Initial migration: drop every object it created (views, tables, functions, enum types, database GUCs),
    # keep alembic_version and the extensions (CREATE EXTENSION IF NOT EXISTS may have found them already there).
    dbapi = op.get_bind().connection.dbapi_connection
    with dbapi.cursor() as cur:
        cur.execute(_DROP_ALL)
