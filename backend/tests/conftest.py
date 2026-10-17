from __future__ import annotations

import base64
import os
import sys
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
    from fastapi.testclient import TestClient

    from fakes import FakeMailer

    app.state.mailer = FakeMailer()
    with TestClient(app) as c:
        yield c


# Personal data and test-created catalog rows are wiped after every test; reference rows seeded by migrations
# (consent purposes, policy versions, allergen groups, diets) stay.
_TRUNCATE = """
BEGIN;
SET LOCAL tastoria.erasure = 'on';
TRUNCATE users, dsr_requests, audit_log, idempotency_keys, recipes, cooking_methods RESTART IDENTITY CASCADE;
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
