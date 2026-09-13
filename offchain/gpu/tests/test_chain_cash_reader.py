"""Canonical custody/ledger events connect to reconciliation without a proof prerequisite."""

import pytest
from eth_abi import encode
from eth_utils import keccak
from hashcredit_prover.gpu.reconcile_cash import reconcile
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from hashcredit_gpu.db.ledgers import Allocation
from hashcredit_gpu.db.models import Facility
from hashcredit_gpu.db.product_models import FacilityBinding
from hashcredit_gpu.db.projections_models import ChainBlock, ChainDeployment, ChainLog
from hashcredit_gpu.reconciliation.chain_reader import CanonicalRepaymentReader
from hashcredit_gpu.reconciliation.engine import (
    record_confirmed_allocation,
    record_destination_receipt,
)

from .test_cash_reconciliation import ROUTE
from .test_event_ledger import MANIFEST, NOW, h32, seed_facility, ulid
from .test_schema import ADDR1, ADDR2, MUSDT, ULID_D

DEPLOY = ulid("deploy")
FACILITY = h32("facility")
TX = h32("repay")
BLOCK = h32("block")


def test_reconcile_cli_service_is_idempotent_without_modifying_debt(setup):
    engine, rpc, _reader = setup
    first = reconcile(engine, rpc, DEPLOY, f"{TX}:2")
    second = reconcile(engine, rpc, DEPLOY, f"{TX}:2")
    assert first == second
    assert first["measuredReceived"] == "1200" and first["debtMutated"] is False
    with Session(engine) as s:
        assert s.scalar(select(func.count()).select_from(Allocation)) == 1
        assert s.get(Facility, ULID_D).principal == 1000


class RPC:
    canonical = True
    token = MUSDT

    def chain_id(self):
        return 102031

    def get_block(self, _):
        return {"hash": BLOCK if self.canonical else h32("orphan")}

    def get_receipt(self, _):
        return {"blockHash": BLOCK, "status": "0x1"}

    def eth_call(self, *_):
        return "0x" + encode(["address"], [self.token]).hex()

    def get_transaction(self, _):
        return {
            "hash": TX, "blockHash": BLOCK, "blockNumber": "0x64", "to": ADDR1,
            "from": ADDR2, "input": "0x" + (
                keccak(text="repayExact(bytes32,uint256)")[:4]
                + encode(["bytes32", "uint256"], [bytes.fromhex(FACILITY[2:]), 1300])
            ).hex(),
        }


@pytest.fixture
def setup(conn, migrated_db_url):
    seed_facility(conn, principal=1000)
    conn.commit()
    engine = create_engine(migrated_db_url)
    with Session(engine) as s, s.begin():
        s.add(
            ChainDeployment(
                deployment_id=DEPLOY,
                chain_id=102031,
                execution_profile="NATIVE_TESTNET",
                env_id="cc3-testnet",
                manifest_hash=MANIFEST,
                deployment_block=100,
                contracts={name: ADDR1 for name in (
                    "LendingVaultV2", "DebtLedger", "CreditFacilityManager", "RepaymentRouter"
                )},
                finality_depth=2,
            )
        )
        s.flush()
        s.add(
            FacilityBinding(
                deployment_id=DEPLOY,
                facility_id=ULID_D,
                onchain_id=FACILITY,
                binding_tx_hash=h32("bind"),
            )
        )
        s.add(
            ChainBlock(
                deployment_id=DEPLOY,
                number=100,
                hash=BLOCK,
                parent_hash=h32("parent"),
                timestamp=int(NOW.timestamp()),
                tier="FINALIZED",
            )
        )
        events = [
            (
                "DebtLedger",
                "Allocated",
                {
                    "feePaid": "10",
                    "interestPaid": "20",
                    "principalPaid": "970",
                    "excess": "200",
                    "newDebt": "30",
                },
            ),
            (
                "LendingVaultV2",
                "RepaymentReceived",
                {"received": "1200", "applied": "1000", "excess": "200"},
            ),
            (
                "CreditFacilityManager",
                "Repaid",
                {
                    "payer": ADDR2,
                    "requested": "1300",
                    "received": "1200",
                    "applied": "1000",
                    "excess": "200",
                    "newDebt": "30",
                },
            ),
        ]
        for index, (contract, name, values) in enumerate(events):
            s.add(
                ChainLog(
                    deployment_id=DEPLOY,
                    block_number=100,
                    block_hash=BLOCK,
                    tx_hash=TX,
                    tx_index=0,
                    log_index=index,
                    tx_status=1,
                    address=ADDR1,
                    contract_name=contract,
                    event_name=name,
                    topics=[],
                    data="0x",
                    decoded={"facilityId": FACILITY, **values},
                    tier="FINALIZED",
                )
            )
    rpc = RPC()
    yield engine, rpc, CanonicalRepaymentReader(engine, rpc, DEPLOY)
    engine.dispose()


def test_direct_repayment_measured_receipt_and_one_allocation(setup):
    engine, _rpc, reader = setup
    reference = f"{TX}:2"
    assert reader.receipt(reference).amount == 1200  # requested 1300 is not custody
    with Session(engine) as s, s.begin():
        assert record_destination_receipt(
            s, reference=reference, route=ROUTE, reader=reader
        ).created
        assert record_confirmed_allocation(s, reference=reference, reader=reader).created
        assert not record_confirmed_allocation(s, reference=reference, reader=reader).created
    with Session(engine) as s:
        assert s.scalar(select(func.count()).select_from(Allocation)) == 1
        assert (
            s.get(Facility, ULID_D).principal == 1000
        )  # no second debt mutation in the offchain mirror


def test_reorg_cash_is_quarantined_and_wrong_asset_rejected(setup):
    engine, rpc, reader = setup
    rpc.canonical = False
    with Session(engine) as s, s.begin():
        assert (
            record_destination_receipt(s, reference=f"{TX}:2", route=ROUTE, reader=reader).reason
            == "DESTINATION_NOT_CANONICAL_FINAL"
        )
    rpc.token = ADDR2
    with pytest.raises(ValueError, match="actual vault asset"):
        reader.receipt(f"{TX}:2")


def use_router(engine):
    with Session(engine) as s, s.begin():
        repaid = s.scalar(select(ChainLog).where(ChainLog.log_index == 2))
        repaid.contract_name = "RepaymentRouter"
        repaid.decoded = {**repaid.decoded, "settlementRef": "0x" + "00" * 32,
                          "feePaid": "10", "interestPaid": "20", "principalPaid": "970"}


@pytest.mark.parametrize("method", ["repayExact", "repayFor"])
def test_router_direct_measured_cash_idempotent(setup, monkeypatch, method):
    engine, rpc, reader = setup
    use_router(engine)
    if method == "repayFor":
        transaction = rpc.get_transaction(TX)
        transaction["input"] = "0x" + (
            keccak(text="repayFor(bytes32,uint256,bytes32)")[:4]
            + encode(["bytes32", "uint256", "bytes32"],
                     [bytes.fromhex(FACILITY[2:]), 1300, bytes(32)])
        ).hex()
        monkeypatch.setattr(rpc, "get_transaction", lambda _: transaction)
    assert reader.receipt(f"{TX}:2").source_kind == "DIRECT_REPAYMENT"
    first = reconcile(engine, rpc, DEPLOY, f"{TX}:2")
    assert reconcile(engine, rpc, DEPLOY, f"{TX.upper()}:02") == first
    assert first["measuredReceived"] == "1200"
    assert first["canonicalNewDebt"] == "30"
    with Session(engine) as s:
        assert s.scalar(select(func.count()).select_from(Allocation)) == 1
        assert s.get(Facility, ULID_D).principal == 1000


@pytest.mark.parametrize("fault", [
    "selector", "target", "payer", "facility", "block", "txhash", "limit",
    "calldata_ref", "event_ref", "allocation_marker", "event_amount", "alias_marker",
])
def test_router_unsupported_or_contradictory_routes_fail_closed(setup, monkeypatch, fault):
    engine, rpc, reader = setup
    use_router(engine)
    transaction = rpc.get_transaction(TX)
    if fault in {"event_ref", "event_amount"}:
        with Session(engine) as s, s.begin():
            repaid = s.scalar(select(ChainLog).where(ChainLog.log_index == 2))
            field, value = ("settlementRef", h32("settlement")) if fault == "event_ref" else ("feePaid", "11")
            repaid.decoded = {**repaid.decoded, field: value}
    elif fault in {"allocation_marker", "alias_marker"}:
        with Session(engine) as s, s.begin():
            s.add(ChainLog(
                deployment_id=DEPLOY, block_number=100, block_hash=BLOCK,
                tx_hash=TX, tx_index=0, log_index=3, tx_status=1,
                address=ADDR1, contract_name="RepaymentRouter", event_name="AllocationApplied",
                topics=[], data="0x", tier="FINALIZED",
                decoded={"facilityId": FACILITY, "settlementId": "0x" + "00" * 32,
                         "amount": "1200", "applied": "1000", "excess": "200"},
            ))
    elif fault == "selector":
        transaction["input"] = "0xdeadbeef" + transaction["input"][10:]
    elif fault == "target":
        transaction["to"] = ADDR2
    elif fault == "payer":
        transaction["from"] = ADDR1
    elif fault == "block":
        transaction["blockHash"] = h32("orphan")
    elif fault == "txhash":
        transaction["hash"] = h32("other")
    else:
        types = ["bytes32", "uint256"]
        values = [bytes.fromhex((h32("other") if fault == "facility" else FACILITY)[2:]),
                  100 if fault == "limit" else 1300]
        signature = "repayExact(bytes32,uint256)"
        if fault == "calldata_ref":
            types.append("bytes32")
            values.append(bytes.fromhex(h32("settlement")[2:]))
            signature = "repayFor(bytes32,uint256,bytes32)"
        transaction["input"] = "0x" + (keccak(text=signature)[:4] + encode(types, values)).hex()
    monkeypatch.setattr(rpc, "get_transaction", lambda _: transaction)
    assert reader.receipt(f"{TX}:{3 if fault == 'alias_marker' else 2}") is None
    with Session(engine) as s:
        assert s.scalar(select(func.count()).select_from(Allocation)) == 0
