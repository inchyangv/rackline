"""
Job queue over the `jobs` table (migration 0002).

State machine (JOB_STATES = PENDING, LEASED, SUCCEEDED, FAILED, DEAD):
    PENDING --claim--> LEASED --complete--> SUCCEEDED
                       LEASED --fail(TRANSIENT)--> PENDING (next_run_at = now + backoff)   [attempt < max_attempts]
                       LEASED --fail(TRANSIENT)--> DEAD                                     [attempts exhausted]
                       LEASED --fail(TERMINAL)---> DEAD
                       DEAD   --resume(actor, role, reason)--> PENDING (audited)
`FAILED` exists in the schema but is not used by this queue: a transient failure is a *scheduled retry*
(PENDING + next_run_at), a terminal failure is *dead-letter* (DEAD). Both keep `last_error`.

Claiming uses the SQL function `hcg_lease_job(job_id, worker, seconds)` from migration 0002, which atomically
checks state / attempt / next_run_at / lease expiry and increments `attempt`. The pair `(leased_by, attempt)`
is the fencing token: `complete` and `fail` only apply when the caller still holds exactly that lease.
"""

from __future__ import annotations

import enum
import hashlib
import json
import os
import random
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from ..domain import enums as E

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_ulid(now_ms: int | None = None, rng: random.Random | None = None) -> str:
    """26-char Crockford ULID (48-bit ms time + 80-bit randomness); matches the DB `ULID_CHECK` regex."""
    ts = int(time.time() * 1000) if now_ms is None else now_ms
    rand = (rng.getrandbits(80) if rng else int.from_bytes(os.urandom(10), "big"))
    value = (ts << 80) | rand
    out = []
    for _ in range(26):
        out.append(_CROCKFORD[value & 31])
        value >>= 5
    return "".join(reversed(out))


def payload_hash(payload: dict[str, Any]) -> str:
    """Canonical JSON hash of the payload (sorted keys, no whitespace)."""
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "0x" + hashlib.sha256(canon.encode("utf-8")).hexdigest()


class FailureKind(enum.StrEnum):
    TRANSIENT = "TRANSIENT"  # retry after backoff; dead-letter when attempts are exhausted
    TERMINAL = "TERMINAL"  # dead-letter immediately (unsupported / invalid / expired)


class TransientError(Exception):
    """Handler outcome: not ready / network / temporary; the job is retried with backoff."""


class TerminalError(Exception):
    """Handler outcome: the job can never succeed as-is (unsupported, invalid, expired). Dead-letter."""


class LeaseLost(RuntimeError):
    """The caller no longer holds the lease (expired and re-claimed, or already completed)."""


class ResumeRequiresReason(ValueError):
    """Dead-lettered jobs are resumed only with an explicit actor, role and reason."""


@dataclass(frozen=True)
class BackoffPolicy:
    base_seconds: float = 2.0
    factor: float = 2.0
    cap_seconds: float = 600.0
    jitter_fraction: float = 0.2  # +/- 20 %

    def delay(self, attempt: int, rng: random.Random | None = None) -> float:
        """Exponential backoff for the *next* run after `attempt` failed attempts (attempt >= 1)."""
        raw = min(self.cap_seconds, self.base_seconds * (self.factor ** max(0, attempt - 1)))
        r = rng if rng is not None else random
        jitter = raw * self.jitter_fraction
        return max(0.0, raw + r.uniform(-jitter, jitter))


@dataclass(frozen=True)
class ClaimedJob:
    job_id: str
    kind: str
    payload: dict[str, Any]
    semantic_idempotency_key: str
    attempt: int  # fencing token together with worker_id
    max_attempts: int
    worker_id: str
    lease_until: datetime


@dataclass(frozen=True)
class JobRow:
    job_id: str
    kind: str
    state: str
    attempt: int
    max_attempts: int
    leased_by: str | None
    lease_until: datetime | None
    next_run_at: datetime
    last_error: str | None
    semantic_idempotency_key: str


def _audit_entry_hash(prev_hash: str | None, actor: str, action: str, entity_id: str, after: dict[str, Any]) -> str:
    canon = json.dumps(
        {"prev": prev_hash, "actor": actor, "action": action, "entity": entity_id, "after": after},
        sort_keys=True,
        separators=(",", ":"),
    )
    return "0x" + hashlib.sha256(canon.encode()).hexdigest()


def write_audit(
    cx: Connection,
    *,
    actor: str,
    actor_role: E.Role | str,
    action: str,
    entity_table: str,
    entity_id: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    correlation_id: str | None = None,
) -> int:
    """Append one hash-chained `audit_log` row (the table is UPDATE/DELETE-immutable by trigger)."""
    prev = cx.execute(text("SELECT entry_hash FROM audit_log ORDER BY id DESC LIMIT 1")).scalar()
    entry_hash = _audit_entry_hash(prev, actor, action, entity_id, after or {})
    row = cx.execute(
        text(
            "INSERT INTO audit_log (actor, actor_role, action, entity_table, entity_id, before, after, correlation_id, prev_hash, entry_hash) "
            "VALUES (:actor, :role, :action, :table, :entity, CAST(:before AS jsonb), CAST(:after AS jsonb), :corr, :prev, :hash) RETURNING id"
        ),
        {
            "actor": actor,
            "role": str(actor_role),
            "action": action,
            "table": entity_table,
            "entity": entity_id,
            "before": json.dumps(before) if before is not None else None,
            "after": json.dumps(after) if after is not None else None,
            "corr": correlation_id,
            "prev": prev,
            "hash": entry_hash,
        },
    )
    return int(row.scalar_one())


class JobQueue:
    """Durable job queue. Each public method opens its own transaction unless given a `Connection`."""

    def __init__(self, engine: Engine, backoff: BackoffPolicy | None = None, rng: random.Random | None = None):
        self.engine = engine
        self.backoff = backoff or BackoffPolicy()
        self.rng = rng

    # ------------------------------------------------------------------ enqueue

    def enqueue(
        self,
        kind: str,
        payload: dict[str, Any],
        semantic_idempotency_key: str,
        *,
        max_attempts: int = 10,
        run_at: datetime | None = None,
        cx: Connection | None = None,
    ) -> str:
        """Insert a job; a duplicate semantic key returns the existing job id and inserts nothing."""
        if not semantic_idempotency_key:
            raise ValueError("semantic_idempotency_key is required")
        job_id = new_ulid()
        sql = text(
            "INSERT INTO jobs (job_id, kind, semantic_idempotency_key, payload_hash, payload, max_attempts, next_run_at) "
            "VALUES (:id, :kind, :key, :hash, CAST(:payload AS jsonb), :max_attempts, COALESCE(:run_at, now())) "
            "ON CONFLICT (semantic_idempotency_key) DO NOTHING RETURNING job_id"
        )
        params = {
            "id": job_id,
            "kind": kind,
            "key": semantic_idempotency_key,
            "hash": payload_hash(payload),
            "payload": json.dumps(payload, sort_keys=True),
            "max_attempts": max_attempts,
            "run_at": run_at,
        }

        def _do(c: Connection) -> str:
            inserted = c.execute(sql, params).scalar()
            if inserted:
                return str(inserted)
            existing = c.execute(
                text("SELECT job_id FROM jobs WHERE semantic_idempotency_key = :key"), {"key": semantic_idempotency_key}
            ).scalar_one()
            return str(existing)

        if cx is not None:
            return _do(cx)
        with self.engine.begin() as c:
            return _do(c)

    # ------------------------------------------------------------------ claim / lease

    def claim(self, worker_id: str, kinds: Sequence[str], lease_seconds: int = 60, candidates: int = 8) -> ClaimedJob | None:
        """Lease one runnable job of the given kinds, or None. Safe under concurrent workers."""
        if not kinds:
            return None
        with self.engine.begin() as c:
            rows = c.execute(
                text(
                    "SELECT job_id FROM jobs WHERE state IN ('PENDING','LEASED') AND kind = ANY(:kinds) "
                    "AND next_run_at <= now() AND attempt < max_attempts "
                    "AND (lease_until IS NULL OR lease_until < now()) ORDER BY next_run_at, job_id LIMIT :n"
                ),
                {"kinds": list(kinds), "n": candidates},
            ).all()
            for (job_id,) in rows:
                won = c.execute(
                    text("SELECT hcg_lease_job(:id, :worker, :secs)"), {"id": job_id, "worker": worker_id, "secs": lease_seconds}
                ).scalar()
                if won:
                    r = c.execute(
                        text(
                            "SELECT job_id, kind, payload, semantic_idempotency_key, attempt, max_attempts, lease_until "
                            "FROM jobs WHERE job_id = :id"
                        ),
                        {"id": job_id},
                    ).one()
                    return ClaimedJob(
                        job_id=r.job_id,
                        kind=r.kind,
                        payload=dict(r.payload or {}),
                        semantic_idempotency_key=r.semantic_idempotency_key,
                        attempt=int(r.attempt),
                        max_attempts=int(r.max_attempts),
                        worker_id=worker_id,
                        lease_until=r.lease_until,
                    )
        return None

    def _fenced_update(self, c: Connection, job: ClaimedJob, set_sql: str, params: dict[str, Any]) -> None:
        res = c.execute(
            text(
                f"UPDATE jobs SET {set_sql}, updated_at = now() WHERE job_id = :id AND state = 'LEASED' "
                "AND leased_by = :worker AND attempt = :attempt AND lease_until >= now()"
            ),
            {**params, "id": job.job_id, "worker": job.worker_id, "attempt": job.attempt},
        )
        if res.rowcount != 1:
            raise LeaseLost(f"job {job.job_id}: lease not held by {job.worker_id}@{job.attempt}")

    def renew_lease(self, job: ClaimedJob, lease_seconds: int = 60, cx: Connection | None = None) -> None:
        def _do(c: Connection) -> None:
            self._fenced_update(c, job, "lease_until = now() + make_interval(secs => :secs)", {"secs": lease_seconds})

        if cx is not None:
            _do(cx)
        else:
            with self.engine.begin() as c:
                _do(c)

    def complete(self, job: ClaimedJob, cx: Connection | None = None) -> None:
        """Mark SUCCEEDED. Pass the business transaction's `cx` so the effect and the completion commit together."""

        def _do(c: Connection) -> None:
            self._fenced_update(c, job, "state = 'SUCCEEDED', lease_until = NULL, leased_by = NULL, last_error = NULL", {})

        if cx is not None:
            _do(cx)
        else:
            with self.engine.begin() as c:
                _do(c)

    def fail(self, job: ClaimedJob, kind: FailureKind, reason: str, cx: Connection | None = None) -> str:
        """Record a failure. Returns the resulting state: 'PENDING' (retry scheduled) or 'DEAD' (dead-letter)."""
        reason = (reason or "")[:2000]
        exhausted = job.attempt >= job.max_attempts
        if kind == FailureKind.TERMINAL or exhausted:
            set_sql = "state = 'DEAD', lease_until = NULL, leased_by = NULL, last_error = :err"
            params: dict[str, Any] = {"err": f"{kind}: {reason}" + (" (attempts exhausted)" if exhausted and kind == FailureKind.TRANSIENT else "")}
            new_state = "DEAD"
        else:
            delay = self.backoff.delay(job.attempt, self.rng)
            set_sql = (
                "state = 'PENDING', lease_until = NULL, leased_by = NULL, last_error = :err, "
                "next_run_at = now() + make_interval(secs => :delay)"
            )
            params = {"err": f"{kind}: {reason}", "delay": float(delay)}
            new_state = "PENDING"

        def _do(c: Connection) -> None:
            self._fenced_update(c, job, set_sql, params)

        if cx is not None:
            _do(cx)
        else:
            with self.engine.begin() as c:
                _do(c)
        return new_state

    # ------------------------------------------------------------------ dead-letter administration

    def resume(self, job_id: str, *, actor: str, actor_role: E.Role | str, reason: str, cx: Connection | None = None) -> None:
        """Move a DEAD job back to PENDING. Requires actor, role and a non-empty reason; writes an audit row."""
        if not actor or not str(actor_role) or not (reason and reason.strip()):
            raise ResumeRequiresReason("resume needs actor, actor_role and a non-empty reason")
        role = str(actor_role)
        if role not in {r.value for r in E.Role}:
            raise ResumeRequiresReason(f"unknown actor_role {role}")

        def _do(c: Connection) -> None:
            before = c.execute(
                text("SELECT state, attempt, max_attempts, last_error FROM jobs WHERE job_id = :id FOR UPDATE"), {"id": job_id}
            ).mappings().one_or_none()
            if before is None:
                raise LookupError(f"job {job_id} not found")
            if before["state"] != "DEAD":
                raise ValueError(f"job {job_id} is {before['state']}, only DEAD jobs can be resumed")
            c.execute(
                text(
                    "UPDATE jobs SET state = 'PENDING', attempt = 0, lease_until = NULL, leased_by = NULL, "
                    "next_run_at = now(), updated_at = now() WHERE job_id = :id"
                ),
                {"id": job_id},
            )
            write_audit(
                c,
                actor=actor,
                actor_role=role,
                action="job.resume",
                entity_table="jobs",
                entity_id=job_id,
                before=dict(before),
                after={"state": "PENDING", "attempt": 0, "reason": reason.strip(), "previous_error": before["last_error"]},
            )

        if cx is not None:
            _do(cx)
        else:
            with self.engine.begin() as c:
                _do(c)

    def get(self, job_id: str) -> JobRow | None:
        with self.engine.connect() as c:
            r = c.execute(
                text(
                    "SELECT job_id, kind, state, attempt, max_attempts, leased_by, lease_until, next_run_at, last_error, semantic_idempotency_key "
                    "FROM jobs WHERE job_id = :id"
                ),
                {"id": job_id},
            ).one_or_none()
        return JobRow(*r) if r else None

    def list_jobs(self, state: str | None = None, kind: str | None = None, limit: int = 100) -> list[JobRow]:
        clauses = []
        params: dict[str, Any] = {"n": limit}
        if state:
            clauses.append("state = :state")
            params["state"] = state
        if kind:
            clauses.append("kind = :kind")
            params["kind"] = kind
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self.engine.connect() as c:
            rows = c.execute(
                text(
                    "SELECT job_id, kind, state, attempt, max_attempts, leased_by, lease_until, next_run_at, last_error, semantic_idempotency_key "
                    f"FROM jobs {where} ORDER BY next_run_at, job_id LIMIT :n"
                ),
                params,
            ).all()
        return [JobRow(*r) for r in rows]


Handler = Callable[[Connection, ClaimedJob], None]
