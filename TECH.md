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

USC (Universal Smart Contract, Creditcoin's settlement layer) follows the same architectural logic:

> **Prove a real-world economic event cryptographically → use that proof to authorize on-chain financial operations.**

The mechanism differs (USC has its own attestation/settlement primitives), but the underlying pattern is identical:

| Dimension | USC | HashCredit (our implementation) |
|-----------|-----|----------------------------------|
| Real-world signal | Off-chain credit/trade event | Bitcoin mining payout |
| Proof mechanism | USC attestation/settlement | Bitcoin SPV (PoW + Merkle + output check) |
| On-chain boundary | USC settlement contract | `IVerifierAdapter` → `PayoutEvidence` |
| Credit layer | Creditcoin credit logic | `HashCreditManager` |
| Settlement asset | USC / stablecoin | `LendingVault` (any ERC20) |

In both cases, the **proof layer is cleanly separated from the credit layer**. The credit contract doesn't know how the proof works — it only receives structured, verified evidence through a well-defined interface.

This is not a coincidence. We deliberately mirrored USC's architecture pattern when building HashCredit, because USC mainnet was not live during development and we needed to prove the concept now rather than wait.

---

## Our Implementation vs USC: The Portability Design

USC mainnet was not available when we built this. Rather than stub it out or wait, we implemented the same architectural pattern ourselves using BTC SPV as the proof source.

The result is a system that works today *and* can attach to USC later without redesigning the core proof-credit separation.

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
    address borrower;
    uint256 amount;        // satoshis or normalized unit
    uint256 blockHeight;
    bytes32 txId;
    uint32  outputIndex;
}
```

This struct is the contract between the proof layer and the credit layer. Swap the proof source, keep the credit logic intact.

### Three Integration Paths to USC

**Path A — Swap the settlement asset**
- Deploy `LendingVault` with USC token address instead of cUSD.
- Keep `BtcSpvVerifier` and `HashCreditManager` unchanged.
- Miners prove BTC payouts, borrow USC instead of cUSD.
- Zero changes to proof or credit logic.

**Path B — Add a USC settlement adapter**
- Keep current BTC SPV payout proof path entirely unchanged.
- Add a `UscSettlementAdapter` that routes credit events through USC's settlement primitives.
- Replay, risk, and debt checks remain in `HashCreditManager`.

**Path C — Multi-verifier mode**
- Keep `BtcSpvVerifier` as one adapter.
- Add a USC-native verifier for USC-specific attestations as a second adapter.
- Route both through `IVerifierAdapter`-compatible interfaces into the same `HashCreditManager`.
- A miner's credit limit could incorporate evidence from both sources.

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
| Frontend — dashboard, checkpoint, proof | Live |

On mainnet, credit limits are driven by real SPV-proven mining payouts — each verified payout updates the miner's trailing-window credit limit. On testnet, real mining cannot be reproduced in a demo, so `grantTestnetCredit` bootstraps a flat 1,000 cUSD credit per borrower. The full SPV proof pipeline remains functional and is demonstrated separately.

USC integration is an **adapter + wiring task**. The proof system, credit engine, and vault do not need to change.

---

## Contracts (Creditcoin EVM Testnet)

| Contract | Address |
|----------|---------|
| HashCreditManager | `0x3cfb7fcf0647c78c3f932763e033b6184d79a936` |
| LendingVault | `0x60cd9c0e8b828c65c494e0f4274753e6968df0c1` |
| CheckpointManager | `0xe792383beb2f78076e644e7361ed7057a1f4cd88` |
| BtcSpvVerifier | `0x98b9ddafe0c49d73cb1cf878c8febad22c357f33` |
| Stablecoin (cUSD) | `0x9e00a3a453704e6948689eb68a4f65649af30a97` |
