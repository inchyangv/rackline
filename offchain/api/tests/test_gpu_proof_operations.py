"""Worker -> scoped operations -> audited retry -> artifact preparation, with no fake verification."""

import pytest
from hashcredit_gpu.db.ledgers import AuditLog, ExceptionCase, Job, NativeVerification, ProofRequest
from hashcredit_gpu.ingestion.collector import FileRawStore
from hashcredit_prover.gpu.attestcoin_worker import ProofPipeline, ProofWorker
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import test_gpu_product_api as support

pg_server_url = support.pg_server_url
fresh_db_url = support.fresh_db_url
migrated_db_url = support.migrated_db_url
setup = support.setup


class SDK:
    """Local transport outcomes only; never native acceptance or real financial evidence."""

    def __init__(self):
        self.manifest = {"manifestHash": support.MANIFEST, "executionProfile": "NATIVE_TESTNET",
                         "source": {"chainKey": 1}, "sdk": {"version": "0.18.0"}}
        self.output = {"version": 1, "manifestHash": support.MANIFEST, "txHash": "0x" + "83" * 32,
                       "status": "NOT_READY", "nativeAccepted": False, "height": "100",
                       "txIndex": 0, "sdkVersion": "0.18.0", "proof": {"untrusted": True}}

    def call(self, *_):
        return dict(self.output)


@pytest.fixture
def flow(setup, tmp_path):
    client, engine, wallets, _ = setup
    proof_id = support.uid(830)
    with Session(engine) as session, session.begin():
        session.add(ProofRequest(proof_request_id=proof_id, env_id="cc3-testnet", chain_key=1,
            tx_hash="0x" + "83" * 32, provider_id="mockdepin-testonly", execution_profile="NATIVE_TESTNET",
            manifest_hash=support.MANIFEST, sdk_version="0.18.0", status="OBSERVED"))
    sdk = SDK()
    pipeline = ProofPipeline(engine, sdk, FileRawStore(tmp_path), support.DEPLOYMENT)
    job_id = pipeline.queue.enqueue("PROOF_WAIT_ATTESTATION", {"proofRequestId": proof_id},
                                     "proof-operations-flow", max_attempts=1)
    worker = ProofWorker(engine, pipeline.queue, pipeline.handlers, deployment_id=support.DEPLOYMENT, manifest=sdk.manifest,
                         worker_id="operations-flow")
    yield client, engine, wallets, sdk, worker, proof_id, job_id


def test_exhausted_worker_case_is_visible_retried_and_resolved_via_authenticated_api(flow):
    client, engine, wallets, sdk, worker, proof_id, job_id = flow
    assert worker.run_once() == "DEAD"
    headers = support.login(client, wallets[2])
    with Session(engine) as session:
        case = session.scalar(select(ExceptionCase).where(ExceptionCase.entity_id == proof_id))
        path = f"/v1/operations/{case.exception_id}"
    listed = client.get("/v1/operations", headers=headers)
    assert listed.status_code == 200
    assert any(row["exceptionId"] == case.exception_id for row in listed.json()["data"])
    assert client.get(path, headers=support.login(client, wallets[0])).status_code == 403
    body = {"action": "retry", "reason": "Attestation cache recovered; retry reviewed",
            "expectedVersion": 0, "idempotencyKey": "proof-retry-flow-001"}
    retried = client.post(path + "/actions", headers=headers, json=body)
    assert retried.status_code == 200, retried.text
    assert retried.json()["data"]["state"] == "RETRY_REQUESTED"
    assert client.post(path + "/actions", headers=headers, json=body).json() == retried.json()
    sdk.output["status"] = "PROOF_READY"
    assert worker.run_once() == "SUCCEEDED"
    with Session(engine) as session:
        assert session.get(Job, job_id).state == "SUCCEEDED"
        assert session.get(Job, job_id).attempt == 2  # API retry never resets the fencing counter
        assert session.get(ProofRequest, proof_id).status == "PROOF_READY"
        assert session.scalar(select(func.count()).select_from(NativeVerification)) == 0
        assert session.scalar(select(func.count()).select_from(AuditLog)) == 1
    resolved = client.post(path + "/actions", headers=headers, json={
        "action": "resolve", "reason": "Artifact fetched; native verification remains unsubmitted",
        "expectedVersion": 1, "idempotencyKey": "proof-resolve-flow-001"})
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["data"]["state"] == "RESOLVED"
    with Session(engine) as session:
        assert session.get(ExceptionCase, case.exception_id).resolved_at is not None
        assert session.scalar(select(func.count()).select_from(NativeVerification)) == 0
        assert session.scalar(select(func.count()).select_from(AuditLog)) == 2


def test_real_terminal_worker_failure_is_not_retryable_even_if_request_status_is_observed(flow):
    client, engine, wallets, sdk, worker, proof_id, job_id = flow
    sdk.output["txHash"] = "0x" + "ff" * 32
    assert worker.run_once() == "DEAD"
    with Session(engine) as session:
        case = session.scalar(select(ExceptionCase).where(ExceptionCase.entity_id == proof_id))
        case_id = case.exception_id
        assert session.get(ProofRequest, proof_id).status == "OBSERVED"
        assert case.detail["retryable"] is False
    denied = client.post(f"/v1/operations/{case_id}/actions", headers=support.login(client, wallets[2]), json={
        "action": "retry", "reason": "An invalid artifact must not be retried as transient",
        "expectedVersion": 0, "idempotencyKey": "proof-terminal-flow-001"})
    assert denied.status_code == 409, denied.text
    with Session(engine) as session:
        assert session.get(Job, job_id).state == "DEAD"
        assert session.scalar(select(func.count()).select_from(AuditLog)) == 0
