#!/usr/bin/env python3
"""Read-only inventory of the legacy (v1, BTC/SPV) deployment.

Reads a pinned block and, for each candidate address, code size/hash, owner/pause/wiring, borrower state
(enumerated from `BorrowerRegistered` / `Borrowed` / `Repaid` logs), vault totals, token balances and the
number of processed payout claims. Every value is reported **as the v1 contracts report it**; nothing is
corrected. Known v1 interest defects are flagged, never fixed here.

Only `eth_chainId`, `eth_getBlockByNumber`, `eth_getCode`, `eth_call`, `eth_getLogs` are used. No key,
no transaction. RPC URLs are reduced to hostnames in every output.

    inventory_legacy.py --rpc <url> --out <snapshot.json> [--block <n>] [--candidates <json>]
    inventory_legacy.py --offline-fixture <recorded.json> --out <snapshot.json>
    inventory_legacy.py --rpc <url> --record <recorded.json> ...   (also records responses for offline runs)

Provenance labels for legacy evidence are fixed to LEGACY_BTC_SPV / LEGACY_RELAYER_SIG and can never be
ATTESTCOIN_NATIVE / VERIFIED.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from eth_abi import decode as abi_decode
from eth_abi import encode as abi_encode
from eth_utils import keccak, to_checksum_address

SCHEMA_VERSION = 1
LEGACY_PROVENANCE = {"payoutClaims": "LEGACY_BTC_SPV", "btcAddressLinks": "LEGACY_RELAYER_SIG"}
FORBIDDEN_PROVENANCE = {"ATTESTCOIN_NATIVE", "VERIFIED", "NATIVE_ACCEPTED"}
LOG_RANGE = 5_000  # blocks per eth_getLogs request
AR_DEFECTS = ["AR-01", "AR-02", "AR-03", "AR-04"]  # interest/ledger defects that taint reported values

# Candidate addresses and their repository provenance (never discovered from chain state).
DEFAULT_CANDIDATES: list[dict[str, str]] = [
    {"name": "HashCreditManager", "address": "0x593e140982cDC040d69B7E7623A045C6d6Ca2055", "source": "apps/web/src/lib/env.ts legacy defaults"},
    {"name": "LendingVault", "address": "0x4d74126369BacB67085a1E70d535cA15515d1AFa", "source": "apps/web/src/lib/env.ts legacy defaults"},
    {"name": "CheckpointManager", "address": "0x4Ae5418242073cd37CCc69C908957E413a04f6f9", "source": "archived DeploySpv artifact"},
    {"name": "BtcSpvVerifier", "address": "0x16DEd6a617a911471cd4549C24Ed8C281f096fd2", "source": "apps/web/src/lib/env.ts legacy defaults"},
    {"name": "TestnetMintableERC20", "address": "0xb9D6E174C8e0267Fb0cC3F2AC34130D680151B6A", "source": "apps/web/src/lib/env.ts legacy defaults"},
    {"name": "RiskConfig", "address": "0x22b0de27ca4fee800a3bc86d92eb1f62b6050ad7", "source": "archived DeploySpv artifact"},
    {"name": "PoolRegistry", "address": "0xdc784de44a28d59c881eae6e64668eab15057584", "source": "archived DeploySpv artifact"},
]

# Legacy ABI surface (from contracts/*.sol at the baseline commit). name -> (types_in, types_out)
VIEWS: dict[str, dict[str, tuple[list[str], list[str]]]] = {
    "HashCreditManager": {
        "owner": ([], ["address"]),
        "paused": ([], ["bool"]),
        "verifier": ([], ["address"]),
        "vault": ([], ["address"]),
        "riskConfig": ([], ["address"]),
        "poolRegistry": ([], ["address"]),
        "stablecoin": ([], ["address"]),
        "totalGlobalDebt": ([], ["uint256"]),
        "autoGrantCreditAmount": ([], ["uint128"]),
    },
    "LendingVault": {
        "owner": ([], ["address"]),
        "manager": ([], ["address"]),
        "asset": ([], ["address"]),
        "totalShares": ([], ["uint256"]),
        "totalBorrowed": ([], ["uint256"]),
        "totalAssets": ([], ["uint256"]),
        "availableLiquidity": ([], ["uint256"]),
        "accumulatedInterest": ([], ["uint256"]),
        "lastAccrualTimestamp": ([], ["uint256"]),
        "fixedBorrowAPRBps": ([], ["uint256"]),
    },
    "CheckpointManager": {"owner": ([], ["address"]), "latestCheckpointHeight": ([], ["uint32"])},
    "BtcSpvVerifier": {"owner": ([], ["address"])},
    "TestnetMintableERC20": {"totalSupply": ([], ["uint256"]), "decimals": ([], ["uint8"]), "symbol": ([], ["string"])},
    "RiskConfig": {"owner": ([], ["address"]), "globalCap": ([], ["uint128"]), "advanceRateBps": ([], ["uint32"]), "windowSeconds": ([], ["uint32"])},
    "PoolRegistry": {},
}
BORROWER_INFO_TYPES = "(uint8,bytes32,uint128,uint128,uint128,uint128,uint64,uint64,uint32,uint64)"
EVENTS = {
    "BorrowerRegistered": "BorrowerRegistered(address,bytes32,uint64)",
    "Borrowed": "Borrowed(address,uint256,uint128)",
    "Repaid": "Repaid(address,uint256,uint128)",
    "PayoutRecorded": "PayoutRecorded(address,bytes32,uint32,uint64,uint32,uint128)",
    "Deposited": "Deposited(address,uint256,uint256)",
    "Withdrawn": "Withdrawn(address,uint256,uint256)",
}


def selector(sig: str) -> str:
    return "0x" + keccak(text=sig)[:4].hex()


def topic(sig: str) -> str:
    return "0x" + keccak(text=sig).hex()


def redact_rpc(url: str) -> str:
    """Only the hostname survives (tokens in path/query/userinfo are dropped)."""
    try:
        return urlsplit(url).hostname or "unknown"
    except ValueError:
        return "unknown"


class RpcError(RuntimeError):
    pass


class Rpc:
    """Minimal JSON-RPC client with optional recording (for offline fixtures) or replay."""

    def __init__(self, url: str | None, fixture: dict[str, Any] | None = None, record: bool = False):
        from threading import Lock
        self.url = url
        self.host = redact_rpc(url) if url else (fixture or {}).get("rpcHost", "fixture")
        self.fixture = fixture
        self.record = record
        self.recorded: dict[str, Any] = {"rpcHost": self.host, "responses": {}}
        self.record_path = None
        self.record_lock = Lock()

    @staticmethod
    def _key(method: str, params: list[Any]) -> str:
        return method + ":" + json.dumps(params, separators=(",", ":"), sort_keys=True)

    def call(self, method: str, params: list[Any]) -> Any:
        key = self._key(method, params)
        if self.record_path and key in self.recorded["responses"] and "result" in self.recorded["responses"][key]:
            return self.recorded["responses"][key]["result"]
        if self.fixture is not None:
            if key not in self.fixture["responses"]:
                raise RpcError(f"fixture has no response for {method} {params}")
            entry = self.fixture["responses"][key]
            if "error" in entry:
                raise RpcError(entry["error"])
            return entry["result"]
        assert self.url
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
        req = urllib.request.Request(self.url, data=body, headers={"content-type": "application/json"})
        import time
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - allowlisted https RPC
                    payload = json.loads(resp.read())
                break
            except Exception as e:  # noqa: BLE001
                if attempt == 2:
                    raise RpcError(f"{method} failed against {self.host}: {type(e).__name__}") from e
                time.sleep(0.5 * (attempt + 1))
        if "error" in payload:
            err = str(payload["error"])
            if self.record:
                self.recorded["responses"][key] = {"error": err}
            raise RpcError(f"{method}: {err}")
        if self.record:
            with self.record_lock:
                self.recorded["responses"][key] = {"result": payload["result"]}
                if self.record_path:
                    Path(self.record_path).write_text(json.dumps(self.recorded, indent=2) + "\n")
        return payload["result"]

    def eth_call(self, to: str, sig: str, args: list[Any], types_in: list[str], types_out: list[str], block: str) -> tuple[Any, ...]:
        data = selector(sig) + (abi_encode(types_in, args).hex() if types_in else "")
        raw = self.call("eth_call", [{"to": to, "data": data}, block])
        if raw in ("0x", None):
            raise RpcError(f"{sig}: empty return")
        return abi_decode(types_out, bytes.fromhex(raw[2:]))


@dataclass
class ContractInventory:
    name: str
    addressCandidate: str
    candidateSource: str
    status: str = "candidate"  # candidate | liveConfirmed | noCode | unreachable
    codeSize: int = 0
    codeKeccak256: str | None = None
    reads: dict[str, Any] = field(default_factory=dict)
    readErrors: dict[str, str] = field(default_factory=dict)


def hex_block(n: int) -> str:
    return hex(n)


def get_logs(rpc: Rpc, address: str, topic0: str, from_block: int, to_block: int) -> list[dict[str, Any]]:
    """Bounded parallel read-only scan; slow archive ranges split without omitting any block."""
    from concurrent.futures import ThreadPoolExecutor

    def read(bounds):
        start, end = bounds
        try:
            return rpc.call("eth_getLogs", [{"address": address, "topics": [topic0], "fromBlock": hex_block(start), "toBlock": hex_block(end)}])
        except RpcError as e:
            if "timeout" in str(e).lower() and end - start + 1 > 256:
                midpoint = (start + end) // 2
                return read((start, midpoint)) + read((midpoint + 1, end))
            raise
    ranges = [(start, min(start + LOG_RANGE - 1, to_block)) for start in range(from_block, to_block + 1, LOG_RANGE)]
    with ThreadPoolExecutor(max_workers=4) as workers:
        return [entry for chunk in workers.map(read, ranges) for entry in chunk]


def jsonable(v: Any) -> Any:
    if isinstance(v, bytes):
        return "0x" + v.hex()
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    if isinstance(v, int) and not isinstance(v, bool):
        return str(v)  # money/uint values as strings (JSON numbers lose precision)
    return v


def inventory(rpc: Rpc, candidates: list[dict[str, str]], block_number: int | None, deploy_block: int) -> dict[str, Any]:
    chain_id = int(rpc.call("eth_chainId", []), 16)
    if block_number is None:
        block_number = int(rpc.call("eth_blockNumber", []), 16)
    blk = rpc.call("eth_getBlockByNumber", [hex_block(block_number), False])
    block_tag = hex_block(block_number)
    snapshot: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "LEGACY_READ_ONLY_INVENTORY",
        "chainId": chain_id,
        "rpcHost": rpc.host,
        "blockNumber": block_number,
        "blockHash": blk["hash"],
        "timestamp": int(blk["timestamp"], 16),
        "contracts": [],
        "borrowers": [],
        "lp": {},
        "processedEvidence": {},
        "sumChecks": [],
        "notes": [
            "Values are as reported by the v1 contracts at the pinned block; nothing is corrected.",
            "Interest-bearing values are tainted by known v1 defects " + ", ".join(AR_DEFECTS) + ".",
            "Legacy evidence provenance is LEGACY_BTC_SPV / LEGACY_RELAYER_SIG and is never reclassified as native.",
        ],
    }
    by_name: dict[str, ContractInventory] = {}
    for c in candidates:
        inv = ContractInventory(c["name"], to_checksum_address(c["address"]), c["source"])
        by_name[inv.name] = inv
        try:
            code = rpc.call("eth_getCode", [inv.addressCandidate, block_tag])
        except RpcError as e:
            inv.status = "unreachable"
            inv.readErrors["eth_getCode"] = str(e)
            snapshot["contracts"].append(inv.__dict__)
            continue
        code_bytes = bytes.fromhex(code[2:]) if code and code != "0x" else b""
        inv.codeSize = len(code_bytes)
        if not code_bytes:
            inv.status = "noCode"
            snapshot["contracts"].append(inv.__dict__)
            continue
        inv.codeKeccak256 = "0x" + keccak(code_bytes).hex()
        ok = True
        for fname, (tin, tout) in VIEWS.get(inv.name, {}).items():
            try:
                res = rpc.eth_call(inv.addressCandidate, f"{fname}()", [], tin, tout, block_tag)
                inv.reads[fname] = jsonable(res[0])
            except RpcError as e:
                ok = False
                inv.readErrors[fname] = str(e)
        inv.status = "liveConfirmed" if ok else "partial"
        snapshot["contracts"].append(inv.__dict__)

    mgr = by_name.get("HashCreditManager")
    vault = by_name.get("LendingVault")
    token = by_name.get("TestnetMintableERC20")

    if mgr and mgr.status in ("liveConfirmed", "partial"):
        registered = get_logs(rpc, mgr.addressCandidate, topic(EVENTS["BorrowerRegistered"]), deploy_block, block_number)
        borrowed = get_logs(rpc, mgr.addressCandidate, topic(EVENTS["Borrowed"]), deploy_block, block_number)
        repaid = get_logs(rpc, mgr.addressCandidate, topic(EVENTS["Repaid"]), deploy_block, block_number)
        payouts = get_logs(rpc, mgr.addressCandidate, topic(EVENTS["PayoutRecorded"]), deploy_block, block_number)
        addrs: list[str] = []
        for lg in registered + borrowed + repaid + payouts:
            a = to_checksum_address("0x" + lg["topics"][1][-40:])
            if a not in addrs:
                addrs.append(a)
        sum_principal = 0
        for a in addrs:
            row: dict[str, Any] = {"borrower": a, "provenanceOfInterestValues": "v1-reported, known AR defects apply (" + ", ".join(AR_DEFECTS) + ")"}
            try:
                info = rpc.eth_call(mgr.addressCandidate, "getBorrowerInfo(address)", [a], ["address"], [BORROWER_INFO_TYPES], block_tag)[0]
                row.update({
                    "status": ["None", "Active", "Frozen", "Closed"][info[0]] if info[0] < 4 else str(info[0]),
                    "btcPayoutKeyHash": "0x" + info[1].hex(),
                    "totalRevenueSats": str(info[2]),
                    "trailingRevenueSats": str(info[3]),
                    "creditLimit": str(info[4]),
                    "currentDebt(principal, v1)": str(info[5]),
                    "lastPayoutTimestamp": str(info[6]),
                    "registeredAt": str(info[7]),
                    "payoutCount": str(info[8]),
                    "lastDebtUpdateTimestamp": str(info[9]),
                })
                sum_principal += int(info[5])
                for fname in ("getCurrentDebt", "getAccruedInterest"):
                    row[f"{fname}(v1)"] = str(rpc.eth_call(mgr.addressCandidate, f"{fname}(address)", [a], ["address"], ["uint256"], block_tag)[0])
                row["payoutHistoryCount"] = str(rpc.eth_call(mgr.addressCandidate, "getPayoutHistoryCount(address)", [a], ["address"], ["uint256"], block_tag)[0])
            except RpcError as e:
                row["readError"] = str(e)
            row["events"] = {
                "borrowed": sum(1 for lg in borrowed if lg["topics"][1][-40:].lower() == a[2:].lower()),
                "repaid": sum(1 for lg in repaid if lg["topics"][1][-40:].lower() == a[2:].lower()),
                "payoutRecorded": sum(1 for lg in payouts if lg["topics"][1][-40:].lower() == a[2:].lower()),
            }
            snapshot["borrowers"].append(row)
        snapshot["processedEvidence"] = {
            "payoutRecordedEvents": len(payouts),
            "distinctTxids": len({lg["topics"][2] for lg in payouts}),
            "provenance": LEGACY_PROVENANCE["payoutClaims"],
            "btcAddressLinkProvenance": LEGACY_PROVENANCE["btcAddressLinks"],
            "nativeStatus": "NOT_APPLICABLE_LEGACY",
            "scannedFromBlock": deploy_block,
        }
        total_global = int(mgr.reads.get("totalGlobalDebt", "0"))
        snapshot["sumChecks"].append({
            "check": "sum(borrower currentDebt) == manager.totalGlobalDebt",
            "lhs": str(sum_principal),
            "rhs": str(total_global),
            "ok": sum_principal == total_global,
            "note": "discrepancy is reported, not corrected",
        })

    if vault and vault.status in ("liveConfirmed", "partial"):
        deposits = get_logs(rpc, vault.addressCandidate, topic(EVENTS["Deposited"]), deploy_block, block_number)
        withdrawals = get_logs(rpc, vault.addressCandidate, topic(EVENTS["Withdrawn"]), deploy_block, block_number)
        holders: list[str] = []
        for lg in deposits + withdrawals:
            a = to_checksum_address("0x" + lg["topics"][1][-40:])
            if a not in holders:
                holders.append(a)
        shares: dict[str, str] = {}
        sum_shares = 0
        for h in holders:
            try:
                s = rpc.eth_call(vault.addressCandidate, "sharesOf(address)", [h], ["address"], ["uint256"], block_tag)[0]
            except RpcError:
                continue
            shares[h] = str(s)
            sum_shares += int(s)
        token_balance: str | None = None
        if token and token.status in ("liveConfirmed", "partial"):
            try:
                token_balance = str(rpc.eth_call(token.addressCandidate, "balanceOf(address)", [vault.addressCandidate], ["address"], ["uint256"], block_tag)[0])
            except RpcError as e:
                vault.readErrors["token.balanceOf(vault)"] = str(e)
        snapshot["lp"] = {
            "totalShares": vault.reads.get("totalShares"),
            "totalAssets(v1)": vault.reads.get("totalAssets"),
            "totalBorrowed(v1)": vault.reads.get("totalBorrowed"),
            "accumulatedInterest(v1)": vault.reads.get("accumulatedInterest"),
            "availableLiquidity(v1)": vault.reads.get("availableLiquidity"),
            "vaultTokenBalance": token_balance,
            "depositEvents": len(deposits),
            "withdrawEvents": len(withdrawals),
            "shareHolders": shares,
        }
        total_shares = int(vault.reads.get("totalShares", "0") or 0)
        snapshot["sumChecks"].append({
            "check": "sum(sharesOf(event holders)) == vault.totalShares",
            "lhs": str(sum_shares),
            "rhs": str(total_shares),
            "ok": sum_shares == total_shares,
            "note": "holders enumerated from Deposited/Withdrawn logs; a mismatch means transfers/unknown holders, reported only",
        })
        if token_balance is not None and vault.reads.get("totalBorrowed") is not None:
            lhs = int(token_balance) + int(vault.reads["totalBorrowed"]) + int(vault.reads.get("accumulatedInterest", "0") or 0)
            rhs = int(vault.reads.get("totalAssets", "0") or 0)
            snapshot["sumChecks"].append({
                "check": "token.balanceOf(vault) + totalBorrowed + accumulatedInterest == vault.totalAssets (v1 definition)",
                "lhs": str(lhs),
                "rhs": str(rhs),
                "ok": lhs == rhs,
                "note": "v1 totalAssets definition; AR-02 applies to totalBorrowed",
            })
    for c in snapshot["contracts"]:
        for v in c.get("reads", {}).values():
            assert str(v) not in FORBIDDEN_PROVENANCE
    return snapshot


def render_markdown(snap: dict[str, Any]) -> str:
    live = [c for c in snap["contracts"] if c["status"] == "liveConfirmed"]
    lines = [
        "# Legacy (v1) deployment inventory — read-only",
        "",
        f"Snapshot: chain `{snap['chainId']}`, block **{snap['blockNumber']}** (`{snap['blockHash']}`), timestamp {snap['timestamp']}, RPC host `{snap['rpcHost']}`.",
        "Generated by `script/gpu/inventory_legacy.py`; the committed JSON lives under `evidence/legacy/`. Values are v1-reported; nothing is corrected.",
        "",
        "## 1. Contracts (candidate → live confirmation)",
        "",
        "| Contract | Candidate address | Source of candidate | Status | Code bytes | owner | Key reads |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for c in snap["contracts"]:
        reads = c.get("reads", {})
        key = {k: v for k, v in reads.items() if k in ("paused", "totalGlobalDebt", "totalShares", "totalAssets", "totalBorrowed", "totalSupply", "globalCap", "latestCheckpointHeight")}
        lines.append(f"| {c['name']} | `{c['addressCandidate']}` | {c['candidateSource']} | **{c['status']}** | {c['codeSize']} | `{reads.get('owner', '—')}` | {json.dumps(key)} |")
    lines += ["", "## 2. Borrowers (from BorrowerRegistered/Borrowed/Repaid/PayoutRecorded logs)", ""]
    if snap["borrowers"]:
        lines += ["| Borrower | status | currentDebt (principal, v1) | getCurrentDebt (v1) | getAccruedInterest (v1) | creditLimit | payouts | borrowed/repaid events |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
        for b in snap["borrowers"]:
            ev = b.get("events", {})
            lines.append(f"| `{b['borrower']}` | {b.get('status', '?')} | {b.get('currentDebt(principal, v1)', '?')} | {b.get('getCurrentDebt(v1)', '?')} | {b.get('getAccruedInterest(v1)', '?')} | {b.get('creditLimit', '?')} | {b.get('payoutCount', '?')} | {ev.get('borrowed', 0)}/{ev.get('repaid', 0)} |")
    else:
        lines.append("No borrower events found in the scanned range.")
    lp = snap.get("lp", {})
    lines += ["", "## 3. LP / vault", "", f"- totalShares: `{lp.get('totalShares')}`; totalAssets (v1): `{lp.get('totalAssets(v1)')}`; totalBorrowed (v1): `{lp.get('totalBorrowed(v1)')}`; accumulatedInterest (v1): `{lp.get('accumulatedInterest(v1)')}`; vault token balance: `{lp.get('vaultTokenBalance')}`",
              f"- Deposited events: {lp.get('depositEvents')}, Withdrawn events: {lp.get('withdrawEvents')}, share holders enumerated: {len(lp.get('shareHolders', {}))}"]
    pe = snap.get("processedEvidence", {})
    lines += ["", "## 4. Processed evidence (legacy provenance)", "", f"- PayoutRecorded events: {pe.get('payoutRecordedEvents')} (distinct txids {pe.get('distinctTxids')}); provenance `{pe.get('provenance')}`; BTC address links `{pe.get('btcAddressLinkProvenance')}`; nativeStatus `{pe.get('nativeStatus')}` — never reclassified as ATTESTCOIN_NATIVE/VERIFIED."]
    lines += ["", "## 5. Sum checks (reported, not corrected)", "", "| Check | lhs | rhs | ok |", "| --- | --- | --- | --- |"]
    for s in snap["sumChecks"]:
        lines.append(f"| {s['check']} | {s['lhs']} | {s['rhs']} | {'✅' if s['ok'] else '❌'} |")
    # judgment
    debt_total = sum(int(b.get("currentDebt(principal, v1)", "0") or 0) for b in snap["borrowers"])
    shares = int(lp.get("totalShares") or 0)
    bal = int(lp.get("vaultTokenBalance") or 0)
    lines += ["", "## 6. Open testnet position assessment", ""]
    if not live:
        lines.append("Live confirmation **not available** for this snapshot (no `liveConfirmed` contract): the judgment is UNCONFIRMED.")
    else:
        lines += [
            f"- Outstanding v1 borrower principal (Σ `currentDebt`): **{debt_total}** base units (6 decimals) at block {snap['blockNumber']}.",
            f"- LP shares outstanding: **{shares}**; vault token balance: **{bal}** base units of the TEST_ONLY mintable token (`TestnetMintableERC20`, owner-mintable, no external value).",
            "- Judgment: " + ("**open v1 positions exist on CC3 testnet** (debt and/or LP shares > 0). They are testnet positions in an owner-mintable test token — no real customer funds — but they are *open rights/records* and must be preserved and closed through explicit on-chain transactions, not deleted." if (debt_total > 0 or shares > 0) else "**no open v1 debt or LP shares** at the pinned block; only historical records exist."),
            "- This judgment is based on chain reads at the pinned block, not on README statements. It says nothing about mainnet (no mainnet candidates exist in the repo).",
        ]
    lines += ["", "## 7. Known v1 interest defects — snapshot values are not adjusted", "",
              "The v1 `getCurrentDebt`/`getAccruedInterest` and `LendingVault.totalBorrowed/accumulatedInterest` figures above are computed by legacy logic with known defects. Affected borrowers (any with principal > 0 or repayment history):", ""]
    affected = [b for b in snap["borrowers"] if int(b.get("currentDebt(principal, v1)", "0") or 0) > 0 or b.get("events", {}).get("repaid", 0) > 0]
    if affected:
        for b in affected:
            lines.append(f"- `{b['borrower']}`: principal {b.get('currentDebt(principal, v1)')}, v1 accrued {b.get('getAccruedInterest(v1)')}; repaid events {b.get('events', {}).get('repaid', 0)} → unpaid-interest, manager/vault split, re-borrow capitalization, and APR-change defects may apply. This inventory does not restate the correct balance.")
    else:
        lines.append("- none with open principal or repayment history in this snapshot.")
    lines += ["", "## 8. Method and limits", "", "- JSON-RPC read-only: `eth_chainId`, `eth_getBlockByNumber`, `eth_getCode`, `eth_call`, `eth_getLogs` (bounded ranges). No keys, no transactions, RPC reduced to hostname.",
              "- `liveConfirmed` = code present at the pinned block **and** all expected v1 view reads succeeded; `partial` = some reads failed; `noCode`/`unreachable` as named.",
              "- Borrowers/holders are enumerated from logs since the deployment block; direct share transfers (if any) would not be enumerated — the share sum check exposes that."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rpc")
    ap.add_argument("--out", required=True)
    ap.add_argument("--block", type=int)
    ap.add_argument("--candidates", help="JSON file: [{name,address,source}]")
    ap.add_argument("--offline-fixture", help="recorded JSON-RPC responses (no network)")
    ap.add_argument("--record", help="write recorded JSON-RPC responses here")
    ap.add_argument("--resume-record", action="store_true", help="resume the same pinned snapshot from successful recorded reads")
    ap.add_argument("--deploy-block", type=int, default=0, help="first block to scan for logs")
    ap.add_argument("--markdown", help="also write the Markdown summary here")
    a = ap.parse_args(argv)
    if not a.rpc and not a.offline_fixture:
        ap.error("--rpc or --offline-fixture required")
    fixture = json.loads(Path(a.offline_fixture).read_text()) if a.offline_fixture else None
    rpc = Rpc(a.rpc if not fixture else None, fixture=fixture, record=bool(a.record))
    if a.resume_record:
        if not a.record or not Path(a.record).exists() or a.offline_fixture:
            ap.error("--resume-record requires an existing --record and live --rpc")
        prior = json.loads(Path(a.record).read_text())
        if prior["rpcHost"] != rpc.host:
            ap.error("recorded RPC host differs")
        rpc.recorded = prior
    rpc.record_path = a.record
    candidates = json.loads(Path(a.candidates).read_text()) if a.candidates else DEFAULT_CANDIDATES
    try:
        snap = inventory(rpc, candidates, a.block, a.deploy_block)
    except RpcError as e:
        snap = {"schemaVersion": SCHEMA_VERSION, "kind": "LEGACY_READ_ONLY_INVENTORY", "rpcHost": rpc.host, "status": "unreachable", "error": str(e), "contracts": [{"name": c["name"], "addressCandidate": c["address"], "candidateSource": c["source"], "status": "unreachable", "codeSize": 0, "reads": {}} for c in candidates], "borrowers": [], "lp": {}, "processedEvidence": {}, "sumChecks": [], "chainId": None, "blockNumber": None, "blockHash": None, "timestamp": None}
        print(f"RPC unreachable: {e}", file=sys.stderr)
    snap["snapshotSha256"] = hashlib.sha256(json.dumps({k: v for k, v in snap.items() if k != "snapshotSha256"}, sort_keys=True).encode()).hexdigest()
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(snap, indent=2) + "\n")
    if a.record:
        Path(a.record).write_text(json.dumps(rpc.recorded, indent=2) + "\n")
    if a.markdown:
        Path(a.markdown).write_text(render_markdown(snap))
    print(f"chainId={snap.get('chainId')} block={snap.get('blockNumber')} contracts={[(c['name'], c['status']) for c in snap['contracts']]} borrowers={len(snap['borrowers'])}")
    return 0 if snap.get("status") != "unreachable" else 3


if __name__ == "__main__":
    sys.exit(main())
