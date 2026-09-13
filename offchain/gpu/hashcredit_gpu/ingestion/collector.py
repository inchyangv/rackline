"""
Transactional collector: one provider adapter page ⇒ one DB transaction containing
raw observations (append-only, unique per payload hash) + outbox events + proof candidates + cursor.

Failure model
- crash *before* commit: nothing of that page persists (raw/outbox/candidate/cursor all roll back), the next
  run re-fetches the same page from the stored page token;
- crash *after* commit: the next run re-fetches the page, every insert is `ON CONFLICT DO NOTHING` on a
  semantic unique key (payload hash / outbox idempotency key / proof query key / job key), so nothing is
  duplicated and no economic effect is repeated;
- `RateLimited` / transport errors mid-window: committed pages stay, the page token stays, nothing is skipped;
- `ExpiredData` (source retention gap): an `exceptions` row is opened and the cursor is NOT advanced past the
  gap — operators decide, the collector never silently jumps.

The collector never writes receivables, eligibility or limits; it has no code path that sets a native status.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from ..jobs.outbox import emit
from ..jobs.queue import JobQueue, new_ulid
from ..providers.base import ProviderAdapter
from ..providers.errors import ExpiredData, RateLimited
from ..providers.types import AccountRef, Cursor, Page, SettlementObservation, Window
from .cursors import CursorState, CursorStore
from .proof_candidates import ProofEnv, candidate_from_settlement, emit_candidate

STREAMS = ("revenue", "settlements")


class IngestionCrash(RuntimeError):
    """Raised by the fault hooks in tests to simulate a process crash at a precise point."""


class RawStore(Protocol):
    """Where the verbatim payload bytes live; the DB keeps hash + reference only (schema has no payload column)."""

    def put(self, payload_hash: str, body: bytes) -> str: ...


class MemoryRawStore:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    def put(self, payload_hash: str, body: bytes) -> str:
        self.blobs.setdefault(payload_hash, body)
        return f"blob://raw/{payload_hash[2:]}"


class FileRawStore:
    """Content-addressed durable volume. O_EXCL prevents overwriting retained evidence."""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    def put(self, payload_hash: str, body: bytes) -> str:
        if payload_hash != payload_hash_of(body):
            raise ValueError("raw content does not match hash")
        path = self.directory / payload_hash[2:]
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.directory, delete=False) as out:
                temp_name = out.name
                out.write(body)
                out.flush()
                os.fsync(out.fileno())
            os.link(temp_name, path)
            directory_fd = os.open(self.directory, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except FileExistsError:
            if path.read_bytes() != body:
                raise ValueError("raw artifact integrity mismatch")
        finally:
            if temp_name is not None:
                os.unlink(temp_name)
        return f"blob://raw/{payload_hash[2:]}"


def canonical_payload(obs: BaseModel) -> bytes:
    return json.dumps(
        obs.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def payload_hash_of(body: bytes) -> str:
    return "0x" + hashlib.sha256(body).hexdigest()


@dataclass(frozen=True)
class IngestionConfig:
    provider_id: str
    proof_env: ProofEnv
    overlap_seconds: int = 3600
    max_window_seconds: int = 7 * 86_400
    max_age_seconds: int = (
        400 * 86_400
    )  # freshness bound passed to the adapter (ExpiredData beyond it)
    schema_id: str = "provider-observation"
    schema_revision: int = 1


@dataclass
class CollectResult:
    stream: str
    pages: int = 0
    fetched: int = 0
    stored: int = 0  # new raw rows
    duplicates: int = 0
    candidates: int = 0
    committed_page_tokens: list[str | None] = field(default_factory=list)
    exception_id: str | None = None


class Collector:
    def __init__(
        self,
        engine: Engine,
        adapter: ProviderAdapter,
        config: IngestionConfig,
        raw_store: RawStore,
        *,
        clock: Callable[[], datetime] | None = None,
        fault_before_commit: Callable[[int], None] | None = None,
        fault_after_commit: Callable[[int], None] | None = None,
    ) -> None:
        if adapter.identity().provider_slug != config.provider_id:
            raise ValueError("adapter slug must equal the DB provider id")
        self.engine = engine
        self.adapter = adapter
        self.cfg = config
        self.raw = raw_store
        self.queue = JobQueue(engine)
        self.clock = clock or (lambda: datetime.now(UTC))
        self._fault_before = fault_before_commit
        self._fault_after = fault_after_commit

    # ------------------------------------------------------------------ public

    @staticmethod
    def stream_name(stream: str, account: AccountRef) -> str:
        return f"{stream}:{account.account_key}"

    def poll(
        self,
        account: AccountRef,
        stream: str,
        *,
        initial_start: datetime | None = None,
        until: datetime | None = None,
    ) -> CollectResult:
        """Collect [high_water - overlap, until] for one account stream, page by page, each page in its own commit."""
        if stream not in STREAMS:
            raise ValueError(f"unknown stream {stream}")
        name = self.stream_name(stream, account)
        now = self.clock()
        until = min(until or now, now)
        # ---- open / resume cursor
        with self.engine.begin() as cx:
            st = CursorStore.open(
                cx,
                self.cfg.provider_id,
                name,
                initial_start=initial_start,
                overlap_seconds=self.cfg.overlap_seconds,
            )
        return self._collect(account, stream, st, until, backfill=False)

    def collect_window(
        self, account: AccountRef, stream: str, start: datetime, end: datetime, *, tag: str
    ) -> CollectResult:
        """Explicit window collection (backfill / correction re-fetch) on a separate cursor stream."""
        name = f"{tag}:{self.stream_name(stream, account)}"
        with self.engine.begin() as cx:
            st = CursorStore.open(
                cx, self.cfg.provider_id, name, initial_start=start, overlap_seconds=0
            )
        return self._collect(account, stream, st, end, backfill=True, window_start=start)

    # ------------------------------------------------------------------ core loop

    def _collect(
        self,
        account: AccountRef,
        stream: str,
        st: CursorState,
        until: datetime,
        *,
        backfill: bool,
        window_start: datetime | None = None,
    ) -> CollectResult:
        result = CollectResult(stream=st.stream)
        assert st.high_water is not None
        if st.page_token is not None and st.window_end is not None:
            # resume an interrupted window exactly where it stopped
            w_start = (window_start or st.high_water) - timedelta(seconds=st.overlap_seconds)
            w_end = st.window_end
            cursor: Cursor | None = Cursor(token=st.page_token, has_more=True)
        else:
            w_start = (window_start or st.high_water) - timedelta(seconds=st.overlap_seconds)
            w_end = (
                min(until, w_start + timedelta(seconds=self.cfg.max_window_seconds))
                if not backfill
                else until
            )
            if w_end <= st.high_water and not backfill:
                return result  # nothing new
            cursor = None
        window = Window(
            start=w_start, end=w_end, max_age_seconds=self.cfg.max_age_seconds, as_of=self.clock()
        )
        page_no = 0
        while True:
            try:
                page = self._fetch(account, stream, window, cursor)
            except ExpiredData as e:
                result.exception_id = self._open_gap_exception(st, window, str(e))
                return result
            except RateLimited:
                raise  # caller backs off; committed pages + page token persist
            page_no += 1
            result.pages += 1
            result.fetched += len(page.items)
            last_page = not page.next.has_more
            next_state = (
                CursorStore.advanced(st, w_end)
                if last_page
                else CursorStore.with_page(st, page.next.token, w_end)
            )
            with self.engine.begin() as cx:
                current = CursorStore.load(cx, st.provider_id, st.stream)
                if current != st:
                    # Another worker committed this cursor while the provider request was in flight.
                    # Retry from that persisted page; never overwrite a newer high-water mark.
                    raise IngestionCrash(
                        "stream cursor changed concurrently; retry from persisted cursor"
                    )
                stored, dup, cands = self._store_page(cx, account, stream, page.items)
                CursorStore.save(cx, next_state)
                if self._fault_before:
                    self._fault_before(page_no)  # raises → whole page rolls back
            if self._fault_after:
                self._fault_after(page_no)
            result.stored += stored
            result.duplicates += dup
            result.candidates += cands
            result.committed_page_tokens.append(page.next.token if not last_page else None)
            st = next_state
            if last_page:
                return result
            cursor = page.next

    def _fetch(
        self, account: AccountRef, stream: str, window: Window, cursor: Cursor | None
    ) -> Page[Any]:
        if stream == "revenue":
            return self.adapter.fetch_revenue(account, window, cursor)
        return self.adapter.fetch_settlements(account, window, cursor)

    # ------------------------------------------------------------------ transactional store

    def _store_page(
        self, cx: Connection, account: AccountRef, stream: str, items: tuple[Any, ...]
    ) -> tuple[int, int, int]:
        stored = dup = cands = 0
        for obs in items:
            oid, new = self.store_observation(cx, obs, origin="API", stream=stream)
            if not new:
                dup += 1
                continue
            stored += 1
            if isinstance(obs, SettlementObservation):
                cand = candidate_from_settlement(obs, self.cfg.proof_env, self.cfg.provider_id)
                if cand and emit_candidate(
                    cx, cand, self.cfg.proof_env, self.queue, raw_observation_id=oid
                ):
                    cands += 1
        return stored, dup, cands

    def store_observation(
        self, cx: Connection, obs: BaseModel, *, origin: str, stream: str
    ) -> tuple[str, bool]:
        """Append the raw observation (+ outbox event) or return the existing row. Same transaction as the caller."""
        body = canonical_payload(obs)
        ph = payload_hash_of(body)
        ref = self.raw.put(ph, body)
        oid = new_ulid()
        observed_at = getattr(obs, "observed_at", None) or self.clock()
        inserted = cx.execute(
            text(
                "INSERT INTO raw_source_observations (observation_id, provider_id, origin, schema_id, schema_revision, "
                "payload_hash, payload_ref, source_cursor, trust, observed_at) "
                "VALUES (:id, :p, :o, :sid, :srev, :ph, :ref, :cur, 'ASSERTED', :obs_at) "
                "ON CONFLICT (provider_id, origin, payload_hash) DO NOTHING RETURNING observation_id"
            ),
            {
                "id": oid,
                "p": self.cfg.provider_id,
                "o": origin,
                "sid": f"{self.cfg.schema_id}:{stream}",
                "srev": self.cfg.schema_revision,
                "ph": ph,
                "ref": ref,
                "cur": None,
                "obs_at": observed_at,
            },
        ).scalar()
        if inserted is None:
            existing = cx.execute(
                text(
                    "SELECT observation_id FROM raw_source_observations WHERE provider_id = :p AND origin = :o AND payload_hash = :ph"
                ),
                {"p": self.cfg.provider_id, "o": origin, "ph": ph},
            ).scalar_one()
            return str(existing), False
        emit(
            cx,
            aggregate_type="raw_source_observation",
            aggregate_id=oid,
            event_type=f"OBSERVED_{stream.upper()}",
            payload={
                "observationId": oid,
                "payloadHash": ph,
                "origin": origin,
                "stream": stream,
                "trust": "ASSERTED",
                "verificationMethod": "OFFCHAIN_ASSERTION",
            },
            idempotency_key=f"raw:{self.cfg.provider_id}:{origin}:{ph}",
        )
        return oid, True

    # ------------------------------------------------------------------ gaps

    def _open_gap_exception(self, st: CursorState, window: Window, detail: str) -> str:
        eid = new_ulid()
        with self.engine.begin() as cx:
            cx.execute(
                text(
                    "INSERT INTO exceptions (exception_id, kind, severity, entity_table, entity_id, detail) "
                    "VALUES (:id, 'SOURCE_RETENTION_GAP', 'BLOCKING', 'ingest_cursors', :ent, CAST(:d AS jsonb))"
                ),
                {
                    "id": eid,
                    "ent": f"{st.provider_id}/{st.stream}",
                    "d": json.dumps(
                        {
                            "windowStart": window.start.isoformat(),
                            "windowEnd": window.end.isoformat(),
                            "highWater": st.high_water.isoformat() if st.high_water else None,
                            "detail": detail,
                            "action": "cursor NOT advanced; operator must confirm the gap (backfill from provider export or accept)",
                        }
                    ),
                },
            )
        return eid


def open_exceptions(engine: Engine, kind: str) -> list[dict[str, Any]]:
    with engine.connect() as c:
        rows = c.execute(
            text(
                "SELECT exception_id, entity_id, detail FROM exceptions WHERE kind = :k AND resolved_at IS NULL ORDER BY opened_at"
            ),
            {"k": kind},
        ).all()
    return [
        {"exception_id": r.exception_id, "entity_id": r.entity_id, "detail": dict(r.detail or {})}
        for r in rows
    ]
