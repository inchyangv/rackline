"""
PostgreSQL test fixtures. SQLite is deliberately unsupported (TICKET GPU-015: "SQLite만 통과하면 미완료").

Resolution order for the server:
  1. HASHCREDIT_GPU_TEST_DATABASE_URL (a superuser-capable PostgreSQL URL; databases are created per test)
  2. an ephemeral cluster started with `initdb`/`pg_ctl` found via PATH, `pg_config --bindir`, or the
     Homebrew postgresql@16 path (TCP only, random port, removed at session end)
If neither is possible the session FAILS (no skip), so a missing database can never look like a pass.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

import psycopg2
import pytest
from psycopg2 import sql

from hashcredit_gpu.db.cli import upgrade

CANDIDATE_BINDIRS = [
    "/opt/homebrew/opt/postgresql@16/bin",
    "/opt/homebrew/opt/postgresql@17/bin",
    "/usr/lib/postgresql/16/bin",
    "/usr/lib/postgresql/17/bin",
]


def _find_bindir() -> Path | None:
    for tool in ("initdb", "pg_ctl"):
        found = shutil.which(tool)
        if found:
            return Path(found).parent
    pg_config = shutil.which("pg_config")
    if pg_config:
        out = subprocess.run([pg_config, "--bindir"], capture_output=True, text=True, check=False)
        if out.returncode == 0 and (Path(out.stdout.strip()) / "initdb").exists():
            return Path(out.stdout.strip())
    for d in CANDIDATE_BINDIRS:
        if (Path(d) / "initdb").exists():
            return Path(d)
    return None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class EphemeralPostgres:
    def __init__(self, bindir: Path):
        self.bindir = bindir
        self.dir = Path(tempfile.mkdtemp(prefix="hcg-pg-"))
        self.port = _free_port()
        self.pgdata = self.dir / "data"
        self.log = self.dir / "pg.log"

    def start(self) -> str:
        env = dict(os.environ, LC_ALL="C", LANG="C")
        subprocess.run(
            [str(self.bindir / "initdb"), "-D", str(self.pgdata), "-U", "postgres", "--auth=trust", "-E", "UTF8", "--locale=C"],
            check=True, capture_output=True, env=env,
        )
        opts = f"-p {self.port} -c unix_socket_directories='' -c listen_addresses=127.0.0.1 -c fsync=off"
        subprocess.run(
            [str(self.bindir / "pg_ctl"), "-D", str(self.pgdata), "-o", opts, "-l", str(self.log), "-w", "start"],
            check=True, capture_output=True, env=env,
        )
        url = f"postgresql+psycopg2://postgres@127.0.0.1:{self.port}/postgres"
        for _ in range(50):
            try:
                psycopg2.connect(_dsn(url)).close()
                return url
            except psycopg2.OperationalError:
                time.sleep(0.2)
        raise RuntimeError(f"ephemeral postgres did not come up; see {self.log}")

    def stop(self) -> None:
        subprocess.run([str(self.bindir / "pg_ctl"), "-D", str(self.pgdata), "-m", "immediate", "stop"], check=False, capture_output=True)
        shutil.rmtree(self.dir, ignore_errors=True)


def _dsn(url: str) -> str:
    return url.replace("postgresql+psycopg2://", "postgresql://")


@pytest.fixture(scope="session")
def pg_server_url() -> str:
    env_url = os.environ.get("HASHCREDIT_GPU_TEST_DATABASE_URL")
    if env_url:
        yield env_url
        return
    bindir = _find_bindir()
    if bindir is None:
        pytest.fail(
            "No PostgreSQL available: set HASHCREDIT_GPU_TEST_DATABASE_URL or install PostgreSQL binaries "
            "(initdb/pg_ctl). These tests do not run on SQLite and do not skip."
        )
    server = EphemeralPostgres(bindir)
    url = server.start()
    try:
        yield url
    finally:
        server.stop()


@pytest.fixture(scope="session")
def pg_bindir() -> Path | None:
    return _find_bindir()


def _admin_conn(server_url: str):
    conn = psycopg2.connect(_dsn(server_url))
    conn.autocommit = True
    return conn


@pytest.fixture
def fresh_db_url(pg_server_url: str):
    """A brand-new empty database for one test; dropped afterwards."""
    name = "hcg_" + uuid.uuid4().hex[:12]
    admin = _admin_conn(pg_server_url)
    with admin.cursor() as cur:
        cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    base = pg_server_url.rsplit("/", 1)[0]
    url = f"{base}/{name}"
    try:
        yield url
    finally:
        with admin.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
                (name,),
            )
            cur.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))
        admin.close()


@pytest.fixture
def migrated_db_url(fresh_db_url: str) -> str:
    upgrade(fresh_db_url, "head")
    return fresh_db_url


@pytest.fixture
def conn(migrated_db_url: str):
    """Raw psycopg2 connection on a migrated database (autocommit off; each statement is its own test)."""
    c = psycopg2.connect(_dsn(migrated_db_url))
    try:
        yield c
    finally:
        c.close()
