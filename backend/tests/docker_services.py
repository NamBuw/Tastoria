"""Throwaway PostgreSQL (pgvector:pg18) and Valkey containers for integration tests.

Each container publishes its port on 127.0.0.1 with a random host port chosen by Docker (`-p 127.0.0.1::5432`),
so tests never collide with services already running on this machine. Containers carry the label
`tastoria-test=1` and are removed when the test session ends.
"""

from __future__ import annotations

import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass

PG_IMAGE = "pgvector/pgvector:pg18"
VALKEY_IMAGE = "valkey/valkey:9"
PG_USER = "tastoria"
PG_PASSWORD = "tastoria-test"
PG_DB = "tastoria"


def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


def _run(*args: str) -> str:
    return subprocess.run(["docker", *args], check=True, capture_output=True, text=True).stdout.strip()


def _host_port(name: str, container_port: str) -> int:
    out = _run("port", name, container_port)  # e.g. "127.0.0.1:49153"
    return int(out.splitlines()[0].rsplit(":", 1)[1])


@dataclass
class Container:
    name: str
    port: int

    def exec(self, *cmd: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["docker", "exec", "-i", self.name, *cmd], input=input_text, capture_output=True, text=True
        )

    def remove(self) -> None:
        subprocess.run(["docker", "rm", "-f", self.name], capture_output=True)


def start_postgres() -> Container:
    name = f"tastoria-test-pg-{uuid.uuid4().hex[:8]}"
    _run(
        "run", "-d", "--rm", "--label", "tastoria-test=1", "--name", name,
        "-p", "127.0.0.1::5432",
        "-e", f"POSTGRES_USER={PG_USER}", "-e", f"POSTGRES_PASSWORD={PG_PASSWORD}", "-e", f"POSTGRES_DB={PG_DB}",
        "--tmpfs", "/var/lib/postgresql:rw",
        PG_IMAGE,
        "-c", "fsync=off", "-c", "synchronous_commit=off", "-c", "full_page_writes=off",
    )  # fmt: skip
    c = Container(name, _host_port(name, "5432/tcp"))
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        # The entrypoint restarts the server once after init; require two consecutive successes over TCP.
        ok = c.exec("pg_isready", "-h", "127.0.0.1", "-U", PG_USER, "-d", PG_DB).returncode == 0
        if ok:
            time.sleep(0.5)
            if c.exec("pg_isready", "-h", "127.0.0.1", "-U", PG_USER, "-d", PG_DB).returncode == 0:
                return c
        time.sleep(0.3)
    c.remove()
    raise RuntimeError("postgres test container did not become ready")


def start_valkey() -> Container:
    name = f"tastoria-test-valkey-{uuid.uuid4().hex[:8]}"
    _run("run", "-d", "--rm", "--label", "tastoria-test=1", "--name", name, "-p", "127.0.0.1::6379", VALKEY_IMAGE)
    c = Container(name, _host_port(name, "6379/tcp"))
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if c.exec("valkey-cli", "ping").stdout.strip() == "PONG":
            return c
        time.sleep(0.2)
    c.remove()
    raise RuntimeError("valkey test container did not become ready")


def pg_url(c: Container, db: str = PG_DB) -> str:
    return f"postgresql+psycopg://{PG_USER}:{PG_PASSWORD}@127.0.0.1:{c.port}/{db}"
