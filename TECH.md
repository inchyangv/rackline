# HashCredit — Technical Note

> SPV-First, Modular, Portable by Design

---

## The Core Insight: Hashrate Is Not a Number, It's a Record

You cannot prove your Bitcoin hashrate directly on-chain. Hashrate is a physical rate — joules per second applied to SHA-256. No contract can observe it directly.

What you *can* prove is the output of hashrate: **pool payouts**.

Every mining pool distributes revenue proportional to contributed hash power. Those distributions are Bitcoin transactions — timestamped, immutable, and verifiable by anyone who has the block headers. Accumulated payout history *is* the observable footprint of hashrate over time.

HashCredit's insight: **prove the payout record, infer the hashrate, issue credit against it.**

This reframes the problem from "prove a rate" to "prove a transaction" — which Bitcoin's own SPV model already solves.

---

## How Hashrate Gets Proven On-Chain

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
SPV proof submitted to HashKey Chain
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

No oracle. No bridge. No custodian. The same verification model Bitcoin light clients have used since 2009 — now running inside a HashKey Chain contract.

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

## Why HashKey Chain

HashCredit is a DeFi lending protocol that underwrites loans based on **verifiable real-world economic activity** — Bitcoin mining revenue. This requires a chain that provides more than just EVM execution. HashKey Chain provides the three missing pieces:

### 1. Compliance Infrastructure for Institutional Lending

Revenue-based lending to miners isn't a purely DeFi-native activity. It involves:
- **Mining pools as counterparties** — pools must agree to withhold repayment from payouts (원천징수). This requires a contractual relationship.
- **KYC/AML for borrowers and pools** — on default, legal recourse requires verified identities.
- **Regulatory clarity** — lending against mining revenue sits at the intersection of crypto finance and traditional credit.

HashKey Chain is operated by **HashKey Group**, a licensed financial institution in Hong Kong (Type 1 & Type 9 SFC licenses). The chain is built compliance-first with identity infrastructure (KYC tooling, policy controls, auditability) at the protocol level. This isn't an afterthought — it's the foundation that makes institutional mining pool partnerships legally viable.

### 2. HashKey Ecosystem as Distribution Channel

HashCredit needs two sides of a marketplace: **miners who borrow** and **LPs who provide USDT liquidity**. HashKey Group's ecosystem accelerates both:

| HashKey Asset | What It Enables for HashCredit |
|---|---|
| **HashKey Exchange** | Fiat on/off-ramp for miners; USDT liquidity source for LPs |
| **HashKey Capital** | Strategic investment; introductions to mining operators |
| **HashKey Cloud** | Node infrastructure; potential validator/operator partnerships |
| **Compliance team** | Legal framework for pool withholding agreements across jurisdictions |

Hong Kong is a natural hub for this — Asia-Pacific hosts ~30% of global hashrate, and HK's regulatory framework for virtual assets (VASP licensing) provides the legal clarity that mining finance requires.

### 3. Full EVM Precompile Support for Trustless BTC Verification

HashCredit's core innovation — **on-chain BTC address ownership proof** — requires three EVM precompiles:
- `ecrecover` (0x01) — verify BTC wallet signature
- `sha256` (0x02) — hash the compressed public key
- `ripemd160` (0x03) — derive the BTC address (Hash160)

HashKey Chain (OP Stack) supports all standard Ethereum precompiles. This means our `claimBtcAddress()` function works natively — **no oracle, no bridge, no custom precompile deployment required**. The same guarantee applies to our full SPV proof verification pipeline (~2-3M gas per proof).

---

## Modular Proof Architecture

HashCredit separates proof verification from credit logic by design:

```
┌──────────────────────────────┐
│        HashCreditManager     │
│  - Credit limit engine       │
│  - Replay protection         │
│  - Borrow / repay routing    │
│                              │
│  calls:  IVerifierAdapter    │ ← proof source is pluggable
└──────────────┬───────────────┘
               │
       ┌───────┴────────┐
       │                │
┌──────▼──────┐  ┌──────▼──────┐
│ BtcSpv      │  │ Future      │
│ Verifier    │  │ Adapter     │ ← Chainlink CCIP, LayerZero, etc.
│ (live now)  │  │             │
└─────────────┘  └─────────────┘
```

This means HashCredit is **not locked into a single proof mechanism**. As HashKey Chain's ecosystem evolves (cross-chain messaging, oracle infrastructure, ZK bridges), new verification adapters can be added without touching credit logic, vault, or risk config.

| Design Principle | Implementation |
|---|---|
| Proof ↔ business separation | `IVerifierAdapter` ↔ `HashCreditManager` |
| Structured evidence | `PayoutEvidence` struct |
| Stateless verifier | `BtcSpvVerifier.verifyPayout()` (no state writes) |
| Replay protection | `processedPayouts[keccak256(txid,vout)]` |
| Checkpoint anchor | `CheckpointManager` trusted headers |

---

## BTC Identity Binding

Cross-chain identity — proving that an EVM address controls a specific BTC address — is an unsolved problem in most ecosystems. HashCredit solves it **on-chain with pure cryptography**:

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

## Roadmap on HashKey Chain

| Phase | Timeline | What |
|-------|----------|------|
| **Testnet (now)** | Q1 2026 | Full protocol deployed on HashKey Chain Testnet — SPV verifier, credit engine, vault, frontend |
| **Audit + Mainnet** | Q2 2026 | Security audit, HashKey Chain mainnet deployment, first 10 pilot miners |
| **Pool Partnerships** | Q3 2026 | Mining pool API integrations, 50 miners, $500K TVL |
| **Scale** | Q4 2026 | Cross-chain oracle adapter (Chainlink CCIP / LayerZero), $5M TVL, 200+ miners |

### Future Proof Source Integration

As HashKey Chain's ecosystem matures, new proof sources can be added via `IVerifierAdapter`:

- **Cross-chain messaging** (Chainlink CCIP, LayerZero) — relay verified BTC payout data from other chains
- **ZK bridges** — zero-knowledge proofs of Bitcoin state for lower gas cost
- **Oracle networks** — price feeds + payout attestations for simplified verification

Each new adapter is a single contract deployment + one `setVerifier()` call. Credit logic, vault, and risk config remain untouched.

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

Everything below runs today on HashKey Chain testnet (chainId `133`):

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

Adding a new proof source is an **adapter + wiring task**. The proof system, credit engine, and vault do not need to change.

---

## Contracts (HashKey Chain Testnet)

| Contract | Address | Explorer |
|----------|---------|----------|
| HashCreditManager | `0x2716cCD5E6ee2845D79cF30657C215e536Ba0F74` | [View](https://testnet-explorer.hsk.xyz/address/0x2716cCD5E6ee2845D79cF30657C215e536Ba0F74) |
| LendingVault | `0x3517D3a0dDd4455091d89CaB9Be5df3439bd15fb` | [View](https://testnet-explorer.hsk.xyz/address/0x3517D3a0dDd4455091d89CaB9Be5df3439bd15fb) |
| CheckpointManager | `0xa27281FDFf89A34e842F251224380FC92F4Eb338` | [View](https://testnet-explorer.hsk.xyz/address/0xa27281FDFf89A34e842F251224380FC92F4Eb338) |
| BtcSpvVerifier | `0xa7506A5c1C03EE38EdDE1572c55DB339f5FD05c4` | [View](https://testnet-explorer.hsk.xyz/address/0xa7506A5c1C03EE38EdDE1572c55DB339f5FD05c4) |
| Stablecoin (mUSDT) | `0x73840B35612eA8B13825288F0955A3F552645675` | [View](https://testnet-explorer.hsk.xyz/address/0x73840B35612eA8B13825288F0955A3F552645675) |
