from __future__ import annotations

import base64
import os
import sys
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

sys.path.insert(0, str(Path(__file__).resolve().parent))

import docker_services as ds  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent

TEST_ENC_KEY = base64.b64encode(bytes(range(32))).decode()
TEST_ENC_KEY_2 = base64.b64encode(bytes(range(1, 33))).decode()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        if "/integration/" in str(item.fspath):
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def docker_ok() -> bool:
    if not ds.docker_available():
        if os.environ.get("TASTORIA_REQUIRE_DOCKER") == "1":
            pytest.fail("Docker is required for integration tests")
        pytest.skip("Docker not available")
    return True


@pytest.fixture(scope="session")
def pg(docker_ok: bool) -> Iterator[ds.Container]:
    c = ds.start_postgres()
    try:
        yield c
    finally:
        c.remove()


@pytest.fixture(scope="session")
def valkey(docker_ok: bool) -> Iterator[ds.Container]:
    c = ds.start_valkey()
    try:
        yield c
    finally:
        c.remove()


@pytest.fixture(scope="session")
def database_url(pg: ds.Container) -> str:
    """The main test database, migrated to head once per session."""
    from alembic import command

    from tastoria.migrations import alembic_config

    url = ds.pg_url(pg)
    command.upgrade(alembic_config(url), "head")
    return url


@pytest.fixture(scope="session")
def engine(database_url: str) -> Iterator[Engine]:
    eng = create_engine(database_url)
    yield eng
    eng.dispose()


def _settings(database_url: str, valkey_port: int, tmp_storage: Path, **overrides: object):
    from tastoria.core.config import Settings

    base: dict[str, object] = {
        "env": "test",
        "database_url": database_url,
        "valkey_url": f"redis://127.0.0.1:{valkey_port}/0",
        "jwt_keys": {"k1": "test-jwt-secret-0123456789-abcdefghijklmnop"},
        "jwt_active_kid": "k1",
        "health_enc_keys": {"t1": TEST_ENC_KEY, "t2": TEST_ENC_KEY_2},
        "health_enc_active_key_id": "t1",
        "dsr_hmac_key": "test-hmac-key",
        "storage_dir": str(tmp_storage),
        "mailer": "log",
        "db_pool_size": 3,
        "log_level": "WARNING",
    }
    base.update(overrides)
    return Settings(**base)


@pytest.fixture(scope="session")
def storage_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("storage")


@pytest.fixture(scope="session")
def make_app(database_url: str, valkey: ds.Container, storage_dir: Path) -> Iterator[Callable[..., object]]:
    from tastoria.app import create_app

    created = []

    def factory(**overrides: object):
        app = create_app(_settings(database_url, valkey.port, storage_dir, **overrides), configure_logs=False)
        created.append(app)
        return app

    yield factory
    for app in created:
        app.state.engine.dispose()


@pytest.fixture(scope="session")
def app(make_app: Callable[..., object]):
    return make_app()


@pytest.fixture
def client(app, clean_db: None) -> Iterator[object]:
    from fakes import FakeMailer
    from fastapi.testclient import TestClient

    app.state.mailer = FakeMailer()
    with TestClient(app) as c:
        yield c


# Personal data and test-created catalog rows are wiped after every test; reference rows seeded by migrations
# (consent purposes, policy versions, allergen groups, diets) stay.
_TRUNCATE = """
BEGIN;
SET LOCAL tastoria.erasure = 'on';
TRUNCATE users, dsr_requests, audit_log, idempotency_keys, recipes, cooking_methods, survey_forms RESTART IDENTITY CASCADE;
DELETE FROM policy_versions WHERE version LIKE 'test-%';
COMMIT;
"""


@pytest.fixture
def clean_db(engine: Engine, valkey: ds.Container) -> Iterator[None]:
    yield
    raw = engine.raw_connection()
    try:
        with raw.cursor() as cur:
            cur.execute(_TRUNCATE)
        raw.commit()
    finally:
        raw.close()
    valkey.exec("valkey-cli", "flushall")


@pytest.fixture
def db(engine: Engine, clean_db: None) -> Iterator[object]:
    """A plain connection for assertions (autocommit)."""
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        yield conn


def q(conn, sql: str, **params: object):
    return conn.execute(text(sql), params)


@pytest.fixture(scope="session")
def catalog_ref(engine: Engine) -> dict[str, list[str]]:
    """Allergen groups and diets from data/kb/ref (the curated reference data of the catalog slice)."""
    import yaml

    ref = REPO_ROOT / "data/kb/ref"
    groups = yaml.safe_load((ref / "allergen_groups.yaml").read_text(encoding="utf-8"))["allergen_groups"]
    diets = yaml.safe_load((ref / "diets.yaml").read_text(encoding="utf-8"))["diets"]
    with engine.begin() as conn:
        for g in groups:
            conn.execute(
                text(
                    "INSERT INTO allergen_groups (code, name_vi, name_en, basis) "
                    "VALUES (:code, :name_vi, :name_en, :basis) ON CONFLICT (code) DO NOTHING"
                ),
                g,
            )
        for d in diets:
            conn.execute(
                text("INSERT INTO diets (code, name_vi) VALUES (:code, :name_vi) ON CONFLICT (code) DO NOTHING"), d
            )
    return {"allergens": [g["code"] for g in groups], "diets": [d["code"] for d in diets]}


def insert_recipe(conn, name: str, *, status: str = "published", slot: str = "man") -> str:
    """A minimal recipe row (the catalog import slice will provide real ones)."""
    conn.execute(text("INSERT INTO cooking_methods (code, name_vi) VALUES ('xao', 'Xào') ON CONFLICT DO NOTHING"))
    return str(
        conn.execute(
            text(
                "INSERT INTO recipes (name_vi, slot, servings, method_code, status) "
                "VALUES (:n, :slot, 2, 'xao', :st) RETURNING id"
            ),
            {"n": name, "slot": slot, "st": status},
        ).scalar_one()
    )


# ---------------------------------------------------------------- catalog databases (slice 2)
# The main test database above is wiped of recipes after every test (slice-1 tests insert ad-hoc recipes).
# Tests that need the real catalog use a second database, migrated and loaded with `tastoria catalog import data/kb`
# once per session; after each test only personal data is wiped there, the catalog stays.

KB_DIR = REPO_ROOT / "data/kb"
PROCESSED_DIR = REPO_ROOT / "data/processed"


def make_database(pg: ds.Container, name: str) -> str:
    from alembic import command

    from tastoria.migrations import alembic_config

    r = pg.exec("psql", "-v", "ON_ERROR_STOP=1", "-U", ds.PG_USER, "-d", ds.PG_DB, "-c", f"CREATE DATABASE {name}")
    assert r.returncode == 0, r.stderr
    url = ds.pg_url(pg, name)
    command.upgrade(alembic_config(url), "head")
    return url


def drop_database(pg: ds.Container, name: str) -> None:
    pg.exec("psql", "-U", ds.PG_USER, "-d", ds.PG_DB, "-c", f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")


@pytest.fixture(scope="session")
def kb_database_url(pg: ds.Container) -> str:
    from tastoria.core.db import make_engine, make_sessionmaker
    from tastoria.modules.admin.service import import_catalog

    url = make_database(pg, "kb")
    engine = make_engine(url, pool_size=1)
    try:
        res = import_catalog(make_sessionmaker(engine), KB_DIR, PROCESSED_DIR)
    finally:
        engine.dispose()
    assert res.ok, res.errors
    return url


@pytest.fixture(scope="session")
def kb_engine(kb_database_url: str) -> Iterator[Engine]:
    eng = create_engine(kb_database_url)
    yield eng
    eng.dispose()


@pytest.fixture(scope="session")
def kb_app(kb_database_url: str, valkey: ds.Container, storage_dir: Path):
    from tastoria.app import create_app

    app = create_app(_settings(kb_database_url, valkey.port, storage_dir), configure_logs=False)
    yield app
    app.state.engine.dispose()


_KB_TRUNCATE = """
BEGIN;
SET LOCAL tastoria.erasure = 'on';
TRUNCATE users, dsr_requests, audit_log, idempotency_keys, substitution_pairs, survey_forms RESTART IDENTITY CASCADE;
DELETE FROM policy_versions WHERE version LIKE 'test-%';
COMMIT;
"""


@pytest.fixture
def kb_clean(kb_engine: Engine, valkey: ds.Container) -> Iterator[None]:
    yield
    raw = kb_engine.raw_connection()
    try:
        with raw.cursor() as cur:
            cur.execute(_KB_TRUNCATE)
        raw.commit()
    finally:
        raw.close()
    valkey.exec("valkey-cli", "flushall")


@pytest.fixture
def kb_client(kb_app, kb_clean: None) -> Iterator[object]:
    from fakes import FakeMailer
    from fastapi.testclient import TestClient

    kb_app.state.mailer = FakeMailer()
    with TestClient(kb_app) as c:
        yield c


@pytest.fixture
def kb_db(kb_engine: Engine, kb_clean: None) -> Iterator[object]:
    with kb_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        yield conn


@pytest.fixture
def fresh_database(pg: ds.Container) -> Iterator[Callable[[], str]]:
    """Factory of empty migrated databases (dropped after the test), for import tests that change the catalog."""
    made: list[str] = []

    def factory() -> str:
        name = f"t_{uuid.uuid4().hex[:10]}"
        made.append(name)
        return make_database(pg, name)

    yield factory
    for name in made:
        drop_database(pg, name)
