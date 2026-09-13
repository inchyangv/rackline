"""Authorized durable review commands. No API path signs or fabricates financial approval."""

import hashlib
import json
import secrets
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from hashcredit_gpu.db import models as M
from hashcredit_gpu.db.ledgers import AuditLog, ExceptionCase, Job, ProofRequest
from hashcredit_gpu.db.product_models import ApiCommand, ConnectionApplication, OperationReview

from ..auth import roles as R
from ..errors import ApiError, forbidden_scope, not_configured, not_found, validation
from ..permissions.deps import Principal, current_principal


def new_id():
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    value = (int(datetime.now(timezone.utc).timestamp() * 1000) << 80) | secrets.randbits(80)
    return "".join(alphabet[(value >> (5 * i)) & 31] for i in range(25, -1, -1))


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    idempotencyKey: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")


class Onboarding(Command):
    jurisdiction: str = Field(min_length=2, max_length=64)
    registrationReference: str = Field(min_length=7, max_length=300, pattern=r"^(doc|vault|secret)://[^\s]+$")


class Connect(Command):
    providerId: str = Field(min_length=1, max_length=64)
    externalAccountId: str = Field(min_length=1, max_length=128)
    evidenceReference: str = Field(min_length=7, max_length=300, pattern=r"^(doc|vault|secret)://[^\s]+$")
    reason: str = Field(min_length=5, max_length=1000)


class Action(Command):
    action: Literal["assign", "acknowledge", "retry", "resolve"]
    reason: str = Field(min_length=5, max_length=1000)
    expectedVersion: int = Field(ge=0)


def audit(session, p, action, entity_table, entity_id, before, after, reason, role=None):
    payload = {"actor": p.wallet.lower(), "action": action, "entity": entity_id,
               "before": before, "after": after, "reason": reason, "at": datetime.now(timezone.utc).isoformat()}
    digest = "0x" + hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    session.add(AuditLog(actor=p.wallet.lower(), actor_role=role or R.BORROWER, action=action,
        entity_table=entity_table, entity_id=entity_id, before=before, after={**after, "reason": reason}, entry_hash=digest))


def execute(request, p, scope, body, fn):
    repository = request.app.state.product
    if repository.engine is None:
        raise not_configured("GPU database is not configured")
    encoded = json.dumps(body.model_dump(), sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    key = (p.chain_id, p.wallet.lower(), scope, body.idempotencyKey)
    with Session(repository.engine) as session, session.begin():
        # Serialize all commands for this wallet; row locks below also serialize staff case edits.
        lock = int.from_bytes(hashlib.sha256(f"{p.chain_id}:{p.wallet.lower()}".encode()).digest()[:8], "big", signed=True)
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})
        prior = session.get(ApiCommand, key)
        if prior:
            if prior.payload_hash != digest:
                raise ApiError(409, "IDEMPOTENCY_CONFLICT", "idempotency key was already used with different input")
            return prior.response
        result = {"schemaVersion": "1.0", "data": fn(session), "financialAuthorization": False}
        session.add(ApiCommand(chain_id=key[0], wallet=key[1], scope=key[2], idempotency_key=key[3],
                               payload_hash=digest, response=result))
        return result


def build_commands_router():
    router = APIRouter(prefix="/v1", tags=["gpu-commands"])

    @router.post("/onboarding", status_code=201)
    def onboard(body: Onboarding, request: Request, p: Principal = Depends(current_principal)):
        def run(session):
            existing = session.scalar(select(M.BorrowerWallet).where(M.BorrowerWallet.chain_id == p.chain_id,
                M.BorrowerWallet.address == p.wallet.lower(), M.BorrowerWallet.released_at.is_(None)))
            if existing:
                return {"borrowerId": existing.borrower_id, "state": "PENDING_REVIEW", "refreshSession": True}
            entity_id, borrower_id = new_id(), new_id()
            session.add(M.LegalEntity(legal_entity_id=entity_id, jurisdiction=body.jurisdiction,
                                     registration_ref=body.registrationReference))
            session.flush()
            session.add(M.Borrower(borrower_id=borrower_id, legal_entity_id=entity_id, kyc_status="PENDING"))
            session.flush()
            # The signature verifies this wallet only, never the submitted legal identity.
            session.add(M.BorrowerWallet(borrower_id=borrower_id, chain_id=p.chain_id, address=p.wallet.lower(),
                                        role="SIGNER", verified_at=datetime.now(timezone.utc)))
            audit(session, p, "SUBMIT_ONBOARDING", "borrowers", borrower_id, None,
                  {"kycStatus": "PENDING", "underwritingStatus": "NONE"}, "wallet-signed submission for review")
            return {"borrowerId": borrower_id, "state": "PENDING_REVIEW", "refreshSession": True}
        return execute(request, p, "onboarding", body, run)

    @router.post("/connections", status_code=202)
    def connect(body: Connect, request: Request, p: Principal = Depends(current_principal)):
        if p.borrower_id is None or R.BORROWER not in p.roles:
            raise forbidden_scope("complete borrower onboarding and refresh your wallet session")
        def run(session):
            provider = session.get(M.Provider, body.providerId)
            if provider is None or provider.execution_profile != request.app.state.product.settings.execution_profile:
                raise not_found()
            prior = session.scalar(select(ConnectionApplication).where(ConnectionApplication.borrower_id == p.borrower_id,
                ConnectionApplication.provider_id == body.providerId, ConnectionApplication.external_account_id == body.externalAccountId))
            if prior:
                return {"applicationId": prior.application_id, "state": prior.status, "credentialConfigured": False}
            ident = new_id()
            session.add(ConnectionApplication(application_id=ident, borrower_id=p.borrower_id,
                provider_id=body.providerId, external_account_id=body.externalAccountId,
                evidence_ref=body.evidenceReference, reason=body.reason))
            audit(session, p, "REQUEST_CONNECTION", "connection_applications", ident, None,
                  {"status": "PENDING_REVIEW", "providerId": body.providerId}, body.reason)
            return {"applicationId": ident, "state": "PENDING_REVIEW", "credentialConfigured": False}
        return execute(request, p, "connections", body, run)

    @router.get("/connection-requests")
    def requests(request: Request, p: Principal = Depends(current_principal)):
        if p.borrower_id is None:
            raise forbidden_scope("borrower onboarding is required")
        with request.app.state.product.session() as session:
            metadata = request.app.state.product.metadata(session)
            rows = session.scalars(select(ConnectionApplication).where(ConnectionApplication.borrower_id == p.borrower_id)
                                   .order_by(ConnectionApplication.created_at.desc()).limit(100))
            return {"schemaVersion": "1.0", "data": [{"applicationId": r.application_id, "providerId": r.provider_id,
                "externalAccountId": r.external_account_id, "state": r.status, "createdAt": r.created_at} for r in rows],
                "meta": metadata, "pagination": {"nextCursor": None, "limit": 100}}

    @router.post("/operations/{exception_id}/actions")
    def action(exception_id: str, body: Action, request: Request, p: Principal = Depends(current_principal)):
        from .router import scope
        scope("operations", p)
        def run(session):
            repo = request.app.state.product
            query, key = repo.query("operations", p, True)
            case = session.scalar(query.where(key == exception_id).with_for_update())
            if case is None:
                raise not_found()
            review = session.get(OperationReview, exception_id)
            if review is None:
                review = OperationReview(exception_id=exception_id, version=0, state="OPEN")
                session.add(review)
            if review.version != body.expectedVersion:
                raise ApiError(409, "STATE_CONFLICT", "case changed; refresh before applying this action")
            if case.resolved_at:
                raise ApiError(409, "STATE_CONFLICT", "case is already resolved")
            before = {"version": review.version, "state": review.state}
            if body.action == "assign":
                review.assignee = p.wallet.lower()
                review.state = "ASSIGNED"
            elif body.action == "acknowledge":
                review.state = "ACKNOWLEDGED"
            elif body.action == "retry":
                if case.detail.get("retryable") is False:
                    raise ApiError(409, "STATE_CONFLICT", "case is not eligible for retry")
                job_id = case.detail.get("jobId")
                job = session.get(Job, job_id, with_for_update=True) if job_id else None
                if job is None or job.state not in ("FAILED", "DEAD"):
                    raise ApiError(409, "STATE_CONFLICT", "case has no failed retryable job")
                if (job.last_error or "").startswith("TERMINAL:"):
                    raise ApiError(409, "STATE_CONFLICT", "terminal proof failure requires a new valid request")
                if job.kind not in ("PROOF_FETCH_ARTIFACT", "PROOF_WAIT_ATTESTATION"):
                    raise forbidden_scope("this job requires its dedicated financial authorization workflow")
                proof_id = job.payload.get("proofRequestId")
                proof = session.get(ProofRequest, proof_id, with_for_update=True) if proof_id else None
                if not proof or (proof.execution_profile, proof.manifest_hash) != (repo.settings.execution_profile, repo.settings.manifest_hash):
                    raise ApiError(409, "STATE_CONFLICT", "job has no proof in this deployment")
                allowed = {"OBSERVED", "WAITING_ATTESTATION"} if job.kind == "PROOF_WAIT_ATTESTATION" else {"WAITING_ATTESTATION"}
                if proof.status not in allowed:
                    raise ApiError(409, "STATE_CONFLICT", "proof is terminal or has moved past this job; refresh its verified status")
                job.state, job.next_run_at, job.last_error = "PENDING", datetime.now(timezone.utc), None
                job.max_attempts = max(job.max_attempts, job.attempt + 3)
                review.state = "RETRY_REQUESTED"
            else:
                if case.severity == "BLOCKING":
                    raise ApiError(409, "STATE_CONFLICT", "blocking cases require verified remediation before resolution")
                review.state = "RESOLVED"
                case.resolved_at, case.resolved_by, case.resolution = datetime.now(timezone.utc), R.OPERATOR, body.reason
            review.version += 1
            review.last_reason, review.updated_at = body.reason, datetime.now(timezone.utc)
            after = {"exceptionId": exception_id, "version": review.version, "state": review.state, "assignee": review.assignee}
            actor_role = next(r for r in (R.OPERATOR, R.SERVICER, R.GUARDIAN) if r in p.roles)
            audit(session, p, body.action.upper(), "exceptions", exception_id, before, after, body.reason, actor_role)
            return after
        return execute(request, p, "operations:" + exception_id, body, run)

    return router
