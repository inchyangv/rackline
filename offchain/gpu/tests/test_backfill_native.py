"""Synthetic RPC and PostgreSQL fixtures exercise native-import validation, not real native verification."""

import copy
import json
from types import SimpleNamespace

import pytest
from eth_abi import encode
from hashcredit_prover.gpu.backfill_native import inspect_consumption, persist_receivables
from hashcredit_prover.gpu.bootstrap_native import ACCOUNT, FACILITY_KEY, PROVIDER, bootstrap
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from hashcredit_gpu.db.ledgers import (
    CashReceipt,
    EvidenceConsumption,
    NativeVerification,
    ProofRequest,
    Receivable,
    ReceivableRevision,
    Settlement,
)
from hashcredit_gpu.db.models import Facility
from hashcredit_gpu.db.product_models import FacilityBinding
from hashcredit_gpu.db.projections_models import ChainDeployment
from hashcredit_gpu.ingestion.collector import MemoryRawStore
from hashcredit_gpu.projections.decoders import ABI_DIR, Decoder, _canonical_type
from hashcredit_gpu.projections.views import _input_value
from hashcredit_gpu.transactions.abi import keccak_hex, selector

from .test_bootstrap_native import fixture as native_fixture  # noqa: F401
from .test_chain_projector import ID, h


def log_for(decoder, contract, name, values, address):
    event = next(e for e in decoder.events[contract].values() if e.name == name)

    def val(typ, value):
        return bytes.fromhex(value[2:]) if typ.startswith("bytes") else value

    return {
        "address": address,
        "topics": [event.topic0]
        + ["0x" + encode([typ], [val(typ, values[key])]).hex() for key, typ in event.indexed],
        "data": "0x"
        + encode(
            [typ for _, typ in event.unindexed],
            [val(typ, values[key]) for key, typ in event.unindexed],
        ).hex(),
    }


@pytest.fixture
def facts(native_fixture):  # noqa: F811 - pytest resolves imported fixture by name
    _rpc, config, manifest, _setup, _views, _answers, _receipt = native_fixture
    config["contracts"].update(
        ReceivableBook="0x" + "cc" * 20, AttestcoinRevenueVerifier="0x" + "dd" * 20
    )
    source = manifest["source"]["emitters"][0]["address"]
    token = manifest["source"]["tokens"][0]["address"]
    decoder = Decoder({"SourceEscrow": source})
    account, provider, ref = keccak_hex(ACCOUNT.encode()), keccak_hex(PROVIDER.encode()), h(777)
    payer = "0x" + "98" * 20
    args = [
        (
            "ObligationRecognizedV2",
            {
                "accountKey": account,
                "obligationRef": ref,
                "issuer": payer,
                "payer": payer,
                "payee": source,
                "token": token,
                "amount": 100,
                "dueAt": 2000000000,
                "revision": 1,
            },
            0,
        ),
        (
            "ObligationAssigned",
            {
                "accountKey": account,
                "obligationRef": ref,
                "facilityKey": keccak_hex(bytes.fromhex(FACILITY_KEY[2:])),
                "revision": 2,
            },
            1,
        ),
        (
            "PayoutReceived",
            {
                "accountKey": account,
                "obligationRef": ref,
                "token": token,
                "payer": payer,
                "amount": 25,
                "settlementSeq": 1,
            },
            3,
        ),
        (
            "SourceCheckpointV2",
            {
                "accountKey": account,
                "checkpointSeq": 1,
                "latestRevision": 3,
                "openAmount": 75,
                "paidCumulative": 25,
                "observedAt": 1800000000,
                "protectedUntil": 1800000900,
            },
            2,
        ),
    ]
    output = []
    for i, (name, values, meaning) in enumerate(args):
        log = log_for(decoder, "SourceEscrow", name, values, source)
        event = decoder.decode(log["address"], log["topics"], log["data"])
        record = {
            "id": h(100 + i),
            "economicEventId": h(110 + i),
            "providerId": provider,
            "accountKey": account,
            "meaning": str(meaning),
            "method": "0",
            "trust": "0",
            "consumer": config["contracts"]["ReceivableBook"],
            "manifestHash": "0x" + manifest["manifestHash"][7:],
            "provenAt": "1800000000",
            "validUntil": "1800001000",
            "locator": {
                "chainKey": "1",
                "height": str(1000 + i),
                "txIndex": "0",
                "logOrdinal": "0",
            },
            "emitter": source,
            "topic0": log["topics"][0],
            "dataHash": keccak_hex(
                encode(
                    ["bytes32[]", "bytes"],
                    [[bytes.fromhex(t[2:]) for t in log["topics"]], bytes.fromhex(log["data"][2:])],
                )
            ),
        }
        artifact = {
            "version": 1,
            "status": "PROOF_READY",
            "nativeAccepted": False,
            "manifestHash": manifest["manifestHash"],
            "sdkVersion": "0.18.0",
            "executionProfile": "NATIVE_TESTNET",
            "verificationMethod": "ATTESTCOIN_NATIVE",
            "height": str(1000 + i),
            "txIndex": 0,
            "txHash": h(200 + i),
            "proof": {
                "chainKey": "1",
                "height": str(1000 + i),
                "transaction": "0x1234",
                "root": h(300),
                "siblings": [],
                "lowerEndpointDigest": h(301),
                "continuityRoots": [],
            },
        }
        output.append(
            {
                "record": record,
                "event": name,
                "args": event.args,
                "artifact": artifact,
                "destinationTx": h(400 + i),
                "destinationBlock": 6 + i,
                "sourceTx": artifact["txHash"],
                "sourceBlockHash": h(1000 + i),
                "sourceLog": log,
            }
        )
    canonical = {
        h(7777): {
            "providerId": provider,
            "accountKey": account,
            "obligationRef": ref,
            "payer": payer,
            "token": token,
            "denominationProven": True,
            "net": "100",
            "paid": "25",
            "revision": "3",
            "dueAt": "2000000000",
            "facilityId": FACILITY_KEY,
            "state": "2",
            "disputed": False,
        }
    }
    checkpoint = {"checkpointSeq": "1", "exists": True}
    return native_fixture, output, canonical, checkpoint


def test_atomic_replay_creates_exact_evidence_history_not_destination_cash(migrated_db_url, facts):
    (rpc, config, manifest, setup, views, _, _), values, canonical, checkpoint = facts
    engine = create_engine(migrated_db_url)
    try:
        bootstrap(engine, rpc, config, manifest, setup, views=views)
        for _ in range(2):
            with Session(engine) as s, s.begin():
                deployment = s.get(ChainDeployment, ID)
                binding = s.scalar(select(FacilityBinding))
                persist_receivables(
                    s,
                    deployment,
                    manifest,
                    values,
                    canonical,
                    checkpoint,
                    MemoryRawStore(),
                    binding,
                )
        with Session(engine) as s:
            row = s.scalar(select(Receivable))
            assert (row.net, row.paid_amount, row.unpaid_amount, row.revision) == (100, 25, 75, 3)
            assert s.scalar(select(func.count()).select_from(EvidenceConsumption)) == 4
            assert s.scalar(select(func.count()).select_from(ReceivableRevision)) == 3
            assert set(s.scalars(select(ProofRequest.status))) == {"CONSUMED"}
            assert set(s.scalars(select(NativeVerification.status))) == {"ACCEPTED"}
            assert s.scalar(select(Settlement.source_amount)) == 25
            assert s.scalar(select(func.count()).select_from(CashReceipt)) == 0
            assert s.scalar(select(Facility.principal)) == 123
    finally:
        engine.dispose()


def test_incomplete_source_history_rolls_back_every_business_record(migrated_db_url, facts):
    (rpc, config, manifest, setup, views, _, _), values, canonical, checkpoint = facts
    engine = create_engine(migrated_db_url)
    try:
        bootstrap(engine, rpc, config, manifest, setup, views=views)
        with Session(engine) as s:
            with pytest.raises(ValueError, match="history is incomplete"), s.begin():
                persist_receivables(
                    s,
                    s.get(ChainDeployment, ID),
                    manifest,
                    [values[0], values[1], values[3]],
                    canonical,
                    checkpoint,
                    MemoryRawStore(),
                    s.scalar(select(FacilityBinding)),
                )
            assert s.scalar(select(func.count()).select_from(EvidenceConsumption)) == 0
            assert s.scalar(select(func.count()).select_from(ProofRequest)) == 0
    finally:
        engine.dispose()


@pytest.mark.parametrize("bad", [None, "artifact", "source", "native_event", "account"])
def test_exact_native_calldata_and_source_log_binding(facts, bad):
    (_, config, manifest, _, _, _, _), values, _, _ = facts
    fact = values[0]
    contracts, record, artifact = config["contracts"], fact["record"], fact["artifact"]
    p = SimpleNamespace(
        source_event_id=record["id"],
        economic_event_key=record["economicEventId"],
        verified_in_same_tx=True,
        proven_height=1000,
        proven_tx_index=0,
        consumption_tx_hash=fact["destinationTx"],
        block_number=6,
    )
    deployment = SimpleNamespace(manifest_hash=manifest["manifestHash"], contracts=contracts)
    decoder = Decoder(contracts)
    logs = [
        log_for(
            decoder,
            "AttestcoinRevenueVerifier",
            "SourceEventVerified",
            {
                "id": record["id"],
                "chainKey": 1,
                "height": 1000,
                "txIndex": 0,
                "logOrdinal": 0,
                "emitter": record["emitter"],
                "topic0": record["topic0"],
            },
            contracts["AttestcoinRevenueVerifier"],
        ),
        log_for(
            decoder,
            "EvidenceBook",
            "SourceEventConsumed",
            {
                "id": record["id"],
                "economicEventId": record["economicEventId"],
                "consumer": record["consumer"],
                "meaning": 0,
                "manifestHash": record["manifestHash"],
            },
            contracts["EvidenceBook"],
        ),
    ]
    fn = next(
        x
        for x in json.loads((ABI_DIR / "ReceivableBook.json").read_text())
        if x.get("type") == "function" and x.get("name") == "ingest"
    )
    types = [_canonical_type(i) for i in fn["inputs"]]
    proof = artifact["proof"]
    envelope = [
        proof["chainKey"],
        proof["height"],
        proof["transaction"],
        proof["root"],
        proof["siblings"],
        proof["lowerEndpointDigest"],
        proof["continuityRoots"],
    ]
    args = [record["providerId"], envelope, record["emitter"], [record["topic0"]], []]
    data = (
        selector("ingest(" + ",".join(types) + ")")
        + encode(types, [_input_value(i, v) for i, v in zip(fn["inputs"], args, strict=True)]).hex()
    )

    class RPC:
        def get_transaction(self, _):
            return {"blockHash": h(6), "to": contracts["ReceivableBook"], "input": data}

        def get_receipt(self, _):
            return {"status": "0x1", "blockNumber": "0x6", "blockHash": h(6), "logs": logs}

        def get_block(self, n):
            return {"hash": h(n)}

    class Source:
        def get_receipt(self, _):
            return {
                "status": "0x1",
                "blockNumber": hex(1000),
                "transactionIndex": "0x0",
                "blockHash": h(1000),
                "logs": [fact["sourceLog"]],
            }

        def get_block(self, n):
            return {"hash": h(n)}

    class Views:
        def read(self, *_):
            return record

    if bad == "artifact":
        artifact = copy.deepcopy(artifact)
        artifact["proof"]["transaction"] = "0x5678"
    if bad == "source":
        fact["sourceLog"]["data"] = "0x"
    if bad == "native_event":
        logs.pop(0)
    if bad == "account":
        record["accountKey"] = h(999)
    if bad:
        with pytest.raises(ValueError):
            inspect_consumption(RPC(), Source(), deployment, manifest, p, artifact, 10, Views())
    else:
        assert (
            inspect_consumption(RPC(), Source(), deployment, manifest, p, artifact, 10, Views())[
                "event"
            ]
            == "ObligationRecognizedV2"
        )
