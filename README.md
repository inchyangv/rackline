# HashCredit

**Revenue-Based Financing for Bitcoin Miners on Creditcoin EVM**

HashCredit turns real Bitcoin mining payouts into on-chain credit lines. Miners prove their revenue with SPV proofs — no collateral lockup required.

```
Bitcoin payout (tx) → SPV proof → On-chain credit limit → Borrow / Repay stablecoins
```

## Live Demo

| Component | URL |
|-----------|-----|
| Frontend  | https://hashcredit.studioliq.com |
| API       | https://api-hashcredit.studioliq.com |

> Chain: **Creditcoin EVM Testnet** (chainId `102031`)

---

## Problem

Bitcoin miners earn recurring revenue but face persistent working capital needs — hardware, electricity, facility costs. Existing on-chain lending requires locking collateral, which doesn't model a miner's actual revenue stream. Off-chain credit underwriting is opaque and impossible to verify on-chain.

The root issue: **hashrate — a miner's core productive asset — is invisible on-chain.** There is no trustless way to verify it without relying on a centralized intermediary.

## Solution

The insight: **you can't prove hashrate directly — it's a physical rate. But you can prove its output.**

Every pool payout is a Bitcoin transaction proportional to contributed hash power. That transaction is committed to by Bitcoin's proof-of-work and verifiable by anyone with block headers. Payout history *is* the hashrate record. SPV verification turns that record into trustless on-chain evidence — no oracle, no bridge, no trusted third party.

HashCredit bridges Bitcoin mining economics to Creditcoin's programmable credit layer through **mining pools as institutional counterparties**:

1. **Register** — Mining pool agrees to withhold a repayment percentage from miner payouts (withholding at source)
2. **Prove** — Generate an SPV proof of a real Bitcoin payout transaction
3. **Verify** — On-chain verifier checks checkpoint anchor, header chain PoW, Merkle inclusion, and output script
4. **Credit** — Protocol records the payout (replay-protected) and updates the miner's trailing-window credit limit
5. **Borrow** — Miner borrows USDT against their verified revenue
6. **Auto-Repay** — Pool withholds X% of each subsequent payout; on default, pool redirects miner's hashrate

LP perspective: USDT depositors earn 10% APR — 2-3× standard DeFi rates (Aave USDT ~3-4%, Curve stables ~5-7%) — backed by SPV-proven mining revenue and pool-level enforcement.

---

## Architecture

```
┌─────────────────┐     ┌──────────────────────┐     ┌──────────────────────────┐
│  Bitcoin Network │     │   Off-chain Services  │     │   Creditcoin EVM         │
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
                        │  Dashboard / Checkpoint / Proof       │
                        └──────────────────────┘
```

### On-chain Contracts (Solidity 0.8.24, Foundry)

| Contract | Role |
|----------|------|
| `HashCreditManager` | Borrower registry, payout processing (replay-protected), trailing-window credit limit calculation, borrow/repay routing |
| `LendingVault` | ERC4626-style stablecoin pool — LP deposit/withdraw, debt accounting, fixed-APR interest accrual |
| `BtcSpvVerifier` | Trustless Bitcoin SPV verification — checkpoint anchor, header chain PoW, Merkle inclusion, P2WPKH/P2PKH output parsing |
| `CheckpointManager` | Stores trusted Bitcoin block header checkpoints (height, hash, chainWork, bits, timestamp) |
| `RiskConfig` | On-chain credit policy — advance rate, trailing window, payout thresholds, caps, large-payout discount |
| `PoolRegistry` | Mining pool source eligibility (permissive mode for testnet) |
| `BitcoinLib` | Pure library — double-SHA256, header parsing, PoW validation, Merkle proof, tx output parsing |

Key design: `HashCreditManager` consumes `PayoutEvidence` through an `IVerifierAdapter` interface. This decouples credit logic from verification details, making the protocol portable to new proof sources (e.g., USC).

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

Tabs: **Dashboard** (credit overview, borrow/repay, protocol status, BTC wallet claim, settings) · **Checkpoint** (register Bitcoin block header checkpoint) · **Proof** (build SPV proof + submit payout)

---

## End-to-End Flow

```
1. Register checkpoint          CheckpointManager.setCheckpoint(height, hash, ...)
2. Map borrower ↔ BTC address   BtcSpvVerifier.setBorrowerPubkeyHash(borrower, hash)
3. Register borrower            HashCreditManager.registerBorrower(borrower)
4. Build SPV proof              API fetches headers + raw tx + Merkle branch from Bitcoin RPC
5. Submit proof                 Wallet/worker calls HashCreditManager.submitPayout(proof)
                                  → verifier checks SPV, returns PayoutEvidence
                                  → manager enforces replay protection
                                  → trailing revenue & credit limit updated
6. Borrow / Repay               Borrower signs borrow(amount) or repay(amount)
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
- **Borrower mapping** — Testnet uses operator-registered mappings; mainnet design requires dual-signature claim (EVM + BTC wallet `signmessage` / BIP-322)
- **Risk parameters** — On-chain `RiskConfig` enforces advance rate, trailing window, min payout threshold, new borrower caps, large-payout discount
- **Reentrancy** — CEI pattern + OpenZeppelin `ReentrancyGuard`
- **Pausability** — Owner can pause the manager in emergencies

See [`docs/threat-model.md`](docs/threat-model.md) and [`docs/audit-checklist.md`](docs/audit-checklist.md) for detailed analysis.

---

## USC (Universal Smart Contract) Readiness

HashCredit and Creditcoin's USC share the same architectural principle:

> **Prove a real-world economic event cryptographically → authorize on-chain financial operations.**

USC (Universal Smart Contract) does this for off-chain credit and trade events. HashCredit does it for Bitcoin mining payouts. The proof mechanism differs; the pattern is identical.

USC mainnet was not live during development. Rather than wait, we implemented the same architecture ourselves using BTC SPV as the proof source — so the protocol works now and can attach to USC later without redesigning the core proof-credit separation.

- `IVerifierAdapter` is the seam: new proof sources plug in without touching credit logic
- `LendingVault` accepts any ERC20 token address — swap the stablecoin with zero code changes
- USC integration is an **adapter + wiring task**, not a protocol rewrite

Integration paths: swap vault asset to USC stablecoin, add USC-specific settlement adapter, or run multi-verifier mode alongside BTC SPV.

---

## Testnet Contract Addresses

> Creditcoin EVM Testnet · chainId `102031`

| Contract | Address |
|----------|---------|
| HashCreditManager | `0x3cfb7fcf0647c78c3f932763e033b6184d79a936` |
| LendingVault | `0x60cd9c0e8b828c65c494e0f4274753e6968df0c1` |
| CheckpointManager | `0xe792383beb2f78076e644e7361ed7057a1f4cd88` |
| BtcSpvVerifier | `0x98b9ddafe0c49d73cb1cf878c8febad22c357f33` |
| Stablecoin (cUSD) | `0x9e00a3a453704e6948689eb68a4f65649af30a97` |

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
  web/                 React 19 frontend — dashboard, checkpoint, proof
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
| [`.env.example`](.env.example) | Environment variable reference |

---

## License

MIT
