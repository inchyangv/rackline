"""Register verified TEST_ONLY SetupGpuFacility metadata. Never seed proof, cash or approval facts."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

from eth_abi import decode
from hashcredit_gpu.db.models import (
    Borrower,
    BorrowerWallet,
    ControlAgreement,
    Facility,
    LegalEntity,
    PolicyVersion,
    Provider,
    ProviderAccount,
    TermsVersion,
)
from hashcredit_gpu.db.product_models import ApiRole, FacilityBinding
from hashcredit_gpu.db.projections_models import ChainDeployment
from hashcredit_gpu.domain.enums import FacilityState
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

PROVIDER = "mockdepin-testonly"
ACCOUNT = PROVIDER + ":native-integration"
FACILITY_KEY = keccak_hex(b"gpu080-facility-v2")
BORROWER_KEY = keccak_hex(b"gpu080-borrower-v2")
AGREEMENT_KEY = keccak_hex(b"gpu080-SIMULATED-control-v2")
POLICY_KEY = keccak_hex(b"gpu080-TEST_ONLY-policy-v2")
TERMS_KEY = keccak_hex(b"TEST_ONLY_NO_MONETARY_VALUE")


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _ensure(session, model, identity, *, immutable, values):
    row = session.get(model, identity)
    if row:
        _require(
            all(getattr(row, key) == value for key, value in immutable.items()),
            f"existing {model.__name__} identity conflicts with canonical deployment",
        )
        return row
    row = model(**immutable, **values)
    session.add(row)
    session.flush()
    return row


def inspect_setup(rpc, deployment, manifest, setup, *, views=None):
    """All facts are read from one canonical final block; a local receipt file is only a locator."""
    _require(deployment["chainId"] == rpc.chain_id() == 102031, "CC3 testnet chain required")
    _require(
        deployment["executionProfile"] == manifest["executionProfile"] == "NATIVE_TESTNET",
        "native TEST_ONLY deployment required",
    )
    _require(
        deployment["manifestHash"] == manifest["manifestHash"]
        and manifest.get("mock") is False
        and manifest.get("environmentStatus") == "PROBED",
        "probed native manifest mismatch",
    )
    _require(deployment["envId"] == "cc3-testnet", "unexpected testnet environment")
    depth = int(deployment["finalityDepth"])
    _require(depth >= 1, "positive finality depth required")
    block = rpc.block_number() - depth
    canonical = rpc.get_block(block)
    _require(canonical is not None, "final block unavailable")
    contracts = {name: addr.lower() for name, addr in deployment["contracts"].items()}
    decoder = Decoder(contracts)
    views = views or ContractViews(rpc, contracts)
    read = lambda c, f, a=(): views.read(c, f, list(a), block)
    info = read("CreditFacilityManager", "facilityInfo", [FACILITY_KEY])
    terms = read("DebtLedger", "terms", [FACILITY_KEY])
    ledger = read("DebtLedger", "view_", [FACILITY_KEY])
    provider = read("ProviderRegistry", "provider", [keccak_hex(PROVIDER.encode())])
    control = read("ControlRegistry", "agreement", [AGREEMENT_KEY])
    policy = read("GpuRiskPolicy", "params", [POLICY_KEY])
    anchor = read("CreditFacilityManager", "anchor", [FACILITY_KEY])
    _require(
        info["exists"]
        and info["borrowerId"] == BORROWER_KEY
        and info["providerId"] == keccak_hex(PROVIDER.encode())
        and info["controlAgreementId"] == AGREEMENT_KEY
        and int(info["profile"]) == 1,
        "unexpected canonical facility identity",
    )
    wallet = info["wallet"].lower()
    _require(
        read("AccountRegistry", "borrowerOfAccount", [keccak_hex(ACCOUNT.encode())]) == BORROWER_KEY
        and read("AccountRegistry", "providerOfAccount", [keccak_hex(ACCOUNT.encode())])
        == info["providerId"]
        and read("AccountRegistry", "isWalletOf", [BORROWER_KEY, wallet]) is True,
        "canonical account or wallet linkage mismatch",
    )
    source = provider["sourceChain"]
    _require(
        provider["testOnly"] is True
        and int(provider["executionProfile"]) == 1
        and source["manifestHash"] == "0x" + manifest["manifestHash"].split(":")[1]
        and source["envIdHash"] == keccak_hex(deployment["envId"].encode())
        and int(source["chainKey"]) == int(manifest["source"]["chainKey"])
        and int(source["chainId"]) == int(manifest["source"]["chainId"])
        and int(source["encoding"]) == 1,
        "provider source/native profile differs from manifest",
    )
    _require(
        read("GpuTestToken", "testOnly") is True
        and read("LendingVaultV2", "asset").lower() == contracts["GpuTestToken"]
        and int(read("GpuTestToken", "decimals")) == 6,
        "actual TEST_ONLY loan token binding required",
    )
    _require(
        terms["loanAsset"]
        == {"chainId": "102031", "token": contracts["GpuTestToken"], "decimals": "6"}
        and terms["termsVersionId"] == TERMS_KEY
        and terms["policyVersionId"] == POLICY_KEY
        and int(terms["executionProfile"]) == 1
        and policy["testOnly"] is True,
        "facility loan terms differ from approved TEST_ONLY setup",
    )
    _require(
        control["borrowerId"] == BORROWER_KEY
        and control["accountKey"] == keccak_hex(ACCOUNT.encode())
        and control["receiver"].lower()
        in {e["address"].lower() for e in manifest["source"]["emitters"]}
        and int(control["receiverChainId"]) == int(manifest["source"]["chainId"])
        and int(control["version"]) == int(info["controlVersion"]),
        "control/source account mismatch",
    )
    for function, contract in (
        ("LEDGER", "DebtLedger"),
        ("VAULT", "LendingVaultV2"),
        ("ACCOUNTS", "AccountRegistry"),
        ("CONTROL", "ControlRegistry"),
        ("POLICY", "GpuRiskPolicy"),
        ("EVIDENCE", "EvidenceBook"),
    ):
        _require(
            read("CreditFacilityManager", function).lower() == contracts[contract],
            "manager dependency mismatch",
        )
    _require(
        read("EvidenceBook", "envIdHash") == keccak_hex(deployment["envId"].encode()),
        "app environment mismatch",
    )
    # Re-fetch matching open receipt and signed transaction input; local Foundry data cannot supply facts.
    topic = decoder.topic0("DebtLedger", "FacilityOpened")
    candidates = [
        r["transactionHash"]
        for r in setup.get("receipts", [])
        if any(
            log["address"].lower() == contracts["DebtLedger"]
            and log.get("topics", [None])[0] == topic
            for log in r.get("logs", [])
        )
    ]
    fn = next(
        x
        for x in json.loads((ABI_DIR / "CreditFacilityManager.json").read_text())
        if x.get("type") == "function" and x.get("name") == "openFacility"
    )
    types = [_canonical_type(i) for i in fn["inputs"]]
    prefix = selector("openFacility(" + ",".join(types) + ")")
    opened = []
    for txhash in set(candidates):
        receipt = rpc.get_receipt(txhash)
        tx = rpc.get_transaction(txhash)
        _require(
            receipt and tx and int(receipt["status"], 16) == 1,
            "setup open transaction not successful",
        )
        number = int(receipt["blockNumber"], 16)
        actual_block = rpc.get_block(number)
        _require(
            int(deployment["deploymentBlock"]) <= number <= block
            and actual_block
            and actual_block["hash"].lower() == receipt["blockHash"].lower()
            and tx["blockHash"].lower() == receipt["blockHash"].lower()
            and tx["to"].lower() == contracts["CreditFacilityManager"]
            and tx["input"].startswith(prefix),
            "setup open transaction is not canonical/final",
        )
        args = decode(types, bytes.fromhex(tx["input"][10:]))
        args = [_output_value(spec, value) for spec, value in zip(fn["inputs"], args, strict=True)]
        if args[0] != FACILITY_KEY:
            continue
        _require(
            args[1] == BORROWER_KEY
            and args[2].lower() == wallet
            and args[3] == terms
            and args[4] == AGREEMENT_KEY,
            "setup calldata identity/terms mismatch",
        )
        events = [
            decoder.decode(log["address"], log["topics"], log["data"]) for log in receipt["logs"]
        ]
        _require(
            any(
                e
                and e.contract == "DebtLedger"
                and e.event == "FacilityOpened"
                and e.args["facilityId"] == FACILITY_KEY
                and e.args["termsVersionId"] == TERMS_KEY
                for e in events
            ),
            "canonical facility opened event missing",
        )
        opened.append(txhash.lower())
    _require(len(opened) == 1, "exactly one canonical Setup open transaction required")
    _require(
        rpc.get_block(block)["hash"] == canonical["hash"], "chain changed during bootstrap read"
    )
    return {
        "block": block,
        "blockHash": canonical["hash"],
        "at": int(canonical["timestamp"], 16),
        "info": info,
        "terms": terms,
        "ledger": ledger,
        "provider": provider,
        "control": control,
        "policy": policy,
        "anchor": anchor,
        "openingTx": opened[0],
    }


def bootstrap(engine, rpc, deployment, manifest, setup, *, roles=None, views=None):
    facts = inspect_setup(rpc, deployment, manifest, setup, views=views)
    did, info, terms, ledger, control = (
        deployment["deploymentId"],
        facts["info"],
        facts["terms"],
        facts["ledger"],
        facts["control"],
    )
    ids = {
        kind: stable_id(f"{did}:{kind}:{FACILITY_KEY}")
        for kind in ("legal", "borrower", "facility", "control")
    }
    now = datetime.fromtimestamp(facts["at"], UTC)
    reference = f"doc://TEST_ONLY/native-setup/{did}/{facts['openingTx']}"
    provenance = {
        "testOnly": True,
        "source": "SIMULATED",
        "partnerSourceBinding": "UNCONFIGURED",
        "legalApproval": False,
        "blockNumber": facts["block"],
        "blockHash": facts["blockHash"],
        "onchainId": AGREEMENT_KEY,
        "onchainGrade": control["grade"],
        "reference": reference,
    }
    with Session(engine) as s, s.begin():
        lock(s, f"bootstrap-native:{did}")
        _ensure(
            s,
            ChainDeployment,
            did,
            immutable={
                "deployment_id": did,
                "chain_id": 102031,
                "execution_profile": "NATIVE_TESTNET",
                "env_id": deployment["envId"],
                "manifest_hash": manifest["manifestHash"],
                "deployment_block": int(deployment["deploymentBlock"]),
                "finality_depth": int(deployment["finalityDepth"]),
                "contracts": {k: v.lower() for k, v in deployment["contracts"].items()},
            },
            values={},
        )
        _ensure(
            s,
            LegalEntity,
            ids["legal"],
            immutable={"legal_entity_id": ids["legal"]},
            values={"registration_ref": reference, "documents_ref": [reference]},
        )
        _ensure(
            s,
            Borrower,
            ids["borrower"],
            immutable={"borrower_id": ids["borrower"], "legal_entity_id": ids["legal"]},
            values={
                "kyc_status": "PENDING",
                "underwriting_status": "IN_REVIEW",
                "group_id": BORROWER_KEY[2:],
            },
        )
        wallet = info["wallet"].lower()
        linked = s.scalar(
            select(BorrowerWallet).where(
                BorrowerWallet.chain_id == 102031,
                BorrowerWallet.address == wallet,
                BorrowerWallet.released_at.is_(None),
            )
        )
        _require(
            not linked or linked.borrower_id == ids["borrower"],
            "wallet already belongs to another DB borrower",
        )
        if not linked:
            s.add(
                BorrowerWallet(
                    borrower_id=ids["borrower"],
                    chain_id=102031,
                    address=wallet,
                    role="SIGNER",
                    verified_at=now,
                )
            )
        _ensure(
            s,
            Provider,
            PROVIDER,
            immutable={
                "provider_id": PROVIDER,
                "execution_profile": "NATIVE_TESTNET",
                "manifest_hash": manifest["manifestHash"],
                "source_env_id": deployment["envId"],
                "source_chain_key": int(manifest["source"]["chainKey"]),
                "source_chain_id": int(manifest["source"]["chainId"]),
            },
            values={
                "display_name": "TEST_ONLY native source integration (simulated revenue)",
                "environment_status": "PROBED",
                "test_only": True,
                "capabilities": {
                    "nativeProof": "SUPPORTED",
                    "source_support": "SUPPORTED",
                    "partnerSourceBinding": "UNCONFIGURED",
                    "partnerRevenue": "SIMULATED",
                    "claimRevenue": False,
                    "requestControlChange": False,
                    "listAssets": False,
                    "fetchRevenue": False,
                    "fetchSettlements": False,
                    "getControlState": False,
                },
            },
        )
        _ensure(
            s,
            ProviderAccount,
            ACCOUNT,
            immutable={
                "provider_account_id": ACCOUNT,
                "provider_id": PROVIDER,
                "external_account_id": "native-integration",
                "borrower_id": ids["borrower"],
            },
            values={
                "roles": ["TEST_ONLY"],
                "auth_scope": [],
                "control_version": int(control["version"]),
                "last_verified_at": now,
            },
        )
        for model, key, identifier, data in (
            (PolicyVersion, "policy_version_id", POLICY_KEY[2:], facts["policy"]),
            (TermsVersion, "terms_version_id", TERMS_KEY[2:], terms),
        ):
            _ensure(
                s,
                model,
                identifier,
                immutable={key: identifier, "test_only": True},
                values={
                    "parameters": {
                        **data,
                        "testOnly": True,
                        "legalApproval": False,
                        "reference": reference,
                    }
                },
            )
        _ensure(
            s,
            ControlAgreement,
            ids["control"],
            immutable={
                "control_agreement_id": ids["control"],
                "borrower_id": ids["borrower"],
                "provider_account_id": ACCOUNT,
            },
            values={
                "control_grade": "E0",
                "subject": [ACCOUNT],
                "receiver_chain_id": int(control["receiverChainId"]),
                "receiver_address": control["receiver"].lower(),
                "change_authority": "BORROWER_ALONE",
                "agreement_hash": control["agreementHash"],
                "version": int(control["version"]),
                "effective_from": datetime.fromtimestamp(int(control["effectiveFrom"]), UTC),
                "effective_to": datetime.fromtimestamp(int(control["effectiveTo"]), UTC),
                "observation_provenance": provenance,
            },
        )
        facility = _ensure(
            s,
            Facility,
            ids["facility"],
            immutable={
                "facility_id": ids["facility"],
                "borrower_id": ids["borrower"],
                "vault_id": deployment["contracts"]["LendingVaultV2"].lower(),
                "loan_chain_id": 102031,
                "loan_token_address": terms["loanAsset"]["token"],
                "loan_decimals": int(terms["loanAsset"]["decimals"]),
                "terms_version_id": TERMS_KEY[2:],
                "policy_version_id": POLICY_KEY[2:],
                "execution_profile": "NATIVE_TESTNET",
                "manifest_hash": manifest["manifestHash"],
            },
            values={
                "state": list(FacilityState)[int(info["state"])].value,
                "test_only_terms": True,
                "control_agreement_id": ids["control"],
                "funded_agreement_version": int(info["controlVersion"]),
                "principal": int(ledger["principal"]),
                "unpaid_interest": int(ledger["unpaidInterest"]),
                "fees": int(ledger["fees"]),
                "reserved_draws": int(ledger["reservedDraws"]),
                "rate_bps": int(ledger["rateBps"]),
                "approved_cap": int(facts["anchor"]["auth"]["limit"])
                if facts["anchor"]["exists"]
                else 0,
                "advance_rate_bps": int(facts["policy"]["advanceRateBps"]),
                "maturity_at": datetime.fromtimestamp(int(terms["maturityAt"]), UTC),
            },
        )
        _ensure(
            s,
            FacilityBinding,
            (did, facility.facility_id),
            immutable={
                "deployment_id": did,
                "facility_id": facility.facility_id,
                "onchain_id": FACILITY_KEY,
                "binding_tx_hash": facts["openingTx"],
            },
            values={},
        )
        for role, addresses in (roles or {}).items():
            _require(
                role in {"operator", "underwriter", "treasury"}, "unsupported bootstrap API role"
            )
            for address in addresses:
                _require(bool(re.fullmatch(r"0x[0-9a-fA-F]{40}", address)), "invalid role address")
                address = address.lower()
                _ensure(
                    s,
                    ApiRole,
                    (102031, address, role),
                    immutable={"chain_id": 102031, "wallet": address, "role": role},
                    values={"active": True, "approval_ref": reference},
                )
        payload = {
            **ids,
            "providerAccountId": ACCOUNT,
            "wallet": wallet,
            "onchainFacilityId": FACILITY_KEY,
            "blockNumber": facts["block"],
            "openingTx": facts["openingTx"],
            "testOnly": True,
            "kycApproved": False,
            "partnerControlGrade": "E0",
            "economicEvidenceCreated": False,
        }
        if emit(
            s.connection(),
            aggregate_type="deployment",
            aggregate_id=did,
            event_type="NATIVE_TEST_METADATA_REGISTERED",
            payload=payload,
            idempotency_key=f"native-bootstrap:{did}",
        ):
            write_audit(
                s.connection(),
                actor="native-bootstrap",
                actor_role="system",
                action="BOOTSTRAP_TEST_METADATA",
                entity_table="chain_deployments",
                entity_id=did,
                before=None,
                after=payload,
            )
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--setup-receipt", required=True)
    for role in ("operator", "underwriter", "treasury"):
        parser.add_argument("--" + role, action="append", default=[])
    args = parser.parse_args()
    _, urls = load_rpc_allowlist(args.manifest)
    engine = create_engine(
        os.environ.get("HASHCREDIT_GPU_DATABASE_URL") or os.environ["GPU_DATABASE_URL"]
    )
    try:
        result = bootstrap(
            engine,
            JsonRpcClient(urls[0], urls),
            json.loads(Path(args.deployment).read_text()),
            json.loads(Path(args.manifest).read_text()),
            json.loads(Path(args.setup_receipt).read_text()),
            roles={role: getattr(args, role) for role in ("operator", "underwriter", "treasury")},
        )
        print(json.dumps(result))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
