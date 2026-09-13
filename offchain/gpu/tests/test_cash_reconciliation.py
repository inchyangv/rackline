"""Real PostgreSQL reconciliation tests; the chain reader is explicitly LOCAL/fake."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from hashcredit_gpu.db.ledgers import Allocation, CashReceipt, Outbox, Settlement
from hashcredit_gpu.db.models import Facility
from hashcredit_gpu.domain import AssetRef
from hashcredit_gpu.reconciliation.engine import (
    AllocationFact,
    DestinationRoute,
    ReceiptFact,
    record_confirmed_allocation,
    record_destination_receipt,
)

from .test_event_ledger import (
    NOW,
    USDC,
    consumption_params,
    consumption_sql,
    h32,
    pipeline_to_accepted,
    seed_facility,
    ulid,
)
from .test_schema import ADDR1, ADDR2, MUSDT, ULID_D, ULID_E, ULID_F, insert_facility, run

ASSET = AssetRef(chain_id=102031, address=MUSDT, symbol="mUSDT", decimals=6)
ROUTE = DestinationRoute("vault-1", ADDR1, ASSET, "NATIVE_TESTNET")


@pytest.fixture
def db(conn, migrated_db_url):
    seed_facility(conn, principal=1000)
    insert_facility(conn, ULID_E, profile="NATIVE_TESTNET", principal=1000)
    insert_facility(conn, ULID_F, profile="NATIVE_TESTNET", principal=1000)
    engine = create_engine(migrated_db_url)
    yield engine
    engine.dispose()


class FixtureReader:
    """No RPC/native calls and no externally validated evidence: test fixture only."""

    def __init__(self, *, receipt=None, allocation=None):
        self.receipt_fact, self.allocation_fact = receipt, allocation

    def receipt(self, reference):
        return self.receipt_fact

    def allocation(self, reference):
        return self.allocation_fact


def receipt(**changes):
    return replace(
        ReceiptFact(
            cash_receipt_id=ulid("cash1"),
            asset=ASSET,
            amount=1200,
            tx_hash=h32("cash-tx"),
            log_index=0,
            block_hash=h32("block"),
            block_number=100,
            payer_address=ADDR2,
            payee_address=ADDR1,
            source_kind="DIRECT_REPAYMENT",
            execution_profile="NATIVE_TESTNET",
            received_at=NOW,
            canonical=True,
            finalized=True,
            receipt_status=1,
        ),
        **changes,
    )


def allocation(**changes):
    return replace(
        AllocationFact(
            allocation_id=ulid("allocation1"),
            cash_receipt_id=ulid("cash1"),
            facility_id=ULID_D,
            received=1200,
            fee_paid=10,
            interest_paid=20,
            principal_paid=970,
            excess=200,
            new_debt=30,
            tx_hash=h32("repay-tx"),
            chain_id=102031,
            execution_profile="NATIVE_TESTNET",
            canonical=True,
            finalized=True,
            receipt_status=1,
        ),
        **changes,
    )


def store_receipt(s, fact=None):
    return record_destination_receipt(
        s,
        reference="chain-log://local/receipt",
        route=ROUTE,
        reader=FixtureReader(receipt=fact or receipt()),
    )


def store_allocation(s, fact=None):
    return record_confirmed_allocation(
        s,
        reference="chain-log://local/repayment",
        reader=FixtureReader(allocation=fact or allocation()),
    )


def test_missing_reader_cannot_be_mistaken_for_native_or_cash_success(db):
    with Session(db) as s, s.begin():
        assert (
            record_destination_receipt(s, reference="x", route=ROUTE).reason
            == "DESTINATION_READER_NOT_CONFIGURED"
        )
        assert (
            record_confirmed_allocation(s, reference="x").reason
            == "DESTINATION_READER_NOT_CONFIGURED"
        )
        assert s.scalar(select(func.count()).select_from(CashReceipt)) == 0


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"source_kind": "SOURCE_ESCROW"}, "NOT_DESTINATION_CASH"),
        ({"source_kind": "IN_FLIGHT"}, "NOT_DESTINATION_CASH"),
        ({"finalized": False}, "DESTINATION_NOT_CANONICAL_FINAL"),
        ({"canonical": False}, "DESTINATION_NOT_CANONICAL_FINAL"),
        ({"receipt_status": 0}, "DESTINATION_NOT_CANONICAL_FINAL"),
        ({"payee_address": ADDR2}, "DESTINATION_ROUTE_MISMATCH"),
        ({"execution_profile": "PRODUCTION"}, "DESTINATION_ROUTE_MISMATCH"),
        (
            {"asset": AssetRef(chain_id=11155111, address=USDC, symbol="USDC", decimals=6)},
            "DESTINATION_ROUTE_MISMATCH",
        ),
        (
            {"asset": AssetRef(chain_id=102031, address=USDC, symbol="wrong", decimals=6)},
            "DESTINATION_ROUTE_MISMATCH",
        ),
        (
            {
                "asset": AssetRef(
                    chain_id=102031, address=MUSDT, symbol="wrong decimals", decimals=18
                )
            },
            "DESTINATION_ROUTE_MISMATCH",
        ),
    ],
)
def test_source_ack_wrong_route_failed_receipt_and_nonfinal_money_cannot_repay(db, changes, reason):
    with Session(db) as s, s.begin():
        assert store_receipt(s, receipt(**changes)).reason == reason
        assert s.scalar(select(func.count()).select_from(CashReceipt)) == 0
        assert s.scalar(select(func.count()).select_from(Allocation)) == 0
        assert s.get(Facility, ULID_D).principal == 1000


def test_direct_repayment_needs_no_external_proof_and_segregates_excess(db):
    with Session(db) as s, s.begin():
        assert store_receipt(s).created
        # Receipt alone never creates allocation or reduces debt.
        assert s.scalar(select(func.count()).select_from(Allocation)) == 0
        assert store_allocation(s).created
        row = s.get(Allocation, ulid("allocation1"))
        assert (row.fee_paid, row.interest_paid, row.principal_paid, row.excess, row.new_debt) == (
            10,
            20,
            970,
            200,
            30,
        )
        assert s.get(CashReceipt, ulid("cash1")).cash_state == "ALLOCATED"
        assert (
            s.get(Facility, ULID_D).principal == 1000
        )  # canonical projector, not this mirror, owns debt
        owned = s.execute(
            text("SELECT lp_applied, borrower_refundable, unallocated FROM v_cash_ownership")
        ).one()
        assert tuple(owned) == (1000, 200, 0)
        assert store_receipt(s).reason == "DUPLICATE_RECEIPT"
        assert store_allocation(s).reason == "DUPLICATE_ALLOCATION"
        assert s.scalar(select(func.count()).select_from(Allocation)) == 1
        assert s.scalar(select(func.count()).select_from(Outbox)) == 2


def test_partial_aggregate_facility_allocations_cannot_exceed_destination_cash(db):
    with Session(db) as s, s.begin():
        store_receipt(s, receipt(amount=100))
        first = allocation(received=60, fee_paid=0, interest_paid=0, principal_paid=60, excess=0)
        assert store_allocation(s, first).created
        assert s.get(CashReceipt, ulid("cash1")).cash_state == "DESTINATION_RECEIVED"
        excess = replace(
            first, allocation_id=ulid("alloc2"), facility_id=ULID_E, received=41, principal_paid=41
        )
        assert store_allocation(s, excess).reason == "ALLOCATION_EXCEEDS_RECEIPT"
        second = replace(excess, received=40, principal_paid=40)
        assert store_allocation(s, second).created
        assert s.get(CashReceipt, ulid("cash1")).cash_state == "ALLOCATED"
        assert s.scalar(select(func.sum(Allocation.received))) == 100


def test_unknown_origin_money_is_persisted_but_never_allocated(db):
    with Session(db) as s, s.begin():
        result = store_receipt(s, receipt(source_kind="UNKNOWN", payer_address=None))
        assert result.created and result.reason == "UNCLASSIFIED_DESTINATION_CASH"
        assert store_allocation(s).reason == "CASH_NOT_ALLOCATABLE"
        assert s.scalar(select(func.count()).select_from(Allocation)) == 0


def test_destination_reorg_quarantines_without_erasing_existing_debt_or_repays(db):
    with Session(db) as s, s.begin():
        store_receipt(s)
        store_allocation(s)
    with Session(db) as s, s.begin():
        assert (
            store_receipt(s, receipt(canonical=False)).reason == "DESTINATION_NOT_CANONICAL_FINAL"
        )
        assert store_allocation(s).reason == "CASH_RECONCILIATION_EXCEPTION"
        assert s.scalar(select(func.count()).select_from(Allocation)) == 1
        assert s.get(Facility, ULID_D).principal == 1000


def test_conflicting_replayed_log_is_not_silently_replaced(db):
    with Session(db) as s, s.begin():
        store_receipt(s)
        assert store_receipt(s, receipt(amount=1300)).reason == "DESTINATION_RECEIPT_CONFLICT"
        assert s.get(CashReceipt, ulid("cash1")).amount == 1200
        assert store_allocation(s).reason == "CASH_RECONCILIATION_EXCEPTION"


def test_bad_allocation_split_and_float_units_are_rejected(db):
    with Session(db) as s, s.begin():
        store_receipt(s)
        for fact in [allocation(received=1199), allocation(excess=200.0), allocation(new_debt=-1)]:
            with pytest.raises(ValueError):
                store_allocation(s, fact)
        assert s.scalar(select(func.count()).select_from(Allocation)) == 0


def test_allocation_without_final_event_or_destination_receipt_is_not_created(db):
    with Session(db) as s, s.begin():
        assert store_allocation(s).reason == "DESTINATION_RECEIPT_MISSING"
        store_receipt(s)
        assert (
            store_allocation(s, allocation(finalized=False)).reason
            == "REPAYMENT_NOT_CANONICAL_FINAL"
        )
        assert s.scalar(select(func.count()).select_from(Allocation)) == 0


def test_expected_finality_lag_can_retry_without_operator_override(db):
    with Session(db) as s, s.begin():
        assert not store_receipt(s, receipt(finalized=False)).created
        assert store_receipt(s).created
        assert not store_allocation(s, allocation(finalized=False)).created
        assert store_allocation(s).created


def test_multiple_destination_logs_are_independent_and_retry_safe(db):
    with Session(db) as s, s.begin():
        assert store_receipt(s).created
        assert store_receipt(
            s, receipt(cash_receipt_id=ulid("cash2"), log_index=1, amount=500)
        ).created
        assert s.scalar(select(func.sum(CashReceipt.amount))) == 1700


def test_one_facility_accepts_partial_payments_from_multiple_destination_receipts(db):
    with Session(db) as s, s.begin():
        for index in (0, 1):
            cid, aid = ulid(f"cash{index}"), ulid(f"alloc{index}")
            assert store_receipt(s, receipt(cash_receipt_id=cid, log_index=index, amount=500)).created
            assert store_allocation(s, allocation(
                allocation_id=aid, cash_receipt_id=cid, received=500,
                fee_paid=0, interest_paid=0, principal_paid=500, excess=0,
                new_debt=500 if index == 0 else 0,
            )).created
        assert s.scalar(select(func.sum(Allocation.received))) == 1000
        assert s.scalar(select(func.count()).select_from(Allocation)) == 2


def test_settlement_cash_cannot_be_assigned_to_another_borrower(db, conn):
    _, _, vid = pipeline_to_accepted(conn)
    cid = ulid("payout")
    run(
        conn,
        consumption_sql(),
        consumption_params(
            cid,
            h32("payout-source"),
            "mockdepin-testonly/acct-A/PAYOUT/settlement",
            vid,
            meaning="PAYOUT",
        ),
    )
    entity, borrower = ulid("entity2"), ulid("borrower2")
    run(conn, "INSERT INTO legal_entities (legal_entity_id) VALUES (%s)", (entity,))
    run(
        conn,
        "INSERT INTO borrowers (borrower_id, legal_entity_id) VALUES (%s,%s)",
        (borrower, entity),
    )
    run(conn, "UPDATE facilities SET borrower_id=%s WHERE facility_id=%s", (borrower, ULID_E))
    with Session(db) as s, s.begin():
        s.add(
            Settlement(
                settlement_id=ulid("settlement"),
                provider_account_id="mockdepin-testonly:acct-A",
                settlement_ref="batch-1",
                state="PAID_AT_SOURCE",
                asset_chain_id=11155111,
                asset_token_address=USDC,
                asset_decimals=6,
                source_amount=2000,
                payout_consumption_id=cid,
                execution_profile="NATIVE_TESTNET",
            )
        )
        s.flush()
        assert store_receipt(
            s, receipt(source_kind="SETTLEMENT", settlement_id=ulid("settlement"))
        ).created
        assert store_allocation(s, allocation(facility_id=ULID_E)).reason == "OTHER_BORROWER_CASH"
        assert store_allocation(s).created


def test_concurrent_receipt_retries_create_one_record(db):
    def worker(_):
        with Session(db) as s, s.begin():
            return store_receipt(s).created

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(worker, [1, 2])) == [False, True]
    with Session(db) as s:
        assert s.scalar(select(func.count()).select_from(CashReceipt)) == 1


def test_concurrent_split_allocations_serialize_on_cash_not_facility(db):
    with Session(db) as s, s.begin():
        store_receipt(s, receipt(amount=100))

    def worker(fid):
        with Session(db) as s, s.begin():
            return store_allocation(
                s,
                allocation(
                    facility_id=fid,
                    allocation_id=fid,
                    received=80,
                    fee_paid=0,
                    interest_paid=0,
                    principal_paid=80,
                    excess=0,
                ),
            ).created

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(worker, [ULID_D, ULID_E])) == [False, True]
    with Session(db) as s:
        assert s.scalar(select(func.sum(Allocation.received))) == 80


def test_receipt_and_outbox_roll_back_together(db):
    with Session(db) as s:
        with pytest.raises(RuntimeError), s.begin():
            store_receipt(s)
            raise RuntimeError("crash before commit")
        assert s.scalar(select(func.count()).select_from(CashReceipt)) == 0
        assert s.scalar(select(func.count()).select_from(Outbox)) == 0
