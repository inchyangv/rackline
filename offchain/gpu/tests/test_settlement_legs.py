"""PostgreSQL workflow tests with explicitly synthetic native rows and a fake rail."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from hashcredit_gpu.db.ledgers import Allocation, CashReceipt, ExceptionCase, Outbox, Settlement
from hashcredit_gpu.db.models import Facility
from hashcredit_gpu.domain import AssetRef
from hashcredit_gpu.jobs import Worker
from hashcredit_gpu.settlement.legs import (
    LegObservation,
    Quote,
    RailBinding,
    SettlementLegExecutor,
    validate_quote,
)

from .test_cash_reconciliation import ASSET, FixtureReader, allocation, receipt
from .test_event_ledger import (
    USDC,
    consumption_params,
    consumption_sql,
    h32,
    pipeline_to_accepted,
    seed_facility,
    ulid,
)
from .test_schema import ADDR1, ADDR2, ULID_D, run


class FakeRail:
    is_mock = True
    idempotent_requests = True
    state = "IN_FLIGHT"
    sent = 0
    known = None
    timeout = False

    def lookup(self, key):
        return self.known

    def send(self, quote, key):
        self.sent += 1
        self.known = "local-rail-receipt"
        if self.timeout:
            raise TimeoutError("lost acknowledgement after sending")
        return self.known

    def observe(self, ref):
        return LegObservation(self.state, ref, "local-destination-receipt")


@pytest.fixture
def setup(conn, migrated_db_url):
    seed_facility(conn, principal=1000)
    _, _, vid = pipeline_to_accepted(conn)
    cid, sid = ulid("payout"), ulid("settlement")
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
    engine = create_engine(migrated_db_url)
    with Session(engine) as s, s.begin():
        s.add(
            Settlement(
                settlement_id=sid,
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
    rail = FakeRail()
    binding = RailBinding(
        "local-fixture",
        "NATIVE_TESTNET",
        "TEST_ONLY",
        "UNCONFIGURED",
        AssetRef(chain_id=11155111, address=USDC, symbol="source", decimals=6),
        ASSET,
        ADDR1,
        "vault-1",
        2000,
        10,
        100,
        "doc://local-approved",
        ADDR2,
    )
    quote = Quote(
        "leg-1",
        sid,
        binding.rail_id,
        1000,
        1200,
        1190,
        5,
        int(datetime.now(UTC).timestamp()) + 300,
        ADDR1,
        ADDR2,
    )
    reader = FixtureReader(
        receipt=receipt(source_kind="SETTLEMENT", settlement_id=sid), allocation=allocation()
    )
    executor = SettlementLegExecutor(engine, binding, rail, reader)
    yield engine, executor, quote, rail
    engine.dispose()


def enqueue(engine, executor, quote):
    with Session(engine) as s, s.begin():
        return executor.enqueue(s, quote, now=int(datetime.now(UTC).timestamp()))


def worker(engine, executor):
    return Worker(engine, executor.queue, {"SETTLEMENT_LEG": executor.handle}, worker_id="rail")


def retry(engine):
    with engine.begin() as cx:
        cx.execute(text("UPDATE jobs SET next_run_at = now()"))


@pytest.mark.parametrize(
    "change",
    [
        {"source_amount": 2001},
        {"source_amount": 1.2},
        {"minimum_destination": 1000},
        {"fee_destination": 11},
        {"expires_at": 1},
        {"destination_receiver": ADDR2},
        {"refund_address": ADDR1},
        {"rail_id": "unapproved"},
    ],
)
def test_quote_caps_exact_units_expiry_and_route(setup, change):
    _, executor, quote, _ = setup
    with pytest.raises(ValueError):
        validate_quote(replace(quote, **change), executor.binding, now=100)


def test_ack_not_repayment_and_repeated_leg_no_double_send(setup):
    engine, executor, quote, rail = setup
    assert enqueue(engine, executor, quote) == enqueue(engine, executor, quote)
    w = worker(engine, executor)
    assert w.run_once() == "PENDING"
    with Session(engine) as s:
        assert s.scalar(select(func.count()).select_from(CashReceipt)) == 0
        assert s.get(Facility, ULID_D).principal == 1000
    rail.state = "DESTINATION_RECEIVED"
    retry(engine)
    assert w.run_once() == "SUCCEEDED"
    assert rail.sent == 1
    with Session(engine) as s:
        assert s.scalar(select(func.count()).select_from(Allocation)) == 1
        assert (
            s.scalar(
                select(func.count())
                .select_from(Outbox)
                .where(Outbox.event_type == "SETTLEMENT_LEG_ALLOCATED")
            )
            == 1
        )
        assert s.get(Facility, ULID_D).principal == 1000  # no second debt ledger


def test_timeout_lookup_avoids_duplicate_send_and_refund_never_repays(setup):
    engine, executor, quote, rail = setup
    rail.timeout = True
    enqueue(engine, executor, quote)
    w = worker(engine, executor)
    assert w.run_once() == "PENDING"
    rail.state = "REFUNDED"
    retry(engine)
    assert w.run_once() == "SUCCEEDED"
    assert rail.sent == 1
    with Session(engine) as s:
        assert s.scalar(select(func.count()).select_from(Allocation)) == 0
        assert s.scalar(select(func.count()).select_from(CashReceipt)) == 0
        assert s.get(Facility, ULID_D).principal == 1000


def test_source_receipt_is_conserved_across_multiple_legs(setup):
    engine, executor, quote, _ = setup
    enqueue(engine, executor, quote)
    enqueue(engine, executor, replace(quote, leg_id="leg-2"))
    with pytest.raises(ValueError, match="exceed source"):
        enqueue(engine, executor, replace(quote, leg_id="leg-3", source_amount=1))
    with pytest.raises(ValueError, match="already bound"):
        enqueue(engine, executor, replace(quote, source_amount=999))


def test_real_cash_is_persisted_while_allocation_pending_and_slippage_is_reviewed(setup):
    engine, executor, quote, rail = setup
    rail.state = "DESTINATION_RECEIVED"
    executor.cash_reader.receipt_fact = replace(executor.cash_reader.receipt_fact, amount=1100)
    executor.cash_reader.allocation_fact = None
    enqueue(engine, executor, quote)
    w = worker(engine, executor)
    assert w.run_once() == "PENDING"
    with Session(engine) as s:
        assert s.scalar(select(CashReceipt.amount)) == 1100
        assert s.scalar(select(ExceptionCase.kind)) == "SETTLEMENT_MINIMUM_BREACH"
        assert s.scalar(select(func.count()).select_from(Allocation)) == 0
    executor.cash_reader.allocation_fact = allocation(received=1100, excess=100)
    retry(engine)
    assert w.run_once() == "SUCCEEDED"
    assert rail.sent == 1


def test_unrelated_direct_repayment_cannot_complete_a_settlement_leg(setup):
    engine, executor, quote, rail = setup
    rail.state = "DESTINATION_RECEIVED"
    executor.cash_reader.receipt_fact = receipt()
    enqueue(engine, executor, quote)
    assert worker(engine, executor).run_once() == "DEAD"
    with Session(engine) as s:
        assert s.scalar(select(func.count()).select_from(CashReceipt)) == 0


def test_production_cannot_use_mock_or_unverified_rail(setup):
    engine, executor, quote, _ = setup
    executor.binding = replace(executor.binding, execution_profile="PRODUCTION")
    with pytest.raises(ValueError, match="verified live rail"):
        enqueue(engine, executor, quote)
