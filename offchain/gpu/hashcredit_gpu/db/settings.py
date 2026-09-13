"""Database URL resolution. Never logs the URL (may contain credentials)."""

from __future__ import annotations

import os

ENV_URL = "HASHCREDIT_GPU_DATABASE_URL"


def database_url(explicit: str | None = None) -> str:
    url = explicit or os.environ.get(ENV_URL)
    if not url:
        raise RuntimeError(f"{ENV_URL} is not set")
    if not url.startswith(("postgresql://", "postgresql+psycopg2://")):
        raise RuntimeError("hashcredit_gpu requires a PostgreSQL URL (sqlite is not supported for migrations)")
    return url


def redact(url: str) -> str:
    from urllib.parse import urlparse

    p = urlparse(url)
    host = p.hostname or "?"
    return f"{p.scheme}://{host}:{p.port or ''}/{p.path.lstrip('/')}"
