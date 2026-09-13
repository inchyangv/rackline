"""
Minimal ABI helpers for the dispatcher: keccak-256 (pure Python, no eth-utils dependency in this package),
4-byte selectors, and the purpose allowlist that binds a *business* purpose to the exact contract function the
dispatcher may sign for (GPU-026, R2-D02/D03).

The allowlist is the only place where the dispatcher learns what it is allowed to sign:
- native evidence is submitted to the app's stateful entry points (`EvidenceBook.consume`,
  `ReceivableBook.ingest`), never to a raw `AttestcoinRevenueVerifier.verifyAndExtract` probe — that call is
  simulation-only (`eth_call`) and never a business DONE;
- fund-moving purposes need the TREASURY credential, keeper/gas-relay purposes the KEEPER credential
  (GPU-013 credential separation); a purpose is never signable by the wrong credential;
- there is no purpose that signs an attestation, marks something verified, or re-sends a proof to another
  verifier (no such option exists).
Canonical signatures are asserted against `test/fixtures/gpu/abi/*.json` by the tests.
"""

from __future__ import annotations

from dataclasses import dataclass

_RC = [
    0x0000000000000001,
    0x0000000000008082,
    0x800000000000808A,
    0x8000000080008000,
    0x000000000000808B,
    0x0000000080000001,
    0x8000000080008081,
    0x8000000000008009,
    0x000000000000008A,
    0x0000000000000088,
    0x0000000080008009,
    0x000000008000000A,
    0x000000008000808B,
    0x800000000000008B,
    0x8000000000008089,
    0x8000000000008003,
    0x8000000000008002,
    0x8000000000000080,
    0x000000000000800A,
    0x800000008000000A,
    0x8000000080008081,
    0x8000000000008080,
    0x0000000080000001,
    0x8000000080008008,
]
_ROT = [
    [0, 36, 3, 41, 18],
    [1, 44, 10, 45, 2],
    [62, 6, 43, 15, 61],
    [28, 55, 25, 21, 56],
    [27, 20, 39, 8, 14],
]
_MASK = (1 << 64) - 1


def _rol(x: int, n: int) -> int:
    n %= 64
    return ((x << n) | (x >> (64 - n))) & _MASK if n else x


def _keccak_f(state: list[list[int]]) -> None:
    for rc in _RC:
        c = [state[x][0] ^ state[x][1] ^ state[x][2] ^ state[x][3] ^ state[x][4] for x in range(5)]
        d = [c[(x - 1) % 5] ^ _rol(c[(x + 1) % 5], 1) for x in range(5)]
        for x in range(5):
            for y in range(5):
                state[x][y] ^= d[x]
        b = [[0] * 5 for _ in range(5)]
        for x in range(5):
            for y in range(5):
                b[y][(2 * x + 3 * y) % 5] = _rol(state[x][y], _ROT[x][y])
        for x in range(5):
            for y in range(5):
                state[x][y] = b[x][y] ^ ((~b[(x + 1) % 5][y]) & b[(x + 2) % 5][y])
        state[0][0] ^= rc


def keccak256(data: bytes) -> bytes:
    """Keccak-256 (the Ethereum variant, padding 0x01…0x80), pure Python."""
    rate = 136
    state = [[0] * 5 for _ in range(5)]
    padded = bytearray(data)
    padded.append(0x01)
    while len(padded) % rate:
        padded.append(0)
    padded[-1] |= 0x80
    for off in range(0, len(padded), rate):
        block = padded[off : off + rate]
        for i in range(rate // 8):
            lane = int.from_bytes(block[i * 8 : i * 8 + 8], "little")
            state[i % 5][i // 5] ^= lane
        _keccak_f(state)
    out = bytearray()
    for i in range(4):
        out += state[i % 5][i // 5].to_bytes(8, "little")
    return bytes(out)


def keccak_hex(data: bytes) -> str:
    return "0x" + keccak256(data).hex()


def selector(signature: str) -> str:
    """4-byte selector (0x-prefixed, lowercase) of a canonical function signature."""
    return "0x" + keccak256(signature.encode("ascii")).hex()[:8]


# ---------------------------------------------------------------- credentials / purposes

KEEPER = "keeper"  # gas relay / proof submission key (on-chain RELAYER role); never moves funds
TREASURY = "treasury"  # fund-moving key (lend/sweep/settlement); never used for keeper traffic
SIGNER_ROLES = (KEEPER, TREASURY)


@dataclass(frozen=True)
class Purpose:
    name: str
    contract_role: (
        str  # which deployed contract (resolved from the deployment manifest by the caller)
    )
    signature: str  # canonical function signature
    signer_role: str  # credential class allowed to sign
    business_entry: bool  # True = stateful app entry point (a mined receipt is a business fact)

    @property
    def selector(self) -> str:
        return selector(self.signature)


PURPOSES: dict[str, Purpose] = {
    p.name: p
    for p in (
        # native evidence: app record/consume entry points (GPU-031 / GPU-035) — the ONLY submission targets
        Purpose(
            "evidence.consume",
            "evidence_book",
            "consume(bytes32,(uint64,uint64,bytes,bytes32,(bytes32,bool)[],bytes32,bytes32[]),address,bytes32[],"
            "(uint32,bytes32,bytes32,uint64)[])",
            KEEPER,
            True,
        ),
        Purpose(
            "receivables.ingest",
            "receivable_book",
            "ingest(bytes32,(uint64,uint64,bytes,bytes32,(bytes32,bool)[],bytes32,bytes32[]),address,bytes32[],"
            "(uint32,bytes32,bytes32,bytes32,bytes,uint64)[])",
            KEEPER,
            True,
        ),
        # facility execution (GPU-036) — borrower-signed draws are not dispatched by us; keeper may execute a
        # reserved draw and relay third-party repayments, treasury moves funds
        Purpose(
            "manager.executeReservedDraw",
            "manager",
            "executeReservedDraw(bytes32,uint256)",
            TREASURY,
            True,
        ),
        Purpose("manager.repayFor", "manager", "repayFor(bytes32,uint256)", TREASURY, True),
        # escrow (GPU-037)
        Purpose("escrow.sweep", "revenue_escrow", "sweep(uint64)", TREASURY, True),
        Purpose(
            "escrow.forwardClaimed",
            "revenue_escrow",
            "forwardClaimed(bytes32,uint256,bytes32)",
            TREASURY,
            True,
        ),
        Purpose("escrow.claim", "revenue_escrow", "claim(address,bytes)", KEEPER, True),
    )
}

#: raw verifier probe — simulation only; never a signable purpose
VERIFIER_PROBE_SIGNATURE = "verifyAndExtract((uint64,uint64,bytes,bytes32,(bytes32,bool)[],bytes32,bytes32[]),address,bytes32[])"
VERIFIER_PROBE_SELECTOR = selector(VERIFIER_PROBE_SIGNATURE)

#: words that would indicate a substitute path; no purpose name may contain them (R2-D03)
FORBIDDEN_PURPOSE_TERMS = (
    "sign",
    "attest",
    "fallback",
    "markverified",
    "mark_verified",
    "bypass",
    "force",
    "spv",
    "resend_other",
)


class PurposeNotAllowed(PermissionError):
    pass


def resolve_purpose(name: str, signer_role: str, calldata: bytes) -> Purpose:
    """Return the purpose if `name` exists, the credential may sign it, and calldata starts with its selector."""
    p = PURPOSES.get(name)
    if p is None:
        raise PurposeNotAllowed(f"unknown purpose {name!r}")
    if signer_role != p.signer_role:
        raise PurposeNotAllowed(
            f"purpose {name!r} requires the {p.signer_role} credential, got {signer_role}"
        )
    if len(calldata) < 4 or "0x" + calldata[:4].hex() != p.selector:
        raise PurposeNotAllowed(f"calldata selector does not match purpose {name!r} ({p.selector})")
    return p


def is_verifier_probe(calldata: bytes) -> bool:
    return len(calldata) >= 4 and "0x" + calldata[:4].hex() == VERIFIER_PROBE_SELECTOR
