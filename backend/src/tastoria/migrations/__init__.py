"""Alembic migrations. 0001 executes the vendored copy of db/schema.sql (sql/0001_schema.sql).

The copy is frozen with the migration: later schema changes are new migrations, never edits of 0001.
tests/unit/test_schema_copy.py fails while db/schema.sql and the copy differ, so a change to db/schema.sql is
noticed and turned into a migration instead of silently drifting.
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config

MIGRATIONS_DIR = Path(__file__).resolve().parent


def alembic_config(database_url: str | None = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    if database_url:
        cfg.attributes["database_url"] = database_url
    return cfg
