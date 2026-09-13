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
