"""PostgreSQL dispatcher recovery; fake transport never broadcasts publicly."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, text

from hashcredit_gpu.jobs import JobQueue
from hashcredit_gpu.transactions import intents
from hashcredit_gpu.transactions.abi import PURPOSES, keccak_hex
from hashcredit_gpu.transactions.dispatcher import AccountSigner, Dispatcher, DispatcherConfig
from hashcredit_gpu.transactions.rpc import RpcTransportError


class RPC:
    def __init__(self):
        self.sent, self.receipts, self.height = [], {}, 10
        self.timeout = False

    def chain_id(self):
        return 31337

    def transaction_count(self, *_):
        return 0

    def eth_call(self, *_):
        return "0x"

    def estimate_gas(self, *_):
        return 100000

    def gas_price(self):
        return 1000

    def block_number(self):
        return self.height

    def get_block(self, n):
        return {"hash": "0x" + format(n, "064x")}

    def get_receipt(self, tx):
        return self.receipts.get(tx)

    def send_raw_transaction(self, raw):
        self.sent.append(raw)
        if self.timeout:
            raise RpcTransportError("timeout after accepting")
        return keccak_hex(bytes.fromhex(raw[2:]))


@pytest.fixture
def dispatcher(migrated_db_url):
    engine, rpc = create_engine(migrated_db_url), RPC()
    signer = AccountSigner("0x" + "11" * 32)
    d = Dispatcher(
        engine,
        rpc,
        signer,
        DispatcherConfig(31337, "treasury", {"manager": "0x" + "22" * 20}, finality_depth=3),
    )
    yield d
    engine.dispose()


def prep(d, action="a"):
    job = JobQueue(d.engine).enqueue("TX", {"action": action}, action)
    data = bytes.fromhex(PURPOSES["manager.repayFor"].selector[2:]) + bytes(64)
    return d.prepare(job, "manager.repayFor", data)


def test_timeout_reuses_signed_transaction_and_semantic_nonce(dispatcher):
    d = dispatcher
    first = prep(d)
    d.rpc.timeout = True
    assert d.broadcast(first.tx_intent_id).state == intents.IntentState.PENDING
    assert prep(d).tx_hash == first.tx_hash
    d.rpc.timeout = False
    assert d.broadcast(first.tx_intent_id).state == intents.IntentState.SENT
    assert len(d.rpc.sent) == 2 and d.rpc.sent[0] == d.rpc.sent[1]
    with d.engine.connect() as cx:
        assert cx.execute(text("SELECT count(*) FROM tx_intents")).scalar() == 1


def test_nonce_allocation_serializes_independent_workers(dispatcher):
    d = dispatcher
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda a: prep(d, a), ["a", "b"]))
    assert sorted(r.nonce for r in results) == [0, 1]


def test_receipt_reorg_then_finality(dispatcher):
    d = dispatcher
    intent = prep(d)
    d.broadcast(intent.tx_intent_id)
    d.rpc.receipts[intent.tx_hash] = {
        "blockNumber": "0xa",
        "blockHash": d.rpc.get_block(10)["hash"],
        "status": "0x1",
    }
    assert d.reconcile(intent.tx_intent_id).state == intents.IntentState.PENDING_MINED
    d.rpc.receipts.clear()
    assert d.reconcile(intent.tx_intent_id).state == intents.IntentState.ORPHANED
    d.rpc.receipts[intent.tx_hash] = {
        "blockNumber": "0xb",
        "blockHash": d.rpc.get_block(11)["hash"],
        "status": "0x1",
    }
    d.rpc.height = 13
    assert d.reconcile(intent.tx_intent_id).state == intents.IntentState.FINALIZED


def test_signed_intent_cannot_be_abandoned(dispatcher):
    d = dispatcher
    intent = prep(d)
    with d.engine.begin() as cx, pytest.raises(intents.IllegalIntentTransition):
        intents.abandon(cx, intent.tx_intent_id, actor="ops", actor_role="SYSTEM", reason="timeout")


def test_reverted_receipt_waits_finality(dispatcher):
    d = dispatcher
    intent = prep(d)
    d.rpc.receipts[intent.tx_hash] = {
        "blockNumber": "0xa",
        "blockHash": d.rpc.get_block(10)["hash"],
        "status": "0x0",
    }
    assert d.reconcile(intent.tx_intent_id).state == intents.IntentState.PENDING
    d.rpc.height = 12
    assert d.reconcile(intent.tx_intent_id).state == intents.IntentState.FAILED


def test_credential_and_calldata_allowlist(dispatcher):
    d = dispatcher
    job = JobQueue(d.engine).enqueue("TX", {}, "bad")
    with pytest.raises(PermissionError):
        d.prepare(job, "evidence.consume", bytes.fromhex(PURPOSES["evidence.consume"].selector[2:]))
    with pytest.raises(PermissionError):
        d.prepare(job, "verifier.verify", bytes(4))
    d.rpc.gas_price = lambda: d.config.max_fee_per_gas + 1
    with pytest.raises(ValueError, match="fee bound"):
        prep(d)
