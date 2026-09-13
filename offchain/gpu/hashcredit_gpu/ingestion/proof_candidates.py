"""
Proof candidates (R2-D02): a provider-reported settlement that references a source-chain transaction becomes
a `proof_requests` row at status **OBSERVED** and a `PROOF_WAIT_ATTESTATION` job, both in the caller's
transaction (same commit as the raw observation and the cursor). Nothing here can set any other status —
`ALLOWED_INITIAL_STATUS` is the only literal written, and migration 0002's trigger rejects anything higher
without the corresponding evidence rows anyway.

A candidate is a *request to prove*, not evidence: it changes no receivable, eligibility or limit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..jobs.outbox import emit
from ..jobs.proof import job_key
from ..jobs.queue import JobQueue, new_ulid
from ..providers.types import SettlementObservation

ALLOWED_INITIAL_STATUS = "OBSERVED"
PROOF_CANDIDATE_JOB_KIND = "PROOF_WAIT_ATTESTATION"
_TX_RE = re.compile(r"^0x[0-9a-f]{64}$")


@dataclass(frozen=True)
class ProofEnv:
    """Facts rail binding for candidates (from the GPU-075 manifest; never user input)."""

    env_id: str
    chain_key: int
    source_chain_id: int
    manifest_hash: str
    sdk_version: str
    execution_profile: str


@dataclass(frozen=True)
class ProofCandidate:
    provider_id: str
    env_id: str
    chain_key: int
    tx_hash: str
    settlement_ref: str
    account_key: str


def candidate_from_settlement(
    obs: SettlementObservation, env: ProofEnv, provider_id: str
) -> ProofCandidate | None:
    """Only PAID settlements with a well-formed tx reference on the manifest's source chain qualify.

    The tx hash is a provider *hint* for the proof query key; whether the tx exists, succeeded, or carries a
    usable event is decided by the official proof path, never here.
    """
    if obs.status != "PAID" or not obs.tx_ref:
        return None
    tx = obs.tx_ref.lower()
    if not _TX_RE.match(tx):
        return None
    if obs.amount.asset.chain_id != env.source_chain_id:
        return None  # unsupported / other chain: no candidate (R2-D08), the raw observation still exists
    return ProofCandidate(
        provider_id=provider_id,
        env_id=env.env_id,
        chain_key=env.chain_key,
        tx_hash=tx,
        settlement_ref=obs.settlement_ref,
        account_key=obs.account.account_key,
    )


def emit_candidate(
    cx: Connection, cand: ProofCandidate, env: ProofEnv, queue: JobQueue, *, raw_observation_id: str
) -> str | None:
    """Insert the OBSERVED proof request + outbox event + wait job in the caller's transaction.

    Returns the proof_request_id when this call created it, None when it already existed (duplicate poll /
    webhook / re-fetch): the query key (env_id, chain_key, tx_hash) is unique.
    """
    rid = new_ulid()
    inserted = cx.execute(
        text(
            "INSERT INTO proof_requests (proof_request_id, env_id, chain_key, tx_hash, provider_id, execution_profile, "
            "manifest_hash, sdk_version, status) VALUES (:id, :env, :ck, :tx, :prov, :prof, :man, :sdk, :st) "
            "ON CONFLICT (env_id, chain_key, tx_hash) DO NOTHING RETURNING proof_request_id"
        ),
        {
            "id": rid,
            "env": cand.env_id,
            "ck": cand.chain_key,
            "tx": cand.tx_hash,
            "prov": cand.provider_id,
            "prof": env.execution_profile,
            "man": env.manifest_hash,
            "sdk": env.sdk_version,
            "st": ALLOWED_INITIAL_STATUS,
        },
    ).scalar()
    if inserted is None:
        return None
    emit(
        cx,
        aggregate_type="proof_request",
        aggregate_id=rid,
        event_type="PROOF_CANDIDATE_OBSERVED",
        payload={
            "proofRequestId": rid,
            "envId": cand.env_id,
            "chainKey": cand.chain_key,
            "txHash": cand.tx_hash,
            "settlementRef": cand.settlement_ref,
            "accountKey": cand.account_key,
            "rawObservationId": raw_observation_id,
            "nativeStatus": ALLOWED_INITIAL_STATUS,
        },
        idempotency_key=f"proof-candidate:{cand.env_id}:{cand.chain_key}:{cand.tx_hash}",
    )
    queue.enqueue(
        PROOF_CANDIDATE_JOB_KIND,
        {
            "proofRequestId": rid,
            "txHash": cand.tx_hash,
            "chainKey": cand.chain_key,
            "envId": cand.env_id,
        },
        job_key(PROOF_CANDIDATE_JOB_KIND, rid),
        cx=cx,
    )
    return rid
