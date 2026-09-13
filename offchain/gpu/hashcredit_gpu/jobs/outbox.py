"""
Transactional outbox over the `outbox` table (migration 0002).

`emit(cx, ...)` must be called inside the *same* transaction as the business change it announces, so an event
exists iff the change committed. `dispatch_outbox` publishes unpublished rows at least once: a publisher
failure leaves the row unpublished (attempt+1), a crash between publish and commit re-publishes the same
`idempotency_key`. Consumers must be idempotent on that key; the queue never promises exactly-once delivery.
Economic dedup is the ledgers' job (unique keys on consumptions / allocations), not the outbox's.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine


@dataclass(frozen=True)
class OutboxEvent:
    id: int
    aggregate_type: str
    aggregate_id: str
    event_type: str
    idempotency_key: str
    payload: dict[str, Any]
    attempt: int
    created_at: datetime


Publisher = Callable[[OutboxEvent], None]


def emit(
    cx: Connection,
    *,
    aggregate_type: str,
    aggregate_id: str,
    event_type: str,
    payload: dict[str, Any],
    idempotency_key: str,
) -> int | None:
    """Insert an outbox row in the caller's transaction. Returns the row id, or None if the key already exists."""
    if not idempotency_key:
        raise ValueError("idempotency_key is required")
    row = cx.execute(
        text(
            "INSERT INTO outbox (aggregate_type, aggregate_id, event_type, idempotency_key, payload) "
            "VALUES (:agg_type, :agg_id, :event_type, :key, CAST(:payload AS jsonb)) "
            "ON CONFLICT (idempotency_key) DO NOTHING RETURNING id"
        ),
        {
            "agg_type": aggregate_type,
            "agg_id": aggregate_id,
            "event_type": event_type,
            "key": idempotency_key,
            "payload": json.dumps(payload, sort_keys=True),
        },
    ).scalar()
    return int(row) if row is not None else None


def dispatch_outbox(engine: Engine, publisher: Publisher, *, batch: int = 100, max_attempts: int = 20) -> tuple[int, int]:
    """Publish unpublished rows (oldest first, SKIP LOCKED so dispatchers can run concurrently).

    Returns (published, failed). Each row is handled in its own transaction: publish → mark `published_at`.
    Rows past `max_attempts` are left unpublished for operators (never deleted, never silently skipped: they
    still show up in `pending_outbox`).
    """
    published = failed = 0
    with engine.connect() as c:
        ids = c.execute(
            text(
                "SELECT id FROM outbox WHERE published_at IS NULL AND attempt < :max ORDER BY created_at, id LIMIT :n"
            ),
            {"n": batch, "max": max_attempts},
        ).scalars().all()
    for row_id in ids:
        with engine.begin() as c:
            r = c.execute(
                text(
                    "SELECT id, aggregate_type, aggregate_id, event_type, idempotency_key, payload, attempt, created_at "
                    "FROM outbox WHERE id = :id AND published_at IS NULL FOR UPDATE SKIP LOCKED"
                ),
                {"id": row_id},
            ).one_or_none()
            if r is None:
                continue  # someone else took it or it was published meanwhile
            event = OutboxEvent(
                id=int(r.id),
                aggregate_type=r.aggregate_type,
                aggregate_id=r.aggregate_id,
                event_type=r.event_type,
                idempotency_key=r.idempotency_key,
                payload=dict(r.payload or {}),
                attempt=int(r.attempt),
                created_at=r.created_at,
            )
            try:
                publisher(event)
            except Exception:  # noqa: BLE001 - any publisher failure is retried later
                c.execute(text("UPDATE outbox SET attempt = attempt + 1 WHERE id = :id"), {"id": row_id})
                failed += 1
                continue
            c.execute(text("UPDATE outbox SET published_at = now(), attempt = attempt + 1 WHERE id = :id"), {"id": row_id})
            published += 1
    return published, failed


def pending_outbox(engine: Engine) -> int:
    with engine.connect() as c:
        return int(c.execute(text("SELECT count(*) FROM outbox WHERE published_at IS NULL")).scalar_one())
