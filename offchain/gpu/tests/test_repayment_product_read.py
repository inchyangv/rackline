"""Product repayment confirmation requires canonical measured-cash and allocation provenance."""

import pytest
from hashcredit_api.gpu.product.repository import ProductRepository
from hashcredit_api.gpu.product.settings import ProductSettings
from hashcredit_prover.gpu.reconcile_cash import reconcile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hashcredit_gpu.db.ledgers import Allocation, CashReceipt
from hashcredit_gpu.db.models import Facility
from hashcredit_gpu.db.product_models import FacilityBinding
from hashcredit_gpu.db.projections_models import ChainBlock, ChainDeployment, ChainLog

from . import test_chain_cash_reader as cash_support
from .test_event_ledger import MANIFEST, h32, ulid
from .test_schema import ADDR1, ADDR2, ULID_D

cash_setup = cash_support.setup


@pytest.fixture
def repayment_read(cash_setup, request):
    engine, rpc, _ = cash_setup
    with Session(engine) as session, session.begin():
        deployment = session.get(ChainDeployment, cash_support.DEPLOY)
        deployment.contracts = {name: ADDR1 for name in (
            "CreditFacilityManager", "RepaymentRouter", "LendingVaultV2", "DebtLedger")}
    result = reconcile(engine, rpc, cash_support.DEPLOY, f"{cash_support.TX}:2")
    with Session(engine) as session, session.begin():
        # Mirror fixtures exercise API evidence pairing independently of import selector checks.
        if getattr(request, "param", "CreditFacilityManager") == "RepaymentRouter":
            repaid = session.scalar(select(ChainLog).where(ChainLog.event_name == "Repaid"))
            repaid.contract_name = "RepaymentRouter"
            repaid.decoded = {**repaid.decoded, "feePaid": "10", "interestPaid": "20", "principalPaid": "970",
                              "settlementRef": "0x" + "00" * 32}
    repository = ProductRepository(ProductSettings(_env_file=None, database_url=None,
        execution_profile="NATIVE_TESTNET", chain_id=102031,
        deployment_id=cash_support.DEPLOY, manifest_hash=MANIFEST))
    return engine, rpc, repository, result["allocationId"]


def read_allocation(engine, repository, allocation_id):
    with Session(engine) as session:
        return repository.serialize(session, session.get(Allocation, allocation_id))


@pytest.mark.parametrize("repayment_read,evidence", [
    ("CreditFacilityManager", "FINALIZED_MANAGER_EVENT"),
    ("RepaymentRouter", "FINALIZED_ROUTER_EVENT"),
], indirect=["repayment_read"])
def test_reconciled_repayment_is_confirmed_without_mutating_debt(repayment_read, evidence):
    engine, _, repository, allocation_id = repayment_read
    row = read_allocation(engine, repository, allocation_id)
    assert row.repaymentApplied is True
    assert row.applicationEvidence == evidence
    assert row.received.amount == "1200" and row.principalPaid.amount == "970"
    assert row.excess.amount == "200" and row.recordedNewDebt.amount == "30"
    with Session(engine) as session:
        assert session.get(Facility, ULID_D).principal == 1000


@pytest.mark.parametrize("missing", ["Repaid", "RepaymentReceived", "Allocated"])
def test_ledger_alone_or_incomplete_event_pair_is_unconfirmed(repayment_read, missing):
    engine, _, repository, allocation_id = repayment_read
    with Session(engine) as session, session.begin():
        session.delete(session.scalar(select(ChainLog).where(ChainLog.event_name == missing)))
    row = read_allocation(engine, repository, allocation_id)
    assert row.repaymentApplied is None and row.applicationEvidence == "UNCONFIRMED_LEDGER_RECORD"


@pytest.mark.parametrize("mismatch", [
    "pending_log", "failed_tx", "orphan_block", "pending_block", "wrong_contract", "wrong_facility",
    "wrong_component", "wrong_custody", "wrong_manager", "wrong_payer", "wrong_tx", "wrong_manifest",
    "missing_binding", "wrong_receipt_index", "wrong_vault_emitter", "wrong_vault_metadata",
])
@pytest.mark.parametrize("repayment_read", ["CreditFacilityManager", "RepaymentRouter"], indirect=True)
def test_unverified_or_mismatched_provenance_never_confirms(repayment_read, mismatch):
    engine, _, repository, allocation_id = repayment_read
    with Session(engine) as session, session.begin():
        logs = {event.event_name: event for event in session.scalars(select(ChainLog))}
        manager, vault, ledger = logs["Repaid"], logs["RepaymentReceived"], logs["Allocated"]
        allocation = session.get(Allocation, allocation_id)
        receipt = session.get(CashReceipt, allocation.cash_receipt_id)
        if mismatch == "pending_log":
            ledger.tier = "PENDING"
        elif mismatch == "failed_tx":
            manager.tx_status = 0
        elif mismatch == "orphan_block":
            session.get(ChainBlock, (cash_support.DEPLOY, 100)).hash = h32("orphan")
        elif mismatch == "pending_block":
            session.get(ChainBlock, (cash_support.DEPLOY, 100)).tier = "PENDING"
        elif mismatch == "wrong_contract":
            manager.address = ADDR2
        elif mismatch == "wrong_facility":
            manager.decoded = {**manager.decoded, "facilityId": h32("another-facility")}
        elif mismatch == "wrong_component":
            ledger.decoded = {**ledger.decoded, "principalPaid": "971"}
        elif mismatch == "wrong_custody":
            vault.decoded = {**vault.decoded, "received": "1300"}
        elif mismatch == "wrong_manager":
            manager.decoded = {**manager.decoded, "newDebt": "999"}
        elif mismatch == "wrong_payer":
            receipt.payer_address = ADDR1
        elif mismatch == "wrong_tx":
            allocation.onchain_tx_hash = h32("unrelated-tx")
        elif mismatch == "wrong_manifest":
            session.get(ChainDeployment, cash_support.DEPLOY).manifest_hash = "sha256:" + "ef" * 32
        elif mismatch == "missing_binding":
            session.delete(session.get(FacilityBinding, (cash_support.DEPLOY, ULID_D)))
        elif mismatch == "wrong_receipt_index":
            receipt.log_index = 1
        elif mismatch == "wrong_vault_emitter":
            vault.address = ADDR2
        elif mismatch == "wrong_vault_metadata":
            receipt.vault_id = "another-vault"
    row = read_allocation(engine, repository, allocation_id)
    assert row.repaymentApplied is None and row.applicationEvidence == "UNCONFIRMED_LEDGER_RECORD"


@pytest.mark.parametrize("repayment_read,second_contract", [
    ("CreditFacilityManager", "CreditFacilityManager"),
    ("CreditFacilityManager", "RepaymentRouter"),
    ("RepaymentRouter", "CreditFacilityManager"),
    ("RepaymentRouter", "RepaymentRouter"),
], indirect=["repayment_read"])
def test_repeated_repayments_in_one_tx_use_their_own_event_boundaries(repayment_read, second_contract):
    engine, _, repository, original_id = repayment_read
    with Session(engine) as session, session.begin():
        previous = list(session.scalars(select(ChainLog).order_by(ChainLog.log_index)))
        for event in previous:
            decoded = {**event.decoded, "excess": "0", "newDebt": "0"}
            contract = event.contract_name
            if event.event_name == "Allocated":
                decoded.update(feePaid="0", interestPaid="0", principalPaid="700")
            else:
                decoded.update(received="700", applied="700")
            if event.event_name == "Repaid":
                contract = second_contract
                for field in ("feePaid", "interestPaid", "principalPaid", "settlementRef"):
                    decoded.pop(field, None)
                if contract == "RepaymentRouter":
                    decoded.update(feePaid="0", interestPaid="0", principalPaid="700", settlementRef="0x" + "00" * 32)
            session.add(ChainLog(deployment_id=event.deployment_id, block_number=event.block_number,
                block_hash=event.block_hash, tx_hash=event.tx_hash, tx_index=event.tx_index,
                log_index=event.log_index + 3, tx_status=1, address=event.address,
                contract_name=contract, event_name=event.event_name,
                topics=[], data="0x", decoded=decoded, tier="FINALIZED"))
        original = session.get(Allocation, original_id)
        cash = session.get(CashReceipt, original.cash_receipt_id)
        session.add(CashReceipt(cash_receipt_id=ulid("second-cash"), vault_id=cash.vault_id,
            chain_id=cash.chain_id, token_address=cash.token_address, decimals=cash.decimals,
            amount=700, tx_hash=cash.tx_hash, log_index=5, payer_address=cash.payer_address,
            source_kind="DIRECT_REPAYMENT", cash_state="ALLOCATED", execution_profile=cash.execution_profile,
            received_at=cash.received_at))
        session.flush()
        session.add(Allocation(allocation_id=ulid("second-allocation"), cash_receipt_id=ulid("second-cash"),
            facility_id=original.facility_id, received=700, fee_paid=0, interest_paid=0,
            principal_paid=700, excess=0, new_debt=0, onchain_tx_hash=original.onchain_tx_hash))
    first_row = read_allocation(engine, repository, original_id)
    second_row = read_allocation(engine, repository, ulid("second-allocation"))
    assert first_row.repaymentApplied is True and first_row.received.amount == "1200"
    assert second_row.repaymentApplied is True and second_row.received.amount == "700"
    assert second_row.applicationEvidence == ("FINALIZED_ROUTER_EVENT" if second_contract == "RepaymentRouter"
                                             else "FINALIZED_MANAGER_EVENT")


def add_allocation_applied(session, *, applied="1000"):
    repaid = session.scalar(select(ChainLog).where(ChainLog.event_name == "Repaid"))
    session.add(ChainLog(deployment_id=repaid.deployment_id, block_number=repaid.block_number,
        block_hash=repaid.block_hash, tx_hash=repaid.tx_hash, tx_index=repaid.tx_index,
        log_index=repaid.log_index + 1, tx_status=1, address=repaid.address,
        contract_name="RepaymentRouter", event_name="AllocationApplied", topics=[], data="0x",
        decoded={"facilityId": repaid.decoded["facilityId"], "settlementId": repaid.decoded["settlementRef"],
                 "amount": repaid.decoded["received"], "applied": applied, "excess": repaid.decoded["excess"]},
        tier="FINALIZED"))


@pytest.mark.parametrize("repayment_read", ["RepaymentRouter"], indirect=True)
def test_allocation_applied_is_not_another_repayment_anchor(repayment_read):
    engine, rpc, repository, allocation_id = repayment_read
    with Session(engine) as session, session.begin():
        add_allocation_applied(session)
    assert read_allocation(engine, repository, allocation_id).repaymentApplied is None
    with pytest.raises(ValueError, match="repayment events not indexed"):
        reconcile(engine, rpc, cash_support.DEPLOY, f"{cash_support.TX}:3")
    with Session(engine) as session, session.begin():
        assert session.scalar(select(func.count()).select_from(Allocation)) == 1
        assert session.scalar(select(func.count()).select_from(CashReceipt)) == 1
        allocation = session.get(Allocation, allocation_id)
        session.get(CashReceipt, allocation.cash_receipt_id).log_index = 3
    row = read_allocation(engine, repository, allocation_id)
    assert row.repaymentApplied is None and row.applicationEvidence == "UNCONFIRMED_LEDGER_RECORD"


@pytest.mark.parametrize("repayment_read", ["RepaymentRouter"], indirect=True)
@pytest.mark.parametrize("corruption", [
    "component", "fractional_component", "invalid_number", "missing_component", "following_allocation", "settlement_reference",
])
def test_malformed_or_contradictory_router_event_is_unconfirmed(repayment_read, corruption):
    engine, _, repository, allocation_id = repayment_read
    with Session(engine) as session, session.begin():
        repaid = session.scalar(select(ChainLog).where(ChainLog.event_name == "Repaid"))
        decoded = dict(repaid.decoded)
        if corruption == "component":
            decoded["feePaid"] = "11"
        elif corruption == "fractional_component":
            decoded["feePaid"] = 10.5
        elif corruption == "invalid_number":
            decoded["received"] = "not-an-amount"
        elif corruption == "missing_component":
            decoded.pop("principalPaid")
        elif corruption == "following_allocation":
            add_allocation_applied(session, applied="999")
        elif corruption == "settlement_reference":
            decoded["settlementRef"] = h32("unsupported-settlement")
        repaid.decoded = decoded
    row = read_allocation(engine, repository, allocation_id)
    assert row.repaymentApplied is None and row.applicationEvidence == "UNCONFIRMED_LEDGER_RECORD"
