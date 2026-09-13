"""Bootstrap uses canonical reads; fixture RPC is synthetic and makes no native-E2E claim."""

import copy
import json
from pathlib import Path

import pytest
from eth_abi import encode
from hashcredit_prover.gpu.bootstrap_native import (
    ACCOUNT,
    AGREEMENT_KEY,
    BORROWER_KEY,
    FACILITY_KEY,
    POLICY_KEY,
    PROVIDER,
    TERMS_KEY,
    bootstrap,
    inspect_setup,
)
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from hashcredit_gpu.db.ledgers import CashReceipt, EvidenceConsumption, ProofRequest
from hashcredit_gpu.db.models import Borrower, ControlAgreement, Facility, Provider
from hashcredit_gpu.db.product_models import ApiRole, FacilityBinding
from hashcredit_gpu.projections.decoders import ABI_DIR, Decoder, _canonical_type
from hashcredit_gpu.projections.views import _input_value
from hashcredit_gpu.transactions.abi import keccak_hex, selector

from .test_chain_projector import ID, h


@pytest.fixture
def fixture():
    manifest = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "config/attestcoin/cc3-testnet.sepolia.release.json"
        ).read_text()
    )
    names = [
        "CreditFacilityManager",
        "DebtLedger",
        "ProviderRegistry",
        "GpuTestToken",
        "LendingVaultV2",
        "ControlRegistry",
        "AccountRegistry",
        "GpuRiskPolicy",
        "EvidenceBook",
    ]
    contracts = {name: "0x" + format(i + 1, "040x") for i, name in enumerate(names)}
    deployment = {
        "deploymentId": ID,
        "chainId": 102031,
        "envId": "cc3-testnet",
        "executionProfile": "NATIVE_TESTNET",
        "manifestHash": manifest["manifestHash"],
        "deploymentBlock": 1,
        "finalityDepth": 2,
        "contracts": contracts,
    }
    wallet = "0x" + "ab" * 20
    terms = {
        "loanAsset": {"chainId": "102031", "token": contracts["GpuTestToken"], "decimals": "6"},
        "rateBps": "1000",
        "maturityAt": "2000000000",
        "termsVersionId": TERMS_KEY,
        "policyVersionId": POLICY_KEY,
        "executionProfile": "1",
        "capitalizeUnpaidInterest": False,
    }
    info = {
        "borrowerId": BORROWER_KEY,
        "wallet": wallet,
        "providerId": keccak_hex(PROVIDER.encode()),
        "controlAgreementId": AGREEMENT_KEY,
        "controlVersion": "1",
        "profile": "1",
        "state": "3",
        "exists": True,
    }
    answers = {
        ("CreditFacilityManager", "facilityInfo"): info,
        ("DebtLedger", "terms"): terms,
        ("DebtLedger", "view_"): {
            "principal": "123",
            "unpaidInterest": "7",
            "fees": "2",
            "reservedDraws": "0",
            "rateBps": "1000",
        },
        ("ProviderRegistry", "provider"): {
            "testOnly": True,
            "executionProfile": "1",
            "sourceChain": {
                "manifestHash": "0x" + manifest["manifestHash"].split(":")[1],
                "envIdHash": keccak_hex(b"cc3-testnet"),
                "chainKey": "1",
                "chainId": "11155111",
                "encoding": "1",
            },
        },
        ("ControlRegistry", "agreement"): {
            "borrowerId": BORROWER_KEY,
            "accountKey": keccak_hex(ACCOUNT.encode()),
            "receiver": manifest["source"]["emitters"][0]["address"],
            "receiverChainId": "11155111",
            "version": "1",
            "grade": "2",
            "agreementHash": h(500),
            "effectiveFrom": "1700000000",
            "effectiveTo": "2000000000",
        },
        ("GpuRiskPolicy", "params"): {"testOnly": True, "advanceRateBps": "5000"},
        ("CreditFacilityManager", "anchor"): {"exists": True, "auth": {"limit": "37500000"}},
        ("AccountRegistry", "borrowerOfAccount"): BORROWER_KEY,
        ("AccountRegistry", "providerOfAccount"): info["providerId"],
        ("AccountRegistry", "isWalletOf"): True,
        ("GpuTestToken", "testOnly"): True,
        ("GpuTestToken", "decimals"): "6",
        ("LendingVaultV2", "asset"): contracts["GpuTestToken"],
        ("EvidenceBook", "envIdHash"): keccak_hex(b"cc3-testnet"),
    }
    for name, contract in (
        ("LEDGER", "DebtLedger"),
        ("VAULT", "LendingVaultV2"),
        ("ACCOUNTS", "AccountRegistry"),
        ("CONTROL", "ControlRegistry"),
        ("POLICY", "GpuRiskPolicy"),
        ("EVIDENCE", "EvidenceBook"),
    ):
        answers[("CreditFacilityManager", name)] = contracts[contract]

    class Views:
        def read(self, contract, function, args, block):
            assert block == 10
            return answers[(contract, function)]

    decoder = Decoder(contracts)
    event = {
        "address": contracts["DebtLedger"],
        "topics": [decoder.topic0("DebtLedger", "FacilityOpened"), FACILITY_KEY],
        "data": "0x"
        + encode(
            ["bytes32", "uint32", "uint64"], [bytes.fromhex(TERMS_KEY[2:]), 1000, 1700000000]
        ).hex(),
    }
    receipt = {
        "transactionHash": h(123),
        "status": "0x1",
        "blockNumber": "0x5",
        "blockHash": h(5),
        "logs": [event],
    }
    fn = next(
        x
        for x in json.loads((ABI_DIR / "CreditFacilityManager.json").read_text())
        if x.get("type") == "function" and x.get("name") == "openFacility"
    )
    types = [_canonical_type(i) for i in fn["inputs"]]
    args = [FACILITY_KEY, BORROWER_KEY, wallet, terms, AGREEMENT_KEY, 1]
    calldata = (
        selector("openFacility(" + ",".join(types) + ")")
        + encode(types, [_input_value(i, v) for i, v in zip(fn["inputs"], args, strict=True)]).hex()
    )

    class Rpc:
        def chain_id(self):
            return 102031

        def block_number(self):
            return 12

        def get_block(self, block):
            return {"hash": h(block), "timestamp": hex(1800000000), "number": hex(block)}

        def get_receipt(self, txhash):
            return receipt

        def get_transaction(self, txhash):
            return {"blockHash": h(5), "to": contracts["CreditFacilityManager"], "input": calldata}

    return (
        Rpc(),
        deployment,
        manifest,
        {"receipts": [copy.deepcopy(receipt)]},
        Views(),
        answers,
        receipt,
    )


def test_bootstrap_preserves_actual_ledger_but_never_creates_economic_evidence(
    migrated_db_url, fixture
):
    rpc, deployment, manifest, setup, views, _, _ = fixture
    engine = create_engine(migrated_db_url)
    try:
        first = bootstrap(engine, rpc, deployment, manifest, setup, views=views)
        assert bootstrap(engine, rpc, deployment, manifest, setup, views=views) == first
        with Session(engine) as s:
            assert s.scalar(select(Borrower.kyc_status)) == "PENDING"
            assert s.scalar(select(ControlAgreement.control_grade)) == "E0"
            assert (
                s.scalar(select(ControlAgreement.observation_provenance))["source"] == "SIMULATED"
            )
            assert s.scalar(select(Facility.principal)) == 123
            assert s.scalar(select(Provider.environment_status)) == "PROBED"
            assert s.scalar(select(FacilityBinding.binding_tx_hash)) == h(123)
            for model in (ProofRequest, EvidenceConsumption, CashReceipt, ApiRole):
                assert s.scalar(select(func.count()).select_from(model)) == 0
    finally:
        engine.dispose()


@pytest.mark.parametrize("bad", ["wallet", "token", "profile", "receipt", "reorg", "terms"])
def test_bootstrap_rejects_unbound_or_noncanonical_identity(fixture, bad):
    rpc, deployment, manifest, setup, views, answers, receipt = fixture
    if bad == "wallet":
        answers[("AccountRegistry", "isWalletOf")] = False
    if bad == "token":
        answers[("GpuTestToken", "testOnly")] = False
    if bad == "profile":
        deployment["executionProfile"] = "PRODUCTION"
    if bad == "receipt":
        receipt["status"] = "0x0"
    if bad == "reorg":
        receipt["blockHash"] = h(999)
    if bad == "terms":
        answers[("DebtLedger", "terms")]["loanAsset"]["token"] = "0x" + "ff" * 20
    with pytest.raises(ValueError):
        inspect_setup(rpc, deployment, manifest, setup, views=views)
