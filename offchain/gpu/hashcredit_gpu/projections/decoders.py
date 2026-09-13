"""
Event decoders built from the pinned ABI fixtures (`test/fixtures/gpu/abi/*.json`, exported with
`forge inspect`; GPU-029/030/031/032/033/034/035/036/037/077/078). No hand-typed event signatures.

A `Decoder` maps (contract address → contract name) and (topic0 → event ABI) for one deployment, decodes a raw
log into JSON-safe values (ints as decimal strings, bytes as 0x hex), and rejects logs whose topic0 is unknown
for that contract (they are stored raw but never projected).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eth_abi import decode as abi_decode
from eth_utils import keccak

REPO_ROOT = Path(__file__).resolve().parents[4]
ABI_DIR = REPO_ROOT / "test" / "fixtures" / "gpu" / "abi"
if not ABI_DIR.exists():
    ABI_DIR = Path(__file__).with_name("abi")

#: the v2 contracts a deployment may register (name → ABI fixture); SourceEscrow lives on the source chain
#: and is projected only when a deployment explicitly lists it (LOCAL/Anvil).
PROJECTED_CONTRACTS = (
    "ProtocolRoles",
    "AuthorizationVerifier",
    "ProviderRegistry",
    "AccountRegistry",
    "AttestcoinRevenueVerifier",
    "EvidenceBook",
    "ControlRegistry",
    "DebtLedger",
    "LendingVaultV2",
    "ReceivableBook",
    "GpuRiskPolicy",
    "ExposureController",
    "RevenueEscrow",
    "CreditFacilityManager",
    "SourceEscrow",
    "RepaymentRouter",
    "RecoveryManager",
    "SettlementReceiver",
    "GovernanceTimelock",
    "TreasuryTimelock",
    "GpuTestToken",
)


@dataclass(frozen=True)
class EventAbi:
    contract: str
    name: str
    signature: str
    topic0: str
    indexed: tuple[tuple[str, str], ...]  # (name, type)
    unindexed: tuple[tuple[str, str], ...]


def _canonical_type(inp: dict) -> str:
    if inp["type"].startswith("tuple"):
        inner = ",".join(_canonical_type(c) for c in inp["components"])
        return f"({inner}){inp['type'][5:]}"
    return inp["type"]


def load_events(contract: str) -> dict[str, EventAbi]:
    filename = "GovernanceTimelock" if contract == "TreasuryTimelock" else contract
    abi = json.loads((ABI_DIR / f"{filename}.json").read_text())
    out: dict[str, EventAbi] = {}
    for entry in abi:
        if entry.get("type") != "event":
            continue
        sig = entry["name"] + "(" + ",".join(_canonical_type(i) for i in entry["inputs"]) + ")"
        topic0 = "0x" + keccak(text=sig).hex()
        out[topic0] = EventAbi(
            contract=contract,
            name=entry["name"],
            signature=sig,
            topic0=topic0,
            indexed=tuple(
                (i["name"], _canonical_type(i)) for i in entry["inputs"] if i.get("indexed")
            ),
            unindexed=tuple(
                (i["name"], _canonical_type(i)) for i in entry["inputs"] if not i.get("indexed")
            ),
        )
    return out


def _json_safe(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        return "0x" + bytes(value).hex()
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, str) and value.startswith("0x") and len(value) == 42:
        return value.lower()
    return value


def _decode_topic(typ: str, topic: str) -> Any:
    raw = bytes.fromhex(topic[2:])
    if typ in ("string", "bytes") or typ.endswith("]"):
        return "0x" + raw.hex()  # dynamic indexed values are hashed on-chain
    return abi_decode([typ], raw)[0]


@dataclass(frozen=True)
class DecodedLog:
    contract: str
    event: str
    args: dict[str, Any]


class Decoder:
    def __init__(self, contracts: dict[str, str]):
        """`contracts` = {contractName: address} for one deployment."""
        unknown = set(contracts) - set(PROJECTED_CONTRACTS)
        if unknown:
            raise ValueError(f"unknown contract names for projection: {sorted(unknown)}")
        self.address_to_name = {addr.lower(): name for name, addr in contracts.items()}
        self.events: dict[str, dict[str, EventAbi]] = {
            name: load_events(name) for name in contracts
        }

    @property
    def addresses(self) -> list[str]:
        return sorted(self.address_to_name)

    def contract_of(self, address: str) -> str | None:
        return self.address_to_name.get(address.lower())

    def topic0(self, contract: str, event: str) -> str:
        for t0, ev in self.events[contract].items():
            if ev.name == event:
                return t0
        raise KeyError(f"{contract}.{event}")

    def decode(self, address: str, topics: list[str], data: str) -> DecodedLog | None:
        name = self.contract_of(address)
        if name is None or not topics:
            return None
        ev = self.events[name].get(topics[0].lower())
        if ev is None:
            return None
        if len(topics) != 1 + len(ev.indexed):
            raise ValueError(
                f"{name}.{ev.name}: expected {len(ev.indexed)} indexed topics, got {len(topics) - 1}"
            )
        args: dict[str, Any] = {}
        for (arg_name, typ), topic in zip(ev.indexed, topics[1:], strict=True):
            args[arg_name] = _json_safe(_decode_topic(typ, topic))
        if ev.unindexed:
            raw = bytes.fromhex(data[2:]) if data and data != "0x" else b""
            values = abi_decode([t for _, t in ev.unindexed], raw)
            for (arg_name, _), v in zip(ev.unindexed, values, strict=True):
                args[arg_name] = _json_safe(v)
        return DecodedLog(contract=name, event=ev.name, args=args)
