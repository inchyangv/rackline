# Cross-Chain Oracle Integration Design — HashCredit

> **Note**: This document was originally written for Creditcoin's USC (Universal Smart Contract) integration.
> The architectural patterns described here (proof ↔ business separation, `IVerifierAdapter`, modular proof sources)
> are chain-agnostic and apply equally to HashKey Chain and any future cross-chain oracle integration.

> How HashCredit's modular proof architecture enables integration with cross-chain oracles,
> why our BTC SPV implementation is a valid instantiation of the same pattern,
> and how future oracle adapters can be added without protocol changes.

---

## 1. What USC Is

USC (Universal Smart Contract) is Creditcoin's cross-chain oracle infrastructure. It enables smart contracts on Creditcoin EVM to **query, verify, and act on transaction data from any external blockchain** — without trusted intermediaries.

### USC Architecture Stack

```
Source Chain (BTC, ETH, SOL, ...)
        │
        ▼
┌─────────────────────────┐
│  Attestors (distributed) │ ← Multiple independent operators monitor source chains
│  Build attestation chain │    and produce consensus-based checkpoint digests
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│  Provers (competitive)   │ ← Generate Merkle proof (tx inclusion) +
│  Build proof envelopes   │    Continuity proof (block in attestation chain)
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│  STARK Proving (Cairo)   │ ← Zero-knowledge proof that continuity verification
│  Certify proof fidelity  │    was conducted faithfully; verifiable by anyone
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│  Native Query Verifier   │ ← Precompile at 0x0FD2 (Rust, ~15 sec)
│  On-chain verification   │    Synchronous: proof → verified event, single tx
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│  Business Logic Contract │ ← Consumes verified data, applies domain logic
│  (DApp-specific)         │    Replay protection, credit scoring, lending, etc.
└─────────────────────────┘
```

### USC Core Interface

```solidity
// Creditcoin native precompile at 0x0FD2
interface INativeQueryVerifier {
    struct MerkleProofEntry {
        bytes32 hash;
        bool isLeft;
    }
    struct MerkleProof {
        bytes32 root;
        MerkleProofEntry[] siblings;
    }
    struct ContinuityProof {
        bytes32 lowerEndpointDigest;
        bytes32[] roots;
    }
    function verifyAndEmit(
        uint64 chainKey,
        uint64 height,
        bytes calldata encodedTransaction,
        MerkleProof calldata merkleProof,
        ContinuityProof calldata continuityProof
    ) external view returns (bool);
}
```

### USC Design Principles (from official docs)

1. **Query-Prove-Verify**: source chain event → off-chain proof generation → on-chain verification + business logic, all in a single synchronous transaction.
2. **Verification ≠ Business Logic**: USC verification contract and business logic contract are cleanly separated.
3. **Replay Protection at App Layer**: each app tracks `processedQueries` via `hash(chainKey, blockHeight, txIndex)`.
4. **Batch Support**: up to 10 queries can share a single continuity proof.

---

## 2. HashCredit: Same Pattern, BTC-Native Proof

We implement the **exact same architectural pattern** as USC, using Bitcoin SPV as the proof mechanism instead of USC's attestor/prover/STARK pipeline.

### Side-by-Side Architecture Comparison

```
USC Pipeline:                          HashCredit Pipeline:
─────────────                          ──────────────────
Source chain event                     Bitcoin mining payout (tx)
        │                                      │
Attestors build digest                 CheckpointManager stores trusted header
        │                                      │
Prover builds Merkle +                 Off-chain worker builds SPV proof:
 Continuity proof                       headers + Merkle branch + raw tx
        │                                      │
STARK proves fidelity                  PoW validates each header (hash ≤ target)
        │                                      │
0x0FD2 precompile verifies             BtcSpvVerifier verifies (pure Solidity)
        │                                      │
Business logic contract                HashCreditManager processes PayoutEvidence
 consumes verified data                 → credit limit update → borrow/repay
```

### Mapping of Equivalent Components

| USC Component | HashCredit Equivalent | Interface |
|---|---|---|
| `INativeQueryVerifier` | `IVerifierAdapter` | `verifyPayout(bytes) → PayoutEvidence` |
| Attestation chain digest | `CheckpointManager` checkpoint | Trusted anchor for chain continuity |
| Merkle proof (Keccak-256) | Merkle proof (SHA-256d) | Transaction inclusion in block |
| Continuity proof (STARK) | PoW header chain verification | Block belongs to canonical chain |
| `encodedTransaction` | `rawTx` (Bitcoin transaction bytes) | Raw event/tx data for parsing |
| `processedQueries` mapping | `processedPayouts` mapping | Replay protection |
| Business logic contract | `HashCreditManager` | Domain-specific credit logic |
| Source chain contract events | Bitcoin tx outputs (P2WPKH/P2PKH) | Observable economic event |

### The Key Abstraction: `IVerifierAdapter`

This is the **architectural seam** that makes our system USC-portable:

```solidity
interface IVerifierAdapter {
    function verifyPayout(bytes calldata proof)
        external returns (PayoutEvidence memory evidence);
    function isPayoutProcessed(bytes32 txid, uint32 vout)
        external view returns (bool);
}

struct PayoutEvidence {
    address borrower;        // EVM address of the miner
    bytes32 txid;            // Bitcoin transaction ID
    uint32  vout;            // Output index
    uint64  amountSats;      // Payout amount in satoshis
    uint32  blockHeight;     // Block where tx was confirmed
    uint32  blockTimestamp;  // Block timestamp
}
```

**`HashCreditManager` never touches proof internals.** It only consumes `PayoutEvidence`. This means:
- Swap the verifier → credit logic unchanged
- Swap the vault asset → credit logic unchanged
- Add a second verifier → credit logic unchanged

---

## 3. Why Our Pattern Is Architecturally Valid

### 3.1 Same Trust Reduction Goal

Both USC and HashCredit aim to **replace trusted intermediaries with cryptographic proofs** for cross-chain data verification.

| Property | USC | HashCredit |
|---|---|---|
| Oracle-free | Attestors + STARK (no single trusted party) | PoW + Merkle (Bitcoin's own security model) |
| Proof completeness | Merkle inclusion + chain continuity | Merkle inclusion + header chain PoW |
| Single-tx verification | Yes (precompile) | Yes (Solidity, higher gas) |
| Deterministic output | Verified event data | `PayoutEvidence` struct |

### 3.2 Same Separation of Concerns

```
USC:           Verification Contract  ←→  Business Logic Contract
HashCredit:    IVerifierAdapter       ←→  HashCreditManager
```

Both enforce that **the verifier knows nothing about credit** and **the credit engine knows nothing about proofs**. The boundary is a structured data interface (`PayoutEvidence` / decoded event data).

### 3.3 Same Replay Protection Model

Both place replay protection in the **business logic layer**, not the verification layer:

- USC: `processedQueries[hash(chainKey, height, txIndex)]`
- HashCredit: `processedPayouts[keccak256(txid, vout)]`

This is deliberate: the verifier is stateless (pure function), and the business contract owns state.

### 3.4 Same Checkpoint/Anchor System

- USC: attestation chain digests (built by distributed attestor consensus)
- HashCredit: `CheckpointManager` stores trusted Bitcoin block headers

Both serve the same role: **"everything after this point is validated from a known-good anchor."**

---

## 4. What HashCredit Does That USC Doesn't

### 4.1 BTC Identity Binding (`claimBtcAddress`)

USC documentation does not specify how to bind a source-chain address to an EVM address. This is left as an application-level concern.

HashCredit solves this **on-chain with pure cryptography**:

```
User signs message with BTC private key (BIP-137)
    → ecrecover(btcMsgHash, v, r, s) verifies signature
    → Compress pubkey: [0x02/0x03 || pubKeyX] (33 bytes)
    → ripemd160(sha256(compressed)) = BTC pubkeyHash (20 bytes)
    → Store: borrowerPubkeyHash[msg.sender] = pubkeyHash
```

Then during SPV proof verification:
```
Parse tx output script → extract pubkeyHash
    → Must match borrowerPubkeyHash[borrower]
    → Only then is PayoutEvidence issued
```

This eliminates any trusted oracle for identity binding. It works because **BTC and ETH share secp256k1**, so EVM's `ecrecover` precompile natively validates BTC signatures.

See `docs/specs/BTC_IDENTITY_BINDING.md` for the full deep-dive.

### 4.2 Revenue-Based Credit Scoring

USC is a generic cross-chain data verification framework. HashCredit adds a complete **revenue-based credit scoring engine** on top:

- Trailing-window revenue accumulation (configurable, default 30 days)
- BTC→USD conversion at on-chain oracle price
- Advance rate application (default 50%)
- Payout heuristics (large-payout discount, new-borrower caps)
- Per-borrower and global debt caps
- Time-weighted interest accrual

### 4.3 Bitcoin-Native PoW Verification

For Bitcoin specifically, our approach is arguably **more trustless** than USC's attestor model:

- We verify **actual Bitcoin proof-of-work** on-chain (each header's hash must be ≤ target derived from `nBits`)
- Forging a proof requires producing valid PoW — i.e., having actual Bitcoin-level hashpower
- USC attestors reach consensus, which is robust but introduces a different trust assumption (attestor set integrity)

---

## 5. What USC Has That We Don't (Yet)

| Capability | USC | HashCredit | Impact |
|---|---|---|---|
| Decentralized checkpoints | Attestor consensus | `onlyOwner` | **Centralization risk** — mitigated by multisig on mainnet |
| Native precompile (gas) | `0x0FD2` (Rust) | Pure Solidity | **Higher gas costs** — acceptable for low-frequency payout proofs |
| Multi-chain support | Any chain via `chainKey` | Bitcoin only | **By design** — our domain is BTC mining |
| STARK proofs | Zero-knowledge continuity | PoW header chain | **Different trust model**, not necessarily worse for BTC |
| Batch queries | 10 per continuity proof | 1 proof per tx | **Optimization opportunity** for future |

---

## 6. Integration Paths When USC Ships

### Path A — Swap Settlement Asset (Simplest)

```
Change: Deploy LendingVault with USC stablecoin address instead of mUSDT
Keep:   BtcSpvVerifier, HashCreditManager, RiskConfig — all unchanged
Result: Miners prove BTC payouts, borrow USC-native stablecoin
Code:   Zero changes to proof or credit logic
```

### Path B — Add USC Verification Adapter

```
New:    UscVerifierAdapter implements IVerifierAdapter
Change: manager.setVerifier(uscAdapterAddress)
Keep:   HashCreditManager, LendingVault, RiskConfig — all unchanged
Result: BTC payouts verified via USC's 0x0FD2 precompile (lower gas)
```

```solidity
contract UscVerifierAdapter is IVerifierAdapter {
    INativeQueryVerifier constant VERIFIER = INativeQueryVerifier(0x0FD2);

    function verifyPayout(bytes calldata proof) external override
        returns (PayoutEvidence memory)
    {
        // 1. Decode proof envelope (chainKey, height, encodedTx, merkle, continuity)
        (
            uint64 chainKey,
            uint64 height,
            bytes memory encodedTx,
            INativeQueryVerifier.MerkleProof memory merkleProof,
            INativeQueryVerifier.ContinuityProof memory continuityProof
        ) = abi.decode(proof, (uint64, uint64, bytes, ...));

        // 2. Verify via USC precompile
        bool valid = VERIFIER.verifyAndEmit(
            chainKey, height, encodedTx, merkleProof, continuityProof
        );
        require(valid, "USC verification failed");

        // 3. Parse Bitcoin tx from encodedTx → extract payout info
        // 4. Map to PayoutEvidence struct
        return PayoutEvidence({
            borrower: ...,
            txid: ...,
            vout: ...,
            amountSats: ...,
            blockHeight: uint32(height),
            blockTimestamp: ...
        });
    }
}
```

### Path C — Multi-Verifier Mode (Most Powerful)

```
Keep:   BtcSpvVerifier as adapter #1
Add:    UscVerifierAdapter as adapter #2
Change: HashCreditManager to support multiple verifiers
Result: Credit limit incorporates evidence from both proof sources
```

This would require a minor HashCreditManager modification to accept a verifier address parameter in `submitPayout()`, or maintain a registry of approved verifiers.

---

## 7. Open Items for USC Integration

| Item | Status | Notes |
|---|---|---|
| USC precompile ABI (`0x0FD2`) | Documented | `verifyAndEmit(chainKey, height, encodedTx, merkleProof, continuityProof)` |
| Bitcoin `chainKey` value | TBD | Need Creditcoin team to confirm BTC chain key |
| `encodedTransaction` format for BTC | TBD | How BTC raw tx is encoded in USC envelope |
| Gas cost comparison | TBD | Precompile vs current Solidity SPV (~500k–2M gas) |
| Attestor coverage for Bitcoin | TBD | USC attestors must monitor Bitcoin chain |
| BTC identity binding in USC context | N/A | Our `claimBtcAddress` works regardless of verifier |
| Batch payout submission | Future | Could submit multiple payouts with shared continuity proof |

## 8. Implementation Checklist

1. [ ] Confirm USC `chainKey` for Bitcoin with Creditcoin team
2. [ ] Define USC proof envelope ABI for BTC transactions
3. [ ] Implement `UscVerifierAdapter` contract
4. [ ] Add Foundry tests: valid/invalid proof mappings, edge cases
5. [ ] Verify `PayoutEvidence` field mapping consistency (txid endianness, amount units)
6. [ ] Deploy adapter to testnet
7. [ ] Call `manager.setVerifier(uscAdapterAddress)` (owner-only)
8. [ ] Run full smoke test: submitPayout → credit update → borrow → repay
9. [ ] Verify unchanged behavior of Manager/Vault/RiskConfig
10. [ ] Update off-chain worker to build USC proof envelopes (parallel to SPV path)

---

## 9. Summary

HashCredit is not a "USC workaround." It is a **production implementation of the same architectural pattern** that USC standardizes — proof-separated, replay-protected, adapter-abstracted credit from cross-chain economic evidence.

The difference is the proof mechanism: we use Bitcoin's native PoW + Merkle instead of USC's attestor + STARK pipeline. Both produce the same output: **verified, structured evidence** that a business logic contract consumes without knowing how it was proven.

When USC ships with Bitcoin chain support, we swap one adapter contract. Credit logic, risk parameters, vault, and identity binding remain untouched. That's the whole point of the `IVerifierAdapter` abstraction — it was designed for exactly this transition.
