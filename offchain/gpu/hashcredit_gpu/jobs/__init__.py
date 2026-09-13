"""
Durable jobs, transactional outbox and worker loop over the GPU-016 tables (GPU-025).

Guarantees (and non-guarantees):
- A job is claimed by at most one worker at a time (`hcg_lease_job`); an expired lease can be re-claimed.
  A worker that lost its lease cannot complete or fail the job (fencing on `(leased_by, attempt)`).
- Delivery is **at least once**. Exactly-once *delivery* is not promised; economic effects are deduplicated by
  the ledgers' unique keys (`evidence_consumptions`, `allocations`, `outbox.idempotency_key`, ...), never by
  the queue.
- A dead-lettered job is never skipped forever silently and never auto-resumed: resuming needs an actor, a role
  and a reason and writes an `audit_log` row.
- Proof lifecycle jobs only move `proof_requests.status`; the DB triggers still demand the artifact /
  ACCEPTED verification / consumption rows, so an HTTP 200 or an `eth_call` success can never become
  NATIVE_ACCEPTED or CONSUMED (R2-D02). There is no signer/fallback job kind (R2-D03).
"""

from .outbox import OutboxEvent, dispatch_outbox, emit
from .proof import PROOF_JOB_KINDS, Outcome, ProofLifecycle
from .queue import (
    BackoffPolicy,
    ClaimedJob,
    FailureKind,
    JobQueue,
    LeaseLost,
    ResumeRequiresReason,
    TerminalError,
    TransientError,
)
from .worker import Worker

__all__ = [
    "PROOF_JOB_KINDS",
    "BackoffPolicy",
    "ClaimedJob",
    "FailureKind",
    "JobQueue",
    "LeaseLost",
    "OutboxEvent",
    "Outcome",
    "ProofLifecycle",
    "ResumeRequiresReason",
    "TerminalError",
    "TransientError",
    "Worker",
    "dispatch_outbox",
    "emit",
]
