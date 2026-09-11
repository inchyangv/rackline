# ADR 0001: Bitcoin SPV Verification for Production

## Status
**Accepted**

## Context

HashCredit's MVP uses a trusted relayer (EIP-712 signature oracle) to verify Bitcoin payout events. For production, we need trust-minimized verification using Bitcoin SPV (Simplified Payment Verification) proofs.

The goal is to verify that a Bitcoin transaction was included in a block with sufficient proof-of-work, and that the transaction outputs match the borrower's registered payout address.

### Constraints

1. **No native Bitcoin precompiles on Creditcoin EVM**: We cannot rely on protocol-level Bitcoin verification.
2. **Gas costs**: Full header chain verification from genesis is impractical. We need checkpoints.
3. **Difficulty retarget complexity**: Bitcoin adjusts difficulty every 2016 blocks. Verifying across retarget boundaries requires additional logic.
4. **SHA256d requirement**: Bitcoin uses double SHA256, which costs ~60 gas per SHA256 via EVM precompile (address 0x02).

## Decision

### 1. Checkpoint Trust Model

We use a **multisig-controlled checkpoint system**:

- A set of trusted attestors (multisig or threshold signature) periodically submits checkpoint headers to `CheckpointManager`.
- Each checkpoint contains:
  - `blockHash`: The 32-byte block hash
  - `blockHeight`: The block height
  - `chainWork`: Cumulative chain work up to this point (optional, for fork resistance)
  - `timestamp`: Block timestamp
  - `bits`: Difficulty target in compact format (anchors expected difficulty for the epoch)

**Checkpoint frequency**: Every ~2000 blocks (approximately 2 weeks), ensuring we stay within a single difficulty period.

**Trust assumption**: The checkpoint attestor set is honest. This is acceptable for MVP/early production. Future versions may use Bitcoin light client consensus or USC's native Bitcoin support.

### 2. Header Chain Verification

When submitting a payout proof, the prover must provide:

1. **Anchor checkpoint**: A previously registered checkpoint
2. **Header chain**: Sequence of Bitcoin block headers from checkpoint to target block
3. **Proof data**: Transaction inclusion proof

**Verification steps**:

```
1. Verify checkpoint exists and is valid
2. For each header in chain (from checkpoint.next to target):
   a. Verify prevBlockHash links to previous header
   b. Verify PoW: sha256d(header) <= target_from_bits(header.bits)
   c. Verify header.bits matches expected difficulty (same period check)
3. Verify header chain length <= MAX_HEADER_CHAIN_LENGTH (e.g., 144 blocks = ~1 day)
```

### 3. Difficulty Period Boundaries

**Decision: Reject proofs that cross difficulty retarget boundaries.**

Rationale:
- Verifying difficulty adjustment requires the previous 2016 headers or trusted retarget checkpoints.
- Operational workaround: Ensure checkpoints are set within each difficulty period.
- If a payout falls near a retarget boundary, wait for a new checkpoint in the next period.

This simplifies implementation significantly while maintaining security.

**Implementation (T2.3):**
- Checkpoint struct includes `bits` field to anchor expected difficulty for the epoch.
- `BtcSpvVerifier._verifyHeaderChain()` validates:
  1. `(checkpointHeight / 2016) == (targetHeight / 2016)` - no retarget boundary crossing
  2. Each header's `bits` must match the checkpoint's `bits` exactly
- Errors: `RetargetBoundaryCrossing(checkpointHeight, targetHeight)`, `DifficultyMismatch(expected, actual)`

### 4. Transaction Inclusion Proof (Merkle)

Bitcoin uses a **double-SHA256 Merkle tree**. The proof consists of:

- `rawTx`: The full serialized Bitcoin transaction
- `merkleProof`: Array of 32-byte hashes forming the Merkle branch
- `txIndex`: Position of the transaction in the block (for left/right determination)

**Verification**:

```
1. txid = sha256d(rawTx)  // reverse byte order for display
2. current = txid
3. for each (sibling, isLeft) in merkleProof:
   if isLeft:
     current = sha256d(sibling || current)
   else:
     current = sha256d(current || sibling)
4. assert current == header.merkleRoot
```

### 5. Transaction Output Parsing

**Supported scriptPubKey types** (in priority order):

1. **P2WPKH** (native SegWit v0): `OP_0 <20-byte-pubkey-hash>`
   - Most common for modern wallets/pools
   - Script: `0x0014{20-bytes}`

2. **P2PKH** (legacy): `OP_DUP OP_HASH160 <20-byte-pubkey-hash> OP_EQUALVERIFY OP_CHECKSIG`
   - Script: `0x76a914{20-bytes}88ac`

3. **P2SH** (optional, phase 2): More complex, requires script hash matching

**Parsing requirements**:
- Decode VarInt for output count
- For each output: decode value (8 bytes LE), scriptPubKey length, scriptPubKey
- Extract the pubkey hash and match against borrower's registered `scriptPubKeyHash`

### 6. Proof Size and Gas Limits

| Component | Size | Gas Estimate |
|-----------|------|--------------|
| Block header | 80 bytes | ~120 gas (SHA256d) |
| Header chain (144 max) | 11,520 bytes | ~17,280 gas |
| Merkle proof (12 levels) | 384 bytes | ~1,440 gas |
| Raw transaction | ~250 bytes (typical) | ~500 gas parsing |
| Total verification | - | ~25,000-50,000 gas |

**Limits**:
- `MAX_HEADER_CHAIN_LENGTH`: 144 blocks (1 day of blocks)
- `MAX_MERKLE_PROOF_LENGTH`: 20 levels (supports blocks with 2^20 txs)
- `MAX_RAW_TX_SIZE`: 4,096 bytes (covers most standard transactions)

### 7. Security Considerations

#### 7.1 Reorg Resistance
- Require minimum confirmations (e.g., 6 blocks) before accepting proofs
- Header chain provides implicit confirmation count
- Checkpoint should be sufficiently deep (100+ confirmations recommended)

#### 7.2 Fake Block Attack
- Attacker would need to produce valid PoW to create fake headers
- Cost: Current Bitcoin hashrate makes this economically infeasible for amounts < millions of USD
- Additional defense: Checkpoint attestors monitor for forks

#### 7.3 Replay Protection
- Each (txid, vout) pair can only be credited once
- Stored in `processedPayouts` mapping

#### 7.4 Output Spoofing
- Raw transaction is fully parsed on-chain
- Output script must match borrower's registered scriptPubKeyHash
- Amount extracted directly from transaction

## Consequences

### Positive
- Trust-minimized verification (only checkpoint attestors are trusted)
- Gas-efficient for typical proofs (~30-50k gas)
- Clear upgrade path: Replace checkpoint system with USC native Bitcoin support when available

### Negative
- Cannot process payouts near difficulty retarget boundaries immediately
- Requires off-chain proof builder infrastructure
- Checkpoint attestor set is a trust assumption

### Neutral
- Complexity is manageable with clear boundaries
- Standard Bitcoin SPV approach, well-understood security model

## Implementation Notes

### Contract Structure

```
CheckpointManager
├── setCheckpoint(height, hash, chainWork, timestamp, bits) [multisig only]
├── getCheckpoint(height) → Checkpoint
└── isValidCheckpoint(height, hash) → bool

BtcSpvVerifier (implements IVerifierAdapter)
├── verifyPayout(proof) → PayoutEvidence
├── isPayoutProcessed(txid, vout) → bool
├── verifyHeaderChain(checkpoint, headers) [internal]
├── verifyMerkleInclusion(txid, proof, merkleRoot) [internal]
└── parseTransaction(rawTx) → (outputs[], ...) [internal]
```

### Proof Encoding

```solidity
struct SpvProof {
    uint32 checkpointHeight;      // Anchor checkpoint
    bytes[] headers;              // Header chain (80 bytes each)
    bytes rawTx;                  // Full serialized transaction
    bytes32[] merkleProof;        // Merkle branch
    uint32 txIndex;               // Transaction position in block
    uint32 outputIndex;           // Which output is the payout (vout)
    address borrower;             // Claimed borrower address
}
```

## References

- [BIP 37: Bloom Filtering](https://github.com/bitcoin/bips/blob/master/bip-0037.mediawiki) - Merkle proof format
- [Bitcoin Block Header Structure](https://developer.bitcoin.org/reference/block_chain.html)
- [tBTC v2 SPV Implementation](https://github.com/keep-network/tbtc-v2) - Reference implementation
- [btcrelay](https://github.com/ethereum/btcrelay) - Historical reference

## Changelog

- 2024-02-02: Initial draft accepted
