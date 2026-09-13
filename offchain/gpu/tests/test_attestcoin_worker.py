"""Proof service readiness never substitutes native acceptance; real PostgreSQL lifecycle."""

from datetime import UTC, datetime, timedelta

import pytest
from hashcredit_prover.gpu.attestcoin_worker import ProofPipeline, ProofTerminalFailure, ProofWorker
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from hashcredit_gpu.db.ledgers import (
    ExceptionCase,
    Job,
    NativeVerification,
    Outbox,
    ProofArtifact,
    ProofRequest,
    TxIntent,
)
from hashcredit_gpu.db.product_models import OperationReview
from hashcredit_gpu.ingestion.collector import FileRawStore
from hashcredit_gpu.jobs import FailureKind, Outcome

from .test_event_ledger import insert_proof_request, ulid
from .test_schema import seed_base


class SDK:
    def __init__(self, request):
        self.manifest = {
            "manifestHash": request.manifest_hash,
            "manifestId": request.env_id,
            "executionProfile": request.execution_profile,
            "source": {"chainKey": request.chain_key},
            "sdk": {"version": request.sdk_version},
        }
        self.output = {
            "version": 1,
            "manifestHash": request.manifest_hash,
            "txHash": request.tx_hash,
            "status": "PROOF_READY",
            "nativeAccepted": False,
            "height": "100",
            "txIndex": 0,
            "sdkVersion": request.sdk_version,
            "proof": {"untrusted": True},
        }

    def call(self, command, body):
        return dict(self.output)


@pytest.fixture
def setup(conn, migrated_db_url, tmp_path):
    seed_base(conn)
    insert_proof_request(conn, ulid("proof"), "0x" + "ab" * 32)
    conn.commit()
    engine = create_engine(migrated_db_url)
    with Session(engine) as s:
        request = s.scalar(select(ProofRequest))
        sdk = SDK(request)
        rid = request.proof_request_id
    p = ProofPipeline(engine, sdk, FileRawStore(tmp_path), ulid("deploy"))
    p.queue.enqueue("PROOF_WAIT_ATTESTATION", {"proofRequestId": rid}, "test:proof")
    w = ProofWorker(engine, p.queue, p.handlers, deployment_id=ulid("deploy"), manifest=sdk.manifest,
                    worker_id="proof-test", lease_seconds=120)
    yield engine, p, sdk, w, rid
    engine.dispose()


def test_api_ready_stores_artifact_but_never_native_acceptance(setup):
    engine, _p, _sdk, worker, rid = setup
    assert worker.run_once() == "SUCCEEDED"
    with Session(engine) as s:
        assert s.get(ProofRequest, rid).status == "PROOF_READY"
        assert s.scalar(select(func.count()).select_from(ProofArtifact)) == 1
        assert s.scalar(select(func.count()).select_from(NativeVerification)) == 0
    # Fetch retry job from same atomic transition is harmless and does not duplicate artifacts.
    assert worker.run_once() == "SUCCEEDED"
    with Session(engine) as s:
        assert s.scalar(select(func.count()).select_from(ProofArtifact)) == 1
    assert "PROOF_SUBMIT" not in worker.handlers  # signer-less mode cannot silently send


def test_cache_lag_retries_without_claiming_verified(setup):
    engine, _p, sdk, worker, rid = setup
    sdk.output.update(status="NOT_READY", code="ATTESTATION_NOT_READY")
    assert worker.run_once() == "PENDING"
    with Session(engine) as s:
        assert s.get(ProofRequest, rid).status == "WAITING_ATTESTATION"
        assert s.scalar(select(func.count()).select_from(ProofArtifact)) == 0
        assert s.scalar(select(func.count()).select_from(ExceptionCase)) == 0


def test_wrong_artifact_dead_letters_and_preserves_request(setup):
    engine, _p, sdk, worker, rid = setup
    sdk.output["txHash"] = "0x" + "ff" * 32
    assert worker.run_once() == "DEAD"
    with Session(engine) as s:
        assert s.get(ProofRequest, rid).status == "OBSERVED"
        assert s.scalar(select(func.count()).select_from(ProofArtifact)) == 0
        case = s.scalar(select(ExceptionCase))
        assert case.kind == "PROOF_TERMINAL_FAILURE"
        assert case.detail["proofStatus"] == "OBSERVED"
        assert case.detail["retryable"] is False  # terminal cause, not just terminal request status


def test_unsupported_is_terminal_without_fallback(setup):
    engine, p, sdk, worker, rid = setup
    sdk.output.update(status="UNSUPPORTED", code="UNSUPPORTED_SOURCE")
    assert worker.run_once() == "DEAD"
    with Session(engine) as s:
        assert s.get(ProofRequest, rid).status == "UNSUPPORTED"
    assert not any("FALLBACK" in k or "SIGN" in k for k in p.handlers)


def test_claimed_native_success_is_rejected(setup):
    engine, _p, sdk, worker, _rid = setup
    sdk.output["nativeAccepted"] = True
    assert worker.run_once() == "DEAD"
    with Session(engine) as s:
        assert s.scalar(select(func.count()).select_from(NativeVerification)) == 0


@pytest.mark.parametrize("status", ["UNSUPPORTED", "INVALID", "EXPIRED"])
def test_terminal_proof_publishes_scoped_nonretryable_case_with_no_economic_effect(setup, status):
    engine, _p, sdk, worker, rid = setup
    sdk.output.update(status=status, code="remote-sensitive-value-must-not-reach-case")
    assert worker.run_once() == "DEAD"
    with Session(engine) as s:
        case = s.scalar(select(ExceptionCase))
        job = s.scalar(select(Job))
        assert (case.entity_table, case.entity_id) == ("proof_requests", rid)
        assert case.detail["jobId"] == job.job_id
        assert case.detail["failureKind"] == "TERMINAL"
        assert case.detail["proofStatus"] == status
        assert case.detail["retryable"] is False
        assert case.detail["financialAuthorization"] is False
        assert case.severity == "BLOCKING"
        assert "remote-sensitive" not in str(case.detail)
        event = s.scalar(select(Outbox).where(Outbox.event_type == "PROOF_JOB_DEAD_LETTERED"))
        assert event.aggregate_id == case.exception_id
        assert s.scalar(select(func.count()).select_from(NativeVerification)) == 0


def test_transient_exhaustion_reuses_open_case_and_reopens_operator_retry(setup):
    engine, _p, sdk, worker, rid = setup
    sdk.output.update(status="NOT_READY", code="ATTESTATION_NOT_READY")
    with Session(engine) as s:
        s.scalar(select(Job)).max_attempts = 1
        s.commit()
    assert worker.run_once() == "DEAD"
    with Session(engine) as s:
        case = s.scalar(select(ExceptionCase))
        case_id = case.exception_id
        assert case.kind == "PROOF_RETRY_EXHAUSTED"
        assert case.detail["failureKind"] == "TRANSIENT_EXHAUSTED"
        assert case.detail["retryable"] is True and case.severity == "WARNING"
        assert s.get(ProofRequest, rid).status == "WAITING_ATTESTATION"
        # Model the authorized API's retry without resetting the lease fencing counter.
        job = s.scalar(select(Job))
        job.state, job.max_attempts, job.next_run_at = "PENDING", 2, datetime.now(UTC)
        s.add(OperationReview(exception_id=case_id, version=1, state="RETRY_REQUESTED"))
        s.commit()
    assert worker.run_once() == "DEAD"
    with Session(engine) as s:
        assert s.scalar(select(func.count()).select_from(ExceptionCase)) == 1
        assert s.get(ExceptionCase, case_id).detail["attempt"] == 2
        review = s.get(OperationReview, case_id)
        assert (review.state, review.version) == ("OPEN", 2)
        assert s.scalar(select(func.count()).select_from(Outbox)) == 2
        assert s.scalar(select(func.count()).select_from(NativeVerification)) == 0


def test_case_and_dead_transition_roll_back_together_when_publication_fails(setup, monkeypatch):
    engine, _p, sdk, worker, rid = setup
    sdk.output.update(status="UNSUPPORTED")
    publish = worker._publish_dead_letter

    def crash(cx, job, kind):
        publish(cx, job, kind)
        raise RuntimeError("simulated publication crash")

    monkeypatch.setattr(worker, "_publish_dead_letter", crash)
    with pytest.raises(RuntimeError, match="simulated publication crash"):
        worker.run_once()
    with Session(engine) as s:
        assert s.scalar(select(Job)).state == "LEASED"
        assert s.get(ProofRequest, rid).status == "OBSERVED"
        assert s.scalar(select(func.count()).select_from(ExceptionCase)) == 0
        assert s.scalar(select(func.count()).select_from(Outbox)) == 0


def test_lost_lease_does_not_publish_phantom_dead_letter(setup):
    engine, p, _sdk, worker, _rid = setup
    claimed = p.queue.claim(worker.worker_id, worker.kinds, worker.lease_seconds)
    with Session(engine) as s:
        s.get(Job, claimed.job_id).lease_until = datetime.now(UTC) - timedelta(seconds=1)
        s.commit()
    assert worker._fail(claimed, FailureKind.TERMINAL, "invalid") == "LEASE_LOST"
    with Session(engine) as s:
        assert s.get(Job, claimed.job_id).state == "LEASED"
        assert s.scalar(select(func.count()).select_from(ExceptionCase)) == 0
        assert s.scalar(select(func.count()).select_from(Outbox)) == 0


def test_final_attempt_process_crash_is_reaped_to_retryable_case_without_reexecuting(setup):
    engine, p, _sdk, worker, rid = setup
    with Session(engine) as s:
        s.scalar(select(Job)).max_attempts = 1
        s.commit()
    claimed = p.queue.claim(worker.worker_id, worker.kinds, worker.lease_seconds)
    with Session(engine) as s:
        s.get(Job, claimed.job_id).lease_until = datetime.now(UTC) - timedelta(seconds=1)
        s.commit()
    assert worker.run_once() == "DEAD"
    assert worker.run_once() is None
    with Session(engine) as s:
        assert s.get(Job, claimed.job_id).state == "DEAD"
        assert "lease expired" in s.get(Job, claimed.job_id).last_error
        case = s.scalar(select(ExceptionCase))
        assert case.kind == "PROOF_RETRY_EXHAUSTED" and case.detail["retryable"] is True
        assert s.get(ProofRequest, rid).status == "OBSERVED"
        assert s.scalar(select(func.count()).select_from(ProofArtifact)) == 0
        assert s.scalar(select(func.count()).select_from(Outbox)) == 1


def test_another_manifest_job_is_not_claimed_or_reaped_by_this_worker(setup):
    engine, p, _sdk, worker, rid = setup
    with Session(engine) as s:
        s.get(ProofRequest, rid).manifest_hash = "sha256:" + "ab" * 32
        s.scalar(select(Job)).max_attempts = 1
        s.commit()
    assert worker.run_once() is None
    claimed = p.queue.claim("other-deployment-worker", worker.kinds, worker.lease_seconds)
    with Session(engine) as s:
        s.get(Job, claimed.job_id).lease_until = datetime.now(UTC) - timedelta(seconds=1)
        s.commit()
    assert worker.run_once() is None
    with Session(engine) as s:
        assert s.get(Job, claimed.job_id).state == "LEASED"
        assert s.get(ProofRequest, rid).status == "OBSERVED"
        assert s.scalar(select(func.count()).select_from(ExceptionCase)) == 0


def test_delayed_terminal_sdk_result_cannot_downgrade_new_attempt_success(setup):
    engine, p, _sdk, worker, rid = setup
    stale = p.queue.claim("old-proof-worker", worker.kinds, worker.lease_seconds)
    with Session(engine) as s:
        s.get(Job, stale.job_id).lease_until = datetime.now(UTC) - timedelta(seconds=1)
        s.commit()
    current = p.queue.claim("new-proof-worker", worker.kinds, worker.lease_seconds)
    assert current.attempt == stale.attempt + 1
    assert worker.run_one(current) == "SUCCEEDED"
    assert worker._fail_exception(stale, FailureKind.TERMINAL,
                                  ProofTerminalFailure(Outcome.INVALID)) == "LEASE_LOST"
    with Session(engine) as s:
        assert s.get(Job, stale.job_id).state == "SUCCEEDED"
        assert s.get(ProofRequest, rid).status == "PROOF_READY"
        assert s.get(ProofRequest, rid).last_error is None
        assert s.scalar(select(func.count()).select_from(ProofArtifact)) == 1
        assert s.scalar(select(func.count()).select_from(ExceptionCase)) == 0


def test_nonready_ok_sdk_status_is_invalid_not_a_proof_artifact(setup):
    engine, _p, sdk, worker, rid = setup
    sdk.output["status"] = "OK"
    assert worker.run_once() == "DEAD"
    with Session(engine) as s:
        assert s.get(ProofRequest, rid).status == "INVALID"
        assert s.scalar(select(func.count()).select_from(ProofArtifact)) == 0


def test_proof_handler_job_lock_permits_dispatcher_foreign_key_insert(setup):
    from sqlalchemy import text

    engine, p, _sdk, worker, _rid = setup
    claimed = p.queue.claim(worker.worker_id, worker.kinds, worker.lease_seconds)
    with engine.begin() as handler:
        worker._before_handler(handler, claimed)
        # Dispatcher prepares the transaction intent through a separate connection.
        # A FOR UPDATE (rather than NO KEY UPDATE) guard would self-deadlock here.
        with engine.begin() as dispatcher, Session(bind=dispatcher) as s:
            dispatcher.execute(text("SET LOCAL lock_timeout = '1s'"))
            s.add(TxIntent(tx_intent_id=ulid("fenced-intent"), job_id=claimed.job_id,
                           chain_id=102031, signer_address="0x" + "12" * 20, nonce=0,
                           purpose="PROOF_SUBMIT", to_address="0x" + "34" * 20,
                           calldata_hash="0x" + "ab" * 32))
            s.flush()


def test_stale_handler_is_fenced_before_it_can_read_or_call_sdk(setup, monkeypatch):
    engine, p, sdk, worker, _rid = setup
    stale = p.queue.claim("old-proof-worker", worker.kinds, worker.lease_seconds)
    with Session(engine) as s:
        s.get(Job, stale.job_id).lease_until = datetime.now(UTC) - timedelta(seconds=1)
        s.commit()
    current = p.queue.claim("new-proof-worker", worker.kinds, worker.lease_seconds)

    def unexpected_sdk(*_):
        pytest.fail("stale handler reached the SDK before fencing")

    monkeypatch.setattr(sdk, "call", unexpected_sdk)
    assert worker.run_one(stale) == "LEASE_LOST"
    with Session(engine) as s:
        assert s.get(Job, stale.job_id).attempt == current.attempt
        assert s.get(Job, stale.job_id).leased_by == "new-proof-worker"
