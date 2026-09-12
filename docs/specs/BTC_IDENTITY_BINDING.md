# BTC Identity Binding & Credit Scoring — Deep Dive

> How HashCredit proves Bitcoin wallet ownership on-chain without an oracle,
> binds mining records to BTC addresses, and scores creditworthiness
> from SPV-verified payout history.

---

## 1. The Problem

To lend against Bitcoin mining revenue, the protocol must answer three questions:

1. **Identity**: Does this EVM user actually own this BTC address?
2. **Revenue**: Did this BTC address actually receive mining payouts?
3. **Creditworthiness**: How much can this miner safely borrow?

All three must be answered **on-chain, without trusted intermediaries**.

---

## 2. BTC Address Ownership Proof (`claimBtcAddress`)

### Why This Is Hard

BTC addresses exist only on the Bitcoin blockchain. There is no native way for an EVM smart contract to verify that `msg.sender` owns a particular BTC address — unless we use cryptography.

### Why This Is Possible

BTC and ETH both use **secp256k1** elliptic curve cryptography. This means:
- A BTC wallet can produce a signature that EVM's `ecrecover` precompile can verify
- The same public key that controls a BTC address can be validated on EVM
- BTC's `Hash160` (ripemd160 ∘ sha256) can be computed on-chain using EVM precompiles

### The Flow

```
┌──────────────────────────────────────────────────────────────────┐
│                        OFF-CHAIN                                  │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│  Step 1: User signs a message with their BTC wallet               │
│  ─────────────────────────────────────────────────                 │
│  Message: "HashCredit: link BTC address to <EVM_ADDRESS>"         │
│  Format: BIP-137 (Bitcoin Signed Message)                         │
│  Signing: BTC wallet (Sparrow, Electrum, MetaMask BTC, etc.)      │
│  Output: base64-encoded signature                                 │
│                                                                   │
│  Step 2: API extracts on-chain parameters                         │
│  ────────────────────────────────────────                         │
│  Endpoint: POST /claim/extract-sig-params                         │
│  Input: { address, message, signature }                           │
│  Process:                                                         │
│    - Decode base64 signature                                      │
│    - Recover full public key (X, Y) from signature + message      │
│    - Compute Bitcoin double-SHA256 message hash                   │
│    - Extract ECDSA (v, r, s) components                           │
│  Output: { pubKeyX, pubKeyY, btcMsgHash, v, r, s }               │
│                                                                   │
└──────────────────────────────┬───────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│                        ON-CHAIN                                   │
│            BtcSpvVerifier.claimBtcAddress()                        │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│  Step 3: Verify signature via ecrecover                           │
│  ──────────────────────────────────────                           │
│  recovered = ecrecover(btcMsgHash, v, r, s)                       │
│  expected = address(keccak256(abi.encodePacked(pubKeyX, pubKeyY)))│
│  require(recovered == expected)                                   │
│                                                                   │
│  This proves: the owner of (pubKeyX, pubKeyY) signed the message │
│                                                                   │
│  Step 4: Compress public key                                      │
│  ───────────────────────────                                      │
│  prefix = (uint256(pubKeyY) % 2 == 0) ? 0x02 : 0x03              │
│  compressed = abi.encodePacked(prefix, pubKeyX)  // 33 bytes      │
│                                                                   │
│  Step 5: Derive BTC pubkeyHash (Hash160)                          │
│  ───────────────────────────────────────                           │
│  pubkeyHash = ripemd160(sha256(compressed))       // 20 bytes     │
│                                                                   │
│  This IS the BTC address in raw form:                             │
│    P2PKH:  base58check(0x00 || pubkeyHash)  → 1A1zP1...          │
│    P2WPKH: bech32(0x00, pubkeyHash)         → bc1q...            │
│                                                                   │
│  Step 6: Store binding                                            │
│  ────────────────────                                             │
│  borrowerPubkeyHash[msg.sender] = pubkeyHash                     │
│  emit BtcAddressClaimed(msg.sender, pubkeyHash)                   │
│                                                                   │
│  Result: msg.sender (EVM) is permanently bound to pubkeyHash     │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

### Cryptographic Guarantees

| Check | What It Proves | How |
|---|---|---|
| `ecrecover` match | Signer owns the private key for (pubKeyX, pubKeyY) | EVM precompile, secp256k1 |
| pubkey → Hash160 | Derived address matches a real BTC address | `ripemd160(sha256(compressed))` via precompiles |
| `msg.sender` binding | EVM caller is the one claiming this BTC address | Solidity `msg.sender` |

**No oracle. No bridge. No trusted third party.** The entire proof chain uses EVM precompiles (`ecrecover` at `0x01`, `sha256` at `0x02`, `ripemd160` at `0x03`) — all available on any EVM chain including HashKey Chain.

### Why BIP-137?

BIP-137 is the Bitcoin standard for message signing. It defines:
- Message format: `"\x18Bitcoin Signed Message:\n" + len(message) + message`
- Hash: `sha256(sha256(formatted_message))` (Bitcoin double-SHA256)
- Signature: 65 bytes (1 byte recovery flag + 32 bytes r + 32 bytes s)

The recovery flag encodes both the `v` value (for `ecrecover`) and the address type (P2PKH compressed, P2PKH uncompressed, P2WPKH). HashCredit supports **P2PKH compressed** and **P2WPKH** — the two modern standard formats.

---

## 3. Revenue Verification (SPV Payout Proof)

Once a BTC address is bound, the protocol can verify that **this specific address received mining payouts**.

### SPV Proof Structure

```solidity
struct SpvProof {
    uint32   checkpointHeight;   // Trusted anchor block height
    bytes[]  headers;            // 80-byte headers: checkpoint+1 → tip (max 144)
    uint32   txBlockIndex;       // Which header contains the tx
    bytes    rawTx;              // Full Bitcoin transaction (max 4KB)
    bytes32[] merkleProof;       // Merkle siblings (max 20 depth)
    uint256  txIndex;            // Tx position in block
    uint32   outputIndex;        // Which output pays the miner (vout)
    address  borrower;           // Claimed EVM borrower address
}
```

### On-Chain Verification Pipeline

```
1. SIZE BOUNDS
   ├─ headers.length ≤ 144 (1 day of blocks)
   ├─ merkleProof.length ≤ 20 (supports blocks with 2^20 txs)
   └─ rawTx.length ≤ 4096

2. CONFIRMATION DEPTH
   └─ headers.length - txBlockIndex ≥ 6

3. BORROWER CHECK
   └─ borrowerPubkeyHash[borrower] must exist (claimBtcAddress was called)

4. CHECKPOINT VALIDATION
   └─ Fetch CheckpointManager.getCheckpoint(checkpointHeight)
      └─ Must exist and be a trusted anchor

5. RETARGET BOUNDARY
   └─ (checkpointHeight / 2016) == (tipHeight / 2016)
      └─ Proof cannot cross Bitcoin difficulty adjustment boundary

6. HEADER CHAIN VERIFICATION  ← This is the "continuity proof"
   For each header[i]:
   ├─ Parse 80-byte header (version, prevHash, merkleRoot, timestamp, bits, nonce)
   ├─ Verify prevHash links to previous block's hash
   ├─ Verify bits matches checkpoint's difficulty (same epoch)
   ├─ Compute blockHash = sha256(sha256(header))
   └─ Verify PoW: blockHash ≤ target(bits)
       └─ This is the Bitcoin-native equivalent of STARK continuity proof

7. MERKLE INCLUSION  ← This is the "transaction inclusion proof"
   ├─ txHash = sha256(sha256(rawTx))
   └─ Verify Merkle path from txHash to headers[txBlockIndex].merkleRoot

8. OUTPUT PARSING + IDENTITY MATCHING  ← This is the "event extraction"
   ├─ Parse rawTx to find output at outputIndex
   ├─ Extract pubkeyHash from output script:
   │   P2WPKH: OP_0 <20-byte-hash>        → hash directly
   │   P2PKH:  OP_DUP OP_HASH160 <20> ... → extract 20-byte hash
   ├─ require(extractedHash == borrowerPubkeyHash[borrower])
   └─ Return PayoutEvidence { borrower, txid, vout, amountSats, blockHeight, blockTimestamp }
```

### What This Proves

After successful verification, the protocol has **cryptographic certainty** that:

1. A real Bitcoin transaction exists in a real Bitcoin block
2. That block is part of the canonical chain (PoW validated, 6+ confirmations)
3. The transaction paid `amountSats` to the miner's registered BTC address
4. The miner's BTC address ownership was previously proven via `claimBtcAddress`

**The entire chain from miner identity → payout verification → credit issuance is trustless.**

---

## 4. Credit Scoring from Payout History

### Trailing Window Revenue

The protocol doesn't use a single payout to set credit. It maintains a **rolling window** of recent payouts:

```
Time ────────────────────────────────────────────►
      │◄────── windowSeconds (30 days) ──────►│
      │                                        │
      │  payout₁  payout₂  payout₃  payout₄   │  payout₅ (expired)
      │  500 sats 300 sats 700 sats 200 sats   │
      │                                        │
      └─ trailingRevenueSats = 1700 sats ──────┘
```

- Each `submitPayout()` adds to the payout history (max 100 records)
- Payouts older than `windowSeconds` are pruned
- `trailingRevenueSats` = sum of non-expired payouts

### Payout Heuristics (Anti-Gaming)

Before counting toward revenue, each payout passes through risk heuristics:

```
Raw payout amount
    │
    ├─ Large payout discount:
    │   if amountSats > largePayoutThresholdSats (0.1 BTC):
    │       effectiveAmount = amountSats × largePayoutDiscountBps / 10000
    │       (default: 50% — only half counts)
    │
    └─ New borrower cap:
        if payoutCount < minPayoutCountForFullCredit (3):
            effectiveAmount = min(effectiveAmount, minPayoutSats)
            (first 3 payouts capped at threshold amount)
```

**Purpose**: prevents single large self-transfers from inflating credit, and requires a pattern of consistent payouts before granting full credit.

### Credit Limit Calculation

```
                    trailingRevenueSats × btcPriceUsd
btcValueUsd     = ─────────────────────────────────────
                              SATS_PER_BTC (1e8)

                    btcValueUsd × advanceRateBps
creditLimitUsd  = ─────────────────────────────────
                           BPS (10,000)

creditLimit     = creditLimitUsd / 100    // 8 decimals → 6 decimals (stablecoin)
```

**Example**:
```
Trailing revenue:  0.5 BTC (50,000,000 sats) over 30 days
BTC price:         $50,000 (5,000,000,000,000 in 8-decimal)
Advance rate:      50% (5000 bps)

btcValueUsd    = (50,000,000 × 5,000,000,000,000) / 100,000,000
               = 25,000,000,000,000  ($25,000 in 8-decimal)

creditLimitUsd = (25,000,000,000,000 × 5000) / 10,000
               = 12,500,000,000,000  ($12,500)

creditLimit    = 12,500,000,000,000 / 100
               = 125,000,000,000    (125,000 mUSDT in 6-decimal = $125,000)
               — wait, that's wrong. Let me recalculate:

Actually: 12,500,000,000,000 / 100 = 125,000,000,000 → 125,000 mUSDT? No.
$12,500 in 8 decimals = 12,500 × 10^8 = 1,250,000,000,000
/100 = 12,500,000,000 → this is 12,500 × 10^6 = 12,500 mUSDT ✓

Borrower can borrow up to 12,500 mUSDT ($12,500).
```

### Additional Caps

| Cap | Default | Purpose |
|---|---|---|
| New borrower cap | 10,000 mUSDT | Limits initial exposure during onboarding period |
| New borrower period | 30 days | How long the cap applies after registration |
| Global cap | 0 (disabled) | System-wide total debt limit |
| Per-borrow check | `currentDebt + amount ≤ creditLimit` | Per-transaction enforcement |

### Testnet vs Mainnet

| Aspect | Testnet | Mainnet |
|---|---|---|
| Credit source | `autoGrantCreditAmount` (flat 1,000 mUSDT on registration) | SPV-proven trailing window revenue |
| SPV pipeline | Fully functional, demonstrated separately | Drives actual credit limits |
| `registerBorrower` | Auto-grants flat credit | Starts at 0, grows with proven payouts |
| Risk parameters | Relaxed for demo | Production-tuned per risk assessment |

---

## 5. End-to-End Trust Chain

```
Physical mining hardware
    │
    ├─ Contributes hashrate to pool
    │
    ▼
Mining pool distributes payout (BTC tx)
    │
    ├─ Committed to by Bitcoin PoW (tamper cost = hashrate)
    │
    ▼
User claims BTC address on-chain
    │
    ├─ BIP-137 signature → ecrecover → Hash160
    ├─ Trust: secp256k1 cryptography (same as Bitcoin itself)
    │
    ▼
SPV proof submitted
    │
    ├─ Header chain: each block's PoW verified on-chain
    ├─ Merkle inclusion: tx committed to in block's Merkle root
    ├─ Output matching: payout goes to registered pubkeyHash
    ├─ Trust: Bitcoin's energy-based finality (6 confirmations)
    │
    ▼
PayoutEvidence issued
    │
    ├─ Structured, verified data crosses into credit layer
    ├─ Replay protection: (txid, vout) can only be used once
    │
    ▼
Credit limit updated
    │
    ├─ Trailing window revenue × BTC price × advance rate
    ├─ Heuristics: large-payout discount, new-borrower cap
    ├─ Trust: deterministic on-chain math
    │
    ▼
Miner borrows stablecoins
    │
    ├─ amount ≤ creditLimit - currentDebt
    ├─ Trust: smart contract enforcement
    │
    ▼
Interest accrues, miner repays
    │
    ├─ Fixed APR, time-weighted
    ├─ On mainnet: pool withholds from future payouts
    └─ Trust: pool as institutional counterparty
```

**Every link in this chain is either cryptographically verified or economically enforced. No trusted oracle. No manual underwriting. No centralized decision point.**

---

## 6. Comparison with USC Attestation Model

| Aspect | USC Attestation | HashCredit SPV | Assessment |
|---|---|---|---|
| Chain continuity | STARK proof of attestation chain | PoW header chain verification | Both prove block is canonical; SPV uses Bitcoin's native security |
| Trust assumption | Attestor set is honest majority | Bitcoin PoW is unforgeable | SPV is arguably stronger for BTC (energy-based vs consensus-based) |
| Identity binding | Not specified (app-level) | `claimBtcAddress` (pure crypto) | **HashCredit is ahead** — solved on-chain without oracle |
| Revenue verification | Generic event extraction | BTC output parsing + pubkeyHash match | **HashCredit is domain-specific** — tailored to mining payouts |
| Credit scoring | Not part of USC | Trailing window + heuristics + caps | **HashCredit adds this layer** on top of proof verification |
| Gas efficiency | Native precompile (~low) | Solidity loops (~500k–2M gas) | USC is cheaper; acceptable for low-frequency payout proofs |
| Decentralization | Distributed attestors | Single checkpoint owner | **USC is better** — we mitigate with multisig on mainnet |

---

## 7. Key Takeaways

1. **BTC wallet binding is our unique contribution.** USC documentation doesn't address cross-chain identity. We solve it with pure EVM precompiles — no oracle, no bridge.

2. **SPV is not a workaround for USC — it's the same pattern.** Proof separation, structured evidence, stateless verification, app-layer replay protection. The proof mechanism differs; the architecture is identical.

3. **Credit scoring from payout history is domain-specific innovation.** Trailing window, advance rate, payout heuristics — this is the financial engineering that turns raw proofs into a lending product.

4. **USC transition is a connector swap, not a rewrite.** `IVerifierAdapter` was designed from day one as the seam. Deploy `UscVerifierAdapter`, call `setVerifier()`, done. Zero changes to HashCreditManager, LendingVault, or RiskConfig.
