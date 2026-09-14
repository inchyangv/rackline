"""Real PostgreSQL journal/replay with encoded ABI logs from external submitters."""

import pytest
from eth_abi import encode
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from hashcredit_gpu.db.projections_models import (
    ChainCursor,
    ChainDeployment,
    ChainLog,
    ProjectedFacility,
    ReorgJournal,
)
from hashcredit_gpu.projections.decoders import Decoder
from hashcredit_gpu.projections.indexer import ChainIndexer, FinalizedReorg

ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
ADDRESS = "0x" + "11" * 20
FACILITY = "0x" + "22" * 32


def h(n):
    return "0x" + format(n, "064x")


class RPC:
    def __init__(self):
        self.height = 3
        self.blocks = {
            n: {"number": hex(n), "hash": h(n), "parentHash": h(n - 1), "timestamp": hex(100 + n)}
            for n in range(1, 7)
        }
        self.logs = []
        self.fail = False

    def chain_id(self):
        return 31337

    def block_number(self):
        return self.height

    def get_block(self, n):
        return self.blocks.get(n) if n <= self.height else None

    def get_receipt(self, tx):
        log = next(x for x in self.logs if x["transactionHash"] == tx)
        return {"blockHash": log["blockHash"], "status": "0x1"}

    def get_logs(self, addresses, start, end):
        if self.fail:
            raise TimeoutError("RPC failed midway")
        return [l for l in self.logs if start <= int(l["blockNumber"], 16) <= end]


def event(rpc, name, values, block, index=0):
    decoder = Decoder({"DebtLedger": ADDRESS})
    ev = next(e for e in decoder.events["DebtLedger"].values() if e.name == name)
    topics = [ev.topic0] + ["0x" + encode([t], [values[k]]).hex() for k, t in ev.indexed]
    data = "0x" + encode([t for _, t in ev.unindexed], [values[k] for k, _ in ev.unindexed]).hex()
    rpc.logs.append(
        {
            "address": ADDRESS,
            "topics": topics,
            "data": data,
            "blockNumber": hex(block),
            "blockHash": rpc.blocks[block]["hash"],
            "transactionHash": h(100 + block),
            "transactionIndex": "0x0",
            "logIndex": hex(index),
        }
    )


def test_cold_cursor_is_inserted_fully_initialized_when_tip_has_no_logs(setup):
    engine, rpc, indexer = setup
    rpc.height = 6
    # Existing setup logs are at block 1. Empty tip blocks must not autoflush a
    # half-constructed cursor, regardless of ORM weak identity-map retention.
    result = indexer.sync(ID)
    assert result["lastBlock"] == 6
    with Session(engine) as s:
        cursor = s.get(ChainCursor, ID)
        assert cursor.last_block_hash == h(6)
        assert cursor.finalized_block_number == 4


@pytest.fixture
def setup(migrated_db_url):
    engine, rpc = create_engine(migrated_db_url), RPC()
    with Session(engine) as s, s.begin():
        s.add(
            ChainDeployment(
                deployment_id=ID,
                chain_id=31337,
                execution_profile="LOCAL_MOCK",
                env_id="local",
                manifest_hash="sha256:" + "a" * 64,
                deployment_block=1,
                contracts={"DebtLedger": ADDRESS},
                finality_depth=2,
            )
        )
    event(
        rpc,
        "FacilityOpened",
        {
            "facilityId": bytes.fromhex(FACILITY[2:]),
            "termsVersionId": bytes(32),
            "rateBps": 1200,
            "openedAt": 101,
        },
        1,
    )
    event(
        rpc,
        "Drawn",
        {"facilityId": bytes.fromhex(FACILITY[2:]), "amount": 500, "newPrincipal": 500},
        3,
    )
    yield engine, rpc, ChainIndexer(engine, rpc)
    engine.dispose()


def test_external_events_backfill_pending_final_and_dedup(setup):
    engine, rpc, indexer = setup
    rpc.logs.append(dict(rpc.logs[-1]))
    assert indexer.sync(ID)["lastBlock"] == 3
    with Session(engine) as s:
        assert s.get(ProjectedFacility, (ID, "FINALIZED", FACILITY)).principal == 0
        assert s.get(ProjectedFacility, (ID, "PENDING", FACILITY)).principal == 500
        assert s.scalar(select(func.count()).select_from(ChainLog)) == 2
    rpc.height = 5
    indexer.sync(ID)
    indexer.sync(ID)
    with Session(engine) as s:
        assert s.get(ProjectedFacility, (ID, "FINALIZED", FACILITY)).principal == 500
        assert s.scalar(select(func.count()).select_from(ChainLog)) == 2


def test_reorg_rolls_back_pending_and_replays(setup):
    engine, rpc, indexer = setup
    indexer.sync(ID)
    rpc.blocks[3]["hash"] = h(333)
    rpc.logs = [x for x in rpc.logs if x["blockNumber"] != "0x3"]
    indexer.sync(ID)
    with Session(engine) as s:
        assert s.get(ProjectedFacility, (ID, "PENDING", FACILITY)).principal == 0
        assert s.scalar(select(func.count()).select_from(ReorgJournal)) == 1
    rpc.blocks[1]["hash"] = h(999)
    rpc.blocks[2]["hash"] = h(998)
    rpc.blocks[3]["hash"] = h(997)
    with pytest.raises(FinalizedReorg):
        indexer.sync(ID)


def test_rpc_failure_preserves_cursor_and_raw_atomicity(setup):
    engine, rpc, indexer = setup
    rpc.fail = True
    with pytest.raises(TimeoutError):
        indexer.sync(ID)
    with Session(engine) as s:
        assert s.get(ChainCursor, ID) is None
        assert s.scalar(select(func.count()).select_from(ChainLog)) == 0
    rpc.fail = False
    assert indexer.sync(ID)["lastBlock"] == 3


def test_wrong_chain_rejected_before_cursor(setup):
    _engine, rpc, indexer = setup
    rpc.chain_id = lambda: 102031
    with pytest.raises(ValueError, match="chain differs"):
        indexer.sync(ID)


def test_reconciliation_separates_accrual_view_lag_from_mismatch(setup, monkeypatch):
    from hashcredit_gpu.db.projections_models import ProjectionDiscrepancy
    from hashcredit_gpu.projections.reconcile import reconcile_views
    from hashcredit_gpu.projections.views import ContractViews

    engine, rpc, indexer = setup
    indexer.sync(ID)

    def read(_self, _contract, function, _args, _block):
        if function == "facilityCount":
            return "1"
        if function == "legalDebtAt":
            return "0"
        if function == "view_":
            return {
                "principal": "0",
                "fees": "1",
                "unpaidInterest": "7",
                "lastAccrualAt": "101",
                "executionProfile": "0",
            }
        raise AssertionError(function)

    monkeypatch.setattr(ContractViews, "read", read)
    result = reconcile_views(engine, rpc, ID)
    assert result["discrepancies"] == 1
    reconcile_views(engine, rpc, ID)
    with Session(engine) as s:
        kinds = list(s.scalars(select(ProjectionDiscrepancy.classification)))
        assert sorted(kinds) == ["DISCREPANCY", "EXPECTED_LAG"]


# ---------------------------------------------------------------- history projections (receivables, repayments)
BOOK = "0x" + "33" * 20
ROUTER = "0x" + "44" * 20
VAULT = "0x" + "55" * 20
ACCOUNT = "0x" + "66" * 32
OBLIGATION = "0x" + "77" * 32
RECEIVABLE = "0x" + "88" * 32
PAYER = "0x" + "99" * 20
MANAGER = "0x" + "aa" * 20
RECOVERY = "0x" + "bb" * 20
HISTORY_CONTRACTS = {"DebtLedger": ADDRESS, "ReceivableBook": BOOK, "RepaymentRouter": ROUTER, "LendingVaultV2": VAULT,
                     "CreditFacilityManager": MANAGER, "RecoveryManager": RECOVERY}


def history_event(rpc, contract, name, values, block, index, tx=None):
    decoder = Decoder(HISTORY_CONTRACTS)
    ev = next(e for e in decoder.events[contract].values() if e.name == name)
    topics = [ev.topic0] + ["0x" + encode([t], [values[k]]).hex() for k, t in ev.indexed]
    data = "0x" + encode([t for _, t in ev.unindexed], [values[k] for k, _ in ev.unindexed]).hex()
    rpc.logs.append({
        "address": HISTORY_CONTRACTS[contract], "topics": topics, "data": data, "blockNumber": hex(block),
        "blockHash": rpc.blocks[block]["hash"], "transactionHash": tx or h(100 + block),
        "transactionIndex": "0x0", "logIndex": hex(index),
    })


@pytest.fixture
def history_setup(migrated_db_url):
    engine, rpc = create_engine(migrated_db_url), RPC()
    with Session(engine) as s, s.begin():
        s.add(ChainDeployment(deployment_id=ID, chain_id=31337, execution_profile="LOCAL_MOCK", env_id="local",
                              manifest_hash="sha256:" + "a" * 64, deployment_block=1, contracts=HISTORY_CONTRACTS, finality_depth=2))
    fid, rid, acct, ref = (bytes.fromhex(x[2:]) for x in (FACILITY, RECEIVABLE, ACCOUNT, OBLIGATION))
    # block 1: recognise 12, assign, correct −2 (SLA), pay 3 (unpaid 7), then a chargeback of the 3
    history_event(rpc, "ReceivableBook", "ReceivableRecognized", {"receivableId": rid, "accountKey": acct, "obligationRef": ref, "net": 12}, 1, 0)
    history_event(rpc, "ReceivableBook", "ReceivableAssigned", {"receivableId": rid, "facilityId": fid, "revision": 2}, 1, 1)
    history_event(rpc, "ReceivableBook", "ReceivableCorrected", {"receivableId": rid, "delta": -2, "revision": 3, "reason": 2}, 1, 2)
    history_event(rpc, "ReceivableBook", "ReceivablePaid", {"receivableId": rid, "amount": 3, "settlementSeq": 1, "unpaidAfter": 7}, 1, 3)
    history_event(rpc, "ReceivableBook", "ReceivablePayoutCancelled", {"receivableId": rid, "amount": 3, "settlementSeq": 1}, 1, 4)
    # block 1: the facility ledger (500 drawn) so the debt projection conserves through the allocation
    history_event(rpc, "DebtLedger", "FacilityOpened", {"facilityId": fid, "termsVersionId": bytes(32), "rateBps": 1000, "openedAt": 101}, 1, 5)
    history_event(rpc, "DebtLedger", "Drawn", {"facilityId": fid, "amount": 500, "newPrincipal": 500}, 1, 6)
    # block 2: a third-party repayFor leg (Accrued → Allocated → RepaymentReceived → Repaid with a settlement ref)
    history_event(rpc, "DebtLedger", "Accrued", {"facilityId": fid, "interestUnits": 2, "from": 101, "to": 102, "rateBps": 1000}, 2, 0)
    history_event(rpc, "DebtLedger", "Allocated", {"facilityId": fid, "feePaid": 0, "interestPaid": 2, "principalPaid": 98, "excess": 0, "newDebt": 402}, 2, 1)
    history_event(rpc, "LendingVaultV2", "RepaymentReceived", {"facilityId": fid, "received": 100, "applied": 100, "excess": 0}, 2, 2)
    history_event(rpc, "RepaymentRouter", "Repaid", {"facilityId": fid, "payer": bytes.fromhex(PAYER[2:]), "settlementRef": bytes.fromhex("ab" * 32),
                  "requested": 100, "received": 100, "applied": 100, "feePaid": 0, "interestPaid": 2, "principalPaid": 98, "excess": 0, "newDebt": 402}, 2, 3)
    # block 3 (pending at height 3): a Repaid without its Allocated leg is never history
    history_event(rpc, "RepaymentRouter", "Repaid", {"facilityId": fid, "payer": bytes.fromhex(PAYER[2:]), "settlementRef": bytes(32),
                  "requested": 5, "received": 5, "applied": 5, "feePaid": 0, "interestPaid": 0, "principalPaid": 5, "excess": 0, "newDebt": 397}, 3, 0)
    yield engine, rpc, ChainIndexer(engine, rpc)
    engine.dispose()


def test_receivable_and_repayment_history_replay_from_finalized_logs(history_setup):
    from hashcredit_gpu.db.projections_models import ProjectedReceivable, ProjectedRepayment

    engine, rpc, indexer = history_setup
    rpc.height = 4
    indexer.sync(ID)
    with Session(engine) as s:
        r = s.get(ProjectedReceivable, (ID, "FINALIZED", RECEIVABLE))
        assert (r.account_key, r.obligation_ref, r.facility_key) == (ACCOUNT, OBLIGATION, FACILITY)
        assert (int(r.net), int(r.paid), r.state, r.revision) == (10, 0, "ASSIGNED", 5)
        assert [e["event"] for e in r.history] == ["ReceivableRecognized", "ReceivableAssigned", "ReceivableCorrected", "ReceivablePaid", "ReceivablePayoutCancelled"]
        assert r.recognition_tx_hash == h(101) and r.last_block == 1
        repayments = list(s.scalars(select(ProjectedRepayment).where(ProjectedRepayment.deployment_id == ID)))
        by_tier = {(x.tier, x.block_number) for x in repayments}
        assert ("FINALIZED", 2) in by_tier and ("PENDING", 2) in by_tier and ("PENDING", 3) not in by_tier
        leg = next(x for x in repayments if x.tier == "FINALIZED")
        assert (int(leg.interest_paid), int(leg.principal_paid), int(leg.new_debt), leg.payer, leg.repaid_contract) == (2, 98, 402, PAYER, "RepaymentRouter")
        assert leg.settlement_ref == "0x" + "ab" * 32 and leg.block_timestamp == 102


def test_receivable_history_rejects_conservation_breaks(history_setup):
    engine, rpc, indexer = history_setup
    # a payout whose unpaidAfter does not follow from the event-carried net/paid is a journal discrepancy
    history_event(rpc, "ReceivableBook", "ReceivablePaid", {"receivableId": bytes.fromhex(RECEIVABLE[2:]), "amount": 1, "settlementSeq": 2, "unpaidAfter": 5}, 3, 1)
    rpc.height = 3
    with pytest.raises(ValueError, match="receivable payout conservation"):
        indexer.sync(ID)


# ---------------------------------------------------------------- credit status (why is the facility in this state)
def b32(text: str) -> bytes:
    return text.encode().ljust(32, b"\0")


def test_credit_status_replays_default_recovery_and_write_off(history_setup):
    from hashcredit_gpu.db.projections_models import ProjectedFacilityCredit

    engine, rpc, indexer = history_setup
    fid, under, guard, owner = bytes.fromhex(FACILITY[2:]), bytes.fromhex("c1" * 20), bytes.fromhex("c2" * 20), bytes.fromhex("c3" * 20)
    STATE = {"ACTIVE": 3, "DELINQUENT": 5, "DEFAULTED": 6, "RECOVERY": 7, "CLOSED_WITH_LOSS": 10}
    # block 2: schedule, overdue → DELINQUENT, a dispute that is opened and cleared, approved default → DEFAULTED
    history_event(rpc, "RecoveryManager", "ScheduleSet", {"facilityId": fid, "dueAt": 150, "graceSeconds": 60, "dueAmount": 100}, 2, 4)
    history_event(rpc, "CreditFacilityManager", "StateChanged", {"facilityId": fid, "from": STATE["ACTIVE"], "to": STATE["DELINQUENT"], "trigger": b32("installment_overdue"), "authority": bytes.fromhex(RECOVERY[2:])}, 2, 5)
    history_event(rpc, "RecoveryManager", "DisputeSet", {"facilityId": fid, "disputed": True, "disputeUntil": 150}, 2, 6)
    history_event(rpc, "RecoveryManager", "DisputeSet", {"facilityId": fid, "disputed": False, "disputeUntil": 150}, 2, 7)
    history_event(rpc, "RecoveryManager", "DefaultApproved", {"facilityId": fid, "reason": b32("non_payment")}, 2, 8)
    history_event(rpc, "CreditFacilityManager", "StateChanged", {"facilityId": fid, "from": STATE["DELINQUENT"], "to": STATE["DEFAULTED"], "trigger": b32("non_payment"), "authority": bytes.fromhex(RECOVERY[2:])}, 2, 9)
    # block 3 (pending at height 4? no: height 5 finalizes 3): recovery, reserve 30 funded / 30 applied, impair 372, write off
    history_event(rpc, "CreditFacilityManager", "StateChanged", {"facilityId": fid, "from": STATE["DEFAULTED"], "to": STATE["RECOVERY"], "trigger": b32("recovery_opened"), "authority": bytes.fromhex(RECOVERY[2:])}, 3, 1)
    history_event(rpc, "RecoveryManager", "ReserveFunded", {"facilityId": fid, "owner": owner, "amount": 30}, 3, 2)
    history_event(rpc, "RecoveryManager", "ReserveApplied", {"facilityId": fid, "amount": 30}, 3, 3)
    history_event(rpc, "LendingVaultV2", "ImpairmentRecognized", {"facilityId": fid, "amount": 400}, 3, 4)
    history_event(rpc, "LendingVaultV2", "ImpairmentReversed", {"facilityId": fid, "amount": 28}, 3, 5)
    history_event(rpc, "RecoveryManager", "LossApplied", {"facilityId": fid, "lossId": b32("loss-impair"), "amount": 372, "writeOff": False}, 3, 6)
    history_event(rpc, "LendingVaultV2", "WrittenOff", {"facilityId": fid, "principal": 372, "interest": 0, "reserveUsed": 0}, 3, 7)
    history_event(rpc, "CreditFacilityManager", "StateChanged", {"facilityId": fid, "from": STATE["RECOVERY"], "to": STATE["CLOSED_WITH_LOSS"], "trigger": b32("loss-writeoff"), "authority": bytes.fromhex(RECOVERY[2:])}, 3, 8)
    history_event(rpc, "RecoveryManager", "LossApplied", {"facilityId": fid, "lossId": b32("loss-writeoff"), "amount": 372, "writeOff": True}, 3, 9)
    rpc.height = 4
    indexer.sync(ID)
    with Session(engine) as s:
        final = s.get(ProjectedFacilityCredit, (ID, "FINALIZED", FACILITY))
        # height 4 with finality depth 2 finalizes block 2 only: the default is final, the recovery is pending
        assert (final.state, final.state_trigger, final.state_changed_at) == ("DEFAULTED", "0x" + b32("non_payment").hex(), 102)
        assert (final.schedule_due_at, final.schedule_grace_seconds, int(final.schedule_due_amount), final.schedule_set_at) == (150, 60, 100, 102)
        assert final.disputed is False and final.default_reason == "0x" + b32("non_payment").hex() and final.default_approved_at == 102
        assert [t["to"] for t in final.transitions] == ["DELINQUENT", "DEFAULTED"] and final.transitions[0]["trigger"] == "0x" + b32("installment_overdue").hex()
        assert (int(final.reserve_pledged), int(final.reserve_applied), int(final.impairment), final.loss_id) == (0, 0, 0, None)
        pending = s.get(ProjectedFacilityCredit, (ID, "PENDING", FACILITY))
        assert pending.state == "CLOSED_WITH_LOSS" and [t["to"] for t in pending.transitions] == ["DELINQUENT", "DEFAULTED", "RECOVERY", "CLOSED_WITH_LOSS"]
        assert (int(pending.reserve_pledged), int(pending.reserve_applied), pending.reserve_owner) == (0, 30, "0x" + "c3" * 20)
        assert int(pending.impairment) == 0 and pending.loss_id == "0x" + b32("loss-writeoff").hex() and int(pending.loss_amount) == 372 and pending.written_off_at == 103
    rpc.height = 5
    indexer.sync(ID)
    with Session(engine) as s:
        final = s.get(ProjectedFacilityCredit, (ID, "FINALIZED", FACILITY))
        assert final.state == "CLOSED_WITH_LOSS" and final.written_off_at == 103 and int(final.reserve_applied) == 30


def test_credit_status_rejects_reserve_over_application(history_setup):
    engine, rpc, indexer = history_setup
    fid = bytes.fromhex(FACILITY[2:])
    history_event(rpc, "RecoveryManager", "ReserveFunded", {"facilityId": fid, "owner": bytes.fromhex("c3" * 20), "amount": 10}, 2, 4)
    history_event(rpc, "RecoveryManager", "ReserveApplied", {"facilityId": fid, "amount": 11}, 2, 5)
    rpc.height = 4
    with pytest.raises(ValueError, match="reserve application exceeds"):
        indexer.sync(ID)


def test_orphan_journal_rows_above_the_cursor_are_swept_instead_of_crashing(setup):
    """A block row beyond the committed cursor (2026-09-17 production incident) must not stop every later sync."""
    from hashcredit_gpu.db.projections_models import ChainBlock, ChainCursor

    engine, rpc, indexer = setup
    rpc.height = 3
    indexer.sync(ID)
    with Session(engine) as s, s.begin():
        cursor = s.get(ChainCursor, ID)
        assert cursor.last_block_number == 3
        s.add(ChainBlock(deployment_id=ID, number=4, hash=h(4444), parent_hash=h(3), timestamp=104, tier="PENDING"))
    rpc.height = 5
    result = indexer.sync(ID)
    assert result["lastBlock"] == 5
    with Session(engine) as s:
        assert s.get(ChainBlock, (ID, 4)).hash == h(4)  # the canonical block replaced the orphan
        assert s.get(ChainCursor, ID).last_block_number == 5
