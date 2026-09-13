# Rackline

**Working capital for GPU operators, secured by revenue they have already earned — on Creditcoin.**

_Formerly HashCredit (v1, BUIDL CTC Spring 2026 winner)._

Rackline (v2) lends stablecoin working capital to operators supplying GPUs to DePIN compute networks, secured by **confirmed, unpaid receivables** assigned to a **controlled payment path**. Source-chain settlement events are verified on Creditcoin through the **official Attestcoin Protocol** (native BlockProver verification, no substitutes), and debt is reduced only when actual settlement cash reaches the vault.

```
Operator onboards → confirmed unpaid settlements assigned → payer pays a controlled escrow (E2, tested)
Settlement event on the source chain → official Attestcoin native verification on Creditcoin
Borrowing base = eligible unpaid receivables × advance rate → operator draws stablecoin
Escrow receipt → approved settlement rail → vault receives loan currency → repayFor → debt falls
```

> **Pivot notice (Sep 2026).** Rackline v1 (then HashCredit) — credit against SPV-proven Bitcoin mining payouts — won BUIDL CTC Spring 2026. We pivoted to GPU receivables because v1 could prove revenue but could not collect on it, and renamed the protocol Rackline. Contract, env and API identifiers keep their legacy `HashCredit*` names. The reasoning is in [`docs/hackathon/WHY_WE_PIVOTED.md`](docs/hackathon/WHY_WE_PIVOTED.md); the design is in [`TECH.md`](TECH.md); the product basis is `PIVOT.md`; the execution ledger is `TICKET.md` (R2); the fixed decisions are in [`docs/gpu/decisions/attestcoin-first.md`](docs/gpu/decisions/attestcoin-first.md). The v1 contracts remain in this repository and on Creditcoin testnet as legacy.
>
> An earlier v2 draft ("GPU NFT credit": tokenized deployments, NFT lien / foreclosure, trailing-payout limits) was retired on 2026-09-14 (R2-D10/D14). NFT-collateral products are a separate, deferred decision.

## Status (as of 2026-09-14)

| Layer | v2 Rackline (GPU receivables, R2) | v1 HashCredit (Bitcoin SPV, legacy) |
|---|---|---|
| Official Attestcoin artifacts | **Pinned** — `@gluwa/usc-sdk` 0.18.0, `@gluwa/asc-contracts` 0.2.1, ABI / source hashes, CC3 testnet manifest, read-only probe (`offchain/attestcoin/`, `config/attestcoin/`, `test/fixtures/gpu/attestcoin/`; GPU-075) | — |
| Native verifier / evidence ledger | `AttestcoinRevenueVerifier`, `EvidenceBook` — *planned* (GPU-078, GPU-031) | `BtcSpvVerifier`, `CheckpointManager` — deployed Spring 2026 |
| Credit / vault contracts | debt ledger, facility manager, `LendingVault` v2, `RiskConfig` v2, `repayFor` router — *planned* (GPU-029~043, 081) | `HashCreditManager`, `LendingVault`, `RiskConfig`, `PoolRegistry` |
| Source chain | controlled escrow / source event contract, TEST_ONLY `MockDePINSettlement` — *planned* (GPU-077, GPU-080) | — |
| Off-chain | official-SDK proof worker, provider connectors, receivable / cash ledgers, settlement adapter — *planned* (GPU-079, 015~028, 040) | FastAPI proof builder, SPV prover worker, EIP-712 relayer |
| Frontend | operator facility / LP / operator console — *planned* (GPU-047~052) | Rackline-branded Borrow / Lend on the v1 contracts (live) |
| Native proof evidence | **none yet** — G-ASC (GPU-080) is the first real public-testnet native verification | n/a |

Implementation inventory and doc-conflict register: [`docs/gpu/execution/ATTESTCOIN_GAP.md`](docs/gpu/execution/ATTESTCOIN_GAP.md). Status ledger: each ticket's `상태` in `TICKET.md`.

Live demo (v1 contracts, Rackline UI): https://hashcredit.studioliq.com · API: https://api-hashcredit.studioliq.com · Chain: Creditcoin CC3 Testnet (`102031`)

---

## Problem

GPU operators supplying compute to DePIN networks (Aethir Cloud Hosts, GPU.net providers, io.net / Render / Akash suppliers) earn today and get paid in 45–180 days: on Aethir, service fees are claimable after 45 days and rewards vest 30% now / 30% at 90 days / 40% at 180 days. Electricity, hosting and hardware leases are due monthly. Traditional finance lends more than $20B against GPUs — to CoreWeave, Lambda, Crusoe, Fluidstack — but only to companies with hundreds of millions in hardware and audited financials. The long tail has the same asset, the same gap, and no lender.

## Solution

1. **Onboard** — the operator's entity, provider account and GPU rights are verified; existing financing and duplicate assignments are checked.
2. **Assign + control** — confirmed, unpaid settlements are assigned to the facility; the payer's receiver is set to a controlled escrow; bypass attempts are tested with a real payment before any funded loan (E2).
3. **Verify** — each source-chain settlement event is proven on Creditcoin through the official Attestcoin native path: `INativeQueryVerifier` (BlockProver precompile `0x…0FD2`) + `EvmV1Decoder` over the verified bytes. Proofs come from the official SDK and are untrusted input.
4. **Base** — eligible unpaid receivables − disputes / refunds / SLA deductions − haircuts, × advance rate. Freshness is bound to a source-authority checkpoint; a past payout is never new borrowing base.
5. **Draw** — the operator borrows stablecoin from the vault; every draw re-checks base, control validity, exposure headroom and vault cash.
6. **Collect** — the payer settles into escrow; funds move to the vault's currency on an approved rail under one settlement ID.
7. **Repay** — only actual receipt at the vault, allocated to the facility (`repayFor`), reduces debt. No repay button. Draw pause never blocks repayment.
8. **Default** — draws freeze → escrow collection continues → grace / cure → reserve, agreed recovery, loss recognition.

Enforcement is graded E0 (read-only) → E1 (escrow set, revocable) → E2 (payer recognizes the assignment; operator cannot change it alone) → E3 (physical lien). Only E2+ receives funded loans. Evidence is natively verified; enforcement is contractual plus payment control.

**Five judgments stay separate** (R2-D05): official proof → *this event occurred on this source*; GPU revenue provenance; current unpaid receivable; E2 control; actual destination cash receipt. Each has its own recorded state (`nativeStatus`, `earningsProvenance`, `controlGrade`, `cashState`).

---

## Architecture (v2, R2 — planned unless marked otherwise)

```
┌─────────────────────────────┐   ┌───────────────────────────────┐   ┌──────────────────────────────────────┐
│ Source chain (Sepolia /     │   │ Off-chain                     │   │ Creditcoin CC3                       │
│ Ethereum; Attestcoin-       │   │                               │   │                                      │
│ supported only)             │   │  proof worker (official SDK)  │   │  AttestcoinRevenueVerifier           │
│                             │   │  ├─ watch settlement events   │──▶│  ├─ INativeQueryVerifier (0x…0FD2)   │
│  approved payer ──▶ escrow ─┼──▶│  ├─ fetch proof (untrusted)   │   │  └─ EvmV1Decoder on verified bytes   │
│  (controlled receiver, E2)  │   │  └─ submit to verifier        │   │  EvidenceBook (canonical events,     │
│  emits atomic receipt event │   │                               │   │    log-level consumption key)        │
│                             │   │  connectors / ledgers (Python)│   │  control registry · debt ledger ·    │
│  settlement rail ───────────┼──▶│  ├─ provider statements       │──▶│  facility manager · borrowing base   │
│  (approved conversion)      │   │  ├─ receivable + cash ledgers │   │  LendingVault v2 · RiskConfig v2     │
│                             │   │  └─ reconciliation, control   │   │  repayFor router (destination cash)  │
└─────────────────────────────┘   │     monitor, settlement adapter│  └──────────────────────────────────────┘
                                  └───────────────────────────────┘                    ▲
                                  ┌───────────────────────────────┐                    │
                                  │ web: facility · LP · operator │────────────────────┘
                                  │ console (React 19, ethers 6)  │
                                  └───────────────────────────────┘
```

### Attestcoin integration (official path only)

Pinned facts: [`docs/gpu/attestcoin/environment.md`](docs/gpu/attestcoin/environment.md) (GPU-075).

- SDK `@gluwa/usc-sdk` 0.18.0; contracts `@gluwa/asc-contracts` 0.2.1; ABI / source sha256 recorded in `config/attestcoin/cc3-testnet.sepolia.json`; `ASC-CHECK` fails on drift.
- CC3 testnet: `INativeQueryVerifier` (BlockProver precompile) `0x0000000000000000000000000000000000000FD2`, ChainInfo `0x…0fd3`, decoder `0x731c345d…9F9f` (code hash pinned). Supported sources by read-only probe (2026-09-13): Sepolia chainKey 1, Ethereum mainnet chainKey 3. CC3 mainnet: Ethereum mainnet chainKey 1 (docs only; no manifest yet).
- Proof service: `GET /api/v1/proof-by-tx/{chainKey}/{txHash}` (primary `proof-gen-api.cc3-testnet…`, alternate `prover.cc3-testnet…`). The response is untrusted input; only the precompile result counts.
- Verification (GPU-078): `verifyAndEmit(chainKey, height, encodedTransaction, merkleProof, continuityProof)` → `EvmV1Decoder.decodeReceiptFields` → `receiptStatus == 1` → expected event from the expected emitter → `EvidenceBook` consumes once (key includes the receipt log ordinal, not just the transaction).
- No fallback: unsupported source ⇒ `UNSUPPORTED_SOURCE`, admission off. Self-signed EIP-712, admin approval, BTC SPV or mock verifiers never produce `nativeStatus=VERIFIED`; there is no lower-advance-rate "attested" class (R2-D02/D03/D08). Writability is not assumed (R2-D09).
- Evidence levels LOCAL / SANDBOX / NATIVE_TESTNET / LIVE / ACCEPTED are never promoted by local passes; the environment is `PROBED`, no native proof has been submitted yet (G-ASC, GPU-080).

Details: [`TECH.md`](TECH.md).

### Credit model (PIVOT §6.3)

```
EligibleReceivables = recognized unpaid receivables
                    − disputes / refunds / SLA / senior deductions
                    − overdue, concentration, FX, recovery-uncertainty haircuts
ReceivableLimit     = EligibleReceivables × advanceRate
FacilityLimit       = min(ReceivableLimit, approved facility cap)
FacilityRoom        = FacilityLimit − principal − unpaid interest − reserved draws
Headroom[category]  = cap − all open exposure in that category − all reservations
AvailableDraw       = max(0, min(FacilityRoom, Headroom[borrower/group/partner/region/global], vault lendable cash))
```

Every draw re-checks fresh evidence and valid control state. Credit is never derived from GPU count, FLOPS, advertised utilization, token price, or past payouts. There is no testnet auto-grant or public owner-key API on the GPU path. GPU-001 (done) isolated the v1 API's register-and-grant route behind a `testnet_demo` profile — the `production` profile holds no admin key and returns 404 — and gated the deploy script's auto-grant to TEST_ONLY tokens on demo chains; the v1 contract's owner-only `grantTestnetCredit` remains as legacy.

### What v2 reuses from v1

| v1 | v2 |
|---|---|
| proof ↔ credit ↔ vault separation (`IVerifierAdapter` seam) | kept as a pattern; new ABI (`IRevenueVerifier` / evidence types, GPU-029) |
| `HashCreditManager` | rewritten: debt ledger + facility manager (`repayFor`, receivables base, separate draw / repayment pauses) |
| `LendingVault` | `LendingVault` v2 (single principal / interest ledger, partial interest preserved, reserve, loss recognition, withdrawal queue) |
| `RiskConfig` | `RiskConfig` v2 |
| `RelayerSigVerifier` + `offchain/relayer` | legacy — not a v2 evidence path (auxiliary signatures only; retire / repurpose is R2-O07) |
| `BtcSpvVerifier`, `CheckpointManager`, `BitcoinLib`, SPV prover | legacy — not on the v2 path |
| wallet UX, design system, Foundry invariant discipline, Railway / Vercel | reused |

---

## Testnet demo path (planned; G-ASC)

| Real system | Public-testnet demo (GPU-080 approval scope required) |
|---|---|
| Aethir / GPU.net settlement | TEST_ONLY `MockDePINSettlement` on Sepolia paying the controlled escrow — `partnerRevenue=SIMULATED` |
| Attestcoin native verification | **real** — official SDK proof + `0x…0FD2` on CC3 testnet |
| Sepolia → Creditcoin settlement rail | mock rail executed by the worker, labelled `Mock settlement` |
| Partner receiver lock (E2) | not demonstrable with a mock payer; real E2 is GPU-009/038 with a real partner |

A public-testnet native proof pass is technical evidence only; it is never partner, E2, cash or business approval evidence. Nothing in this table is implemented as of 2026-09-14.

---

## Contract addresses

_Contract, package and service identifiers keep their legacy `HashCredit*` names; the product is Rackline._

**v2 — Creditcoin CC3 Testnet (`102031`)**: not deployed as of 2026-09-14 (`AttestcoinRevenueVerifier`, `EvidenceBook`, debt ledger / facility manager, `LendingVault` v2, `RiskConfig` v2 — all `<TODO>`). **Sepolia**: controlled escrow / source event contract, TEST_ONLY `MockDePINSettlement` — `<TODO>`.

**v1 — legacy (Creditcoin CC3 Testnet, deployed Spring 2026, not re-verified here)**

| Contract | Address |
|---|---|
| HashCreditManager | `0x593e140982cDC040d69B7E7623A045C6d6Ca2055` |
| LendingVault | `0x4d74126369BacB67085a1E70d535cA15515d1AFa` |
| CheckpointManager | `0x4Ae5418242073cd37CCc69C908957E413a04f6f9` |
| BtcSpvVerifier | `0x16DEd6a617a911471cd4549C24Ed8C281f096fd2` |
| Stablecoin (mUSDT, test) | `0xb9D6E174C8e0267Fb0cC3F2AC34130D680151B6A` |

---

## Local development

Prerequisites: [Foundry](https://getfoundry.sh/), Python 3.11+ (3.13 verified; `.venv-py313`), Node 22+. Reproducible setup and baseline results: [`docs/gpu/execution/BASELINE.md`](docs/gpu/execution/BASELINE.md).

```bash
# contracts (v1 today; contracts/gpu/ + test/gpu/ planned)
forge install && forge build && forge test -vvv

# official Attestcoin artifacts / read-only probe (GPU-075)
npm ci --prefix offchain/attestcoin
npm --prefix offchain/attestcoin run check
npm --prefix offchain/attestcoin run test -- --run
npm --prefix offchain/attestcoin run probe -- --manifest config/attestcoin/cc3-testnet.sepolia.json

# v1 api / prover (legacy)
cd offchain/api && pip install -e . && hashcredit-api
cd offchain/prover && pip install -e . && hashcredit-prover --help

# frontend
cd apps/web && cp .env.example .env && npm install && npm run dev

# full local stack (v1)
docker compose up
```

## Project structure

```
contracts/             v1 contracts (legacy) · contracts/gpu/ planned for v2 (GPU-029+, not present yet)
test/                  Foundry tests · test/gpu/ planned · test/fixtures/gpu/attestcoin/ official ABI copies + probe report
script/                deploy scripts (v1)
config/attestcoin/     official environment manifests (cc3-testnet.sepolia, local-mock) + schema
offchain/
  attestcoin/          official SDK pins, manifest validation, read-only probe (TypeScript; GPU-075)
  api/                 FastAPI (v1 proof builder; v2 connectors planned)
  prover/              v1 SPV worker (legacy)
  relayer/             v1 EIP-712 relayer (legacy; not a v2 evidence path)
apps/web/              React 19 frontend (Rackline UI on v1 contracts)
docs/
  gpu/                 decisions/ (R2 ledger) · execution/ (per-ticket records, gap inventory, baseline) · attestcoin/ (environment ledger)
  hackathon/           WHY_WE_PIVOTED, HACKATHON_MVP_SCOPE (demo slice), submission checklist & templates, v1 history
  specs/, adr/, *.md   v1 specifications and security docs (legacy)
PIVOT.md / TICKET.md   product basis and execution tickets (R2)
```

## Documentation

| Document | Description |
|---|---|
| [`TECH.md`](TECH.md) | v2 technical note: R2 architecture, Attestcoin integration, credit model, control levels, accounting invariants, status |
| [`docs/gpu/decisions/attestcoin-first.md`](docs/gpu/decisions/attestcoin-first.md) | Fixed R2 decisions (R2-D01…D14) and open items |
| [`docs/gpu/execution/ATTESTCOIN_GAP.md`](docs/gpu/execution/ATTESTCOIN_GAP.md) | Implementation inventory and doc-conflict register |
| [`docs/gpu/attestcoin/environment.md`](docs/gpu/attestcoin/environment.md) | Pinned official artifacts, native interface facts, environments |
| [`docs/hackathon/WHY_WE_PIVOTED.md`](docs/hackathon/WHY_WE_PIVOTED.md) | Why we moved from Bitcoin hashrate to GPU receivables |
| [`docs/hackathon/HACKATHON_MVP_SCOPE.md`](docs/hackathon/HACKATHON_MVP_SCOPE.md) | Demo slice (R2-aligned), simulation labels, build order |
| [`docs/hackathon/SUBMISSION_CHECKLIST.md`](docs/hackathon/SUBMISSION_CHECKLIST.md) | DoraHacks / BUIDL CTC 2026 Fall checklist |
| `PIVOT.md`, `TICKET.md` | Product basis and execution tickets (partner due diligence, E2 control PoC, financial core, audit) |
| [`docs/threat-model.md`](docs/threat-model.md), [`docs/audit-checklist.md`](docs/audit-checklist.md) | v1 security docs (legacy; v2 rewrite is GPU-058/065) |
| [`docs/specs/`](docs/specs/) | v1 specifications (legacy) |

## License

MIT
