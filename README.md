# HashCredit

**Revenue-Based Financing for Bitcoin Miners on HashKey Chain**

HashCredit turns real Bitcoin mining payouts into on-chain credit lines. Miners prove their revenue with SPV proofs — no collateral lockup required.

```
Bitcoin payout (tx) → SPV proof → On-chain credit limit → Borrow / Repay stablecoins
```

## Live Demo

| Component | URL |
|-----------|-----|
| Frontend  | https://hashcredit.studioliq.com |
| API       | https://api-hashcredit.studioliq.com |

> Chain: **HashKey Chain Testnet** (chainId `133`)

---

## Problem

Bitcoin miners earn recurring revenue but face persistent working capital needs — hardware, electricity, facility costs. Existing on-chain lending requires locking collateral, which doesn't model a miner's actual revenue stream. Off-chain credit underwriting is opaque and impossible to verify on-chain.

The root issue: **hashrate — a miner's core productive asset — is invisible on-chain.** There is no trustless way to verify it without relying on a centralized intermediary.

## Solution

The insight: **you can't prove hashrate directly — it's a physical rate. But you can prove its output.**

Every pool payout is a Bitcoin transaction proportional to contributed hash power. That transaction is committed to by Bitcoin's proof-of-work and verifiable by anyone with block headers. Payout history *is* the hashrate record. SPV verification turns that record into trustless on-chain evidence — no oracle, no bridge, no trusted third party.

HashCredit bridges Bitcoin mining economics to HashKey Chain's programmable DeFi layer through **mining pools as institutional counterparties**:

1. **Register** — Mining pool agrees to withhold a repayment percentage from miner payouts (withholding at source)
2. **Prove** — Generate an SPV proof of a real Bitcoin payout transaction
3. **Verify** — On-chain verifier checks checkpoint anchor, header chain PoW, Merkle inclusion, and output script
4. **Credit** — Protocol records the payout (replay-protected) and updates the miner's trailing-window credit limit
5. **Borrow** — Miner borrows USDT against their verified revenue
6. **Auto-Repay** — Pool withholds X% of each subsequent payout; on default, pool redirects miner's hashrate

LP perspective: USDT depositors earn fixed APR (currently 8%) — backed by SPV-proven mining revenue and pool-level enforcement.

---

## Architecture

```
┌─────────────────┐     ┌──────────────────────┐     ┌──────────────────────────┐
│  Bitcoin Network │     │   Off-chain Services  │     │   HashKey Chain         │
│  (testnet/main)  │     │   (Railway)           │     │   (Contracts)            │
│                  │     │                       │     │                          │
│  Mining payouts ─┼────►│  API (FastAPI)        │     │  CheckpointManager       │
│  Block headers   │     │  ├─ SPV proof builder │────►│  BtcSpvVerifier          │
│                  │     │  ├─ Checkpoint payload│     │  HashCreditManager       │
│                  │     │  └─ Claim verification│     │  ├─ Credit limit engine  │
│                  │     │                       │     │  ├─ Replay protection    │
│                  │     │  Prover (Worker)      │     │  └─ Borrow/Repay router  │
│                  │     │  └─ Auto-detect &     │     │  LendingVault            │
│                  │     │    submit proofs      │     │  └─ Stablecoin pool      │
│                  │     │                       │     │  RiskConfig              │
│                  │     │  Postgres (state/     │     │  └─ Policy parameters    │
│                  │     │   deduplication)      │     │                          │
└─────────────────┘     └──────────────────────┘     └──────────────────────────┘
                                                              ▲
                        ┌──────────────────────┐              │
                        │  Frontend (Vercel)    │              │
                        │  React 19 + ethers.js ├──────────────┘
                        │  Dashboard / Pool                     │
                        └──────────────────────┘
```

### On-chain Contracts (Solidity 0.8.24, Foundry)

| Contract | Role |
|----------|------|
| `HashCreditManager` | Borrower registry, payout processing (replay-protected), trailing-window credit limit calculation, borrow/repay routing |
| `LendingVault` | ERC4626-style stablecoin pool — LP deposit/withdraw, debt accounting, fixed-APR interest accrual |
| `BtcSpvVerifier` | Trustless Bitcoin SPV verification — checkpoint anchor, header chain PoW, Merkle inclusion, P2WPKH/P2PKH output parsing; on-chain BTC address claim via `claimBtcAddress` (ecrecover + sha256/ripemd160 precompiles) |
| `CheckpointManager` | Stores trusted Bitcoin block header checkpoints (height, hash, chainWork, bits, timestamp) |
| `RiskConfig` | On-chain credit policy — advance rate, trailing window, payout thresholds, caps, large-payout discount |
| `PoolRegistry` | Mining pool source eligibility (permissive mode for testnet) |
| `BitcoinLib` | Pure library — double-SHA256, header parsing, PoW validation, Merkle proof, tx output parsing |

Key design: `HashCreditManager` consumes `PayoutEvidence` through an `IVerifierAdapter` interface. This decouples credit logic from verification details, making the protocol portable to new proof sources.

### Off-chain Services (Python, Railway)

| Service | Role |
|---------|------|
| `offchain/api` | FastAPI — read/verify only: builds SPV proofs + checkpoint payloads and verifies claim signatures; exposes BTC address history via Esplora indexer |
| `offchain/prover` | Background worker — watches BTC addresses, detects qualifying payouts, waits for confirmations, auto-builds and submits SPV proofs |

### Frontend (Vercel)

| Stack | Details |
|-------|---------|
| Framework | React 19 + TypeScript + Vite 7 |
| Styling | Tailwind CSS v4 + shadcn/ui (Radix) |
| State | Zustand 5 |
| Chain | ethers.js v6 |

Tabs: **Dashboard** (credit overview, borrow/repay, BTC wallet link via on-chain sig verification) · **Pool** (LP deposit/withdraw, vault metrics, share management). Checkpoint registration and SPV proof submission are operator functions handled by the off-chain prover worker, not exposed in the user-facing UI.

---

## End-to-End Flow

```
1. Claim BTC address            User signs BIP-137 message → API extracts params →
                                  BtcSpvVerifier.claimBtcAddress(pubKeyX, pubKeyY, hash, v, r, s)
                                  → on-chain ecrecover + ripemd160(sha256(compressed pubkey))
2. Register borrower            HashCreditManager.registerBorrower(borrower, btcPayoutKeyHash)
3. Auto-grant testnet credit    registerBorrower auto-grants 1,000 mUSDT via autoGrantCreditAmount
                                  (testnet only — mainnet credit is driven by SPV-proven payout history)
4. Register checkpoint          CheckpointManager.setCheckpoint(height, hash, ...)
5. Build SPV proof              API fetches headers + raw tx + Merkle branch from Bitcoin RPC
6. Submit proof                 Wallet/worker calls HashCreditManager.submitPayout(proof)
                                  → verifier checks SPV, returns PayoutEvidence
                                  → manager enforces replay protection
                                  → trailing revenue & credit limit updated
7. Borrow / Repay               Borrower signs borrow(amount) or repay(amount)
```

---

## SPV Proof Verification

The proof contains:
- **Checkpoint** — Trusted block header stored on-chain
- **Header chain** — Sequence of 80-byte headers from checkpoint+1 to target block (max 144)
- **Raw transaction** — The Bitcoin payout tx
- **Merkle proof** — Siblings + tx index for inclusion in target block
- **Output index** — Which output pays the miner

On-chain checks:
1. Header chain connects from checkpoint to target (prev-hash linkage)
2. Each header satisfies proof-of-work (hash ≤ target from `bits`)
3. Retarget boundary stays within same 2016-block epoch
4. Target block's Merkle root includes the transaction
5. Specified output pays to the borrower's registered `pubkeyHash` (P2WPKH or P2PKH)
6. Minimum 6 confirmations enforced

---

## Security Model

- **Replay protection** — Each `(txid, vout)` processed exactly once via `processedPayouts` mapping
- **Borrower mapping** — On-chain BTC address ownership via `claimBtcAddress`: user signs a BIP-137 message with their BTC wallet, then `ecrecover` + `ripemd160(sha256(compressedPubKey))` precompiles verify and derive the BTC pubkeyHash entirely on-chain — no trusted oracle required
- **Risk parameters** — On-chain `RiskConfig` enforces advance rate, trailing window, min payout threshold, new borrower caps, large-payout discount
- **Reentrancy** — CEI pattern + OpenZeppelin `ReentrancyGuard`
- **Pausability** — Owner can pause the manager in emergencies

See [`docs/threat-model.md`](docs/threat-model.md) and [`docs/audit-checklist.md`](docs/audit-checklist.md) for detailed analysis.

---

## Why HashKey Chain

Mining-revenue-based lending isn't a purely DeFi-native activity — it requires compliance infrastructure, institutional partnerships, and full EVM capability. HashKey Chain provides all three.

**1. Compliance infrastructure for institutional lending**
Mining pools must contractually agree to withhold repayment from payouts. Borrowers and pools need KYC for legal recourse on default. HashKey Chain is operated by HashKey Group (SFC-licensed in Hong Kong) and built compliance-first — identity tooling, policy controls, and auditability at the protocol level. This makes institutional pool partnerships legally viable.

**2. HashKey ecosystem as distribution channel**
HashCredit needs miners who borrow and LPs who provide liquidity. HashKey Exchange provides fiat on/off-ramps, HashKey Capital provides strategic investment and introductions to mining operators, and HashKey's compliance team enables the legal framework for cross-jurisdictional pool withholding agreements. Hong Kong's position as an Asia-Pacific financial hub — where ~30% of global hashrate operates — is a natural fit.

**3. Full EVM precompile support for trustless BTC verification**
`claimBtcAddress()` proves BTC address ownership on-chain using `ecrecover` (0x01) + `sha256` (0x02) + `ripemd160` (0x03) — all standard EVM precompiles. HashKey Chain (OP Stack) supports these natively. No oracle, no bridge, no custom deployment required.

---

## Modular Proof Architecture

The protocol separates proof verification from business logic through the `IVerifierAdapter` interface — new proof sources (cross-chain oracles, ZK bridges) can be plugged in without touching credit logic:

```
HashCreditManager ──→ IVerifierAdapter.verifyPayout(proof) → PayoutEvidence
                              │
                  ┌───────────┼───────────┐
                  │           │           │
            BtcSpvVerifier  CCIP       ZK Bridge
            (live now)      Adapter    Adapter
```

**BTC identity binding** — `claimBtcAddress()` proves BTC address ownership on-chain using EVM precompiles (`ecrecover` + `sha256` + `ripemd160`). No oracle, no bridge — pure cryptography.

See [`TECH.md`](TECH.md) for full technical details and [`docs/specs/BTC_IDENTITY_BINDING.md`](docs/specs/BTC_IDENTITY_BINDING.md) for the identity binding deep-dive.

---

## Testnet Contract Addresses

> HashKey Chain Testnet · chainId `133`

| Contract | Address | Explorer |
|----------|---------|----------|
| HashCreditManager | [`0x2716cCD5E6ee2845D79cF30657C215e536Ba0F74`](https://testnet-explorer.hsk.xyz/address/0x2716cCD5E6ee2845D79cF30657C215e536Ba0F74) | [View](https://testnet-explorer.hsk.xyz/address/0x2716cCD5E6ee2845D79cF30657C215e536Ba0F74) |
| LendingVault | [`0x3517D3a0dDd4455091d89CaB9Be5df3439bd15fb`](https://testnet-explorer.hsk.xyz/address/0x3517D3a0dDd4455091d89CaB9Be5df3439bd15fb) | [View](https://testnet-explorer.hsk.xyz/address/0x3517D3a0dDd4455091d89CaB9Be5df3439bd15fb) |
| CheckpointManager | [`0xa27281FDFf89A34e842F251224380FC92F4Eb338`](https://testnet-explorer.hsk.xyz/address/0xa27281FDFf89A34e842F251224380FC92F4Eb338) | [View](https://testnet-explorer.hsk.xyz/address/0xa27281FDFf89A34e842F251224380FC92F4Eb338) |
| BtcSpvVerifier | [`0xa7506A5c1C03EE38EdDE1572c55DB339f5FD05c4`](https://testnet-explorer.hsk.xyz/address/0xa7506A5c1C03EE38EdDE1572c55DB339f5FD05c4) | [View](https://testnet-explorer.hsk.xyz/address/0xa7506A5c1C03EE38EdDE1572c55DB339f5FD05c4) |
| Stablecoin (mUSDT) | [`0x73840B35612eA8B13825288F0955A3F552645675`](https://testnet-explorer.hsk.xyz/address/0x73840B35612eA8B13825288F0955A3F552645675) | [View](https://testnet-explorer.hsk.xyz/address/0x73840B35612eA8B13825288F0955A3F552645675) |

---

## Local Development

### Prerequisites

- [Foundry](https://getfoundry.sh/) (forge, anvil, cast)
- Python 3.11+
- Node 20+

### Contracts

```bash
forge install          # Solidity deps
forge build            # Compile
forge test -vvv        # Run tests
forge test --gas-report # Gas profiling
```

### Off-chain API

```bash
cd offchain/api
cp .env.example .env   # Configure
pip install -e .
hashcredit-api         # Start server
```

### Off-chain Prover (Worker)

```bash
cd offchain/prover
cp .env.example .env   # Configure
pip install -e .
hashcredit-prover --help
```

### Frontend

```bash
cd apps/web
cp .env.example .env   # Configure
npm install
npm run dev
```

### Full Local Stack (Docker)

```bash
docker compose up      # Postgres + API + Prover
```

### Makefile Shortcuts

```bash
make build             # forge build
make test              # forge test -vvv
make test-gas          # Gas report
make deploy-local      # Deploy to local Anvil
make anvil             # Start local chain
```

---

## Project Structure

```
contracts/             Solidity contracts + interfaces + mocks + library
test/                  Foundry tests (unit, integration, invariant fuzzing, gas profiling)
script/                Foundry deploy scripts
offchain/
  api/                 FastAPI — proof/checkpoint payload builders, claim verification (no tx submit)
  prover/              Background SPV worker — auto-detect, prove, submit
apps/
  web/                 React 19 frontend — dashboard, pool (user-facing)
docs/
  adr/                 Architecture Decision Records
  specs/               Protocol specifications
  hackathon/           Submission templates
lib/                   Foundry dependencies (forge-std, openzeppelin)
```

---

## Documentation

| Document | Description |
|----------|-------------|
| [`docs/adr/0001-btc-spv.md`](docs/adr/0001-btc-spv.md) | SPV design rationale, checkpoint model, gas budgets |
| [`docs/threat-model.md`](docs/threat-model.md) | Threat analysis and mitigations |
| [`docs/audit-checklist.md`](docs/audit-checklist.md) | Security audit checklist |
| [`docs/gas-limits.md`](docs/gas-limits.md) | Per-operation gas estimates |
| [`docs/specs/PROJECT.md`](docs/specs/PROJECT.md) | Full protocol specification |
| [`docs/specs/USC_ADAPTER.md`](docs/specs/USC_ADAPTER.md) | Cross-chain oracle integration design and transition paths |
| [`docs/specs/BTC_IDENTITY_BINDING.md`](docs/specs/BTC_IDENTITY_BINDING.md) | BTC wallet binding, SPV revenue verification, credit scoring deep-dive |
| [`.env.example`](.env.example) | Environment variable reference |

---

## License

MIT
