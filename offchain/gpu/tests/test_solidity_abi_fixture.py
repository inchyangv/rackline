"""
GPU-029: Solidity/Python shared fixtures — vendored official files are byte-pinned, exported interface ABIs
carry no Bitcoin-era fields, and the enum fixture used by the Solidity parity test equals the domain schema.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
VENDOR = REPO / "contracts" / "gpu" / "vendor" / "attestcoin"
ABI_DIR = REPO / "test" / "fixtures" / "gpu" / "abi"
ENUMS = REPO / "test" / "fixtures" / "gpu" / "enums-v1.json"
SCHEMA = REPO / "config" / "gpu" / "schema" / "domain-v1.schema.json"

PINNED = {
    "common/EvmV1Decoder.sol": "2de1a8faf7b203c33a08db73e7a79e0523c4a84580c9c75ce209df0d5bf2e692",
    "write-ability/common/INativeQueryVerifier.sol": "bc81982eb4070d3a5519346c868c73eff177b7c514ef2befae6cadfe9cddd1ed",
    "write-ability/common/BlockProverTypes.sol": "7f2f5aecf619566a154341c75481fc2a6b3e749e021070d59bc26112c8a47b43",
}
BTC_WORDS = ("sats", "txid", "vout", "btc", "bitcoin", "pubkeyhash", "checkpointmanager", "spv")


def test_vendored_official_files_are_byte_pinned():
    for rel, sha in PINNED.items():
        assert hashlib.sha256((VENDOR / rel).read_bytes()).hexdigest() == sha, rel
    manifest = (VENDOR / "VENDORED.md").read_text()
    for sha in PINNED.values():
        assert sha in manifest


def test_interface_abis_have_no_btc_fields_and_expected_surface():
    files = sorted(ABI_DIR.glob("*.json"))
    assert len(files) == 13, [f.name for f in files]
    for f in files:
        abi = json.loads(f.read_text())
        text = json.dumps(abi).lower()
        for w in BTC_WORDS:
            assert w not in text, f"{f.name} contains {w}"
    manager = json.loads((ABI_DIR / "ICreditFacilityManager.json").read_text())
    names = {e.get("name") for e in manager}
    assert {"borrow", "repayFor", "pauseDraws", "anchorAuthorization", "evaluateDraw"} <= names
    assert "pauseRepayments" not in names and "grantTestnetCredit" not in names
    repay = next(e for e in manager if e.get("name") == "repayFor")
    out = repay["outputs"][0]["components"]
    assert [c["name"] for c in out] == ["requested", "received", "applied", "feePaid", "interestPaid", "principalPaid", "excess", "newDebt"]
    verifier = json.loads((ABI_DIR / "IRevenueVerifier.json").read_text())
    vnames = {e.get("name") for e in verifier}
    assert "verifyAndExtract" in vnames and "verifySingle" not in vnames
    book = json.loads((ABI_DIR / "IEvidenceBook.json").read_text())
    assert {"consume", "isConsumed", "economicEventSeen"} <= {e.get("name") for e in book}


def test_enum_fixture_matches_domain_schema():
    enums = json.loads(ENUMS.read_text())["enums"]
    defs = json.loads(SCHEMA.read_text())["$defs"]
    for name in ("ExecutionProfile", "VerificationMethod", "NativeStatus", "EarningsProvenance", "ControlGrade", "CashState", "FacilityState", "Trust", "EvidenceMeaning"):
        assert enums[name] == defs[name]["enum"], name
    assert enums["AssertionPurpose"] == ["WALLET_LINK", "AGREEMENT_CONSENT", "CREDIT_APPROVAL", "CONTROL_ATTESTATION", "RELAY", "TREASURY_OP"]
