"""Durable official SDK proof preparation, stateful app submission and canonical consumption."""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from hashcredit_gpu.db.ledgers import (
    EVIDENCE_MEANINGS,
    EvidenceConsumption,
    ExceptionCase,
    Job,
    NativeVerification,
    ProofArtifact,
    ProofRequest,
)
from hashcredit_gpu.db.models import ProviderAccount
from hashcredit_gpu.db.product_models import OperationReview
from hashcredit_gpu.db.projections_models import ChainCursor, ChainDeployment, ProjectedEvidence
from hashcredit_gpu.ingestion.collector import FileRawStore, payload_hash_of
from hashcredit_gpu.jobs import (
    ClaimedJob,
    FailureKind,
    JobQueue,
    LeaseLost,
    TerminalError,
    TransientError,
    Worker,
)
from hashcredit_gpu.jobs.outbox import emit
from hashcredit_gpu.jobs.proof import Outcome, ProofLifecycle, job_key
from hashcredit_gpu.jobs.queue import new_ulid
from hashcredit_gpu.projections.views import ContractViews
from hashcredit_gpu.transactions import intents
from hashcredit_gpu.transactions.abi import keccak_hex
from hashcredit_gpu.transactions.dispatcher import AccountSigner, Dispatcher, DispatcherConfig
from hashcredit_gpu.transactions.intents import IntentState
from hashcredit_gpu.transactions.rpc import JsonRpcClient, load_rpc_allowlist
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import DisconnectionError, OperationalError
from sqlalchemy.orm import Session


class ProofTransientFailure(TransientError):
    def __init__(self, outcome: Outcome):
        self.outcome = outcome
        super().__init__(str(outcome))


class ProofTerminalFailure(TerminalError):
    def __init__(self, outcome: Outcome):
        self.outcome = outcome
        super().__init__(str(outcome))


class ProofWorker(Worker):
    """Publish actionable dead letters atomically; exhausted polling is not loan default."""

    def __init__(self, *args, deployment_id: str, manifest: dict, **kwargs):
        super().__init__(*args, **kwargs)
        self.deployment_id = deployment_id
        self.manifest = manifest

    def _jobs(self):
        # A different deployment's worker must never lease and terminal-reject this proof.
        return select(Job).join(ProofRequest, ProofRequest.proof_request_id == Job.payload["proofRequestId"].astext).where(
            Job.kind.in_(self.kinds), ProofRequest.manifest_hash == self.manifest["manifestHash"],
            ProofRequest.execution_profile == self.manifest["executionProfile"],
            ProofRequest.chain_key == self.manifest["source"]["chainKey"],
            ProofRequest.sdk_version == self.manifest["sdk"]["version"],
        )

    def _lock_case(self, cx, job):
        cx.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                   {"key": "proof-dead-letter:" + job.job_id})
        cx.execute(text(
            "SELECT exception_id FROM exceptions WHERE entity_table='proof_requests' "
            "AND entity_id=:request AND detail->>'jobId'=:job AND resolved_at IS NULL FOR UPDATE"
        ), {"request": job.payload.get("proofRequestId"), "job": job.job_id})

    def _before_handler(self, cx, job):
        # Match API and failure order (case -> job -> proof), including late handlers
        # whose lease has already been replaced. NO KEY UPDATE permits the dispatcher's
        # separate transaction to insert a TxIntent with a job foreign key.
        self._lock_case(cx, job)
        held = cx.execute(text(
            "SELECT job_id FROM jobs WHERE job_id=:id AND state='LEASED' AND leased_by=:worker "
            "AND attempt=:attempt AND lease_until>=now() FOR NO KEY UPDATE"
        ), {"id": job.job_id, "worker": job.worker_id, "attempt": job.attempt}).scalar()
        if held is None:
            raise LeaseLost("proof lease is no longer held before handling")

    def _reap_exhausted(self):
        try:
            with self.engine.begin() as cx, Session(bind=cx) as s:
                row = s.scalar(self._jobs().where(
                    Job.state == "LEASED", Job.attempt >= Job.max_attempts,
                    Job.lease_until < func.now(),
                ).order_by(Job.next_run_at, Job.job_id).limit(1))
                if row is None:
                    return None
                job = ClaimedJob(row.job_id, row.kind, row.payload, row.semantic_idempotency_key,
                                 row.attempt, row.max_attempts, row.leased_by, row.lease_until)
                self._publish_dead_letter(cx, job, FailureKind.TRANSIENT)
                # An expired final lease cannot be reclaimed by claim(). Reap its exact
                # generation without ever executing the handler or assuming its outcome.
                updated = cx.execute(text(
                    "UPDATE jobs SET state='DEAD', lease_until=NULL, leased_by=NULL, updated_at=now(), "
                    "last_error='TRANSIENT: worker lease expired after final attempt (attempts exhausted)' "
                    "WHERE job_id=:id AND state='LEASED' AND attempt=:attempt AND leased_by=:worker "
                    "AND lease_until=:deadline AND lease_until<now() AND attempt>=max_attempts"
                ), {"id": job.job_id, "attempt": job.attempt, "worker": job.worker_id,
                    "deadline": job.lease_until})
                if updated.rowcount != 1:
                    raise LeaseLost("exhausted lease changed before publication")
                return "DEAD"
        except LeaseLost:
            return "LEASE_LOST"

    def run_once(self):
        reaped = self._reap_exhausted()
        if reaped is not None:
            return reaped
        with Session(self.engine) as s:
            candidates = s.scalars(self._jobs().with_only_columns(Job.job_id).where(
                Job.state.in_(("PENDING", "LEASED")), Job.attempt < Job.max_attempts,
                Job.next_run_at <= func.now(),
                (Job.lease_until.is_(None)) | (Job.lease_until < func.now()),
            ).order_by(Job.next_run_at, Job.job_id).limit(8)).all()
        job = self.queue.claim(self.worker_id, self.kinds, self.lease_seconds, job_ids=candidates)
        return None if job is None else self.run_one(job)

    def _publish_dead_letter(self, cx, job, kind):
        with Session(bind=cx) as s:
            request = s.get(ProofRequest, job.payload.get("proofRequestId"))
            if request is None:
                # A malformed job has no authenticated source/account scope to publish under.
                logging.getLogger(__name__).error("proof job %s has no request", job.job_id)
                return
            cx.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                       {"key": "proof-dead-letter:" + job.job_id})
            case = s.scalar(select(ExceptionCase).where(
                ExceptionCase.entity_table == "proof_requests",
                ExceptionCase.entity_id == request.proof_request_id,
                ExceptionCase.detail["jobId"].astext == job.job_id,
                ExceptionCase.resolved_at.is_(None),
            ).with_for_update())
            allowed = {"PROOF_WAIT_ATTESTATION": {"OBSERVED", "WAITING_ATTESTATION"},
                       "PROOF_FETCH_ARTIFACT": {"WAITING_ATTESTATION"}}
            retryable = kind == FailureKind.TRANSIENT and request.status in allowed.get(job.kind, set())
            failure = "TERMINAL" if kind == FailureKind.TERMINAL else "TRANSIENT_EXHAUSTED"
            detail = {
                "jobId": job.job_id, "jobKind": job.kind, "failureKind": failure,
                "proofStatus": request.status, "retryable": retryable,
                "attempt": job.attempt, "maxAttempts": job.max_attempts,
                "deploymentId": self.deployment_id, "executionProfile": request.execution_profile,
                "manifestHash": request.manifest_hash,
                # Do not copy remote SDK/RPC text into operator-visible payloads.
                "errorCode": "PROOF_TERMINAL_FAILURE" if kind == FailureKind.TERMINAL else "PROOF_RETRY_EXHAUSTED",
                "financialAuthorization": False,
            }
            if case is None:
                case = ExceptionCase(exception_id=new_ulid(), entity_table="proof_requests",
                                     entity_id=request.proof_request_id)
                s.add(case)
            case.kind, case.detail = detail["errorCode"], detail
            case.severity = "BLOCKING" if kind == FailureKind.TERMINAL else "WARNING"
            s.flush()
            review = s.get(OperationReview, case.exception_id)
            if review is not None:
                if review.state == "RETRY_REQUESTED":
                    review.state = "OPEN"
                review.version += 1
                review.last_reason = "Proof worker exhausted the retry or encountered a terminal failure."
                review.updated_at = datetime.now(UTC)
                s.flush()
            emit(cx, aggregate_type="exceptions", aggregate_id=case.exception_id,
                 event_type="PROOF_JOB_DEAD_LETTERED", payload={"exceptionId": case.exception_id, **detail},
                 idempotency_key=f"proof-dead-letter:{job.job_id}:{job.attempt}:{job.lease_until.isoformat()}")

    def _fail_exception(self, job, kind, error):
        if isinstance(error, (ProofTransientFailure, ProofTerminalFailure)):
            return self._fail(job, kind, str(error), proof_outcome=error.outcome)
        return super()._fail_exception(job, kind, error)

    def _record_proof_failure(self, cx, job, outcome):
        with Session(bind=cx) as s:
            request = s.get(ProofRequest, job.payload.get("proofRequestId"), with_for_update=True)
            if request is None or request.status not in {"OBSERVED", "WAITING_ATTESTATION"}:
                return  # never downgrade a prepared/accepted/consumed or terminal proof
            if outcome in {Outcome.NOT_READY, Outcome.NETWORK_ERROR}:
                if job.kind == "PROOF_WAIT_ATTESTATION":
                    request.status = "WAITING_ATTESTATION"
            else:
                request.status = str(outcome)
            request.last_error = str(outcome)  # stable code only; no remote diagnostic text
            request.attempt += 1
            request.updated_at = datetime.now(UTC)
            s.flush()

    def _fail(self, job, kind, reason, *, proof_outcome=None):
        try:
            with self.engine.begin() as cx:
                dead = kind == FailureKind.TERMINAL or job.attempt >= job.max_attempts
                # Do this for transient outcomes too: a delayed old transient worker
                # may race an API retry of a newer generation's terminal case.
                self._lock_case(cx, job)
                state = self.queue.fail(job, kind, reason, cx=cx)
                if proof_outcome is not None:
                    self._record_proof_failure(cx, job, proof_outcome)
                if dead:
                    self._publish_dead_letter(cx, job, kind)
                return state
        except LeaseLost:
            logging.getLogger(__name__).warning("proof job %s lost its outcome lease", job.job_id)
            return "LEASE_LOST"


class OfficialSdkClient:
    def __init__(self, manifest: str, cli: str, *, node: str = "node", timeout: float = 45):
        self.manifest_path = str(Path(manifest).resolve())
        self.manifest = json.loads(Path(self.manifest_path).read_text())
        self.cli, self.node, self.timeout = str(Path(cli).resolve()), node, timeout

    def call(self, command: str, payload: dict) -> dict:
        if command not in {"proof", "encode-submission"}:
            raise ValueError("unsupported official SDK operation")
        body = json.dumps(payload, separators=(",", ":")).encode()
        if len(body) > 4_194_304:
            raise TerminalError("official SDK input exceeds bound")
        try:
            # Fixed executable/argument array; no shell. stderr cannot leak remote URLs or secrets.
            with tempfile.TemporaryFile() as output:
                result = subprocess.run(
                    [self.node, self.cli, command, "--manifest", self.manifest_path],
                    input=body,
                    stdout=output,
                    stderr=subprocess.DEVNULL,
                    timeout=self.timeout,
                    check=False,
                    env={
                        k: v
                        for k, v in os.environ.items()
                        if k in {"PATH", "LANG", "NODE_EXTRA_CA_CERTS"}
                    },
                )
                if result.returncode:
                    raise TransientError("official SDK command failed")
                size = output.tell()
                if size > 4_194_304:
                    raise TerminalError("official SDK output exceeds bound")
                output.seek(0)
                response = json.load(output)
        except subprocess.TimeoutExpired as exc:
            raise TransientError("official SDK timeout") from exc
        except (ValueError, OSError) as exc:
            raise TransientError("official SDK returned invalid JSON or could not start") from exc
        if not isinstance(response, dict) or response.get("version") != 1:
            raise TerminalError("official SDK response schema mismatch")
        return response


class ProofPipeline:
    """Plans are operator-reviewed source/app bindings, never browser-supplied calldata."""

    def __init__(self, engine, sdk, raw_store, deployment_id, dispatcher=None, plans=None):
        self.engine, self.sdk, self.store = engine, sdk, raw_store
        self.deployment_id, self.dispatcher, self.plans = deployment_id, dispatcher, plans or {}
        self.queue = JobQueue(engine)

    @property
    def handlers(self):
        handlers = {"PROOF_WAIT_ATTESTATION": self.fetch, "PROOF_FETCH_ARTIFACT": self.fetch}
        if self.dispatcher:
            handlers.update(
                {
                    "PROOF_SUBMIT": self.submit,
                    "PROOF_CONFIRM": self.confirm,
                    "EVIDENCE_CONSUME": self.consume,
                }
            )
        return handlers

    def _request(self, s, job):
        request = s.get(ProofRequest, job.payload["proofRequestId"])
        if request is None:
            raise TerminalError("unknown proof request")
        m = self.sdk.manifest
        if (
            request.manifest_hash != m["manifestHash"]
            or request.execution_profile != m["executionProfile"]
            or request.chain_key != m["source"]["chainKey"]
            or request.sdk_version != m["sdk"]["version"]
        ):
            raise TerminalError("proof request does not match worker manifest")
        return request

    def _advance(self, cx, request_id, kind):
        result = ProofLifecycle.apply(cx, request_id, kind, Outcome.OK)
        if result.next_kind:
            self.queue.enqueue(
                result.next_kind,
                {"proofRequestId": request_id},
                job_key(result.next_kind, request_id),
                max_attempts=100,
                cx=cx,
            )

    def fetch(self, cx, job):
        with Session(bind=cx) as s:
            request = self._request(s, job)
            if request.status in {"PROOF_READY", "SUBMITTED", "NATIVE_ACCEPTED", "CONSUMED"}:
                return
            output = self.sdk.call(
                "proof",
                {"version": 1, "txHash": request.tx_hash, "manifestHash": request.manifest_hash},
            )
            if (
                output.get("manifestHash") != request.manifest_hash
                or output.get("txHash") != request.tx_hash
            ):
                raise TerminalError("SDK response belongs to another request")
            if output.get("status") != "PROOF_READY":
                try:
                    outcome = Outcome(output.get("status"))
                except ValueError:
                    outcome = Outcome.INVALID
                # The worker records this after handler rollback in the SAME transaction
                # as its fenced job outcome. No autonomous stale-worker status writes.
                if outcome in {Outcome.NOT_READY, Outcome.NETWORK_ERROR}:
                    raise ProofTransientFailure(outcome)
                if outcome not in {Outcome.UNSUPPORTED, Outcome.INVALID, Outcome.EXPIRED}:
                    outcome = Outcome.INVALID
                raise ProofTerminalFailure(outcome)
            if (
                output.get("nativeAccepted") is not False
                or output.get("sdkVersion") != request.sdk_version
            ):
                raise TerminalError(
                    "SDK output cannot claim native acceptance or another SDK version"
                )
            body = json.dumps(output, sort_keys=True, separators=(",", ":")).encode()
            digest = payload_hash_of(body)
            ref = self.store.put(digest, body)
            artifact = s.scalar(
                select(ProofArtifact).where(
                    ProofArtifact.proof_request_id == request.proof_request_id,
                    ProofArtifact.artifact_hash == digest,
                )
            )
            if not artifact:
                s.add(
                    ProofArtifact(
                        proof_artifact_id=new_ulid(),
                        proof_request_id=request.proof_request_id,
                        artifact_hash=digest,
                        storage_ref=ref,
                        byte_length=len(body),
                        sdk_version=request.sdk_version,
                        encoding_version=request.encoding_version,
                        claimed_height=int(output["height"]),
                        claimed_tx_index=output["txIndex"],
                    )
                )
            request.api_ready_at = datetime.now(UTC)
            s.flush()
            if request.status == "OBSERVED":
                self._advance(cx, request.proof_request_id, "PROOF_WAIT_ATTESTATION")
            self._advance(cx, request.proof_request_id, "PROOF_FETCH_ARTIFACT")

    def _artifact(self, s, request):
        artifact = s.scalar(
            select(ProofArtifact)
            .where(ProofArtifact.proof_request_id == request.proof_request_id)
            .order_by(ProofArtifact.created_at.desc())
            .limit(1)
        )
        if artifact is None:
            raise TerminalError("stored proof artifact missing")
        body = (self.store.directory / artifact.artifact_hash[2:]).read_bytes()
        if payload_hash_of(body) != artifact.artifact_hash or len(body) != artifact.byte_length:
            raise TerminalError("stored proof artifact hash mismatch")
        return artifact, json.loads(body)

    def submit(self, cx, job):
        with Session(bind=cx) as s:
            request = self._request(s, job)
            if request.status in {"SUBMITTED", "NATIVE_ACCEPTED", "CONSUMED"}:
                return
            plan = self.plans.get(request.tx_hash)
            if not plan:
                raise TransientError("source business submission plan is not configured")
            artifact, output = self._artifact(s, request)
            encoded = self.sdk.call("encode-submission", {"artifact": output, "plan": plan})
            if (
                encoded.get("manifestHash") != request.manifest_hash
                or encoded.get("purpose") != plan["purpose"]
            ):
                raise TerminalError("submission encoding binding mismatch")
            intent = self.dispatcher.prepare(
                job.job_id, plan["purpose"], bytes.fromhex(encoded["calldata"][2:])
            )
            self.dispatcher.broadcast(intent.tx_intent_id)
            existing = s.scalar(
                select(NativeVerification).where(
                    NativeVerification.proof_request_id == request.proof_request_id,
                    NativeVerification.submission_tx_hash == intent.tx_hash,
                )
            )
            if not existing:
                s.add(
                    NativeVerification(
                        native_verification_id=new_ulid(),
                        proof_request_id=request.proof_request_id,
                        proof_artifact_id=artifact.proof_artifact_id,
                        execution_profile=request.execution_profile,
                        verification_method="ATTESTCOIN_NATIVE",
                        destination_chain_id=int(self.sdk.manifest["destination"]["chainId"]),
                        verifier_address=self.sdk.manifest["destination"]["blockProver"][
                            "address"
                        ].lower(),
                        submission_tx_hash=intent.tx_hash,
                        status="SUBMITTED",
                    )
                )
            s.flush()
            self._advance(cx, request.proof_request_id, "PROOF_SUBMIT")

    def confirm(self, cx, job):
        with Session(bind=cx) as s:
            request = self._request(s, job)
            if request.status in {"NATIVE_ACCEPTED", "CONSUMED"}:
                return
            d = s.get(ChainDeployment, self.deployment_id)
            cursor = s.get(ChainCursor, self.deployment_id)
            if (
                not d
                or d.env_id != request.env_id
                or d.manifest_hash != request.manifest_hash
                or d.execution_profile != request.execution_profile
            ):
                raise TerminalError("proof deployment binding mismatch")
            verification = s.scalar(
                select(NativeVerification)
                .where(NativeVerification.proof_request_id == request.proof_request_id)
                .order_by(NativeVerification.created_at.desc())
                .limit(1)
            )
            if verification is None or cursor is None:
                raise TransientError("submission or finalized index cursor pending")
            # Unknown send outcomes retain the same signed bytes and nonce until mined.
            with self.engine.connect() as intent_cx:
                intent = intents.by_hash(intent_cx, verification.submission_tx_hash)
            if intent is not None:
                settled = self.dispatcher.reconcile(intent.tx_intent_id)
                if settled.state == IntentState.FAILED:
                    ProofLifecycle.apply(
                        cx,
                        request.proof_request_id,
                        job.kind,
                        Outcome.INVALID,
                        error="APP_TRANSACTION_REVERTED",
                    )
                if settled.state != IntentState.FINALIZED:
                    self.dispatcher.broadcast(intent.tx_intent_id)
                    raise TransientError("application transaction finality pending")
            projections = list(
                s.scalars(
                    select(ProjectedEvidence).where(
                        ProjectedEvidence.deployment_id == d.deployment_id,
                        ProjectedEvidence.tier == "FINALIZED",
                        ProjectedEvidence.consumption_tx_hash == verification.submission_tx_hash,
                    )
                )
            )
            plan = self.plans.get(request.tx_hash, {})
            if not projections or len(projections) != len(plan.get("instructions", [])):
                raise TransientError("finalized application consumption pending")
            views = ContractViews(self.dispatcher.rpc, d.contracts)
            if views.read(
                "EvidenceBook", "envIdHash", [], cursor.finalized_block_number
            ) != keccak_hex(request.env_id.encode()):
                raise TerminalError("canonical app environment differs from request")
            for p in projections:
                record = views.read(
                    "EvidenceBook", "record", [p.source_event_id], cursor.finalized_block_number
                )
                if (
                    record["id"] != p.source_event_id
                    or record["economicEventId"] != p.economic_event_key
                    or record["manifestHash"] != "0x" + request.manifest_hash[7:]
                    or record["providerId"] != plan["providerId"]
                    or record["method"] != "0"
                    or record["trust"] != "0"
                    or not p.verified_in_same_tx
                ):
                    raise TerminalError("canonical native app record differs from projection")
                verification.verifier_address = d.contracts["AttestcoinRevenueVerifier"].lower()
                verification.verification_block, verification.receipt_status = p.block_number, 1
                verification.proven_height, verification.proven_tx_index = (
                    p.proven_height,
                    p.proven_tx_index,
                )
                verification.status, verification.accepted_at = "ACCEPTED", datetime.now(UTC)
                s.flush()
            self._advance(cx, request.proof_request_id, "PROOF_CONFIRM")

    def consume(self, cx, job):
        with Session(bind=cx) as s:
            request = self._request(s, job)
            if request.status == "CONSUMED":
                return
            d = s.get(ChainDeployment, self.deployment_id)
            cursor = s.get(ChainCursor, self.deployment_id)
            verification = s.scalar(
                select(NativeVerification).where(
                    NativeVerification.proof_request_id == request.proof_request_id,
                    NativeVerification.status == "ACCEPTED",
                )
            )
            if verification is None:
                raise TransientError("native acceptance pending")
            views = ContractViews(self.dispatcher.rpc, d.contracts)
            projections = list(
                s.scalars(
                    select(ProjectedEvidence).where(
                        ProjectedEvidence.deployment_id == d.deployment_id,
                        ProjectedEvidence.tier == "FINALIZED",
                        ProjectedEvidence.consumption_tx_hash == verification.submission_tx_hash,
                    )
                )
            )
            for p in projections:
                if s.scalar(
                    select(EvidenceConsumption).where(
                        EvidenceConsumption.env_id == request.env_id,
                        EvidenceConsumption.source_event_id == p.source_event_id,
                    )
                ):
                    continue
                record = views.read(
                    "EvidenceBook", "record", [p.source_event_id], cursor.finalized_block_number
                )
                binding = (
                    self.plans[request.tx_hash].get("bindings", {}).get(str(p.proven_log_ordinal))
                )
                if not binding:
                    raise TransientError("economic event/account binding unavailable")
                account = s.get(ProviderAccount, binding["providerAccountId"])
                if (
                    not account
                    or account.provider_id != request.provider_id
                    or record["accountKey"] != keccak_hex(account.provider_account_id.encode())
                    or binding["economicEventKey"] != p.economic_event_key
                    or not binding["economicEventId"].startswith(
                        f"{account.provider_id}/{account.external_account_id}/"
                    )
                ):
                    raise TerminalError("economic account binding mismatch")
                locator = record["locator"]
                s.add(
                    EvidenceConsumption(
                        consumption_id=new_ulid(),
                        env_id=request.env_id,
                        source_event_id=p.source_event_id,
                        economic_event_id=binding["economicEventId"],
                        native_verification_id=verification.native_verification_id,
                        provider_id=request.provider_id,
                        provider_account_id=account.provider_account_id,
                        meaning=EVIDENCE_MEANINGS[int(record["meaning"])],
                        verification_method="ATTESTCOIN_NATIVE",
                        trust="PROVEN",
                        execution_profile=request.execution_profile,
                        consumer_address=record["consumer"],
                        consumption_tx_hash=p.consumption_tx_hash,
                        manifest_hash=request.manifest_hash,
                        proven_at=datetime.fromtimestamp(int(record["provenAt"]), UTC),
                        valid_until=datetime.fromtimestamp(int(record["validUntil"]), UTC),
                        chain_key=int(locator["chainKey"]),
                        height=int(locator["height"]),
                        tx_index=int(locator["txIndex"]),
                        log_ordinal=int(locator["logOrdinal"]),
                        emitter_address=record["emitter"],
                        topic0=record["topic0"],
                        data_hash=record["dataHash"],
                    )
                )
            s.flush()
            self._advance(cx, request.proof_request_id, "EVIDENCE_CONSUME")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument(
        "--sdk-cli", required=True, help="compiled offchain/attestcoin/dist/src/cli.js"
    )
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument(
        "--plans", help="reviewed source submission plan JSON; absent = proof preparation only"
    )
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    engine = create_engine(
        os.environ.get("HASHCREDIT_GPU_DATABASE_URL") or os.environ["GPU_DATABASE_URL"]
    )
    sdk = OfficialSdkClient(args.manifest, args.sdk_cli)
    plans = json.loads(Path(args.plans).read_text()) if args.plans else {}
    dispatcher = None
    if plans:
        _, urls = load_rpc_allowlist(args.manifest)
        rpc = JsonRpcClient(urls[0], urls)
        with Session(engine) as s:
            deployment = s.get(ChainDeployment, args.deployment_id)
            if not deployment:
                raise ValueError("deployment must be registered before starting proof relay")
            contracts = {
                "evidence_book": deployment.contracts["EvidenceBook"],
                "receivable_book": deployment.contracts["ReceivableBook"],
            }
            dispatcher = Dispatcher(
                engine,
                rpc,
                AccountSigner(os.environ["GPU_KEEPER_PRIVATE_KEY"]),
                DispatcherConfig(
                    deployment.chain_id,
                    "keeper",
                    contracts,
                    finality_depth=max(1, deployment.finality_depth),
                ),
            )
    pipeline = ProofPipeline(
        engine, sdk, FileRawStore(args.artifact_dir), args.deployment_id, dispatcher, plans
    )
    worker = ProofWorker(
        engine,
        pipeline.queue,
        pipeline.handlers,
        deployment_id=args.deployment_id,
        manifest=sdk.manifest,
        worker_id=f"proof-{os.getpid()}",
        lease_seconds=120,
    )
    try:
        if args.once:
            print(worker.run_once())
        else:
            while True:
                try:
                    worker.run_forever()
                except (OperationalError, DisconnectionError) as exc:
                    logging.getLogger(__name__).warning(
                        "proof database unavailable (%s); durable lease preserved",
                        type(exc).__name__,
                    )
                    time.sleep(5)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
