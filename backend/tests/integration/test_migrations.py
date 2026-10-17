"""The Alembic chain reproduces db/schema.sql exactly, and runs cleanly up and down."""

from __future__ import annotations

import re

import docker_services as ds
from alembic import command
from conftest import REPO_ROOT

from tastoria.migrations import alembic_config


def _create_db(pg: ds.Container, name: str) -> None:
    r = pg.exec("psql", "-v", "ON_ERROR_STOP=1", "-U", ds.PG_USER, "-d", ds.PG_DB, "-c", f"CREATE DATABASE {name}")
    assert r.returncode == 0, r.stderr


def _schema_dump(pg: ds.Container, db: str) -> str:
    r = pg.exec("pg_dump", "--schema-only", "--no-owner", "--no-privileges", "-U", ds.PG_USER, "-d", db)
    assert r.returncode == 0, r.stderr
    text = r.stdout
    # pg_dump embeds a random \restrict token per run; alembic adds its bookkeeping table.
    text = re.sub(r"^\\(un)?restrict .*$", "", text, flags=re.MULTILINE)
    text = re.sub(
        r"CREATE TABLE public\.alembic_version \(.*?\);\n|ALTER TABLE ONLY public\.alembic_version\n.*?;\n",
        "",
        text,
        flags=re.DOTALL,
    )
    text = re.sub(r"--\n-- Name: alembic_version.*?\n--\n", "", text, flags=re.DOTALL)
    return re.sub(r"\n{3,}", "\n\n", text)


def test_migration_0001_equals_schema_sql(pg: ds.Container) -> None:
    _create_db(pg, "ref_schema")
    r = pg.exec(
        "psql", "-v", "ON_ERROR_STOP=1", "-q", "-U", ds.PG_USER, "-d", "ref_schema",
        input_text=(REPO_ROOT / "db/schema.sql").read_text(encoding="utf-8"),
    )  # fmt: skip
    assert r.returncode == 0, r.stderr

    _create_db(pg, "mig_schema")
    command.upgrade(alembic_config(ds.pg_url(pg, "mig_schema")), "0001")

    ref, mig = _schema_dump(pg, "ref_schema"), _schema_dump(pg, "mig_schema")
    assert "CREATE TABLE public.users" in ref
    assert mig == ref


def test_upgrade_downgrade_upgrade(pg: ds.Container) -> None:
    _create_db(pg, "roundtrip")
    cfg = alembic_config(ds.pg_url(pg, "roundtrip"))
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    sql = "SELECT count(*) FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
    r = pg.exec("psql", "-tA", "-U", ds.PG_USER, "-d", "roundtrip", "-c", sql)
    assert r.stdout.strip() == "63"  # 62 of db/schema.sql + recipe_make_ahead (0003)
