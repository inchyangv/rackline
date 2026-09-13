"""
Durable proof lifecycle (R2-D02) as job kinds over `proof_requests.status`.

    OBSERVED --PROOF_WAIT_ATTESTATION--> WAITING_ATTESTATION --PROOF_FETCH_ARTIFACT--> PROOF_READY
             --PROOF_SUBMIT--> SUBMITTED --PROOF_CONFIRM--> NATIVE_ACCEPTED --EVIDENCE_CONSUME--> CONSUMED
    any step --UNSUPPORTED / INVALID / EXPIRED--> terminal status of the same name (job dead-lettered)

Each `OK` transition only *sets the status*; migration 0002's trigger `trg_proof_requests_status_evidence` still
requires the proof artifact row (PROOF_READY+), an ACCEPTED `native_verifications` row (NATIVE_ACCEPTED+) and an
`evidence_consumptions` row (CONSUMED). Therefore `api_ready_at` (HTTP 200) or `precheck_ok_at` (eth_call) can
never advance the request on their own, and a retried job cannot re-consume: the second consumption insert hits
the unique keys of `evidence_consumptions` and is treated as already done.

There is deliberately no job kind that signs, attests, or "marks verified" (R2-D03): `SIGNER_FALLBACK_TERMS`
is used by the tests to assert that no job kind name carries such semantics.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .queue import FailureKind, TerminalError, TransientError

PROOF_JOB_KINDS: tuple[str, ...] = (
    "PROOF_WAIT_ATTESTATION",
    "PROOF_FETCH_ARTIFACT",
    "PROOF_SUBMIT",
    "PROOF_CONFIRM",
    "EVIDENCE_CONSUME",
)

#: words that would indicate a substitute verification path; no job kind may contain them (R2-D03)
SIGNER_FALLBACK_TERMS: tuple[str, ...] = ("SIGN", "ATTEST_LOCAL", "FALLBACK", "ADMIN_ACCEPT", "MARK_VERIFIED", "SPV", "BYPASS", "FORCE")


class Outcome(enum.StrEnum):
    OK = "OK"
    NOT_READY = "NOT_READY"  # transient: attestation not reached / cache lag / tx not mined
    NETWORK_ERROR = "NETWORK_ERROR"  # transient
    UNSUPPORTED = "UNSUPPORTED"  # terminal
    INVALID = "INVALID"  # terminal: native verification rejected / malformed
    EXPIRED = "EXPIRED"  # terminal: policy validity passed


TRANSIENT = frozenset({Outcome.NOT_READY, Outcome.NETWORK_ERROR})
TERMINAL = frozenset({Outcome.UNSUPPORTED, Outcome.INVALID, Outcome.EXPIRED})

#: status set on OK per kind (the DB trigger checks the evidence rows)
_OK_STATUS = {
    "PROOF_WAIT_ATTESTATION": "WAITING_ATTESTATION",
    "PROOF_FETCH_ARTIFACT": "PROOF_READY",
    "PROOF_SUBMIT": "SUBMITTED",
    "PROOF_CONFIRM": "NATIVE_ACCEPTED",
    "EVIDENCE_CONSUME": "CONSUMED",
}
#: the status a kind may start from
_FROM_STATUS = {
    "PROOF_WAIT_ATTESTATION": {"OBSERVED", "WAITING_ATTESTATION"},
    "PROOF_FETCH_ARTIFACT": {"WAITING_ATTESTATION"},
    "PROOF_SUBMIT": {"PROOF_READY"},
    "PROOF_CONFIRM": {"SUBMITTED"},
    "EVIDENCE_CONSUME": {"NATIVE_ACCEPTED"},
}
_NEXT_KIND = {
    "PROOF_WAIT_ATTESTATION": "PROOF_FETCH_ARTIFACT",
    "PROOF_FETCH_ARTIFACT": "PROOF_SUBMIT",
    "PROOF_SUBMIT": "PROOF_CONFIRM",
    "PROOF_CONFIRM": "EVIDENCE_CONSUME",
    "EVIDENCE_CONSUME": None,
}


@dataclass(frozen=True)
class Transition:
    proof_request_id: str
    kind: str
    outcome: Outcome
    status_before: str
    status_after: str
    next_kind: str | None
    failure: FailureKind | None


def classify(outcome: Outcome) -> FailureKind | None:
    if outcome in TRANSIENT:
        return FailureKind.TRANSIENT
    if outcome in TERMINAL:
        return FailureKind.TERMINAL
    return None


def job_key(kind: str, proof_request_id: str) -> str:
    """Semantic idempotency key: one job per (kind, request); retries reuse the same job row."""
    return f"proof:{kind}:{proof_request_id}"


class ProofLifecycle:
    """Applies a handler outcome to `proof_requests` inside the caller's transaction."""

    @staticmethod
    def current_status(cx: Connection, proof_request_id: str) -> str:
        st = cx.execute(text("SELECT status FROM proof_requests WHERE proof_request_id = :id FOR UPDATE"), {"id": proof_request_id}).scalar()
        if st is None:
            raise LookupError(f"proof request {proof_request_id} not found")
        return str(st)

    @classmethod
    def apply(cls, cx: Connection, proof_request_id: str, kind: str, outcome: Outcome, *, error: str | None = None) -> Transition:
        """Move the request according to `outcome`. Raises TransientError/TerminalError for the worker to record.

        OK on a kind whose evidence row is missing is rejected by the DB trigger (check_violation); that error
        propagates as-is so an HTTP 200 / eth_call success can never masquerade as acceptance.

        Failure outcomes are recorded in an *autonomous* transaction on the same engine before the error is
        raised: the worker rolls the handler transaction back (partial writes must not survive), but the
        request's status/last_error must — otherwise UNSUPPORTED/INVALID/EXPIRED would be lost with the rollback.
        """
        if kind not in PROOF_JOB_KINDS:
            raise ValueError(f"unknown proof job kind {kind}")
        before = cls.current_status(cx, proof_request_id)
        if before in {"INVALID", "UNSUPPORTED", "EXPIRED", "CONSUMED"}:
            raise TerminalError(f"proof request {proof_request_id} is terminal ({before})")
        failure = classify(outcome)
        if outcome == Outcome.OK:
            if before not in _FROM_STATUS[kind]:
                raise TerminalError(f"{kind} cannot run from status {before}")
            after = _OK_STATUS[kind]
            cx.execute(
                text("UPDATE proof_requests SET status = :st, last_error = NULL, attempt = attempt + 1, updated_at = now() WHERE proof_request_id = :id"),
                {"st": after, "id": proof_request_id},
            )
            return Transition(proof_request_id, kind, outcome, before, after, _NEXT_KIND[kind], None)
        if failure == FailureKind.TRANSIENT:
            after = "WAITING_ATTESTATION" if kind == "PROOF_WAIT_ATTESTATION" and before == "OBSERVED" else before
            err_cls: type[Exception] = TransientError
        else:
            after = str(outcome)
            err_cls = TerminalError
        # release our row lock so the autonomous transaction below cannot deadlock on it
        cx.rollback()
        with cx.engine.begin() as own:
            own.execute(
                text("UPDATE proof_requests SET status = :st, last_error = :err, attempt = attempt + 1, updated_at = now() WHERE proof_request_id = :id"),
                {"st": after, "err": f"{outcome}: {error or ''}"[:2000], "id": proof_request_id},
            )
        raise err_cls(f"{kind} {proof_request_id}: {outcome}")

    @staticmethod
    def has_signer_fallback(kinds: tuple[str, ...] = PROOF_JOB_KINDS) -> bool:
        upper = [k.upper() for k in kinds]
        return any(term in k for k in upper for term in SIGNER_FALLBACK_TERMS)
