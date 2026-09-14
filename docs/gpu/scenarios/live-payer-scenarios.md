# Live payer-persona and credit-operation scenarios (TEST_ONLY deployment)

Companion to [`live-user-scenarios.md`](live-user-scenarios.md). That catalog covers personas of *our* product
(visitor, LP, borrower, operator, attacker). This one covers the counterparties we do not control — the
DePIN networks that pay a GPU operator — and the credit operations that only make sense once such payers exist:
partial payments, adjustments, chargebacks, cancelled invoices, overdue invoices, freezes, delinquency, third-party
repayment — and, on a facility sacrificed for the purpose, non-payment: default, recovery reserve, impairment and
write-off.

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
regression), `gpu080-facility-v8` (recovery drill, sacrificed). All were opened with `native_tools.mjs open-facility`
(11 Creditcoin transactions each) and imported into the API with `bootstrap_native --facility-name`.

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
| R0 | Operator | Recovery-drill facility | v8 ACTIVE for the borrower wallet; manager and vault bound to `RecoveryManager`; drill wallets hold UNDERWRITER / GUARDIAN / SERVICER / TREASURY; API lists it; no debt, no receivables | no |
| R1 | SIM-AETHIR | Epoch-5 financing basis | epoch-5 (12 tUSD) recognised and assigned to v8; official proofs; both consumed proof-only; one ASSIGNED receivable | Sepolia ×2, CC3 ×2 |
| R2 | Borrower | Checkpoint C and draw | reserve → proof → observation v8 → consumption; eligible 12 / draw 6; Borrowed 4; API principal 4, availableDraw 2 | Sepolia ×1, CC3 ×3 |
| R3 | SIM-AETHIR | Paid after financing | payer settles epoch-5 in full → proof → consumption; receivable PAID; eligible 0, availableDraw 0; legal debt still 4 tUSD (a source payout never reduces destination debt); API `NO_ELIGIBLE_DRAW` with debt 4 | Sepolia ×1, CC3 ×1 |
| R4 | Underwriter / guardian / servicer | Default | `setSchedule` (due +90 s, grace 60 s) → `markDelinquent` → `NotDue` inside grace → `declareDefault` without approval `NotApproved` → servicer dispute → `DisputeOpen` → dispute cleared → servicer key `NotRole` → `approveDefault` → `declareDefault` → DEFAULTED (API); accrual frozen (30 days ahead = same debt); draw refused; repay path open | CC3 ×6 |
| R5 | Servicer / third party | Recovery reserve | `beginRecovery` → RECOVERY (API); LP wallet pledges 1 tUSD (`fundReserve`); borrower cannot take the reserve (`NotReserveOwner`); `returnReserve` refused (`OutstandingDebt`); `applyReserve` → router `Repaid` with payer = RecoveryManager; debt −1 exactly; API debt equal | CC3 ×4 |
| R6 | Underwriter / treasury | Impairment and write-off | impair above exposure refused; impair remaining 3.000013 → NAV −3.000013 (API equal); loss-id reuse refused; write-off without approval refused; underwriter key refused (`NotRole`); `approveWriteOff` → treasury `writeOff` → `LossApplied(writeOff)`; CLOSED_WITH_LOSS (API); impairment released, NAV unchanged by the write-off; ledger still carries the legal debt; draw refused | CC3 ×3 |

### Ordering and gates

- P-scenarios mutate the shared source account; `reserveCheckpoint` (N4, K8) blocks source mutations for its
  window, so N4 runs only after every P-scenario, and K8 waits for checkpoint A to expire.
- N2 consumes in source order because the destination enforces revision continuity per obligation and
  `cancelPayout` requires the settlement it reverses to be consumed first.
- Eligibility needs a consumed checkpoint (< 15 min old, `latestRevision == eventsConsumed`), receivable
  evidence within its validity window, and a control observation < 15 min old — N4/K8 refresh all three.
- Official proofs for Sepolia transactions take ~8–10 min; the 850 s reservation leaves 2–4 minutes for draws.
- R-scenarios run on their own facility after K8 (they need a free source account for checkpoint C and the
  epoch-5 payout) and leave it CLOSED_WITH_LOSS; the vault keeps the written-off facility on its books.

## Execution record — 2026-09-14 16:12 → 17:40 UTC and 2026-09-15 01:40 → 02:31 UTC

Evidence: [`evidence/native-testnet/qa-20260915/payer-personas.json`](../../../evidence/native-testnet/qa-20260915/payer-personas.json)
(this suite, 30 scenarios) and [`regression.json`](../../../evidence/native-testnet/qa-20260915/regression.json)
(the user-scenario catalog, 27 scenarios, run the same evening).

| Suite | PASS | FAIL | SKIPPED | Note |
| --- | --- | --- | --- | --- |
| Payer personas + credit operations (P/N/K) | 22 | 1 | 0 | K2 and K3 each had one harness check amended after the run (recorded in the evidence under `amendment`; every product check passed). K7 fails on a real gap, see findings. |
| Non-payment drill (R0–R6, facility v8) | 7 | 0 | 0 | R4 had one harness check amended (static `repayExact` without an allowance, same pattern as K3; R5 then repaid through the router for real). Every product check passed. |
| User scenarios (A–G) | 23 | 0 | 4 | D3/D3b/D5/D6 skipped as superseded by this suite (same paths, fresh facilities). C2 needed a rerun after a transient API connection reset (harness poll hardened). D4 rerun on facility v4 inside checkpoint A's window. |

Real transactions: 29 Sepolia (6 persona setup, 20 persona transitions, 1 unattributed deposit, 2 checkpoints)
and 91 Creditcoin (33 facility opening, 22 consumptions, 3 control observations, 20 credit operations, 13 LP
including the aborted first C2 attempt and its cleanup withdrawal) on 2026-09-14, plus 4 Sepolia and 24
Creditcoin for the non-payment drill on 2026-09-15. All with faucet tokens; `partnerRevenue=SIMULATED`.

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

### Non-payment drill (facility v8, 2026-09-15 01:40 → 02:31 UTC)

Facility `gpu080-facility-v8` (API `5KG50B0YW3NSBS91ZZH14YJH92`, opened with approval nonce 7, 11 Creditcoin
transactions) was financed and then deliberately not repaid. Real transactions: 4 Sepolia, 24 Creditcoin.

| Step | Transaction | Result |
| --- | --- | --- |
| epoch-5 recognise + assign (Sepolia 11706740–41) | `0x618e1a20…`, `0xb31ab7ca…` → consumed `0xdd90e670…`, `0x7b81b205…` | one ASSIGNED 12 tUSD receivable, payer SIM-AETHIR |
| checkpoint C (Sepolia 11706802) → observation → consumption | `0x8c41e47a…` → `0xeaa098ee…` (block 5489744) | eligible 12 tUSD, availableDraw 6 |
| borrow 4 tUSD | `0xc4bca806…` (block 5489750) | debt 4; API principal 4, availableDraw 2 |
| epoch-5 paid in full by the payer (Sepolia 11706866) → consumption | `0xe0dca832…` → `0xc3aab248…` (block 5489796) | receivable PAID; eligible 0; debt 4.000009 unchanged; API `NO_ELIGIBLE_DRAW` |
| schedule → `markDelinquent` | `0xf398b160…` → `0x9e77145d…` (block 5489810) | DELINQUENT; `NotDue` inside the 60 s grace |
| dispute opened / cleared | `0xa43f5de2…` / `0x19500bbf…` | `approveDefault` refused `DisputeOpen` while open |
| `approveDefault` → `declareDefault` | `0x28e05018…` → `0x546919ae…` (block 5489820) | DEFAULTED; accrual frozen at 4.000013 (30 days ahead identical); API DEFAULTED |
| `beginRecovery` | `0xc313f319…` (block 5489827) | RECOVERY (API) |
| `fundReserve` 1 tUSD (LP wallet) → `applyReserve` | `0x00d77eb5…` → `0x2b9153d8…` (block 5489832) | `Repaid` payer = RecoveryManager, interest 13 + principal 999,987; debt 3.000013 (API equal) |
| `impair` 3.000013 | `0x7059a9fa…` | vault NAV 1000.000034 → 997.000021; `/v1/lp` equal |
| `approveWriteOff` → `writeOff` (treasury) | `0x7686b0e3…` → `0xd2608048…` (block 5489848) | `LossApplied(writeOff=true, 3.000013)`; CLOSED_WITH_LOSS (API); impairment released, NAV unchanged; ledger legal debt 3.000013 remains |

Negative paths exercised on the way: `NotApproved` (declare before approval; write-off before approval; reused
loss id), `DisputeOpen`, `NotRole` (servicer approving a default; underwriter executing a write-off),
`NotReserveOwner`, `OutstandingDebt`, `ImpairmentExceedsExposure`, `FacilityNotActive` (draw while DEFAULTED and
after the write-off).

### Findings

1. **API history mirrors are import-only (product gap, medium).** `/v1/receivables` and `/v1/repayments` show
   only rows created by `backfill_native` / `reconcile_cash`. The chain now carries eleven receivables and eight
   `Repaid` allocations across facilities v2–v7; the API lists one of each. `transaction-context`
   (debt, principal, availableDraw) reads the chain directly and was correct throughout, so credit decisions are
   unaffected — but the borrower's receivable and repayment history in the app is incomplete. K7 records this.
   **Fixed after the run:** migration `0006` adds `proj_receivables` / `proj_repayments`, replayed from finalized
   `ReceivableBook` and `RepaymentRouter`/`DebtLedger`/`LendingVaultV2` events on every indexer sync; the API
   merges them with ledger imports (`recordOrigin: FINALIZED_CHAIN_EVENTS` vs `LEDGER_IMPORT`).
2. **Harness: API polls did not tolerate a transient connection reset** (C2 first attempt). Fixed in
   `live-review-browser.mjs` (`pollRead`).
3. **Harness: window-relative read-backs.** Post-draw eligibility (K2) and static `repayExact` without an
   allowance (K3) produced misleading failures; both checks were made state-aware. Recorded as amendments, not
   hidden.
4. **Non-payment path holds end to end (product, confirmed).** The one scenario the product exists for — the
   network paid the operator directly and the operator did not repay — behaves as designed on chain and in the
   API: the paid receivable drops out of the borrowing base immediately, the debt is untouched by the source
   payout, the default needs an underwriter approval that a servicer dispute can block, accrual freezes at
   default, a third-party reserve is applied through the ordinary router (`Repaid.payer` = RecoveryManager),
   impairment hits LP NAV before the write-off, and the write-off closes the facility without forgiving the legal
   debt. Residual: the borrower UI was not driven through DEFAULTED / RECOVERY / CLOSED_WITH_LOSS (API projection
   verified only), and the TEST_ONLY vault now permanently carries one written-off facility (NAV 997.000021).
5. **Timing envelope confirmed.** Official proofs arrived 8–10 min after each Sepolia block; the 850 s
   reservation left ~3 min for the draws; CC3 consumptions took ~90 s each this evening (20 → ~30 min).
