"""Self-test for the read-only legacy inventory tool. Runs against a synthetic recorded-RPC fixture
(no network): classification candidate → liveConfirmed / noCode / unreachable, sum-check discrepancy
reporting, legacy provenance labels, and RPC URL redaction.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from eth_abi import encode as abi_encode

sys.path.insert(0, str(Path(__file__).resolve().parent))
import inventory_legacy as inv  # noqa: E402

MGR = "0x593e140982cDC040d69B7E7623A045C6d6Ca2055"
VAULT = "0x4d74126369BacB67085a1E70d535cA15515d1AFa"
TOKEN = "0xb9D6E174C8e0267Fb0cC3F2AC34130D680151B6A"
BORROWER = "0xA20Eb21DE5AE396E9c8Cc6DE719E9593bF6705cE"
LP = "0x00000000000000000000000000000000000000A1"
BLOCK = 5_000_000


def _enc(types: list[str], values: list) -> str:
    return "0x" + abi_encode(types, values).hex()


def _call_key(to: str, data: str, block: str) -> str:
    return inv.Rpc._key("eth_call", [{"to": to, "data": data}, block])


def _view(to: str, sig: str, types_out: list[str], values: list, block: str, args_hex: str = "") -> tuple[str, dict]:
    return _call_key(to, inv.selector(sig) + args_hex, block), {"result": _enc(types_out, values)}


def build_fixture(*, mgr_total_debt: int = 400_000_000, vault_total_shares: int = 1_000_000, holder_shares: int = 1_000_000) -> dict:
    """Synthetic v1 state: one borrower with principal 400 USDC, one LP; manager/vault/token live, others noCode."""
    b = hex(BLOCK)
    responses: dict[str, dict] = {
        inv.Rpc._key("eth_chainId", []): {"result": hex(102031)},
        inv.Rpc._key("eth_getBlockByNumber", [b, False]): {"result": {"hash": "0x" + "ab" * 32, "timestamp": hex(1_800_000_000)}},
    }
    live = {MGR: "0x6080" + "00" * 30, VAULT: "0x6080" + "11" * 30, TOKEN: "0x6080" + "22" * 30}
    for c in inv.DEFAULT_CANDIDATES:
        addr = inv.to_checksum_address(c["address"])
        responses[inv.Rpc._key("eth_getCode", [addr, b])] = {"result": live.get(addr, "0x")}
    for name, sig, tout, val in [
        ("m", "owner()", ["address"], ["0x00000000000000000000000000000000000000AD"]),
        ("m", "paused()", ["bool"], [False]),
        ("m", "verifier()", ["address"], ["0x16DEd6a617a911471cd4549C24Ed8C281f096fd2"]),
        ("m", "vault()", ["address"], [VAULT]),
        ("m", "riskConfig()", ["address"], ["0x22b0dE27CA4fee800a3Bc86D92eB1F62B6050Ad7"]),
        ("m", "poolRegistry()", ["address"], ["0xdc784DE44A28D59c881eae6E64668eAb15057584"]),
        ("m", "stablecoin()", ["address"], [TOKEN]),
        ("m", "totalGlobalDebt()", ["uint256"], [mgr_total_debt]),
        ("m", "autoGrantCreditAmount()", ["uint128"], [0]),
        ("v", "owner()", ["address"], ["0x00000000000000000000000000000000000000AD"]),
        ("v", "manager()", ["address"], [MGR]),
        ("v", "asset()", ["address"], [TOKEN]),
        ("v", "totalShares()", ["uint256"], [vault_total_shares]),
        ("v", "totalBorrowed()", ["uint256"], [400_000_000]),
        ("v", "totalAssets()", ["uint256"], [1_000_000_000]),
        ("v", "availableLiquidity()", ["uint256"], [600_000_000]),
        ("v", "accumulatedInterest()", ["uint256"], [0]),
        ("v", "lastAccrualTimestamp()", ["uint256"], [1_799_000_000]),
        ("v", "fixedBorrowAPRBps()", ["uint256"], [1000]),
        ("t", "totalSupply()", ["uint256"], [10_000_000_000]),
        ("t", "decimals()", ["uint8"], [6]),
        ("t", "symbol()", ["string"], ["mUSDT"]),
    ]:
        to = {"m": MGR, "v": VAULT, "t": TOKEN}[name]
        k, v = _view(to, sig, tout, val, b)
        responses[k] = v
    # logs: one Borrowed for BORROWER, one Deposited for LP, nothing else, in one range [0, BLOCK]
    def log_key(addr: str, sig: str, start: int, end: int) -> str:
        return inv.Rpc._key("eth_getLogs", [{"address": addr, "topics": [inv.topic(sig)], "fromBlock": hex(start), "toBlock": hex(end)}])

    start = 0
    while start <= BLOCK:
        end = min(start + inv.LOG_RANGE - 1, BLOCK)
        for sig in ("BorrowerRegistered(address,bytes32,uint64)", "Borrowed(address,uint256,uint128)", "Repaid(address,uint256,uint128)", "PayoutRecorded(address,bytes32,uint32,uint64,uint32,uint128)"):
            responses[log_key(MGR, sig, start, end)] = {"result": []}
        for sig in ("Deposited(address,uint256,uint256)", "Withdrawn(address,uint256,uint256)"):
            responses[log_key(VAULT, sig, start, end)] = {"result": []}
        start = end + 1
    responses[log_key(MGR, "Borrowed(address,uint256,uint128)", 0, inv.LOG_RANGE - 1)] = {
        "result": [{"address": MGR.lower(), "topics": [inv.topic("Borrowed(address,uint256,uint128)"), "0x" + BORROWER[2:].lower().rjust(64, "0")], "data": "0x"}]
    }
    responses[log_key(MGR, "PayoutRecorded(address,bytes32,uint32,uint64,uint32,uint128)", 0, inv.LOG_RANGE - 1)] = {
        "result": [{"address": MGR.lower(), "topics": [inv.topic("PayoutRecorded(address,bytes32,uint32,uint64,uint32,uint128)"), "0x" + BORROWER[2:].lower().rjust(64, "0"), "0x" + "cd" * 32], "data": "0x"}]
    }
    responses[log_key(VAULT, "Deposited(address,uint256,uint256)", 0, inv.LOG_RANGE - 1)] = {
        "result": [{"address": VAULT.lower(), "topics": [inv.topic("Deposited(address,uint256,uint256)"), "0x" + LP[2:].lower().rjust(64, "0")], "data": "0x"}]
    }
    arg = abi_encode(["address"], [BORROWER]).hex()
    info = (1, b"\x11" * 32, 40_000_000, 40_000_000, 10_000_000_000, 400_000_000, 1_790_000_000, 1_780_000_000, 1, 1_790_000_000)
    responses[_call_key(MGR, inv.selector("getBorrowerInfo(address)") + arg, b)] = {"result": _enc([inv.BORROWER_INFO_TYPES], [info])}
    responses[_call_key(MGR, inv.selector("getCurrentDebt(address)") + arg, b)] = {"result": _enc(["uint256"], [440_000_000])}
    responses[_call_key(MGR, inv.selector("getAccruedInterest(address)") + arg, b)] = {"result": _enc(["uint256"], [40_000_000])}
    responses[_call_key(MGR, inv.selector("getPayoutHistoryCount(address)") + arg, b)] = {"result": _enc(["uint256"], [1])}
    responses[_call_key(VAULT, inv.selector("sharesOf(address)") + abi_encode(["address"], [LP]).hex(), b)] = {"result": _enc(["uint256"], [holder_shares])}
    responses[_call_key(TOKEN, inv.selector("balanceOf(address)") + abi_encode(["address"], [VAULT]).hex(), b)] = {"result": _enc(["uint256"], [600_000_000])}
    return {"rpcHost": "fixture.invalid", "responses": responses}


def run(fixture: dict) -> dict:
    rpc = inv.Rpc(None, fixture=fixture)
    return inv.inventory(rpc, inv.DEFAULT_CANDIDATES, BLOCK, 0)


def test_classification_candidate_live_nocode():
    snap = run(build_fixture())
    status = {c["name"]: c["status"] for c in snap["contracts"]}
    assert status["HashCreditManager"] == "liveConfirmed"
    assert status["LendingVault"] == "liveConfirmed"
    assert status["TestnetMintableERC20"] == "liveConfirmed"
    assert status["CheckpointManager"] == "noCode" and status["RiskConfig"] == "noCode"
    mgr = next(c for c in snap["contracts"] if c["name"] == "HashCreditManager")
    assert mgr["candidateSource"] == "apps/web/src/lib/env.ts legacy defaults"
    assert mgr["codeKeccak256"].startswith("0x") and mgr["codeSize"] == 32
    assert snap["blockNumber"] == BLOCK and snap["blockHash"] == "0x" + "ab" * 32


def test_borrowers_and_sum_checks_pass_when_consistent():
    snap = run(build_fixture())
    assert len(snap["borrowers"]) == 1
    b = snap["borrowers"][0]
    assert b["borrower"] == BORROWER and b["status"] == "Active"
    assert b["currentDebt(principal, v1)"] == "400000000" and b["getAccruedInterest(v1)"] == "40000000"
    assert "AR-01" in b["provenanceOfInterestValues"]
    assert b["events"] == {"borrowed": 1, "repaid": 0, "payoutRecorded": 1}
    assert all(s["ok"] for s in snap["sumChecks"]), snap["sumChecks"]
    assert snap["lp"]["shareHolders"] == {LP: "1000000"} and snap["lp"]["vaultTokenBalance"] == "600000000"


def test_sum_check_discrepancy_is_reported_not_corrected():
    snap = run(build_fixture(mgr_total_debt=999_000_000, holder_shares=900_000))
    debt = next(s for s in snap["sumChecks"] if s["check"].startswith("sum(borrower"))
    assert debt["ok"] is False and debt["lhs"] == "400000000" and debt["rhs"] == "999000000"
    shares = next(s for s in snap["sumChecks"] if "sharesOf" in s["check"])
    assert shares["ok"] is False and shares["lhs"] == "900000" and shares["rhs"] == "1000000"
    # values are untouched
    assert snap["borrowers"][0]["currentDebt(principal, v1)"] == "400000000"
    mgr = next(c for c in snap["contracts"] if c["name"] == "HashCreditManager")
    assert mgr["reads"]["totalGlobalDebt"] == "999000000"


def test_legacy_provenance_never_native():
    snap = run(build_fixture())
    pe = snap["processedEvidence"]
    assert pe["provenance"] == "LEGACY_BTC_SPV" and pe["btcAddressLinkProvenance"] == "LEGACY_RELAYER_SIG"
    assert pe["payoutRecordedEvents"] == 1 and pe["distinctTxids"] == 1
    text = json.dumps(snap)
    for forbidden in ("ATTESTCOIN_NATIVE", '"VERIFIED"', "NATIVE_ACCEPTED"):
        assert forbidden not in text
    md = inv.render_markdown(snap)
    assert "LEGACY_BTC_SPV" in md and "Open testnet position assessment" in md
    assert "Known v1 interest defects" in md
    assert "open v1 positions exist" in md


def test_unreachable_rpc_is_reported_honestly(tmp_path: Path):
    out = tmp_path / "snap.json"
    rc = inv.main(["--rpc", "https://rpc.invalid.localhost/v1/secret-token-123?key=abc", "--out", str(out)])
    assert rc == 3
    snap = json.loads(out.read_text())
    assert snap["status"] == "unreachable" and all(c["status"] == "unreachable" for c in snap["contracts"])
    assert snap["rpcHost"] == "rpc.invalid.localhost"
    assert "secret-token-123" not in out.read_text() and "key=abc" not in out.read_text()


def test_rpc_url_redaction():
    assert inv.redact_rpc("https://user:pw@rpc.example.com/v1/abcdef?apikey=zzz") == "rpc.example.com"
    assert inv.redact_rpc("not a url") == "unknown"


def test_recorded_live_fixture_if_present():
    """If the recorded CC3 testnet fixture exists, the offline replay must reproduce the committed snapshot."""
    root = Path(__file__).resolve().parents[2]
    fx = root / "test" / "gpu" / "inventory" / "rpc-fixtures-complete.json"
    snapshot = root / "evidence" / "legacy" / "102031-5484137.json"
    if not fx.exists() or not snapshot.exists():
        pytest.fail("recorded fixture / committed snapshot missing")
    fixture = json.loads(fx.read_text())
    committed = json.loads(snapshot.read_text())
    rpc = inv.Rpc(None, fixture=fixture)
    snap = inv.inventory(rpc, inv.DEFAULT_CANDIDATES, committed["blockNumber"], committed["scannedFromBlock"] if "scannedFromBlock" in committed else committed["processedEvidence"]["scannedFromBlock"])
    for k in ("chainId", "blockNumber", "blockHash", "contracts", "borrowers", "lp", "processedEvidence", "sumChecks"):
        assert snap[k] == committed[k], k
    assert "secret" not in fx.read_text().lower()
