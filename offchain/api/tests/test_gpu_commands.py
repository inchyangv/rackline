"""Real DB/wallet tests for review persistence, replay safety and denial boundaries."""

from eth_account import Account
import pytest
from eth_account.messages import encode_typed_data
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from hashcredit_gpu.db.models import Borrower, ProviderAccount
from hashcredit_gpu.db.ledgers import AuditLog
from hashcredit_gpu.db.product_models import ConnectionApplication

from .test_gpu_product_api import setup, login, uid, pg_server_url, fresh_db_url, migrated_db_url


def test_onboarding_durable_idempotent_without_credit_or_legal_approval(setup):
    client, engine, _, _ = setup
    wallet = Account.create()
    headers = login(client, wallet)
    body = {"jurisdiction": "KR", "registrationReference": "doc://review/company", "idempotencyKey": "onboard-0001"}
    first = client.post("/v1/onboarding", headers=headers, json=body)
    assert first.status_code == 201, first.text
    assert client.post("/v1/onboarding", headers=headers, json=body).json() == first.json()
    changed = client.post("/v1/onboarding", headers=headers, json={**body, "jurisdiction": "US"})
    assert changed.status_code == 409
    borrower_id = first.json()["data"]["borrowerId"]
    with Session(engine) as session:
        borrower = session.get(Borrower, borrower_id)
        assert borrower.kyc_status == "PENDING"
        assert borrower.underwriting_status == "NONE"
        assert session.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.entity_id == borrower_id)) == 1
    refreshed = login(client, wallet)
    assert client.get("/v1/me", headers=refreshed).json()["data"]["borrowerId"] == borrower_id
    assert client.get("/v1/facilities", headers=refreshed).json()["data"] == []


def test_connection_request_does_not_claim_account_or_native_evidence(setup):
    client, engine, wallets, _ = setup
    headers = login(client, wallets[0])
    body = {"providerId": "mockdepin-testonly", "externalAccountId": "account-2",
            "evidenceReference": "doc://review/ownership", "reason": "Please review this account",
            "idempotencyKey": "connect-0001"}
    response = client.post("/v1/connections", headers=headers, json=body)
    assert response.status_code == 202, response.text
    assert response.json()["data"]["state"] == "PENDING_REVIEW"
    assert client.post("/v1/connections", headers=headers, json=body).json() == response.json()
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ConnectionApplication)) == 1
        assert session.get(ProviderAccount, "mockdepin-testonly:account-2").borrower_id == uid(202)
    own = client.get("/v1/connection-requests", headers=headers)
    assert len(own.json()["data"]) == 1 and "doc://" not in own.text
    assert client.get("/v1/connection-requests", headers=login(client, wallets[1])).json()["data"] == []


def test_operations_optimistic_version_audit_and_no_fake_retry(setup):
    client, engine, wallets, _ = setup
    headers = login(client, wallets[2])
    path = f"/v1/operations/{uid(700)}/actions"
    body = {"action": "acknowledge", "reason": "Investigating source discrepancy",
            "expectedVersion": 0, "idempotencyKey": "action-0001"}
    result = client.post(path, headers=headers, json=body)
    assert result.status_code == 200, result.text
    assert result.json()["data"]["version"] == 1
    assert client.post(path, headers=headers, json=body).json() == result.json()
    stale = client.post(path, headers=headers, json={**body, "idempotencyKey": "action-0002"})
    assert stale.status_code == 409
    denied = client.post(path, headers=login(client, wallets[0]), json=body)
    assert denied.status_code == 403
    retry = client.post(path, headers=headers, json={**body, "action": "retry", "expectedVersion": 1,
                                                   "idempotencyKey": "action-0003"})
    assert retry.status_code == 409
    resolve = client.post(path, headers=headers, json={**body, "action": "resolve", "expectedVersion": 1,
                                                     "idempotencyKey": "action-0004"})
    assert resolve.status_code == 409
    record = client.get(f"/v1/operations/{uid(700)}", headers=headers).json()["data"]
    assert record["version"] == 1 and record["state"] == "ACKNOWLEDGED"
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(AuditLog)) == 1


def test_challenge_shared_across_replicas_and_replay_rejected(setup):
    from fastapi.testclient import TestClient
    from hashcredit_api.gpu.app import create_app
    client, _, wallets, app = setup
    wallet = wallets[0]
    challenge = client.post("/gpu/auth/challenge", json={"wallet": wallet.address, "chainId": 102031}).json()
    body = {"wallet": wallet.address, "chainId": 102031, "nonce": challenge["nonce"],
            "signature": wallet.sign_message(encode_typed_data(full_message=challenge["typedData"])).signature.hex()}
    with TestClient(create_app(app.state.product.settings, roles=app.state.gpu.roles)) as replica:
        assert replica.post("/gpu/auth/verify", json=body).status_code == 200
        assert client.post("/gpu/auth/verify", json=body).status_code == 401


def test_unconfigured_contracts_are_visible_but_never_simulated(setup):
    client, _, wallets, _ = setup
    config = client.get("/v1/config")
    assert config.status_code == 200 and config.json()["configured"] is False
    assert "rpcUrl" not in config.json()
    assert client.get("/v1/lp", headers=login(client, wallets[0])).status_code == 503


def test_proof_requests_persist_with_wallet_scope_and_never_claim_acceptance(setup, monkeypatch, tmp_path):
    import json
    from pathlib import Path
    from hashcredit_gpu.db.models import Provider
    from hashcredit_gpu.db.ledgers import ProofRequest, Job
    from .test_gpu_product_api import MANIFEST
    client, engine, wallets, _ = setup
    manifest = json.loads((Path(__file__).resolve().parents[3] / "config/attestcoin/cc3-testnet.sepolia.json").read_text())
    manifest["manifestHash"] = MANIFEST
    target = tmp_path / "manifest.json"
    target.write_text(json.dumps(manifest))
    monkeypatch.setenv("GPU_ATTESTCOIN_MANIFEST", str(target))
    with Session(engine) as session, session.begin():
        provider = session.get(Provider, "mockdepin-testonly")
        provider.capabilities = {"source_support": "SUPPORTED"}
    headers = login(client, wallets[0])
    body = {"providerAccountId": "mockdepin-testonly:account-1", "txHash": "0x" + "67" * 32,
            "idempotencyKey": "proof-request-0001"}
    first = client.post("/v1/proofs", headers=headers, json=body)
    assert first.status_code == 202, first.text
    assert first.json()["data"]["nativeStatus"] == "NOT_SUBMITTED"
    assert client.post("/v1/proofs", headers=headers, json=body).json() == first.json()
    own = client.get("/v1/proofs", headers=login(client, wallets[0]))
    assert own.status_code == 200 and own.json()["data"] == [first.json()["data"]]
    assert client.get("/v1/proofs", headers=login(client, wallets[1])).json()["data"] == []
    other = client.post("/v1/proofs", headers=login(client, wallets[1]), json=body)
    assert other.status_code == 404
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ProofRequest)) == 1
        assert session.scalar(select(func.count()).select_from(Job)) == 1


def test_onboarding_rejects_unsupported_document_reference(setup):
    client, _, _, _ = setup
    result = client.post("/v1/onboarding", headers=login(client, Account.create()), json={
        "jurisdiction": "KR", "registrationReference": "review://not-a-document",
        "idempotencyKey": "invalid-ref-0001"})
    assert result.status_code == 422


@pytest.mark.parametrize("status", ["INVALID", "UNSUPPORTED", "EXPIRED", "WAITING_ATTESTATION"])
def test_operator_retry_only_restarts_live_proof_stage(setup, status):
    from hashcredit_gpu.db.ledgers import ProofRequest, Job, ExceptionCase
    from hashcredit_gpu.jobs.queue import JobQueue
    from .test_gpu_product_api import MANIFEST
    client, engine, wallets, _ = setup
    proof_id, case_id = uid(820), uid(821)
    with Session(engine) as session, session.begin():
        session.add(ProofRequest(proof_request_id=proof_id, env_id="cc3-testnet", chain_key=1,
            tx_hash="0x" + "83" * 32, provider_id="mockdepin-testonly", execution_profile="NATIVE_TESTNET",
            manifest_hash=MANIFEST, sdk_version="0.18.0", status=status))
    job_id = JobQueue(engine).enqueue("PROOF_WAIT_ATTESTATION", {"proofRequestId": proof_id}, "retryable-proof-stage")
    with Session(engine) as session, session.begin():
        session.get(Job, job_id).state = "DEAD"
        session.add(ExceptionCase(exception_id=case_id, kind="PROOF_JOB_DEAD", severity="BLOCKING",
            entity_table="proof_requests", entity_id=proof_id, detail={"jobId": job_id}))
    response = client.post(f"/v1/operations/{case_id}/actions", headers=login(client, wallets[2]), json={
        "action": "retry", "reason": "Reviewed retry after provider recovery", "expectedVersion": 0,
        "idempotencyKey": "retry-proof-state-1"})
    assert response.status_code == (200 if status == "WAITING_ATTESTATION" else 409), response.text
    with Session(engine) as session:
        assert session.get(Job, job_id).state == ("PENDING" if status == "WAITING_ATTESTATION" else "DEAD")
        assert session.get(ProofRequest, proof_id).status == status
