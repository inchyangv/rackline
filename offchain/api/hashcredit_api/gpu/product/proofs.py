"""Account-scoped official proof requests; callers never supply verification state or calldata."""
import json
import os
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import select

from hashcredit_gpu.db.models import ProviderAccount
from hashcredit_gpu.db.ledgers import ProofRequest, ProofArtifact, NativeVerification
from hashcredit_gpu.db.product_models import ApiCommand
from hashcredit_gpu.db.projections_models import ChainBlock, ProjectedEvidence
from hashcredit_gpu.ingestion.requests import request_source_proof

from .commands import Command, execute
from ..errors import not_configured, not_found, unsupported_source
from ..permissions.deps import Principal, current_principal


def proof_status(session, proof, provider_account_id, settings):
    native = "NOT_SUBMITTED"
    artifact = session.scalar(select(ProofArtifact).where(ProofArtifact.proof_request_id == proof.proof_request_id)
                              .order_by(ProofArtifact.created_at.desc()).limit(1))
    verification = session.scalar(select(NativeVerification).where(
        NativeVerification.proof_request_id == proof.proof_request_id,
        NativeVerification.destination_chain_id == settings.chain_id,
        NativeVerification.execution_profile == settings.execution_profile,
    ).order_by(NativeVerification.created_at.desc()).limit(1))
    if verification:
        native = verification.status if verification.status != "ACCEPTED" else "UNCONFIRMED"
        if verification.status == "ACCEPTED" and verification.verification_method == "ATTESTCOIN_NATIVE":
            rows = session.scalars(select(ProjectedEvidence).where(
                ProjectedEvidence.deployment_id == settings.deployment_id,
                ProjectedEvidence.tier == "FINALIZED",
                ProjectedEvidence.consumption_tx_hash == verification.submission_tx_hash,
                ProjectedEvidence.verification_method == "ATTESTCOIN_NATIVE",
                ProjectedEvidence.verified_in_same_tx.is_(True)))
            for row in rows:
                block = session.get(ChainBlock, (settings.deployment_id, row.block_number))
                if block and block.tier == "FINALIZED" and block.hash == row.block_hash:
                    native = "CONSUMED"
                    break
    return {"proofRequestId": proof.proof_request_id, "providerAccountId": provider_account_id,
            "status": proof.status, "txHash": proof.tx_hash, "nativeStatus": native,
            "artifactHash": artifact.artifact_hash if artifact else None,
            "artifactVersion": artifact.encoding_version if artifact else None,
            "businessEligibility": None}


class SourceProof(Command):
    providerAccountId: str = Field(min_length=1, max_length=200)
    txHash: str = Field(pattern=r"^0x[0-9a-f]{64}$")


def build_proof_router():
    router = APIRouter(prefix="/v1", tags=["gpu-source-proofs"])

    @router.get("/proofs")
    def requests(request: Request, p: Principal = Depends(current_principal)):
        repository = request.app.state.product
        with repository.session() as session:
            metadata = repository.metadata(session)
            commands = session.scalars(select(ApiCommand).where(ApiCommand.chain_id == p.chain_id,
                ApiCommand.wallet == p.wallet.lower(), ApiCommand.scope == "proofs")
                .order_by(ApiCommand.created_at.desc()).limit(100))
            data, seen = [], set()
            for command in commands:
                record = command.response.get("data", {})
                account = session.get(ProviderAccount, record.get("providerAccountId")) if record.get("providerAccountId") else None
                if not account or not p.borrower_id or account.borrower_id != p.borrower_id:
                    continue
                proof = session.get(ProofRequest, record.get("proofRequestId"))
                if not proof or proof.proof_request_id in seen or proof.provider_id != account.provider_id:
                    continue
                if proof.execution_profile != repository.settings.execution_profile or proof.manifest_hash != repository.settings.manifest_hash:
                    continue
                seen.add(proof.proof_request_id)
                data.append(proof_status(session, proof, account.provider_account_id, repository.settings))
            return {"schemaVersion": "1.0", "data": data, "meta": metadata,
                    "pagination": {"nextCursor": None, "limit": 100}}

    @router.post("/proofs", status_code=202)
    def submit(body: SourceProof, request: Request, p: Principal = Depends(current_principal)):
        def run(session):
            account = session.get(ProviderAccount, body.providerAccountId)
            if account is None or p.borrower_id is None or account.borrower_id != p.borrower_id:
                raise not_found()
            path = os.environ.get("GPU_ATTESTCOIN_MANIFEST")
            if not path:
                raise not_configured("official source environment is not configured")
            try:
                manifest = json.loads(Path(path).read_text())
            except (OSError, ValueError):
                raise not_configured("official source manifest is unavailable") from None
            if manifest["manifestHash"] != request.app.state.product.settings.manifest_hash:
                raise not_configured("official source and application deployment differ")
            try:
                proof = request_source_proof(session, provider_account_id=body.providerAccountId,
                                            tx_hash=body.txHash, manifest=manifest)
            except ValueError:
                raise unsupported_source("provider account is not admitted to this official source environment") from None
            # A request links no receivable and makes no claim that the transaction belongs to this account.
            return proof_status(session, proof, body.providerAccountId, request.app.state.product.settings)
        return execute(request, p, "proofs", body, run)

    return router
