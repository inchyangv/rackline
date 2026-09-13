# Rackline

**GPU NFTs that borrow against their own revenue — on Creditcoin.**

_Formerly HashCredit (v1, BUIDL CTC Spring 2026 winner)._

Rackline (v2) tokenizes GPU deployments on DePIN compute networks as NFTs, routes each node's payouts into a protocol-controlled Node Account, proves those payouts on Creditcoin with the **Attestcoin Protocol**, and issues stablecoin credit lines that repay themselves from the next payout.

```
Register GPU deployment → mint GpuNodeNFT (Creditcoin)
Network pays the NFT's NodeAccount (Ethereum / Sepolia)
Attestcoin proves the payout on Creditcoin → credit limit
Operator draws stablecoin → NFT locked as collateral
Next payout → sweep → repayFor(tokenId) → debt falls
Sustained default → NFT forecloses to the vault
```

> **Pivot notice (Sep 2026).** Rackline v1 (then HashCredit) — credit against SPV-proven Bitcoin mining payouts — won BUIDL CTC Spring 2026. We pivoted to GPU NFTs because v1 could prove revenue but could not collect on it, and renamed the protocol Rackline to match the asset. Contract, env and API identifiers keep their legacy `HashCredit*` names. The reasoning is in [`docs/hackathon/WHY_WE_PIVOTED.md`](docs/hackathon/WHY_WE_PIVOTED.md); the v2 design is in [`TECH.md`](TECH.md); the production plan is in `PIVOT.md` / `TICKET.md`; the fixed production decisions (R2, official Attestcoin native verification required) are in `docs/gpu/decisions/attestcoin-first.md`. The v1 contracts remain in this repository and on Creditcoin testnet as legacy.

## Status

| Layer | v2 Rackline (GPU NFT) | v1 HashCredit (Bitcoin SPV, legacy) |
|---|---|---|
| Contracts | `GpuNodeNFT`, `AttestcoinRevenueVerifier`, `GpuCreditManager`, `LendingVault` v2, `RiskConfig` v2 — *planned; not implemented in this repository as of 2026-09-14 (hackathon slice: `docs/hackathon/HACKATHON_MVP_SCOPE.md`; gap inventory: `docs/gpu/execution/ATTESTCOIN_GAP.md`)* | `HashCreditManager`, `LendingVault`, `BtcSpvVerifier`, `CheckpointManager`, `RiskConfig`, `PoolRegistry` — deployed to testnet (v1) |
| Source chain | `NodeAccount` (+ registry), `MockDePINPayout` on Sepolia — *planned* | — |
| Off-chain | keeper (proof fetch → record → sweep → repayFor) — *planned* | FastAPI proof builder, SPV prover worker |
| Frontend | Operator / Node / Pool tabs — *planned* | Dashboard / Pool tabs |

Live demo: https://hashcredit.studioliq.com · API: https://api-hashcredit.studioliq.com · Chain: Creditcoin CC3 Testnet (`102031`)

---

## Problem

GPU operators supplying compute to DePIN networks (Aethir Cloud Hosts, GPU.net providers, io.net / Render / Akash suppliers) earn today and get paid in 45–180 days: on Aethir, service fees are claimable after 45 days and rewards vest 30% now / 30% at 90 days / 40% at 180 days. Electricity, hosting and hardware leases are due monthly. Traditional finance lends more than $20B against GPUs — to CoreWeave, Lambda, Crusoe, Fluidstack — but only to companies with hundreds of millions in hardware and audited financials. The long tail has the same asset, the same gap, and no lender.

## Solution

1. **Register** — operator links a provider account; the protocol mints a `GpuNodeNFT` (provider, SKU, hardware hash, source chain, Node Account).
2. **Route** — the NFT's **Node Account** on the payout chain becomes the network's reward / service-fee receiver.
3. **Earn** — the network pays the Node Account; it emits `PayoutReceived(tokenId, token, amount)`.
4. **Prove** — the keeper fetches the Attestcoin proof; `AttestcoinRevenueVerifier` verifies it via the BlockProver precompile (`0x0FD2`) and records `RevenueEvidence`.
5. **Credit** — trailing verified net revenue × advance rate = facility limit.
6. **Draw** — operator borrows stablecoin from `LendingVault`; the NFT locks (no transfer, no receiver / sweep-policy change).
7. **Sweep** — each payout is split by policy; the repayment share reaches the vault through `repayFor(tokenId)`. No repay button.
8. **Default** — draw freeze → sweep ratio up → NFT foreclosure to the vault.

Enforcement is graded E0 (read-only) → E1 (escrow set, revocable) → E2 (payment path locked by the network / contract) → E3 (physical lien). Only E2+ receives funded loans. Evidence is trustless; enforcement is contractual plus on-chain control.

---

## Architecture (v2)

```
┌───────────────────────────┐    ┌──────────────────────────┐    ┌──────────────────────────────────┐
│ Source chain (Sepolia /   │    │ Off-chain                │    │ Creditcoin CC3                   │
│ Ethereum)                 │    │                          │    │                                  │
│  MockDePINPayout ─┐       │    │  keeper                  │    │  GpuNodeNFT  (ERC-721, lien)     │
│  (network stand-in)│      │    │  ├─ watch PayoutReceived │    │  AttestcoinRevenueVerifier       │
│                    ▼      │    │  ├─ GET proof-by-tx      │───▶│  └─ INativeQueryVerifier(0x0FD2) │
│  NodeAccount (per NFT) ───┼───▶│  ├─ recordRevenue        │    │  GpuCreditManager                │
│  ├─ PayoutReceived event  │    │  ├─ sweep()              │    │  ├─ facility per tokenId         │
│  └─ sweep(): repay share  │    │  └─ settlement → repayFor│───▶│  ├─ borrow / repay / repayFor    │
│     → settlement route    │    │                          │    │  └─ freeze / default / foreclose │
│     remainder → operator  │    │  api (provider connectors│    │  LendingVault v2 · RiskConfig v2 │
└───────────────────────────┘    │   for underwriting)      │    └──────────────────────────────────┘
                                 └──────────────────────────┘                    ▲
                                 ┌──────────────────────────┐                    │
                                 │ web: Operator · Node ·   ├────────────────────┘
                                 │ Pool (React 19, ethers 6)│
                                 └──────────────────────────┘
```

### Attestcoin integration

- Source: Ethereum Sepolia (chainkey 1 on CC3 testnet); mainnet path Ethereum mainnet, Arbitrum when supported.
- Proof: `GET https://prover.cc3-testnet.creditcoin.network/proof-by-tx/{chainKey}/{txHash}` (`@gluwa/usc-sdk`).
- Verify: `INativeQueryVerifier(0x0FD2).verifyAndEmit(chainKey, blockHeight, encodedTx, merkleProof, continuityProof)` → `EvmV1Decoder.decodeReceiptFields` → `require(receiptStatus == 1)` → `PayoutReceived` log from the registered `NodeAccount` → `RevenueEvidence`.
- Replay: `keccak256(chainKey, blockHeight, txIndex)`.
- No fallback: a source chain Attestcoin does not support is `UNSUPPORTED_SOURCE` (no admission). Self-signed / relayer-attested evidence never substitutes native verification and there is no lower-advance-rate evidence class (R2-D03/D08 in `docs/gpu/decisions/attestcoin-first.md`).

Details: [`TECH.md`](TECH.md).

### Credit model

```
EligibleRevenue = Σ verified net payouts in window − deductions − haircuts
FacilityLimit   = min(EligibleRevenue × advanceRate, approvedCap)
AvailableDraw   = max(0, min(FacilityLimit − debt − reservedDraws, provider/global headroom, vault cash))
```

Every draw re-checks fresh evidence and valid control state. Credit is never derived from GPU count, FLOPS, advertised utilization or token price. Testnet auto-grant credit does not exist in v2.

### What v2 reuses from v1

| v1 | v2 |
|---|---|
| `IVerifierAdapter` / `PayoutEvidence` | `IRevenueVerifier` / `RevenueEvidence` (same seam, new ABI) |
| `HashCreditManager` | `GpuCreditManager` (facility per NFT, `repayFor`, lien, separate draw / repayment pauses) |
| `LendingVault` | `LendingVault` v2 (single principal / interest ledger, partial interest preserved, reserve, loss recognition) |
| `RiskConfig` | `RiskConfig` v2 |
| `RelayerSigVerifier` | legacy — not a v2 evidence path (auxiliary signatures only, never a native substitute) |
| `BtcSpvVerifier`, `CheckpointManager`, `BitcoinLib`, SPV prover | legacy — not on the v2 path |

---

## Testnet substitutions (demo)

| Real system | Demo |
|---|---|
| Aethir / GPU.net payout contract | `MockDePINPayout` on Sepolia |
| Sepolia → Creditcoin settlement (bridge / partner) | keeper executes the leg with a mock bridge |
| Partner receiver lock (E2) | enforced at the `NodeAccount` controller only; partner-level lock is the Phase 1 PoC |

Mint, Attestcoin verification, limit computation, draw, lien, sweep, `repayFor` and LP accounting are designed to run as real contracts on Creditcoin CC3 testnet; as of 2026-09-14 none of the v2 contracts are implemented or deployed from this repository (planned — see `docs/gpu/execution/ATTESTCOIN_GAP.md`). Debt is reduced only when the vault actually receives stablecoin.

---

## Contract addresses

_Contract, package and service identifiers keep their legacy `HashCredit*` names; the product is Rackline._

**v2 — Creditcoin CC3 Testnet (`102031`)**

| Contract | Address |
|---|---|
| GpuNodeNFT | `<TODO>` |
| AttestcoinRevenueVerifier | `<TODO>` |
| GpuCreditManager | `<TODO>` |
| LendingVault v2 | `<TODO>` |
| RiskConfig v2 | `<TODO>` |
| Stablecoin (mUSDT) | `0xb9D6E174C8e0267Fb0cC3F2AC34130D680151B6A` |

**v2 — Sepolia**: NodeAccountRegistry `<TODO>` · MockDePINPayout `<TODO>`

**v1 — legacy (Creditcoin CC3 Testnet)**

| Contract | Address |
|---|---|
| HashCreditManager | `0x593e140982cDC040d69B7E7623A045C6d6Ca2055` |
| LendingVault | `0x4d74126369BacB67085a1E70d535cA15515d1AFa` |
| CheckpointManager | `0x4Ae5418242073cd37CCc69C908957E413a04f6f9` |
| BtcSpvVerifier | `0x16DEd6a617a911471cd4549C24Ed8C281f096fd2` |

---

## Local development

Prerequisites: [Foundry](https://getfoundry.sh/), Python 3.11+, Node 20+.

```bash
# contracts
forge install && forge build && forge test -vvv

# v2 tests only (once contracts/gpu and test/gpu exist)
forge test --match-path 'test/gpu/*' -vvv

# keeper / api
cd offchain/api && pip install -e . && hashcredit-api
cd offchain/prover && pip install -e . && hashcredit-prover --help   # v1 SPV worker (legacy)

# frontend
cd apps/web && cp .env.example .env && npm install && npm run dev

# full local stack
docker compose up
```

## Project structure

```
contracts/             v1 contracts (legacy) · contracts/gpu/ planned for v2 (not present yet)
test/                  Foundry tests · test/gpu/ planned for v2 (not present yet)
script/                deploy scripts
offchain/
  api/                 FastAPI (v1 proof builder; v2 provider connectors)
  prover/              v1 SPV worker (legacy)
  relayer/             v1 EIP-712 relayer (legacy; not a v2 evidence path)
  keeper/              planned v2 worker (not present yet; see TICKET.md GPU-079)
apps/web/              React 19 frontend
docs/
  hackathon/           WHY_WE_PIVOTED, HACKATHON_MVP_SCOPE, submission checklist & templates
  specs/               v1 protocol specs (legacy)
  adr/                 architecture decision records
PIVOT.md / TICKET.md   v2 production plan and execution tickets (R2) · docs/gpu/ decisions and execution records
```

## Documentation

| Document | Description |
|---|---|
| [`TECH.md`](TECH.md) | v2 technical note: components, Attestcoin integration, credit model, control levels, accounting invariants |
| [`docs/hackathon/WHY_WE_PIVOTED.md`](docs/hackathon/WHY_WE_PIVOTED.md) | Why we moved from Bitcoin hashrate to GPU NFTs |
| [`docs/hackathon/HACKATHON_MVP_SCOPE.md`](docs/hackathon/HACKATHON_MVP_SCOPE.md) | Demo vertical slice: contracts, keeper, UI, build order |
| [`docs/hackathon/SUBMISSION_CHECKLIST.md`](docs/hackathon/SUBMISSION_CHECKLIST.md) | DoraHacks / BUIDL CTC 2026 Fall checklist |
| `PIVOT.md`, `TICKET.md` | Production pivot plan and tickets (partner due diligence, E2 control PoC, accounting core, audit) |
| [`docs/threat-model.md`](docs/threat-model.md), [`docs/audit-checklist.md`](docs/audit-checklist.md) | v1 security docs (to be rewritten for v2) |
| [`docs/specs/`](docs/specs/) | v1 specifications (legacy) |

## License

MIT
