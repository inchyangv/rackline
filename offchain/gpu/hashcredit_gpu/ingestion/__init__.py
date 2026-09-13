"""
GPU-022 — provider data ingestion: persistent per-account cursors, transactional collection (raw
observation + cursor + outbox + proof candidate in ONE commit), signed webhook ingress with DB-backed
replay protection, overlapping backfill and correction re-fetch.

Ingestion records what a provider *said* (OFFCHAIN_ASSERTION, trust ASSERTED). It never writes receivables,
eligibility, limits or any native status above OBSERVED (R2-D02/D04/D06): a settlement with a chain tx
reference becomes a `proof_requests` row at status OBSERVED plus a `PROOF_WAIT_ATTESTATION` job — the official
proof path (GPU-079/078/031) is the only way forward. API polling is a data source, never a native fallback.
"""

from .backfill import backfill_account, refetch_corrections
from .collector import (
    Collector,
    CollectResult,
    FileRawStore,
    IngestionConfig,
    IngestionCrash,
    MemoryRawStore,
    RawStore,
)
from .cursors import CursorState, CursorStore, MissingCursorError
from .proof_candidates import (
    ALLOWED_INITIAL_STATUS,
    ProofCandidate,
    candidate_from_settlement,
    emit_candidate,
)
from .webhook import WebhookError, WebhookReceiver, sign_webhook, verify_webhook

__all__ = [
    "ALLOWED_INITIAL_STATUS",
    "CollectResult",
    "Collector",
    "CursorState",
    "CursorStore",
    "FileRawStore",
    "IngestionConfig",
    "IngestionCrash",
    "MemoryRawStore",
    "MissingCursorError",
    "ProofCandidate",
    "RawStore",
    "WebhookError",
    "WebhookReceiver",
    "backfill_account",
    "candidate_from_settlement",
    "emit_candidate",
    "refetch_corrections",
    "sign_webhook",
    "verify_webhook",
]
