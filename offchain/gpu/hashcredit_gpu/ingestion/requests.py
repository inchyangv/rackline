"""Authenticated callers may request observations; source facts remain pending native verification."""

import re

from sqlalchemy import select

from ..db.ledgers import ProofRequest
from ..db.models import Provider, ProviderAccount
from ..jobs.outbox import emit
from ..jobs.proof import job_key
from ..jobs.queue import JobQueue, new_ulid
from ..receivables.service import lock


def request_source_proof(
    session, *, provider_account_id: str, tx_hash: str, manifest: dict
) -> ProofRequest:
    """Call after API account authorization. No caller-supplied status, amount, emitter or approval."""
    if not re.fullmatch(r"0x[0-9a-f]{64}", tx_hash):
        raise ValueError("normalized source transaction hash required")
    account = session.get(ProviderAccount, provider_account_id)
    provider = session.get(Provider, account.provider_id) if account else None
    if not provider:
        raise ValueError("unknown provider account")
    if (
        provider.manifest_hash != manifest["manifestHash"]
        or provider.execution_profile != manifest["executionProfile"]
        or provider.source_chain_id != manifest["source"]["chainId"]
        or provider.source_chain_key != manifest["source"]["chainKey"]
        or provider.environment_status != "PROBED"
        or provider.capabilities.get("source_support") != "SUPPORTED"
        or manifest.get("mock")
        or manifest.get("verificationMethod") != "ATTESTCOIN_NATIVE"
    ):
        raise ValueError("provider source/native manifest is not supported and bound")
    key = f"proof-source:{provider.source_env_id}:{provider.source_chain_key}:{tx_hash}"
    lock(session, key)
    existing = session.scalar(
        select(ProofRequest).where(
            ProofRequest.env_id == provider.source_env_id,
            ProofRequest.chain_key == provider.source_chain_key,
            ProofRequest.tx_hash == tx_hash,
        )
    )
    if existing:
        if (
            existing.provider_id != provider.provider_id
            or existing.manifest_hash != provider.manifest_hash
        ):
            raise ValueError("source transaction already belongs to another provider/manifest")
        return existing
    request = ProofRequest(
        proof_request_id=new_ulid(),
        provider_id=provider.provider_id,
        env_id=provider.source_env_id,
        chain_key=provider.source_chain_key,
        tx_hash=tx_hash,
        execution_profile=provider.execution_profile,
        manifest_hash=provider.manifest_hash,
        sdk_version=manifest["sdk"]["version"],
        encoding_version=manifest["source"]["encoding"],
        abi_sha256s=manifest["sdk"]["abiSha256"],
        decoder_ref=manifest["destination"]["decoder"]["sourceFile"],
        status="OBSERVED",
    )
    session.add(request)
    session.flush()
    emit(
        session.connection(),
        aggregate_type="proof_request",
        aggregate_id=request.proof_request_id,
        event_type="PROOF_CANDIDATE_OBSERVED",
        idempotency_key=key,
        payload={
            "proofRequestId": request.proof_request_id,
            "providerAccountId": provider_account_id,
            "txHash": tx_hash,
            "nativeStatus": "OBSERVED",
        },
    )
    JobQueue(session.bind).enqueue(
        "PROOF_WAIT_ATTESTATION",
        {"proofRequestId": request.proof_request_id},
        job_key("PROOF_WAIT_ATTESTATION", request.proof_request_id),
        max_attempts=100,
        cx=session.connection(),
    )
    return request
