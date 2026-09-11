# HashCredit — Technical Note

> SPV-First, USC-Ready, Portable by Design

---

## The Core Insight: Hashrate Is Not a Number, It's a Record

You cannot prove your Bitcoin hashrate directly on-chain. Hashrate is a physical rate — joules per second applied to SHA-256. No contract can observe it directly.

What you *can* prove is the output of hashrate: **pool payouts**.

Every mining pool distributes revenue proportional to contributed hash power. Those distributions are Bitcoin transactions — timestamped, immutable, and verifiable by anyone who has the block headers. Accumulated payout history *is* the observable footprint of hashrate over time.

HashCredit's insight: **prove the payout record, infer the hashrate, issue credit against it.**

This reframes the problem from "prove a rate" to "prove a transaction" — which Bitcoin's own SPV model already solves.

---

## How Hashrate Gets Proven on Creditcoin

The proof chain is a straight line from mining activity to on-chain credit:

```
Miner contributes hashrate
        ↓
Mining pool issues payout (Bitcoin tx)
        ↓
Payout is included in a Bitcoin block (PoW commits to it)
        ↓
Off-chain worker builds SPV proof:
  - headers: checkpoint → tip (each PoW-validated)
  - merkle branch: tx inclusion in target block
  - raw tx + output index: identifies which output pays the miner
        ↓
SPV proof submitted to Creditcoin EVM
        ↓
BtcSpvVerifier checks on-chain (trustless):
  1. Header chain connects from trusted checkpoint
  2. Each header satisfies PoW (hash ≤ target derived from bits)
  3. Target block's Merkle root includes the payout tx
  4. Specified output pays to borrower's registered pubkeyHash
  5. Minimum 6 confirmations enforced
        ↓
PayoutEvidence returned to HashCreditManager
        ↓
Manager records payout (replay-protected), updates trailing credit limit
        ↓
Miner borrows stablecoins
```

No oracle. No bridge. No custodian. The same verification model Bitcoin light clients have used since 2009 — now running inside a Creditcoin EVM contract.

### What the Verifier Actually Checks

| Check | What It Proves |
|-------|---------------|
| Checkpoint anchor | Header chain is rooted in a known, trusted Bitcoin state |
| prev-hash linkage | Headers form a continuous chain from checkpoint to target |
| PoW per header | Each block is genuine Bitcoin work (can't be fabricated cheaply) |
| Retarget boundary | Difficulty didn't change mid-proof in an unexpected way |
| Merkle inclusion | Payout tx is committed to in the target block |
| Output script | Output pays specifically to this borrower's address (P2WPKH / P2PKH) |
| Confirmation depth | Target block is buried ≥ 6 blocks deep (finality assumption) |

All of this runs in `BtcSpvVerifier` and `BitcoinLib`. The result is a `PayoutEvidence` struct: verified amount, verified recipient, verified block height. Nothing else crosses the boundary into the credit layer.

---

## Why This Is the Same Principle as USC

USC (Universal Smart Contract) is Creditcoin's cross-chain oracle infrastructure. It enables smart contracts to query, verify, and act on transaction data from any external blockchain through a pipeline of distributed attestors, competitive provers, STARK zero-knowledge proofs, and a native verifier precompile at `0x0FD2`.

HashCredit follows the **exact same architectural pattern**, using Bitcoin SPV as the proof mechanism:

> **Prove a real-world economic event cryptographically → use that proof to authorize on-chain financial operations.**

### Precise Architectural Mapping

| Design Principle | USC | HashCredit |
|---|---|---|
| **Proof ↔ business separation** | `INativeQueryVerifier` ↔ Business contract | `IVerifierAdapter` ↔ `HashCreditManager` |
| **Structured evidence output** | Decoded event data from `encodedTransaction` | `PayoutEvidence` struct |
| **Stateless verifier** | `0x0FD2` precompile (pure function) | `BtcSpvVerifier.verifyPayout()` (no state writes) |
| **App-layer replay protection** | `processedQueries[hash(chain,height,index)]` | `processedPayouts[keccak256(txid,vout)]` |
| **Checkpoint / anchor** | Attestation chain digests (attestor consensus) | `CheckpointManager` trusted headers |
| **Chain continuity proof** | STARK zero-knowledge proof | PoW header chain verification |
| **Transaction inclusion** | Merkle proof (Keccak-256) | Merkle proof (SHA-256d) |
| **Event / output extraction** | `EvmV1Decoder` extracts logs | `BitcoinLib` parses tx outputs, matches pubkeyHash |

This alignment is deliberate. USC mainnet was not live during development. We implemented the same architecture ourselves — so the protocol works now and transitions to native USC via a single adapter swap.

---

## BTC Identity Binding: What USC Doesn't Cover

USC documentation does not specify how to bind a source-chain address to an EVM address. This is left as an application-level concern. HashCredit solves it **on-chain with pure cryptography**:

```
BTC wallet signs message (BIP-137)
    → ecrecover(btcMsgHash, v, r, s)                  // verify signature
    → compressed = [0x02|0x03 || pubKeyX]              // compress pubkey
    → ripemd160(sha256(compressed))                     // derive BTC address
    → borrowerPubkeyHash[msg.sender] = pubkeyHash      // store binding
```

This works because BTC and ETH share **secp256k1**. EVM precompiles (`ecrecover` at `0x01`, `sha256` at `0x02`, `ripemd160` at `0x03`) natively validate BTC signatures and derive BTC addresses. No oracle, no bridge, no trusted third party.

During SPV proof verification, the output script's pubkeyHash must match the stored `borrowerPubkeyHash` — ensuring that only the registered miner can claim payouts to their BTC address.

See [`docs/specs/BTC_IDENTITY_BINDING.md`](docs/specs/BTC_IDENTITY_BINDING.md) for the full deep-dive.

---

## Our Implementation vs USC: The Portability Design

### The Key Abstraction: `IVerifierAdapter`

```
┌──────────────────────────────┐
│        HashCreditManager     │
│  - Credit limit engine       │
│  - Replay protection         │
│  - Borrow / repay routing    │
│                              │
│  calls:  IVerifierAdapter    │ ← this is the seam
└──────────────┬───────────────┘
               │
       ┌───────┴────────┐
       │                │
┌──────▼──────┐  ┌──────▼──────┐
│ BtcSpv      │  │ USC         │
│ Verifier    │  │ Adapter     │ ← plug in when ready
│ (live now)  │  │ (future)    │
└─────────────┘  └─────────────┘
```

`HashCreditManager` is entirely unaware of Bitcoin internals. It only consumes `PayoutEvidence`:

```solidity
struct PayoutEvidence {
    address borrower;      // EVM address of the miner
    bytes32 txid;          // Bitcoin transaction ID
    uint32  vout;          // Output index
    uint64  amountSats;    // Payout amount in satoshis
    uint32  blockHeight;   // Confirmation block height
    uint32  blockTimestamp; // Block timestamp
}
```

This struct is the contract between the proof layer and the credit layer. Swap the proof source, keep the credit logic intact.

### Three Integration Paths to USC

**Path A — Swap the settlement asset**
- Deploy `LendingVault` with USC stablecoin address instead of mUSDT.
- Keep `BtcSpvVerifier` and `HashCreditManager` unchanged.
- Miners prove BTC payouts, borrow USC-native stablecoin.
- Zero changes to proof or credit logic.

**Path B — Add a USC verification adapter**
- Implement `UscVerifierAdapter` that calls `0x0FD2` precompile.
- Maps verified BTC transaction data to `PayoutEvidence`.
- Call `manager.setVerifier(uscAdapterAddress)`.
- Credit logic, vault, risk config — all untouched.

**Path C — Multi-verifier mode**
- Keep `BtcSpvVerifier` as adapter #1.
- Add `UscVerifierAdapter` as adapter #2.
- Credit limit incorporates evidence from both proof sources.

See [`docs/specs/USC_ADAPTER.md`](docs/specs/USC_ADAPTER.md) for detailed integration design.

---

## Credit Scoring from Mining Records

### Mainnet: SPV-Driven Credit

Each `submitPayout()` call triggers the following credit pipeline:

```
SPV-verified payout
    → Heuristics applied (large-payout discount, new-borrower cap)
    → Added to trailing window (30 days)
    → trailingRevenueSats × btcPriceUsd / SATS_PER_BTC = btcValueUsd
    → btcValueUsd × advanceRateBps / 10000 = creditLimit
    → More mining = higher credit limit
```

Risk parameters (configurable via `RiskConfig`):
- Advance rate: 50% (borrow up to half of trailing revenue value)
- Window: 30 days (only recent payouts count)
- New borrower cap: $10,000 (first 30 days)
- Large payout discount: 50% (single payouts > 0.1 BTC counted at half)
- Min payout threshold: 10,000 sats (dust payouts ignored)

### Testnet: Auto-Grant

Real mining cannot be reproduced on testnet. `registerBorrower` auto-grants a flat 1,000 mUSDT credit per borrower (via `autoGrantCreditAmount`). The full SPV proof pipeline remains functional and is demonstrated separately.

---

## Current State

Everything below runs today on Creditcoin EVM testnet (chainId `102031`):

| Component | Status |
|-----------|--------|
| `CheckpointManager` — trusted BTC header anchors | Live |
| `BtcSpvVerifier` — full SPV verification + on-chain BTC address claim (`claimBtcAddress`) | Live |
| `HashCreditManager` — credit limit engine, replay protection, borrow/repay | Live |
| `LendingVault` — stablecoin pool, debt accounting | Live |
| `RiskConfig` — advance rate, trailing window, payout thresholds | Live |
| Off-chain prover worker — auto-detects payouts, builds + submits proofs | Live |
| Off-chain API — checkpoint ops, borrower mapping, SPV proof builder, BTC sig param extraction | Live |
| Frontend — dashboard, pool (user-facing; checkpoint/proof are operator functions via off-chain worker) | Live |

USC integration is an **adapter + wiring task**. The proof system, credit engine, and vault do not need to change.

---

## Contracts (Creditcoin EVM Testnet)

| Contract | Address |
|----------|---------|
| HashCreditManager | `0x593e140982cDC040d69B7E7623A045C6d6Ca2055` |
| LendingVault | `0x4d74126369BacB67085a1E70d535cA15515d1AFa` |
| CheckpointManager | `0x4Ae5418242073cd37CCc69C908957E413a04f6f9` |
| BtcSpvVerifier | `0x16DEd6a617a911471cd4549C24Ed8C281f096fd2` |
| Stablecoin (mUSDT) | `0xb9D6E174C8e0267Fb0cC3F2AC34130D680151B6A` |
