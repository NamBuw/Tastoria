from __future__ import annotations

import hashlib

from conftest import REPO_ROOT

from tastoria.migrations import MIGRATIONS_DIR

FROZEN_0001_SHA256 = "d626650dcfb6c604d4707ea16b8af486e1ef9575cfd6bbe5c6e9b2d219638252"


def test_migration_0001_schema_remains_frozen() -> None:
    """0001_schema.sql is frozen history; never mutate it after release."""
    raw = (MIGRATIONS_DIR / "sql/0001_schema.sql").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == FROZEN_0001_SHA256
    mig_0001 = (MIGRATIONS_DIR / "versions/0001_initial_schema.py").read_text(encoding="utf-8")
    assert "sql/0001_schema.sql" in mig_0001


def test_db_schema_sql_contains_0007_markers() -> None:
    """db/schema.sql reflects head (0007) DDL; full pg_dump parity is verified in integration/test_migrations.py."""
    schema = (REPO_ROOT / "db/schema.sql").read_text(encoding="utf-8")
    for marker in (
        "CREATE TABLE recipe_make_ahead",
        "CREATE TABLE app_params",
        "CREATE TABLE email_outbox",
        "CREATE TABLE email_verification_tokens",
        "CREATE TABLE meal_logs",
        "CREATE TABLE meal_log_items",
        "response_headers jsonb",
        "sub_species_slug text",
        "pantry_lot_id uuid",
        "CREATE FUNCTION trg_user_favorite_recipes_limit()",
        "CREATE OR REPLACE FUNCTION erase_user_account(",
    ):
        assert marker in schema, marker
