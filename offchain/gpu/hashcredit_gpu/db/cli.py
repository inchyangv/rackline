"""
`hashcredit-gpu-db` — reproducible migration CLI (wraps Alembic with the package's config).

  hashcredit-gpu-db upgrade [head|<rev>]     apply migrations
  hashcredit-gpu-db downgrade <rev|base>     roll back
  hashcredit-gpu-db current                  show current revision
  hashcredit-gpu-db check                    fail if ORM metadata and DB schema differ (drift guard)

Database URL from HASHCREDIT_GPU_DATABASE_URL (PostgreSQL only). Exit 0 ok, 1 failure, 2 usage.
"""

from __future__ import annotations

import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine

from .models import Base
from .settings import database_url, redact

PACKAGE_ROOT = Path(__file__).resolve().parents[2]  # offchain/gpu


def alembic_config(url: str) -> Config:
    cfg = Config(str(PACKAGE_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PACKAGE_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def upgrade(url: str, rev: str = "head") -> None:
    command.upgrade(alembic_config(url), rev)


def downgrade(url: str, rev: str) -> None:
    command.downgrade(alembic_config(url), rev)


def current(url: str) -> str | None:
    engine = create_engine(url)
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def schema_diff(url: str) -> list:
    """Differences between the ORM metadata and the live schema (empty list = no drift)."""
    engine = create_engine(url)
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True, "compare_server_default": False})
        return compare_metadata(ctx, Base.metadata)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__)
        return 2
    cmd, *rest = argv
    try:
        url = database_url()
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    try:
        if cmd == "upgrade":
            upgrade(url, rest[0] if rest else "head")
            print(f"upgraded {redact(url)} -> {current(url)}")
            return 0
        if cmd == "downgrade":
            if not rest:
                print("usage: downgrade <rev|base>", file=sys.stderr)
                return 2
            downgrade(url, rest[0])
            print(f"downgraded {redact(url)} -> {current(url)}")
            return 0
        if cmd == "current":
            print(current(url) or "(none)")
            return 0
        if cmd == "check":
            diff = schema_diff(url)
            if diff:
                print("schema drift detected:")
                for d in diff:
                    print(f"  {d}")
                return 1
            print("no drift between ORM metadata and database")
            return 0
        print(f"unknown command {cmd}", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
