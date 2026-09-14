# Live payer-persona and credit-operation scenarios (TEST_ONLY deployment)

Companion to [`live-user-scenarios.md`](live-user-scenarios.md). That catalog covers personas of *our* product
(visitor, LP, borrower, operator, attacker). This one covers the counterparties we do not control — the
DePIN networks that pay a GPU operator — and the credit operations that only make sense once such payers exist:
partial payments, adjustments, chargebacks, cancelled invoices, overdue invoices, freezes, delinquency, third-party
repayment.

Runner: `apps/web/scripts/live-payer-scenarios.mjs`. Source-side tooling: `script/gpu/payer_sim.mjs`.
Persona registry: `config/gpu/scenarios/payer-personas.json`. Evidence: `evidence/native-testnet/qa-<date>/`.

## How Aethir and GPU.net are mocked

There is no Aethir or GPU.net integration in this repository (no API credentials, no partner binding, no
recognised settlement path — `partnerSourceBinding=UNCONFIGURED`). What we can mock honestly is their
*settlement behaviour*, because the credit product only ever sees a payer through the source escrow's events:
an obligation is recognised, assigned, corrected, paid, reversed, or cancelled.

Each persona is a `MockDePINPayout` contract deployed on Sepolia and registered as a **PAYER** on the
TEST_ONLY `SourceEscrow`. It pays through the real token path (`approve` + `settle`), so the escrow measures
what actually arrived and the resulting `PayoutReceived` log is proven and consumed on Creditcoin exactly like a
partner payout would be. The issuer role (our deployer key, TEST_ONLY) recognises the obligations "on behalf of"
the persona and applies its adjustments.

| Persona | Payer contract (Sepolia) | Imitates | Behaviours exercised |
| --- | --- | --- | --- |
| `SIM-AETHIR` | `0x0a2586d583acdd3aff95e5aac0f1f9dd754e5103` | Aethir-style Cloud Host rewards: one reward obligation per epoch, paid in full after the epoch closes, QoS/uptime adjustments before payment | epoch obligations, full settlement, `SLA` correction (−) |
| `SIM-GPUNET` | `0xdd8a4237bff5978fbb63d42480937b58c64c9982` | GPU.net-style marketplace invoices: one invoice per job, streaming partial settlements, disputes, chargebacks | job invoices, partial payouts, `cancelPayout` chargeback, `CANCEL` correction, overdue invoice |

Everything they pay is faucet test USD with `earningsProvenance=SIMULATED`. The persona names are prefixed
`SIM-` on purpose; nothing here is partner revenue, a partner acknowledgement, or E2 with a real payer.
Both personas pay into the same operator account (`mockdepin-testonly:native-integration`) — one GPU operator,
several networks — and their receivables are assigned to separate facilities so each persona's cycle can be
audited on its own.

## Scenario matrix

Facilities: `gpu080-facility-v5` (SIM-AETHIR), `gpu080-facility-v6` (SIM-GPUNET), `gpu080-facility-v7` (browser
regression). All three were opened with `native_tools.mjs open-facility` (11 Creditcoin transactions each) and
imported into the API with `bootstrap_native --facility-name`.

| ID | Persona | Scenario | Expected result | Real tx |
| --- | --- | --- | --- | --- |
| P0 | Operator | Persona payers exist | Both payer contracts have code, are registered PAYERs bound to the escrow, declare `simulatedRevenue=true`, hold faucet tokens, are not the borrower wallet | no |
| P1 | SIM-AETHIR | Epoch rewards recognised and assigned | epoch-1/2/3 (12 tUSD each) → v5, epoch-4 (10 tUSD) → v7; account revision +8, open amount +46 | Sepolia ×8 |
| P2 | SIM-AETHIR | Epoch-1 paid in full | measured payout 12 = declared; obligation PAID; tokens left the payer | Sepolia ×1 |
| P3 | SIM-AETHIR | QoS adjustment | `correctObligation(−2, SLA)` on epoch-2 → net 10, still OPEN and assigned | Sepolia ×1 |
| P4 | SIM-GPUNET | Job invoices recognised and assigned | job-1 (8), job-2 (6, due in 45 s → overdue before financing), job-3 (5) → v6 | Sepolia ×6 |
| P5 | SIM-GPUNET | Streaming partial settlements | 3 then 2 tUSD on job-1; paid 5/8; sequences increase | Sepolia ×2 |
| P6 | SIM-GPUNET | Chargeback | `cancelPayout` of the second stream; paid back to 3; 2 tUSD returned to the payer; second cancel reverts | Sepolia ×1 |
| P7 | SIM-GPUNET | Dispute cancels an invoice | `correctObligation(−5, CANCEL)` on job-3 → CANCELLED, net 0; paying it reverts | Sepolia ×1 |
| P8 | Misuse | Source-side misuse | unregistered payer, stranger issuer, unknown obligation, overpayment, cancel leaving an open amount, unknown account, non-admitted token → named reverts | no |
| P9 | Stranger | Direct deposit | `depositUnattributed` lands in the unattributed bucket (THIRD_PARTY_UNKNOWN); paid total and revision untouched; topic not a registered evidence meaning | Sepolia ×1 |
| N1 | Keeper | Official proofs | every pending persona transition becomes `PROOF_READY`, bound to the release manifest | no |
| N2 | Keeper | Consumption in source order | 20 consumptions audited proof-only; `eventsConsumed == source revision`; open/paid totals reconcile; epoch-1 PAID, epoch-2 net 10, job-1 paid 3, job-3 CANCELLED; debt 0 | CC3 ×20 |
| N3 | Misuse | Replay | consumed `sourceEventId`; tool answers `ALREADY_CONSUMED`; identical calldata reverts | no |
| N4 | Keeper | Checkpoint A | reserve → `AccountReserved` on mutations → official proof → observations v5/v6 → consumption; v5 eligible 22 / draw 11; v6 eligible 10.4 (5 + 6×0.9) / draw 5.2; API matches | Sepolia ×1, CC3 ×3 |
| K1 | Borrower | 5 tUSD draw on v5 | 12 tUSD reverts `ExceedsAvailableDraw`; LP wallet reverts `NotBorrower`; Borrowed 5; availableDraw ≈ 6; API principal 5 | CC3 ×1 |
| K2 | Borrower | 3 tUSD draw on v6 | Borrowed 3 against partially paid, haircut and cancelled invoices; availableDraw ≈ 2.2 | CC3 ×1 |
| K3 | Guardian / underwriter | Freeze and resume | `freezeDraws` → DRAW_FROZEN (API); draw reverts, repay still allowed; operator cannot resume (`NotRole`); underwriter → ACTIVE (API) | CC3 ×2 |
| K4 | Third party | `repayFor` | LP wallet repays 1 tUSD with a settlement ref; `Repaid.payer` ≠ borrower; API principal 2 | CC3 ×2 |
| K5 | Borrower | Partial repayment | `repayExact` 2 on v5; interest accrues at 1000 bps ACT/365 (~822 units/day on 3 tUSD) | CC3 ×2 |
| K6 | Underwriter / keeper | Delinquency and cure | `setSchedule` (due +90 s) → `NotDue` early → `markDelinquent` → DELINQUENT (API), draws refused, `cure` refused → 1 tUSD paid → `cure` → ACTIVE (API) | CC3 ×5 |
| K7 | Borrower | Full repayment | v5 and v6 `repayExact` with cap → debt 0, excess 0 → REPAID; redraw reverts; NAV not lower; API debt 0; `/v1/repayments` lists the txs | CC3 ×4 |
| K8 | Borrower (browser) | UI regression on v7 | checkpoint B → proof → observation → consumption; eligible 10 / draw 5; browser borrow 1 → repay 1.001 cap; Repaid principal 1, excess 0; REPAID | Sepolia ×1, CC3 ×2, wallet ×3 |
| K9 | LP | Read parity | `/v1/lp` shares/NAV equal chain; no borrower-owned residue | no |

### Ordering and gates

- P-scenarios mutate the shared source account; `reserveCheckpoint` (N4, K8) blocks source mutations for its
  window, so N4 runs only after every P-scenario, and K8 waits for checkpoint A to expire.
- N2 consumes in source order because the destination enforces revision continuity per obligation and
  `cancelPayout` requires the settlement it reverses to be consumed first.
- Eligibility needs a consumed checkpoint (< 15 min old, `latestRevision == eventsConsumed`), receivable
  evidence within its validity window, and a control observation < 15 min old — N4/K8 refresh all three.
- Official proofs for Sepolia transactions take ~8–10 min; the 850 s reservation leaves 2–4 minutes for draws.

## Execution record — 2026-09-14 16:12 → 17:40 UTC (2026-09-15 KST)

Evidence: [`evidence/native-testnet/qa-20260915/payer-personas.json`](../../../evidence/native-testnet/qa-20260915/payer-personas.json)
(this suite, 23 scenarios) and [`regression.json`](../../../evidence/native-testnet/qa-20260915/regression.json)
(the user-scenario catalog, 27 scenarios, run the same evening).

| Suite | PASS | FAIL | SKIPPED | Note |
| --- | --- | --- | --- | --- |
| Payer personas + credit operations (P/N/K) | 22 | 1 | 0 | K2 and K3 each had one harness check amended after the run (recorded in the evidence under `amendment`; every product check passed). K7 fails on a real gap, see findings. |
| User scenarios (A–G) | 23 | 0 | 4 | D3/D3b/D5/D6 skipped as superseded by this suite (same paths, fresh facilities). C2 needed a rerun after a transient API connection reset (harness poll hardened). D4 rerun on facility v4 inside checkpoint A's window. |

Real transactions: 29 Sepolia (6 persona setup, 20 persona transitions, 1 unattributed deposit, 2 checkpoints)
and 91 Creditcoin (33 facility opening, 22 consumptions, 3 control observations, 20 credit operations, 13 LP
including the aborted first C2 attempt and its cleanup withdrawal). All with faucet tokens; `partnerRevenue=SIMULATED`.

### Persona source transitions and their consumptions

| Sepolia block | Transition | Sepolia tx | Creditcoin consumption |
| --- | --- | --- | --- |
| 11703976–11703983 | SIM-AETHIR epoch-1…4 recognise + assign | `0x9db731cb…` … `0x2ee73f38…` | `0x284ee269…` … `0x66ad5413…` |
| 11703984 | SIM-AETHIR epoch-1 payout 12 tUSD | `0x5f193209…` | `0xe66e7953…` |
| 11703985 | SIM-AETHIR epoch-2 correction −2 (SLA) | `0x8aa71d3f…` | `0x4dcd2783…` |
| 11703986–11703991 | SIM-GPUNET job-1…3 recognise + assign | `0x7e887d65…` … `0x3d373bc1…` | `0xa062eae1…` … `0xf993400e…` |
| 11703992–11703993 | SIM-GPUNET job-1 payouts 3 + 2 | `0x5799c0a6…`, `0x1b0a05c9…` | `0xb2060a0f…`, `0x44152c5e…` |
| 11703994 | SIM-GPUNET chargeback of the 2 tUSD payout | `0x408a162a…` | `0x23e2dfbf…` |
| 11703995 | SIM-GPUNET job-3 cancelled (CANCEL) | `0x2a75faee…` | `0x78f82035…` |
| 11703997 | stranger `depositUnattributed` 1 tUSD (no consumption possible) | `0x7f3dfd29…` | — |
| 11704182 | checkpoint A (`reserveCheckpoint`) | `0xe44e5e6a…` | `0x2af45cee…` (block 5487597) |
| 11704321 | checkpoint B | `0xaa44cf61…` | `0x05ce51fb…` (block 5487712) |

After the 20 consumptions: source revision 31 = destination `eventsConsumed` 31; open 166 tUSD and paid
42 tUSD identical on both chains. Replay of the first consumption: tool `ALREADY_CONSUMED`, identical calldata
reverts on chain.

### Credit operations (Creditcoin)

| Step | Facility | Transaction | Result |
| --- | --- | --- | --- |
| control observations | v5, v6 | `0xd0dfad03…`, `0xafe6a97d…` | blocks 5487593/5487595 |
| eligibility after checkpoint A | v5 / v6 | — | 22 tUSD → draw 11 / 10.4 tUSD → draw 5.2 (API equal) |
| borrow 5 tUSD | v5 | `0x8875b45d…` | block 5487604; 12 tUSD refused `ExceedsAvailableDraw`; LP wallet refused `NotBorrower` |
| borrow 3 tUSD | v6 | `0x8f7451a6…` | block 5487611 |
| guardian `freezeDraws` → underwriter ACTIVE | v6 | `0x3332ab4b…` → `0x38c15065…` | DRAW_FROZEN projected by the API; draw `FacilityNotActive`; operator resume `NotRole` |
| `repayFor` 1 tUSD by the LP wallet | v6 | `0x82b51cf7…` | payer ≠ borrower; interest 2, principal 999,998; debt 2.000002 |
| `repayExact` 2 tUSD | v5 | `0xc47a7eff…` | interest 7, principal 1,999,993; debt 3.000007; +822 units/day projected |
| schedule → `markDelinquent` → installment → `cure` | v5 | `0x20e146fb…` → `0xdf0b2e05…` → `0xccf27bd0…` → `0x0d7ec622…` | DELINQUENT then ACTIVE, both projected by the API |
| final `repayExact` | v5, v6 | `0x641fd6d3…`, `0x5df47dc4…` | debt 0, excess 0, REPAID; NAV 1000.000020 → 1000.000021 |
| browser borrow 1 / approve / repay 1.001 cap | v7 | `0x7bda729a…`, `0xd06377aa…`, `0x29cccafa…` | Repaid principal 1, excess 0; net cost 0; REPAID |

### Findings

1. **API history mirrors are import-only (product gap, medium).** `/v1/receivables` and `/v1/repayments` show
   only rows created by `backfill_native` / `reconcile_cash`. The chain now carries eleven receivables and eight
   `Repaid` allocations across facilities v2–v7; the API lists one of each. `transaction-context`
   (debt, principal, availableDraw) reads the chain directly and was correct throughout, so credit decisions are
   unaffected — but the borrower's receivable and repayment history in the app is incomplete. K7 records this.
2. **Harness: API polls did not tolerate a transient connection reset** (C2 first attempt). Fixed in
   `live-review-browser.mjs` (`pollRead`).
3. **Harness: window-relative read-backs.** Post-draw eligibility (K2) and static `repayExact` without an
   allowance (K3) produced misleading failures; both checks were made state-aware. Recorded as amendments, not
   hidden.
4. **Timing envelope confirmed.** Official proofs arrived 8–10 min after each Sepolia block; the 850 s
   reservation left ~3 min for the draws; CC3 consumptions took ~90 s each this evening (20 → ~30 min).
