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
    assert len(files) == 31, [f.name for f in files]  # 16 interfaces + 4 GPU-030 + GPU-078/031/033/032/077/034/037/036 + 3 GPU-035 impls
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
    assert {"NativeVerificationFailed", "MalformedEncoding", "ProviderNotAdmitted", "MockNotAllowedInProfile"} <= vnames
    native = json.loads((ABI_DIR / "AttestcoinRevenueVerifier.json").read_text())
    nnames = {e.get("name") for e in native}
    assert vnames - {None} <= nnames  # implements the whole interface surface
    # no signature / admin / SPV fallback entry points on the native adapter (R2-D03)
    assert not {"verifyWithSignature", "adminAccept", "setResult", "forceVerified", "verifySpv"} & nnames
    book = json.loads((ABI_DIR / "IEvidenceBook.json").read_text())
    bnames = {e.get("name") for e in book}
    assert {"consume", "isConsumed", "economicEventSeen", "firstSourceEventOf"} <= bnames
    consume = next(e for e in book if e.get("name") == "consume")
    # the book verifies natively itself: the only event input is an untrusted proof envelope, never a caller-built event
    assert [i["name"] for i in consume["inputs"]] == ["providerId", "envelope", "expectedEmitter", "topic0s", "instructions"]
    ledger = json.loads((ABI_DIR / "DebtLedger.json").read_text())
    lnames = {e.get("name") for e in ledger}
    assert {"open", "accrue", "setRate", "recordDraw", "recordFee", "allocate", "freezeAccrual", "capitalize", "legalDebtAt"} <= lnames
    assert "forgiveDebt" not in lnames and "resetAccrual" not in lnames
    control = json.loads((ABI_DIR / "ControlRegistry.json").read_text())
    cnames = {e.get("name") for e in control}
    assert {"createAgreement", "bumpVersion", "observe", "revoke", "release", "isEffective", "isFresh"} <= cnames
    # no proof/lock-event input and no automatic E2 promotion path on the control registry (R2)
    assert not {"recordLockProof", "promoteToE2", "setGradeFromProof"} & cnames
    escrow = json.loads((ABI_DIR / "SourceEscrow.json").read_text())
    enames = {e.get("name") for e in escrow}
    assert {"settle", "recognizeObligation", "correctObligation", "anchorStatement", "partnerSourceBinding"} <= enames
    assert "notify" not in enames and "reportBalance" not in enames  # no arbitrary notify(amount) path (GPU-077)
    topic_fixture = json.loads((REPO / "test" / "fixtures" / "gpu" / "attestcoin" / "source-events-v1.abi.json").read_text())
    escrow_events = {e["name"]: e for e in escrow if e.get("type") == "event"}
    for ev in topic_fixture["events"]:
        assert ev["name"] in escrow_events, ev["name"]
        sig = ev["name"] + "(" + ",".join(i["type"] for i in escrow_events[ev["name"]]["inputs"]) + ")"
        assert sig == ev["signature"], sig
    vault = json.loads((ABI_DIR / "LendingVaultV2.json").read_text())
    vnames2 = {e.get("name") for e in vault}
    assert {"deposit", "withdraw", "totalAssets", "lend", "onRepayment", "recognizeImpairment"} <= vnames2
    assert not {"setRate", "rateBps", "accrue", "grantTestnetCredit"} & vnames2  # no vault-side interest math (AR-02)
    book_r = json.loads((ABI_DIR / "ReceivableBook.json").read_text())
    rnames = {e.get("name") for e in book_r}
    assert "ingest" in rnames and not {"setUnpaid", "recognizeDirect", "registerReceivable"} & rnames  # balances only via EvidenceBook
    policy = json.loads((ABI_DIR / "GpuRiskPolicy.json").read_text())
    assert "CapNotSet" in {e.get("name") for e in policy}  # cap=0 is never an unlimited sentinel
    escrow_r = json.loads((ABI_DIR / "RevenueEscrow.json").read_text())
    ernames = {e.get("name") for e in escrow_r}
    assert {"sweep", "release"} & ernames or {"sweepPayout", "release"} & ernames
    assert not {"execute", "approveToken", "setModule", "allocate", "repayFor"} & ernames  # no admin bypass, no ledger writes
    mgr_impl = json.loads((ABI_DIR / "CreditFacilityManager.json").read_text())
    mnames = {e.get("name") for e in mgr_impl}
    assert {"borrow", "repayFor", "anchorAuthorization", "pauseDraws"} <= mnames
    assert not {"pauseRepayments", "grantTestnetCredit", "increaseLimit", "borrowTo"} & mnames
    borrow = next(e for e in mgr_impl if e.get("name") == "borrow")
    assert [i["name"] for i in borrow["inputs"]] == ["facilityId", "amount", "minReceived"]  # recipient is never a parameter
    import filecmp
    assert filecmp.cmp(REPO / "config" / "gpu" / "schema" / "facility-transitions-v1.json", REPO / "test" / "fixtures" / "gpu" / "facility-transitions-v1.json", shallow=False)
    impl_book = json.loads((ABI_DIR / "EvidenceBook.json").read_text())
    inames = {e.get("name") for e in impl_book}
    assert bnames - {None} <= inames
    assert not {"recordEvent", "adminRecord", "consumeSigned", "registerEvidence"} & inames


def test_enum_fixture_matches_domain_schema():
    enums = json.loads(ENUMS.read_text())["enums"]
    defs = json.loads(SCHEMA.read_text())["$defs"]
    for name in ("ExecutionProfile", "VerificationMethod", "NativeStatus", "EarningsProvenance", "ControlGrade", "CashState", "FacilityState", "Trust", "EvidenceMeaning"):
        assert enums[name] == defs[name]["enum"], name
    assert enums["AssertionPurpose"] == ["WALLET_LINK", "AGREEMENT_CONSENT", "CREDIT_APPROVAL", "CONTROL_ATTESTATION", "RELAY", "TREASURY_OP"]
