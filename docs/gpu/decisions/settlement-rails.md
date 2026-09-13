# ADR — Creditcoin ledger, official source verification, assets and settlement rails (GPU-008)

Status: **DRAFT v0.1** (2026-09-14). Fixed parts inherit R2-D01/D02/D07/D08/D09 (`attestcoin-first.md`);
every value that depends on the chosen partner, an issuer, a liquidity venue or a bridge is **UNCONFIRMED**
and enumerated in §7 as `SR-Oxx`. Nothing here is LIVE readiness. Real fund movement stays inside the
authority of GPU-009 (control experiment) and GPU-056/063 (approved pilot).

## 1. Decision (baseline structure — FIXED)

| # | Decision | Basis |
| --- | --- | --- |
| SR-D01 | The loan ledger, credit facility manager, vault and repayment router run on **Creditcoin (CC3)**. Debt exists only there. | R2-D01, PD-01/03 |
| SR-D02 | Facts about the **source chain** (obligation recognized / assigned / corrected, payout received, checkpoint) enter the ledger only through the **official Attestcoin native path**: BlockProver precompile `0x…0FD2` + official `EvmV1Decoder` over the exact verified bytes (GPU-078) → EvidenceBook (GPU-031). | R2-D02/D03 |
| SR-D03 | Funds and facts travel on **different rails**. A proven source event never moves money; money that arrives at the destination never proves a source event. Debt changes only when loan currency is received at the designated destination account/vault **and** allocated to the facility (`repayFor`). | R2-D07, PD-03 |
| SR-D04 | The source-side receiving contract is a **source escrow** we deploy on the source chain (GPU-077 `SourceEscrow`), registered as an emitter for the provider. Payout evidence is the escrow's *measured* ERC20 delta, never a `notify(amount)`. | GPU-076 §4/§5, GPU-077 |
| SR-D05 | Any source chain / asset that is not in the official supported table **and** not confirmed as the partner's real payout rail is `UNSUPPORTED_SOURCE`, `admissionEnabled=false`, `railStatus=DISABLED`. No lower-advance-rate, signed, or "bridge-then-prove" workaround. | R2-D08 |
| SR-D06 | PIVOT §10.2's alternate configuration (vault/escrow on another settlement chain, Creditcoin as evidence ledger only) is **not adopted**. Adopting it is R2-O05 and a product/capital-structure decision by the user. | R2-D01, R2-O05 |
| SR-D07 | Writability (cross-chain claim/receiver changes, trustless bridge) is not part of any rail. Remote control uses real partner authority (GPU-009/038); settlement uses verified rails (GPU-040). | R2-D09 |
| SR-D08 | Every settlement leg (source receipt → conversion → transfer → destination receipt → allocation) carries the **same `settlementId`** (source escrow `settlementSeq`/`settlementId`), so the same money can never reduce debt twice and in-flight amounts are never shown as available cash. | PIVOT §10.3 |

## 2. Official support vs partner reality (2026-09-14)

Official support (docs + read-only probe, `docs/gpu/attestcoin/environment.md` §4; **runtime-unverified for
proofs**, GPU-080):

| Creditcoin env | chainKey → source (EVM chainId) | encoding | status |
| --- | --- | --- | --- |
| CC3 testnet (102031) | 1 → Sepolia (11155111); 3 → Ethereum mainnet (1) | 1 | PROBED |
| CC3 mainnet (102030) | 1 → Ethereum mainnet (1) | 1 | UNCONFIRMED (no RPC probed, no manifest) |

Partner candidates (PIVOT §3; **no partner material received**, GPU-004/005 not started):

| Partner | Rails mentioned in public docs | Natively provable today? | Rail status |
| --- | --- | --- | --- |
| Aethir (Cloud Host) | ATH on Ethereum / Arbitrum (official bridges page), service-fee settlement in ATH with vesting; actual contract/token/chain per host **unknown** | Ethereum mainnet: **maybe** (chainKey 1 on CC3 mainnet) — only if the host's payout/claim contract and token are on Ethereum mainnet and emit a usable event; Arbitrum: **no** (not in the supported table) | `UNCONFIRMED` → DISABLED until GPU-004 delivers contract/token/chain per account |
| GPU.net (supplier) | $GPU rewards on GAN Chain, consumer top-ups on Polygon, Ethereum tokens, RWA settlements | GAN Chain / Polygon: **no** (not supported); Ethereum mainnet: only if supplier payouts are actually settled there | `UNCONFIRMED` → DISABLED until GPU-005 |
| TEST_ONLY MockDePIN (Rackline) | Sepolia (chainKey 1 on CC3 testnet) | yes, by construction (SourceEscrow events) | `TEST_ONLY` — G-ASC only, `partnerRevenue=SIMULATED` |

Consequence (R2-O02/O03): the first production admission needs a partner whose **obligation/assignment**
(not just payout) facts are on an officially supported chain. If GPU-004/005 show payout-only or
API-only facts, first-product admission is **held OPEN**; the product is not silently switched to a
trailing-payout or future-cash-flow design (R2-D06/D10, GPU-072).

## 3. One settlement, one `settlementId` — where each judgment changes

Sample: obligation `inv-2026-08-A` (12,000 USDC-equivalent on the source chain), facility `F1`, draw
executed earlier. Legs are numbered; the right-hand columns say **what changes** and **what does not**.

| Leg | Event / evidence | Trusted party | `nativeStatus` / `cashState` after | Debt / NAV change |
| --- | --- | --- | --- | --- |
| 0 | Issuer emits `ObligationRecognized(inv-A, rev 1)` on the source contract | issuer role on the source contract (partner-recognized) | evidence `NATIVE_ACCEPTED→CONSUMED` once proven & consumed (GPU-078/031) | none (eligibility input only; GPU-035) |
| 1 | Payer transfers 12,000 to `SourceEscrow`; escrow `settle(settlementId=S1)` emits `PayoutReceived(amount = measured delta)` | escrow code (ours, on the source chain); payer registration | after proof+consume: receivable `unpaid −= 12,000`, `cashState = SOURCE_ESCROW` | **none** — source receipt is not repayment (SR-D03) |
| 2 | Conversion source asset → loan currency (approved venue, min-out, price validity, max slippage, liquidity cap) | conversion venue + TREASURY execution policy (GPU-040) | `cashState = IN_FLIGHT`; conversion result recorded with S1 | none; in-flight amount is **not** available cash and **not** NAV |
| 3 | Transfer to the destination repayment account / vault on Creditcoin (bridge / settlement partner) | bridge or settlement partner (**UNCONFIRMED**, SR-O03) | `cashState = IN_FLIGHT` until confirmed receipt | none |
| 4 | Destination receipt confirmed on Creditcoin (vault balance delta + S1 reference) | Creditcoin finality; vault code | `cashState = DESTINATION_RECEIVED` | vault idle cash ↑ (NAV unchanged until allocation? **No**: NAV counts cash held for LPs; unallocated receipts sit in a *pending settlement* bucket that is neither LP cash nor borrower refund until leg 5) |
| 5 | `repayFor(F1, S1, received)` → `DebtLedger.allocate` (fees → interest → principal → excess) | RepaymentRouter role (GPU-039) | `cashState = ALLOCATED` | **debt ↓ by `applied`**; excess → borrower refundable balance (never LP NAV) |
| 6 | Partner API / statement shows "paid" | partner (OFFCHAIN_ASSERTION) | reconciliation only | none |

Rules derived from the table: (a) legs 0–1 are proof legs, 2–5 are money legs; (b) only leg 5 changes
debt; (c) leg 1 must never be double-counted with leg 5 (the `settlementId` links them; a receivable's
`unpaid` decreases at leg 1, the facility's debt at leg 5 — these are different objects); (d) a failure at
legs 2–4 leaves debt unchanged, freezes nothing on the repayment side, and is tracked as an in-flight
exception with owner/retry authority (GPU-024/040); (e) proof outage blocks new facts only — leg 5 via
direct destination receipt still works (PD-06).

## 4. Trust parties and what each one may decide

| Party | May establish | May never establish |
| --- | --- | --- |
| Creditcoin BlockProver + official decoder | that a source log occurred at a proven position | provenance, unpaid balance, control, cash |
| Source escrow (ours, source chain) | measured receipt amounts, settlement ids, obligation state transitions as *emitted by the issuer role* | that the issuer is honest; legal assignment |
| Partner issuer role | obligation recognized / assigned / corrected / cancelled (business facts) | that money arrived |
| Conversion venue | executed price/amount for a leg | destination receipt |
| Bridge / settlement partner | delivery of loan currency to the destination | repayment (needs allocation) |
| Creditcoin vault / ledger | actual destination receipt, allocation, debt | any source fact |
| Underwriter / treasury / guardian (roles) | policy, approval, pause, impairment (OFFCHAIN_ASSERTION inputs) | source facts, native status, cash receipt |

## 5. Assets, conversion, bridge, fees, failure recovery (DRAFT — UNCONFIRMED values)

| Topic | Baseline rule | Unconfirmed input |
| --- | --- | --- |
| Loan currency | one stablecoin on Creditcoin, issuer-supported, real contract, redeemable (TS-O02, R2-O06) | issuer support / contract / liquidity on CC3 mainnet (SR-O01) |
| Source asset | the token the partner actually pays (ATH / $GPU / USDC / …); token-denominated receivables valued at a conservative loan-currency rate with claim/vesting delay (term sheet §5) | per-partner token, decimals, chain (SR-O02) |
| Conversion | allowed venues/routers, min-out, price validity window, max slippage, per-leg liquidity cap, gas/fee payer; TREASURY executes under policy; every leg references `settlementId` | venue list, limits (SR-O04) |
| Bridge / settlement | delivery confirmed only by destination receipt; partner responsibility, fee schedule, failure SLA, who retries | bridge/settlement partner (SR-O03) |
| Finality | source: attestation height only (proofs impossible below it); destination: Creditcoin finalized block | none |
| Fees | conversion + bridge + gas are settlement costs borne per agreement (TS-O06); never netted against debt silently | agreement |
| Failure recovery | in-flight ledger row per leg with owner, state, retry authority; stuck funds are neither LP cash nor repayment; recovery plan per venue | partner procedures |
| Kill switches | new execution, conversion and recovery are controlled **separately** on depeg, token freeze, DEX liquidity loss, bridge outage (PIVOT §10.3) | thresholds (GPU-007/010) |

## 6. Rails manifest (schema)

`config/gpu/schema/settlement-rails-v1.schema.json` defines one **rail manifest** per (provider, environment):
debt chain (Creditcoin id, RPC/explorer allowlists, finality), source chain (EVM id, Attestcoin chainKey,
encoding, attestation genesis, RPC/explorer allowlists, finality = attestation), assets (source token, loan
token, decimals, issuer references), escrow (address or `null` + deployment references), conversion venue
and bridge/settlement entries (each with `status ∈ {UNCONFIRMED, PROBED, APPROVED, DISABLED}`),
`railStatus`, `partnerSourceBinding`, and `evidence` (Attestcoin manifest hash the rail relies on).
`config/gpu/rails/cc3-testnet.mockdepin.draft.json` is the TEST_ONLY instance (Sepolia → CC3 testnet, mock
partner, `railStatus=TEST_ONLY`). No production instance exists; creating one requires SR-O01…O04 answers
and a GPU-062 probe. The validator (`offchain/attestcoin/src/rails.ts`, ASC-CHECK) refuses production rails
with `UNCONFIRMED` legs, invented addresses (`null` is the only honest unknown), or a source chain absent from
the Attestcoin manifest's supported table.

## 7. OPEN items (need user / partner / issuer input)

| ID | Question | Decider | Blocks |
| --- | --- | --- | --- |
| SR-O01 | Loan stablecoin on CC3 mainnet: issuer support, contract, redemption, liquidity (= R2-O06 / TS-O02) | issuer + user | production rail manifest, GPU-006/010 |
| SR-O02 | Chosen partner's real payout **and** obligation contracts: chain id, token, decimals, event authority (= R2-O01/O02) | GPU-004 or GPU-005 | admission, GPU-020/021, GPU-076 EC-O01~O03 |
| SR-O03 | Bridge / settlement partner for source → Creditcoin delivery: responsibility, fees, SLA, recovery (= R2-O05) | user + partner | GPU-040, GPU-056 |
| SR-O04 | Conversion venues and limits (min-out, slippage, price validity, liquidity cap) | treasury policy (GPU-007/010) | GPU-040 |
| SR-O05 | If the partner's obligation facts are API-only: hold admission vs change product (= R2-O03) | user | GPU-010, GPU-072 |
| SR-O06 | Second configuration (vault on another chain) ever? (= R2-O05) | user | none unless chosen |

## 8. NO_GO conditions (this ADR does not soften them)

- Partner payout chain unsupported by Attestcoin and no supported obligation/assignment source ⇒ no launch on
  that partner (R2-D08). Deploying our own emitter elsewhere or proving a post-bridge arrival is not a fix.
- Loan currency without issuer support / redemption on Creditcoin ⇒ no mainnet pilot (SR-O01).
- No verified settlement rail (bridge/venue) with recovery ownership ⇒ no funded draw beyond the approved
  limited experiment (GPU-056).
- Any design that would reduce debt on a source proof, an API "paid" flag, or a cross-chain message ⇒ rejected
  by construction (SR-D03, PD-03).

## 9. Verification performed for this ADR (SPEC, LOCAL)

Sample path (§3) walked against the implemented contracts: `SourceEscrow.settle` (measured delta, settlement
id) → `AttestcoinRevenueVerifier` → `EvidenceBook.consume` → receivable `unpaid` (GPU-035) vs
`DebtLedger.allocate` (debt) — the two decrements are on different objects and only the latter changes
debt/NAV. The rails schema and TEST_ONLY instance validate under ASC-CHECK; a production instance with
unconfirmed legs is rejected (test). No funds moved, no partner contacted, no RPC writes.
