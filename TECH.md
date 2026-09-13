# Rackline — Technical Note

> Rackline, formerly HashCredit. Stablecoin working capital for GPU operators on DePIN compute networks, secured by confirmed unpaid receivables with payment control; source-chain settlement events verified on Creditcoin through the official Attestcoin Protocol; debt reduced only by actual destination cash receipts.
> v1 (Bitcoin SPV) technical note is archived in git history and under `archive/v1-btc/` (local).
>
> **Basis and status (2026-09-14).** Product basis: `PIVOT.md`. Execution ledger: `TICKET.md` (R2, 83 tickets). Fixed decisions: `docs/gpu/decisions/attestcoin-first.md` (R2-D01…D14). Official artifact facts: `docs/gpu/attestcoin/environment.md` (GPU-075). Implementation inventory: `docs/gpu/execution/ATTESTCOIN_GAP.md`. **Only the official Attestcoin artifact pins, manifests and read-only probe exist in code; every verifier, source contract, worker, credit contract and UI below is planned.** Contract and function names are design proposals until the owning ticket lands. The earlier "GPU NFT credit" draft (NFT lien / foreclosure, trailing-payout limits, attested fallback) is retired (R2-D10/D14).

---

## 1. The core idea

A lender needs three things from a cash flow: to identify it, to control it, and to verify it. Bitcoin hashrate offered none of these without a mining pool's cooperation. A confirmed receivable owed to a GPU operator by a DePIN network offers all three:

- **Identify** — a named payer, a settlement / statement ID, a period, gross and net amounts, a due date.
- **Control** — the payer settles to a receiver it records; that right can be assigned, and with the payer's recognition the operator cannot redirect it alone (E2).
- **Verify** — settlement events on Attestcoin-supported chains are finalized EVM transactions that Creditcoin proves natively.

Rackline finances that receivable and controls the payment path. It does not lend against hardware value, token price, GPU count, or past payouts.

```
Operator onboards → confirmed unpaid settlements assigned → payer pays a controlled escrow (E2, tested)
Settlement event on the source chain → official Attestcoin native verification on Creditcoin → EvidenceBook
Eligible unpaid receivables × advance rate → facility room → operator draws stablecoin
Escrow receipt → approved settlement rail → vault receives loan currency → repayFor(facility) → debt falls
```

Two rules from the v1 post-mortem govern everything: no funded loan unless the contracted repayment can be collected without the borrower's further consent; no borrowing base on a source-chain fact that is not natively verified on Creditcoin.

---

## 2. Five judgments, kept separate (R2-D05)

| Judgment | Question | Evidence | Recorded as |
|---|---|---|---|
| (a) Source event | Did this settlement event occur on this source chain? | Official Attestcoin native verification | `nativeStatus` |
| (b) Provenance | Is it GPU operating revenue from an approved payer / account? | Provider connector, control agreement, underwriting | `earningsProvenance` |
| (c) Receivable | Is it currently unpaid, eligible, and not already financed? | Source-authority checkpoint / revision, receivable ledger, reconciliation | receivable ledger state |
| (d) Control | Can the borrower bypass the payment path alone? | Payer-recognized assignment, proven by a real control test | `controlGrade` |
| (e) Cash | Did the designated vault actually receive loan currency for this facility? | Destination receipt + facility allocation (`repayFor`) | `cashState` |

Consequences: a proof is not revenue; a past payout event is history, not a receivable; source receipt, claimable amount, cross-chain message or proof is not repayment; an API watermark or "no paid event seen" is not freshness. Our own statement-hash anchors emitted on a supported chain are `OFFCHAIN_ASSERTION`, never native GPU revenue (R2-D04).

---

## 3. Components (planned; owner tickets in parentheses)

### 3.1 Creditcoin CC3 (credit layer)

| Component | Responsibility |
|---|---|
| `AttestcoinRevenueVerifier` (GPU-078) | The only path to `nativeStatus=VERIFIED`. Calls the official `INativeQueryVerifier` precompile with the pinned ABI, decodes the *verified* bytes with the pinned `EvmV1Decoder`, requires `receiptStatus == 1`, and extracts the expected event from the expected emitter. Rejects unpinned manifests, mock profiles in native / production, and any downgrade. |
| `EvidenceBook` (GPU-031) | Canonical record of accepted source events. Consumption key = canonical source identity + proof-bound transaction position + receipt log ordinal (query-cache key ≠ consumption key). Corrections as reversal / delta referencing the original. Separates official verification results from auxiliary approvals. |
| Payment-control registry (GPU-032) | Records control agreements (E-grade, receiver, change / release rights, agreement hash, validity, precedence, last confirmation). A recorded right; `isLocked=true` alone is never E2. |
| Debt ledger + facility manager (GPU-033, 035, 036) | Single source for principal / unpaid interest / fees per facility; exact interest accrual; on-chain borrowing base, concentration headroom and execution reservations; atomic approved draws; separate draw pause and repayment pause. |
| `LendingVault` v2 (GPU-034, 042) | Stablecoin LP pool: cash / loan receivable / NAV; protected shares; first-loss reserve; loss recognition; withdrawal queue; loss attribution. |
| Source escrow, waterfall, `repayFor` router (GPU-037, 039) | Escrow accounting, contractual waterfall, residual return, release on full repayment. `repayFor` allocates actual destination receipts to a facility; nothing else reduces debt. |
| Partner control / settlement adapters (GPU-038, 040) | Real partner authority for payment control; verified settlement rails (conversion, bridge / partner, destination receipt) under one settlement ID. Writability is not assumed (R2-D09). |
| Delinquency / default / recovery (GPU-041), governance & pause (GPU-043) | Grace, cure, reserve use, impairment, write-off (not forgiveness), recoveries; draw pause ≠ repayment pause; key rotation. |

### 3.2 Source chain (Attestcoin-supported only; Sepolia on CC3 testnet)

| Component | Responsibility |
|---|---|
| Controlled escrow / source event contract (GPU-077) | Receives payer settlements for a facility; emits the atomic receipt event in the same transaction as the value transfer (no arbitrary `notify(amount)`, no balance re-reporting); receiver / policy changes only under the recorded control agreement. Minimal logic on the source chain; business logic lives on Creditcoin. |
| `MockDePINSettlement` (TEST_ONLY, GPU-080) | Public-testnet stand-in for the payer used only for G-ASC with `partnerRevenue=SIMULATED`. Never a production provider; never evidence of E2. |

If the chosen partner's real settlement chain is not officially supported, that path is `UNSUPPORTED_SOURCE` and admission stays off. Deploying our own emitter on a supported chain or proving only a post-bridge arrival does not prove the original chain's payment (R2-D08).

### 3.3 Off-chain

| Service | Responsibility |
|---|---|
| `offchain/attestcoin/` — **exists** (GPU-075) | Official SDK pins (`@gluwa/usc-sdk` 0.18.0, `@gluwa/asc-contracts` 0.2.1), manifest schema / validation, ABI drift checks, read-only probe. Commands: `ASC-CHECK`, `ASC-TEST`, `ASC-PROBE`. |
| Proof worker (GPU-079) | Watches source events, fetches proofs through the official SDK (untrusted input), submits to the verifier with durable jobs and idempotency, records `nativeStatus` only from the on-chain result. Narrow TypeScript package with versioned JSON to Python; the SDK is never bundled into the web app. |
| Connectors / ledgers (GPU-015~028, 073) | Provider read connectors (Aethir, GPU.net), receivable classification and eligible borrowing base, cash receipt reconciliation, durable jobs / outbox, EVM dispatcher, on-chain projector, underwriting / limits / overrides, auxiliary signatures (never native substitutes). |
| Control monitor / recovery workflow (GPU-044) | Control validity, expiry, breach detection, recovery cases. |
| `api` (GPU-045) | GPU product API and read model; authorized mutations only; no owner keys. |
| `web` (GPU-047~052) | Operator facility (draw / repay / release), LP (assets, realized income, exposure, withdrawals), operator console (underwriting, reconciliation exceptions, recovery). Today: Rackline-branded Borrow / Lend on the v1 contracts with every unavailable step labelled. |

---

## 4. Attestcoin integration (official path; facts from `docs/gpu/attestcoin/environment.md`)

```
Source chain                Proof worker (official SDK)         Creditcoin
─────────────────────────   ─────────────────────────────────   ──────────────────────────────────────────────
payer settles into escrow   GET /api/v1/proof-by-tx/            AttestcoinRevenueVerifier.recordEvent(proof)
→ receipt event in tx T,      {chainKey}/{T}                      INativeQueryVerifier(0x…0FD2)
  block B                   → txBytes, merkleProof,                 .verifyAndEmit(chainKey, B, encodedTx,
                              continuityProof                                     merkleProof, continuityProof)
                            (untrusted input; success:true         EvmV1Decoder.decodeReceiptFields(encodedTx)
                             from the service ≠ verified)          require(receipt.receiptStatus == 1)
                                                                   log = expected event from expected emitter
                                                                   EvidenceBook.consume(canonical id, txIndex
                                                                     from calculateTxIndex(proof), log ordinal)
```

Pinned facts (GPU-075, read-only probe 2026-09-13T22:14Z):

- `INativeQueryVerifier` precompile `0x0000000000000000000000000000000000000FD2`: `verify(...)` (view, reverts on invalid proof), `verifyAndEmit(...)` (emits `TransactionVerified(chainKey, height, transactionIndex)`), batch variants, `calculateTxIndex(MerkleProof)`. Native precompiles have `extcodesize == 0`; empty bytecode is not evidence of absence.
- `EvmV1Decoder` (pure library): `decodeReceiptFields` → `receiptStatus`, `receiptLogs[]{address_, topics[], data}`; `getLogsByEventSignature`. Encoding = SDK `EncodingVersion.V1`. Official sources use `pragma ^0.8.28`; `contracts/gpu/` needs a matching Foundry profile (compat item E1).
- ChainInfo precompile `0x…0fd3`: `get_supported_chains()` = Sepolia (chainKey 1, chainId 11155111) and Ethereum mainnet (chainKey 3) on CC3 testnet; latest attestation height per chain.
- CC3 testnet decoder contract `0x731c345d79Fb8BbDC541f9DF3b6317585F849F9f` (code hash pinned; the app decodes with the pinned library, it does not `delegatecall` an address it does not control).
- Proof service (SDK 0.18.0): primary `proof-gen-api.cc3-testnet.creditcoin.network`, alternate `prover.cc3-testnet.creditcoin.network`; `cached` / `generatedAt` / `txHash` / `txIndex` are hints, not proven values.
- CC3 mainnet: docs-only values, no manifest, `UNCONFIRMED` until a read-only probe with a confirmed RPC (GPU-062).

Rules enforced in the verifier (GPU-078 / GPU-082):
- Manifest pinned by hash; `executionProfile ∈ {LOCAL_MOCK, NATIVE_TESTNET, PRODUCTION}`; a `LOCAL_MOCK` manifest can never be used in a native or production profile; no `latest`, no invented address.
- `receiptStatus == 1` is mandatory (the precompile does not check transaction success).
- The event must come from the registered emitter for that facility on that `chainKey`; other logs are ignored; the same log is consumed once.
- HTTP 200, SDK `success:true`, keeper signature, Anvil precompile doubles or skipped tests never produce `nativeStatus=VERIFIED` (R2-D12).
- No fallback verifier. `RelayerSigVerifier` (v1 EIP-712) is legacy and never a v2 evidence path; auxiliary signatures (wallet auth, agreement consent, underwriting approval) use separate domains and never create borrowing base (R2-D03/D04).

---

## 5. Credit model (PIVOT §6.3)

```
EligibleReceivables = recognized unpaid receivables
                    − disputes / refunds / SLA / senior deductions
                    − overdue, concentration, FX, recovery-uncertainty haircuts
ReceivableLimit     = EligibleReceivables × advanceRate
FacilityLimit       = min(ReceivableLimit, approved facility cap)
FacilityRoom        = FacilityLimit − principal − unpaid interest − reserved draws
Headroom[category]  = cap − all open exposure in that category − all reservations   (borrower / group / partner / region / global)
AvailableDraw       = max(0, min(FacilityRoom, Headroom[...], vault lendable cash))
```

Freshness (R2-D06, GPU-076): a receivable is current only against a source-authority checkpoint / revision or an approved bounded-lag / buffer / reservation policy. Inclusion of a past event does not prove current unpaid status or the absence of later paid / cancel / correction events; an old proof cannot refresh freshness; without a freshness guarantee new draws are blocked. Paid events reduce the receivable and are matched to cash receipts; they never create new base. Token-denominated receivables are valued conservatively in the loan currency with vesting / claim / transfer delays checked against maturity.

Every draw re-evaluates the formula with current evidence and current control state. A stale "locked" observation does not authorize a draw. Credit is never derived from nominal GPU count, FLOPS, advertised utilization, or token price appreciation. No testnet auto-grant or public owner-key API exists on the GPU path. GPU-001 (done) moved the v1 API's register-and-grant route into a `testnet_demo` profile (production: no admin key, route 404) and gated deploy-script auto-grant to TEST_ONLY tokens on demo chains; the v1 contract's owner-only `grantTestnetCredit` remains legacy. GPU-002 (done) pinned the known v1 accounting / address-binding defects as regression vectors for v2 acceptance.

Illustrative only: eligible unpaid receivables $20,000, advance rate 50%, approved cap $8,000, debt $3,000, reservations $1,000 → additional draw $4,000 before liquidity and headroom limits. The 50% and $8,000 are calculation examples, not market terms.

---

## 6. Payment control, states and default (PIVOT §4–5)

| Level | State | Lending |
|---|---|---|
| E0 | Read-only API, signatures, payout history | Observe only |
| E1 | Escrow set as receiver, operator can still change or revoke it | Observe + control experiments |
| E2 | Payer recognizes the assignment / control; operator cannot change the receiver alone while debt is open; revenue controlled for the agreed period | Underwritten confirmed receivables; limited cash-flow facilities |
| E3 | E2 + physical lien, custodian consent, removal restrictions, takeover / disposal procedure | Equipment purchase financing (separate approval) |

E2 is proven per partner by real control experiments (PIVOT §4.3: receiver / claim / unstake / account changes, admin bypass, lock-vs-draw races, actual receipt with no borrower signature) in a partner-approved environment (GPU-009). "GPU can be remotely stopped" is not a recovery source.

Facility states: `Draft → UnderReview → ControlPending → Active → Repaid → Released`; recovery branch `Active → DrawFrozen → Delinquent → Defaulted → Recovery → ClosedWithLoss`.

On breach or delinquency: new draws stop; escrow collection continues; incident scope is fixed; grace / cure; then agreed reserve, additional cover, operational takeover or collateral disposal (E3 only); loss recognized against reserve first, then LP NAV. Utilization drops are a signal, not a default. Oracle / proof-service outage blocks new evidence-dependent draws and never triggers auto-default, global repayment pause, or forced disposal.

What is not on-chain: legal assignment of receivables, the operator / control agreement, and any hardware lien. They are prerequisites tracked per facility (`controlAgreementHash`, version, validity) and verified off-chain before `ControlPending → Active`.

---

## 7. Accounting invariants (v2 ledger; PIVOT §5.2, TICKET §0.3)

- One calculation source for principal, unpaid interest, fees, recoveries and losses; borrower receivables are borrowing base, never added to vault loan receivables as LP assets.
- Partial interest payment reduces unpaid interest only and never resets the accrual timestamp; rate changes open a new accrual segment.
- Source-chain receipt, in-flight settlement, and destination vault receipt are three states; only the last, allocated to the facility, reduces debt. The same amount is never deducted on both chains.
- Caps count all open exposure plus execution reservations in the category; loan reservation nonces are distinct from EVM nonces.
- Write-off is not forgiveness; borrower-owned reserve, excess receipts and refund obligations are never mixed with LP cash; excess receipts are never auto-applied to another borrower.
- Draw pause never blocks `repay` / `repayFor`; the v1 global pause (which blocks repayment) is not reused for recovery.
- `Σ LP claims + reserve + protocol fees = vault cash + outstanding principal − recognized losses` (checked by an independent reference model, GPU-012/055).

Regression vectors from the v1 review (e.g. $5,000 at 10% for one year, $250 partial interest → remaining $5,250, not $5,000) become fixtures in the v2 suite (GPU-002/014).

---

## 8. What is reused from v1

| v1 | v2 |
|---|---|
| proof ↔ credit ↔ vault separation | kept as a pattern; new ABI (GPU-029) |
| `HashCreditManager` | rewritten as debt ledger + facility manager (`repayFor`, receivables base, separate pauses) |
| `LendingVault` | `LendingVault` v2 (corrected accounting, reserve, loss recognition, withdrawal queue) |
| `RiskConfig` | `RiskConfig` v2 (receivable eligibility, freshness, haircuts, caps) |
| `RelayerSigVerifier`, `offchain/relayer` | legacy; not a v2 evidence path (auxiliary signatures only; R2-O07 decides retire / repurpose) |
| `BtcSpvVerifier`, `CheckpointManager`, `BitcoinLib`, prover worker | legacy; not on the v2 path |
| Wallet UX, Zustand stores, design system, Foundry invariants, Railway / Vercel | reused |

---

## 9. Testnet demo substitutions (G-ASC; stated for judges)

| Real system | Public-testnet demo |
|---|---|
| Aethir / GPU.net settlement | TEST_ONLY `MockDePINSettlement` on Sepolia → controlled escrow; `partnerRevenue=SIMULATED` |
| Attestcoin native verification | **real**: official SDK proof + `0x…0FD2` on CC3 testnet |
| Sepolia → Creditcoin settlement rail | mock rail executed by the worker, labelled `Mock settlement` |
| Partner receiver lock (E2) | not demonstrable with a mock payer; real E2 is GPU-009/038 |
| Provider statements | fixture data |

Requires the GPU-080 approval scope (dedicated wallet, gas / test tokens, contracts, period). A native proof pass is technical evidence only (`NATIVE_TESTNET`), never partner / E2 / cash / business evidence, and never promotes LOCAL results. **Nothing in this table is implemented as of 2026-09-14.**

---

## 10. Status and contracts

| Item | State (2026-09-14) |
|---|---|
| Official artifacts, manifests, probe | done (GPU-075); CC3 testnet `environmentStatus=PROBED`, manifest hash recorded in `docs/gpu/attestcoin/environment.md` |
| v2 contracts on Creditcoin CC3 testnet (`102031`) | not deployed; addresses `<TODO>` |
| Source contracts on Sepolia | not deployed; `<TODO>` |
| Native proof evidence | none; G-ASC (GPU-080) pending approval scope |
| Legacy v1 (Creditcoin CC3 testnet, deployed Spring 2026, not re-verified here) | HashCreditManager `0x593e140982cDC040d69B7E7623A045C6d6Ca2055`, LendingVault `0x4d74126369BacB67085a1E70d535cA15515d1AFa`, BtcSpvVerifier `0x16DEd6a617a911471cd4549C24Ed8C281f096fd2`, CheckpointManager `0x4Ae5418242073cd37CCc69C908957E413a04f6f9`, mUSDT `0xb9D6E174C8e0267Fb0cC3F2AC34130D680151B6A` |

Verification commands that exist today: `git diff --check`, `forge build --sizes && forge test --summary && forge fmt --check` (v1), pytest for `offchain/{api,prover,relayer}`, web lint / build, `ASC-CHECK` / `ASC-TEST` / `ASC-PROBE`. `ASC-NATIVE`, `PY-GPU`, `WEB-TEST`, `V2-E2E` do not exist yet (GPU-080/015/052/057).
