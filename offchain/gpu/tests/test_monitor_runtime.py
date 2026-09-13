"""Monitoring follows its canonical deployment, never mutable financial metadata."""

from datetime import UTC, datetime

import pytest
from hashcredit_prover.gpu.control_monitor import run_once
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hashcredit_gpu.db.ledgers import CashReceipt, ExceptionCase, ProofRequest
from hashcredit_gpu.db.models import ControlAgreement, Facility
from hashcredit_gpu.db.product_models import FacilityBinding
from hashcredit_gpu.db.projections_models import (
    ChainBlock,
    ChainCursor,
    ChainDeployment,
    ProjectedFacility,
)
from hashcredit_gpu.monitoring.service import Finding, assess_facility, record_findings

from . import test_monitoring as support
from .test_event_ledger import MANIFEST, h32, ulid
from .test_schema import MUSDT, ULID_C, ULID_D

db = support.db
DEPLOY, KEY = ulid("monitor-deployment"), h32("monitor-facility")


@pytest.fixture
def scoped(db):
    with Session(db) as s, s.begin():
        s.add(ChainDeployment(deployment_id=DEPLOY, chain_id=102031, execution_profile="NATIVE_TESTNET",
                              env_id="cc3-testnet", manifest_hash=MANIFEST, deployment_block=100, contracts={}))
        s.flush()
        s.add(ChainBlock(deployment_id=DEPLOY, number=100, hash=h32("monitor-block"),
                        parent_hash=h32("parent"), timestamp=int(datetime.now(UTC).timestamp()), tier="FINALIZED"))
        s.add(ChainCursor(deployment_id=DEPLOY, last_block_number=100, last_block_hash=h32("monitor-block"),
                         finalized_block_number=100, updated_at=datetime.now(UTC)))
        s.add(FacilityBinding(deployment_id=DEPLOY, facility_id=ULID_D, onchain_id=KEY, binding_tx_hash=h32("bind")))
        s.add(ProjectedFacility(deployment_id=DEPLOY, tier="FINALIZED", facility_key=KEY,
                                execution_profile="NATIVE_TESTNET", state="ACTIVE", principal=1000, last_block=100))
        s.get(ControlAgreement, ULID_C).control_grade = "E0"
    return db


@pytest.mark.parametrize("terminal", ["REPAID", "RELEASED", "CLOSED_WITH_LOSS"])
def test_canonical_terminal_stops_active_findings_without_financial_or_grade_writes(scoped, terminal):
    with Session(scoped) as s, s.begin():
        s.get(ProjectedFacility, (DEPLOY, "FINALIZED", KEY)).state = terminal
        ids = record_findings(s, ULID_D, (Finding("PROJECTION_STALE", True, "OBSERVABILITY"),
                                            Finding("CONTROL_RECEIVER_CHANGED", True, "CONTROL")), now=datetime.now(UTC))
    assert run_once(scoped, DEPLOY) == 0
    with Session(scoped) as s:
        assert s.get(Facility, ULID_D).state == "ACTIVE"
        assert s.get(Facility, ULID_D).principal == 1000
        assert s.get(ControlAgreement, ULID_C).control_grade == "E0"
        assert s.get(ExceptionCase, ids[0]).resolved_at is not None
        assert s.get(ExceptionCase, ids[1]).resolved_at is None  # actual breach retains reviewed cure


@pytest.mark.parametrize("mismatch", ["profile", "chain", "unbound", "other_deployment"])
def test_out_of_scope_facilities_are_neither_assessed_nor_resolved(scoped, mismatch):
    with Session(scoped) as s, s.begin():
        case = record_findings(s, ULID_D, (Finding("PROJECTION_STALE", True, "OBSERVABILITY"),), now=datetime.now(UTC))[0]
        if mismatch == "profile":
            s.get(ChainDeployment, DEPLOY).execution_profile = "PRODUCTION"
        elif mismatch == "chain":
            s.get(ChainDeployment, DEPLOY).chain_id = 102032
        else:
            s.delete(s.get(FacilityBinding, (DEPLOY, ULID_D)))
            if mismatch == "other_deployment":
                other = ulid("other-monitor-deployment")
                s.add(ChainDeployment(deployment_id=other, chain_id=102031, execution_profile="NATIVE_TESTNET",
                                      env_id="other", manifest_hash=MANIFEST, deployment_block=101, contracts={}))
                s.flush()
                s.add(FacilityBinding(deployment_id=other, facility_id=ULID_D, onchain_id=KEY, binding_tx_hash=h32("other-bind")))
    assert run_once(scoped, DEPLOY) == 0
    with Session(scoped) as s:
        assert s.get(ExceptionCase, case).resolved_at is None
        assert s.scalar(select(func.count()).select_from(ExceptionCase)) == 1


@pytest.mark.parametrize("mismatch", ["pending_only", "pending_block", "past_watermark", "profile"])
def test_unconfirmed_terminal_projection_does_not_suppress_monitoring(scoped, mismatch):
    with Session(scoped) as s, s.begin():
        projected = s.get(ProjectedFacility, (DEPLOY, "FINALIZED", KEY))
        projected.state = "REPAID"
        if mismatch == "pending_only":
            projected.tier = "PENDING"
        elif mismatch == "pending_block":
            s.get(ChainBlock, (DEPLOY, 100)).tier = "PENDING"
        elif mismatch == "past_watermark":
            s.get(ChainCursor, DEPLOY).finalized_block_number = 99
        else:
            projected.execution_profile = "LOCAL_MOCK"
    assert run_once(scoped, DEPLOY) > 0
    with Session(scoped) as s:
        assert s.get(ControlAgreement, ULID_C).control_grade == "E0"
        assert s.get(Facility, ULID_D).principal == 1000


def test_unknown_deployment_is_not_successful_monitoring(db):
    with pytest.raises(ValueError, match="not registered"):
        run_once(db, DEPLOY)


def test_foreign_manifest_proof_and_foreign_chain_cash_do_not_create_findings(scoped):
    with Session(scoped) as s, s.begin():
        proof = ProofRequest(proof_request_id=ulid("foreign-proof"), env_id="another-manifest", chain_key=1,
                             tx_hash=h32("foreign-proof-tx"), provider_id="mockdepin-testonly",
                             execution_profile="NATIVE_TESTNET", manifest_hash="sha256:" + "ab" * 32,
                             sdk_version="0.18.0", status="WAITING_ATTESTATION")
        cash = CashReceipt(cash_receipt_id=ulid("foreign-cash"), vault_id="vault-1", chain_id=102032,
                           token_address=MUSDT, decimals=6, amount=100, tx_hash=h32("foreign-cash-tx"),
                           log_index=0, source_kind="UNKNOWN", execution_profile="NATIVE_TESTNET",
                           received_at=datetime.now(UTC))
        s.add_all([proof, cash])
        s.flush()
        codes = {f.code for f in assess_facility(s, ULID_D, now=datetime.now(UTC), deployment_id=DEPLOY)}
        assert "NATIVE_PROOF_PENDING" not in codes and "UNALLOCATED_CASH_REVIEW" not in codes
        proof.manifest_hash, cash.chain_id = MANIFEST, 102031
        s.flush()
        codes = {f.code for f in assess_facility(s, ULID_D, now=datetime.now(UTC), deployment_id=DEPLOY)}
        assert {"NATIVE_PROOF_PENDING", "UNALLOCATED_CASH_REVIEW"} <= codes
