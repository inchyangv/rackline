"""Import actual TEST_ONLY native app consumptions and source receivables, never inferred revenue."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from eth_abi import decode, encode
from hashcredit_gpu.db.ledgers import (
    EVIDENCE_MEANINGS,
    EvidenceConsumption,
    NativeVerification,
    ProofArtifact,
    ProofRequest,
    Receivable,
    ReceivableRevision,
    Settlement,
)
from hashcredit_gpu.db.models import Facility, ProviderAccount
from hashcredit_gpu.db.product_models import FacilityBinding
from hashcredit_gpu.db.projections_models import ChainCursor, ChainDeployment, ProjectedEvidence
from hashcredit_gpu.ingestion.collector import FileRawStore, payload_hash_of
from hashcredit_gpu.jobs.outbox import emit
from hashcredit_gpu.jobs.queue import write_audit
from hashcredit_gpu.projections.decoders import ABI_DIR, Decoder, _canonical_type
from hashcredit_gpu.projections.views import ContractViews, _output_value
from hashcredit_gpu.receivables.service import lock
from hashcredit_gpu.reconciliation.chain_reader import stable_id
from hashcredit_gpu.transactions.abi import keccak_hex, selector
from hashcredit_gpu.transactions.rpc import JsonRpcClient, load_rpc_allowlist
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from .bootstrap_native import ACCOUNT, FACILITY_KEY, PROVIDER, _ensure, _require


def _decode_call(contract, function, raw):
    fn = next(
        x
        for x in json.loads((ABI_DIR / f"{contract}.json").read_text())
        if x.get("type") == "function" and x.get("name") == function
    )
    types = [_canonical_type(i) for i in fn["inputs"]]
    _require(
        raw.startswith(selector(function + "(" + ",".join(types) + ")")),
        "unexpected app transaction selector",
    )
    values = decode(types, bytes.fromhex(raw[10:]))
    return [_output_value(i, v) for i, v in zip(fn["inputs"], values, strict=True)]


def _envelope(artifact):
    p = artifact["proof"]
    return {
        "chainKey": str(p["chainKey"]),
        "height": str(p["height"]),
        "encodedTransaction": p["transaction"],
        "merkleRoot": p["root"],
        "siblings": p["siblings"],
        "lowerEndpointDigest": p["lowerEndpointDigest"],
        "continuityRoots": p["continuityRoots"],
    }


def inspect_consumption(
    rpc, source_rpc, deployment, manifest, projection, artifact, final_block, views
):
    """Verify exact official artifact was actually consumed, then bind canonical source receipt contents."""
    _require(
        artifact.get("status") == "PROOF_READY"
        and artifact.get("nativeAccepted") is False
        and artifact.get("manifestHash") == deployment.manifest_hash
        and artifact.get("sdkVersion") == "0.18.0"
        and artifact.get("executionProfile") == "NATIVE_TESTNET"
        and artifact.get("verificationMethod") == "ATTESTCOIN_NATIVE",
        "native artifact profile/version mismatch",
    )
    contracts = deployment.contracts
    record = views.read("EvidenceBook", "record", [projection.source_event_id], final_block)
    loc = record["locator"]
    _require(
        projection.verified_in_same_tx
        and record["id"] == projection.source_event_id
        and record["economicEventId"] == projection.economic_event_key
        and record["providerId"] == keccak_hex(PROVIDER.encode())
        and record["accountKey"] == keccak_hex(ACCOUNT.encode())
        and record["method"] == "0"
        and record["trust"] == "0"
        and record["consumer"].lower() == contracts["ReceivableBook"].lower()
        and record["manifestHash"] == "0x" + deployment.manifest_hash[7:]
        and int(loc["chainKey"]) == int(manifest["source"]["chainKey"])
        and int(loc["height"]) == int(artifact["height"]) == projection.proven_height
        and int(loc["txIndex"]) == int(artifact["txIndex"]) == projection.proven_tx_index,
        "canonical native record/projection/artifact binding mismatch",
    )
    tx = rpc.get_transaction(projection.consumption_tx_hash)
    receipt = rpc.get_receipt(projection.consumption_tx_hash)
    block = rpc.get_block(projection.block_number)
    _require(
        tx
        and receipt
        and block
        and int(receipt["status"], 16) == 1
        and int(receipt["blockNumber"], 16) == projection.block_number <= final_block
        and receipt["blockHash"].lower() == block["hash"].lower() == tx["blockHash"].lower()
        and tx["to"].lower() == contracts["ReceivableBook"].lower(),
        "app consumption not canonical/final",
    )
    call = _decode_call("ReceivableBook", "ingest", tx["input"])
    _require(
        call[0] == record["providerId"]
        and call[1] == _envelope(artifact)
        and call[2].lower() == record["emitter"].lower(),
        "stored proof is not the exact natively consumed calldata",
    )
    decoder = Decoder(contracts)
    events = [decoder.decode(log["address"], log["topics"], log["data"]) for log in receipt["logs"]]
    for contract, event in (
        ("AttestcoinRevenueVerifier", "SourceEventVerified"),
        ("EvidenceBook", "SourceEventConsumed"),
    ):
        _require(
            any(
                e and e.contract == contract and e.event == event and e.args["id"] == record["id"]
                for e in events
            ),
            "native verification and economic consumption must be in the same final receipt",
        )
    source = source_rpc.get_receipt(artifact["txHash"])
    _require(
        source
        and int(source["status"], 16) == 1
        and int(source["blockNumber"], 16) == int(loc["height"])
        and int(source["transactionIndex"], 16) == int(loc["txIndex"]),
        "source receipt locator mismatch",
    )
    source_block = source_rpc.get_block(int(loc["height"]))
    _require(
        source_block and source["blockHash"].lower() == source_block["hash"].lower(),
        "source receipt was reorganized",
    )
    ordinal = int(loc["logOrdinal"])
    _require(0 <= ordinal < len(source["logs"]), "source log ordinal outside receipt")
    log = source["logs"][ordinal]
    data_hash = keccak_hex(
        encode(
            ["bytes32[]", "bytes"],
            [[bytes.fromhex(t[2:]) for t in log["topics"]], bytes.fromhex(log["data"][2:])],
        )
    )
    _require(
        log["address"].lower() == record["emitter"].lower()
        and log["address"].lower() in {e["address"].lower() for e in manifest["source"]["emitters"]}
        and log["topics"][0].lower() == record["topic0"]
        and data_hash == record["dataHash"],
        "native decoded event differs from canonical source receipt",
    )
    source_decoder = Decoder({"SourceEscrow": log["address"]})
    event = source_decoder.decode(log["address"], log["topics"], log["data"])
    _require(
        event and event.args.get("accountKey") == keccak_hex(ACCOUNT.encode()),
        "source event account mismatch",
    )
    meanings = {
        "ObligationRecognizedV2": "OBLIGATION_RECOGNIZED",
        "ObligationAssigned": "ASSIGNMENT_RECOGNIZED",
        "PayoutReceived": "PAYOUT",
        "SourceCheckpointV2": "CORRECTION",
    }
    _require(
        event.event in meanings
        and EVIDENCE_MEANINGS[int(record["meaning"])] == meanings[event.event],
        "unsupported source business event for this bounded native import",
    )
    return {
        "record": record,
        "event": event.event,
        "args": event.args,
        "artifact": artifact,
        "destinationTx": projection.consumption_tx_hash,
        "destinationBlock": projection.block_number,
        "sourceBlockHash": source["blockHash"],
        "sourceTx": artifact["txHash"],
    }


def persist_evidence(s, deployment, manifest, fact, store):
    artifact, record = fact["artifact"], fact["record"]
    loc = record["locator"]
    request = s.scalar(
        select(ProofRequest).where(
            ProofRequest.env_id == deployment.env_id,
            ProofRequest.chain_key == int(loc["chainKey"]),
            ProofRequest.tx_hash == fact["sourceTx"],
        )
    )
    if not request:
        request = ProofRequest(
            proof_request_id=stable_id(f"proof:{deployment.env_id}:{fact['sourceTx']}"),
            env_id=deployment.env_id,
            chain_key=int(loc["chainKey"]),
            tx_hash=fact["sourceTx"],
            provider_id=PROVIDER,
            execution_profile="NATIVE_TESTNET",
            manifest_hash=deployment.manifest_hash,
            sdk_version="0.18.0",
            encoding_version=1,
            abi_sha256s=manifest["sdk"]["abiSha256"],
            status="OBSERVED",
        )
        s.add(request)
        s.flush()
    _require(
        request.provider_id == PROVIDER
        and request.manifest_hash == deployment.manifest_hash
        and request.execution_profile == "NATIVE_TESTNET",
        "existing proof query belongs to different deployment",
    )
    raw = json.dumps(artifact, sort_keys=True, separators=(",", ":")).encode()
    digest = payload_hash_of(raw)
    storage_ref = store.put(digest, raw)
    stored = s.scalar(
        select(ProofArtifact).where(
            ProofArtifact.proof_request_id == request.proof_request_id,
            ProofArtifact.artifact_hash == digest,
        )
    )
    if not stored:
        stored = ProofArtifact(
            proof_artifact_id=stable_id(f"artifact:{request.proof_request_id}:{digest}"),
            proof_request_id=request.proof_request_id,
            artifact_hash=digest,
            storage_ref=storage_ref,
            byte_length=len(raw),
            sdk_version="0.18.0",
            encoding_version=1,
            claimed_height=int(loc["height"]),
            claimed_tx_index=int(loc["txIndex"]),
        )
        s.add(stored)
        s.flush()
    verification_id = stable_id(f"native:{request.proof_request_id}:{fact['destinationTx']}")
    verification = s.scalar(
        select(NativeVerification).where(
            NativeVerification.proof_request_id == request.proof_request_id,
            NativeVerification.submission_tx_hash == fact["destinationTx"],
        )
    )
    if not verification:
        verification = NativeVerification(
            native_verification_id=verification_id,
            proof_request_id=request.proof_request_id,
            proof_artifact_id=stored.proof_artifact_id,
            execution_profile="NATIVE_TESTNET",
            verification_method="ATTESTCOIN_NATIVE",
            destination_chain_id=deployment.chain_id,
            verifier_address=deployment.contracts["AttestcoinRevenueVerifier"].lower(),
            submission_tx_hash=fact["destinationTx"],
            status="SUBMITTED",
        )
        s.add(verification)
    _require(
        verification.proof_artifact_id == stored.proof_artifact_id,
        "existing submission artifact differs from canonical calldata",
    )
    verification.status, verification.receipt_status = "ACCEPTED", 1
    verification.verification_block = fact["destinationBlock"]
    verification.proven_height, verification.proven_tx_index = (
        int(loc["height"]),
        int(loc["txIndex"]),
    )
    verification.accepted_at = datetime.fromtimestamp(int(record["provenAt"]), UTC)
    s.flush()
    meaning = EVIDENCE_MEANINGS[int(record["meaning"])]
    economic_id = f"{PROVIDER}/native-integration/{meaning}/{record['economicEventId']}"
    consumption = s.scalar(
        select(EvidenceConsumption).where(
            EvidenceConsumption.env_id == deployment.env_id,
            EvidenceConsumption.source_event_id == record["id"],
        )
    )
    if consumption:
        _require(
            consumption.economic_event_id == economic_id
            and consumption.provider_account_id == ACCOUNT,
            "existing consumption semantic binding conflict",
        )
    else:
        consumption = EvidenceConsumption(
            consumption_id=stable_id(f"consumption:{deployment.env_id}:{record['id']}"),
            env_id=deployment.env_id,
            source_event_id=record["id"],
            economic_event_id=economic_id,
            native_verification_id=verification.native_verification_id,
            provider_id=PROVIDER,
            provider_account_id=ACCOUNT,
            meaning=meaning,
            verification_method="ATTESTCOIN_NATIVE",
            trust="PROVEN",
            execution_profile="NATIVE_TESTNET",
            consumer_address=record["consumer"].lower(),
            consumption_tx_hash=fact["destinationTx"],
            manifest_hash=deployment.manifest_hash,
            proven_at=datetime.fromtimestamp(int(record["provenAt"]), UTC),
            valid_until=datetime.fromtimestamp(int(record["validUntil"]), UTC),
            chain_key=int(loc["chainKey"]),
            height=int(loc["height"]),
            tx_index=int(loc["txIndex"]),
            log_ordinal=int(loc["logOrdinal"]),
            emitter_address=record["emitter"].lower(),
            topic0=record["topic0"],
            data_hash=record["dataHash"],
        )
        s.add(consumption)
        s.flush()
    request.status = (
        "CONSUMED"  # Trigger checks actual persisted artifact, acceptance and consumption.
    )
    s.flush()
    return consumption


def persist_receivables(s, deployment, manifest, facts, canonical, checkpoint, store, binding):
    consumptions = {
        f["record"]["id"]: persist_evidence(s, deployment, manifest, f, store) for f in facts
    }
    checkpoints = [
        f
        for f in facts
        if f["event"] == "SourceCheckpointV2"
        and int(f["args"]["checkpointSeq"]) == int(checkpoint["checkpointSeq"])
    ]
    _require(
        checkpoint["exists"] and len(checkpoints) == 1, "current source checkpoint proof is missing"
    )
    checkpoint_id = consumptions[checkpoints[0]["record"]["id"]].consumption_id
    imported = []
    for onchain_id, value in canonical.items():
        relevant = sorted(
            [f for f in facts if f["args"].get("obligationRef") == value["obligationRef"]],
            key=lambda f: (
                int(f["record"]["locator"]["height"]),
                int(f["record"]["locator"]["txIndex"]),
                int(f["record"]["locator"]["logOrdinal"]),
            ),
        )
        recognition = [f for f in relevant if f["event"] == "ObligationRecognizedV2"]
        _require(
            len(recognition) == 1
            and value["providerId"] == keccak_hex(PROVIDER.encode())
            and value["accountKey"] == keccak_hex(ACCOUNT.encode())
            and value["facilityId"] == FACILITY_KEY
            and value["denominationProven"] is True,
            "canonical receivable ownership/recognition mismatch",
        )
        original = recognition[0]["args"]
        _require(
            int(original["amount"]) == int(value["net"])
            and original["token"].lower() == value["token"].lower(),
            "native importer requires complete correction history",
        )
        token = next(
            (
                t
                for t in manifest["source"]["tokens"]
                if t["address"].lower() == value["token"].lower()
            ),
            None,
        )
        _require(token is not None, "receivable source asset not admitted by manifest")
        paid, revision = 0, 0
        history = []
        for f in relevant:
            if f["event"] == "ObligationRecognizedV2":
                revision = int(f["args"]["revision"])
                kind = "RECOGNIZED"
            elif f["event"] == "ObligationAssigned":
                revision = int(f["args"]["revision"])
                kind = "ASSIGNMENT"
            elif f["event"] == "PayoutReceived":
                paid += int(f["args"]["amount"])
                revision += 1
                kind = "PAYOUT"
            else:
                continue
            history.append((revision, kind, paid, f))
        _require(
            paid == int(value["paid"]) and revision == int(value["revision"]),
            "native receivable history is incomplete",
        )
        cid = consumptions[recognition[0]["record"]["id"]]
        rid = stable_id(f"receivable:{deployment.deployment_id}:{onchain_id}")
        values = {
            "gross": int(original["amount"]),
            "net": int(value["net"]),
            "paid_amount": paid,
            "unpaid_amount": int(value["net"]) - paid,
            "revision": revision,
            "checkpoint_seq": int(checkpoint["checkpointSeq"]),
            "checkpoint_consumption_id": checkpoint_id,
            "state": "DISPUTED"
            if value["disputed"]
            else {1: "RECOGNIZED", 2: "ASSIGNED", 3: "PAID", 4: "CANCELLED"}[int(value["state"])],
            "disputed_reason": "CANONICAL_ONCHAIN_DISPUTE" if value["disputed"] else None,
        }
        row = _ensure(
            s,
            Receivable,
            rid,
            immutable={
                "receivable_id": rid,
                "provider_account_id": ACCOUNT,
                "economic_event_id": cid.economic_event_id,
                "obligation_ref": value["obligationRef"],
                "facility_id": binding.facility_id,
                "asset_chain_id": int(manifest["source"]["chainId"]),
                "asset_token_address": value["token"].lower(),
                "asset_decimals": int(token["decimals"]),
                "execution_profile": "NATIVE_TESTNET",
            },
            values={
                **values,
                "debtor": value["payer"].lower(),
                "due_at": datetime.fromtimestamp(int(value["dueAt"]), UTC),
                "contract_ref": f"doc://TEST_ONLY/source/{manifest['source']['chainId']}/{onchain_id}",
            },
        )
        _require(row.revision <= revision, "refuse to roll back a newer receivable snapshot")
        for key, val in values.items():
            setattr(row, key, val)
        for rev, kind, paid_at, f in history:
            existing = s.scalar(
                select(ReceivableRevision).where(
                    ReceivableRevision.receivable_id == rid,
                    ReceivableRevision.revision == rev,
                    ReceivableRevision.kind == kind,
                )
            )
            if not existing:
                s.add(
                    ReceivableRevision(
                        receivable_id=rid,
                        revision=rev,
                        kind=kind,
                        consumption_id=consumptions[f["record"]["id"]].consumption_id,
                        delta=0,
                        net_after=int(value["net"]),
                        unpaid_after=int(value["net"]) - paid_at,
                    )
                )
                s.flush()
            if kind == "PAYOUT":
                seq = int(f["args"]["settlementSeq"])
                sid = stable_id(f"settlement:{deployment.deployment_id}:{PROVIDER}:{seq}")
                _ensure(
                    s,
                    Settlement,
                    sid,
                    immutable={
                        "settlement_id": sid,
                        "provider_account_id": ACCOUNT,
                        "settlement_ref": str(seq),
                        "settlement_seq": seq,
                        "asset_chain_id": int(manifest["source"]["chainId"]),
                        "asset_token_address": value["token"].lower(),
                        "asset_decimals": int(token["decimals"]),
                        "source_amount": int(f["args"]["amount"]),
                        "payout_consumption_id": consumptions[f["record"]["id"]].consumption_id,
                        "execution_profile": "NATIVE_TESTNET",
                    },
                    values={"state": "PAID_AT_SOURCE"},
                )
        imported.append(rid)
    return imported


def backfill(engine, rpc, source_rpc, deployment_id, manifest, artifacts, store):
    with Session(engine) as s, s.begin():
        lock(s, f"native-backfill:{deployment_id}")
        deployment, cursor = (
            s.get(ChainDeployment, deployment_id),
            s.get(ChainCursor, deployment_id),
        )
        _require(
            deployment
            and cursor
            and deployment.execution_profile == "NATIVE_TESTNET"
            and deployment.manifest_hash == manifest["manifestHash"]
            and deployment.chain_id == rpc.chain_id() == 102031
            and source_rpc.chain_id() == int(manifest["source"]["chainId"]),
            "indexed native deployment required",
        )
        binding = s.scalar(
            select(FacilityBinding).where(
                FacilityBinding.deployment_id == deployment_id,
                FacilityBinding.onchain_id == FACILITY_KEY,
            )
        )
        account = s.get(ProviderAccount, ACCOUNT)
        _require(
            binding
            and account
            and s.get(Facility, binding.facility_id).borrower_id == account.borrower_id,
            "canonical facility/account bootstrap required",
        )
        block = cursor.finalized_block_number
        canonical_block = rpc.get_block(block)
        views = ContractViews(rpc, deployment.contracts)
        _require(
            views.read("EvidenceBook", "envIdHash", [], block)
            == keccak_hex(deployment.env_id.encode()),
            "app environment mismatch",
        )
        proofs = {
            (int(a["height"]), int(a["txIndex"])): a
            for a in artifacts
            if a.get("status") == "PROOF_READY"
        }
        projections = list(
            s.scalars(
                select(ProjectedEvidence).where(
                    ProjectedEvidence.deployment_id == deployment_id,
                    ProjectedEvidence.tier == "FINALIZED",
                    ProjectedEvidence.verified_in_same_tx.is_(True),
                )
            )
        )
        facts = [
            inspect_consumption(
                rpc,
                source_rpc,
                deployment,
                manifest,
                p,
                proofs[(p.proven_height, p.proven_tx_index)],
                block,
                views,
            )
            for p in projections
            if (p.proven_height, p.proven_tx_index) in proofs
        ]
        _require(facts, "no matching finalized native app consumptions")
        ids = views.read("ReceivableBook", "facilityReceivables", [FACILITY_KEY], block)
        canonical = {rid: views.read("ReceivableBook", "receivable", [rid], block) for rid in ids}
        _require(canonical, "no canonical facility receivables")
        checkpoint = views.read(
            "ReceivableBook",
            "checkpoint",
            [keccak_hex(PROVIDER.encode()), keccak_hex(ACCOUNT.encode())],
            block,
        )
        imported = persist_receivables(
            s, deployment, manifest, facts, canonical, checkpoint, store, binding
        )
        _require(
            canonical_block and rpc.get_block(block)["hash"] == canonical_block["hash"],
            "chain changed during native backfill",
        )
        payload = {
            "receivableIds": imported,
            "nativeConsumptions": len(facts),
            "blockNumber": block,
            "testOnly": True,
            "partnerRevenue": "SIMULATED",
            "debtApplied": False,
            "cashCreated": False,
        }
        if emit(
            s.connection(),
            aggregate_type="deployment",
            aggregate_id=deployment_id,
            event_type="NATIVE_RECEIVABLES_RECONCILED",
            idempotency_key=f"native-backfill:{deployment_id}:{block}",
            payload=payload,
        ):
            write_audit(
                s.connection(),
                actor="native-backfill",
                actor_role="system",
                action="RECONCILE_NATIVE_RECEIVABLES",
                entity_table="chain_deployments",
                entity_id=deployment_id,
                before=None,
                after=payload,
            )
        return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("manifest", "deployment-id", "proof-dir", "artifact-dir"):
        parser.add_argument("--" + flag, required=True)
    args = parser.parse_args()
    _, urls = load_rpc_allowlist(args.manifest)
    _, source_urls = load_rpc_allowlist(args.manifest, side="source")
    artifacts = [json.loads(p.read_text()) for p in Path(args.proof_dir).glob("*.proof.json")]
    engine = create_engine(
        os.environ.get("HASHCREDIT_GPU_DATABASE_URL") or os.environ["GPU_DATABASE_URL"]
    )
    try:
        print(
            json.dumps(
                backfill(
                    engine,
                    JsonRpcClient(urls[0], urls),
                    JsonRpcClient(source_urls[0], source_urls),
                    args.deployment_id,
                    json.loads(Path(args.manifest).read_text()),
                    artifacts,
                    FileRawStore(args.artifact_dir),
                )
            )
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
