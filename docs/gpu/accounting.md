# Financial accounting specification and reference model

Reference model: `offchain/gpu/hashcredit_gpu/accounting/reference.py`
(pure integers). Vectors: `test/fixtures/gpu/accounting.json` (hand-derived expectations, 13 vectors) run
by `offchain/gpu/tests/test_accounting_reference.py`. The contracts and Python ledgers must reproduce
these vectors exactly; the Solidity suites under `test/gpu/` exercise the same invariants.

## 1. Ledgers and what they mean

| Ledger | Owner | Contains | Does not contain |
| --- | --- | --- | --- |
| **Facility ledger** (legal debt) | facility (on-chain authoritative, DB mirror) | `principal`, `unpaid_interest` (exact accumulator), `fees`, rate segments, write-off markers | NAV judgments |
| **Vault ledger** (LP book, NAV) | vault | LP-owned `cash`, performing principal + performing accrued interest receivable, impairment, shares | borrower money, source escrow, in-flight legs, written-off exposure |
| **Borrower cash** | borrower | `reserve` (first-loss, borrower-owned), `refundable` excess repayments | — |
| **Collection pipeline** | servicer | `source_escrow[settlement]`, `in_flight[settlement]` | debt or NAV effects |

Legal debt ≠ NAV book value: write-off and impairment change the vault's book, never the borrower's
obligation. Borrower receivables are the borrowing base, never a vault asset.

## 2. Interest

- Simple interest on **principal only**, day-count `ACT/365` expressed in seconds:
  `interest_units = floor(Σ_segments principal × rate_bps × seconds / (10 000 × 365 × 86 400))`.
- The ledger stores the exact numerator (`interest_accum = Σ principal × rate_bps × seconds`) and
  derives units by floor division, so results are independent of how often accrual runs and no
  dust is lost between accruals. Payments subtract `units × DENOM` from the numerator.
- Rate changes create a segment at the change time; the past is settled at the old rate
  first ($10,000 at 10% for exactly half a year, then 20%, produces $1,500). A rate
  change is never retroactive.
- Capitalization is disabled by default (`Terms.capitalize_unpaid_interest = false`). A re-draw adds
  only the new amount to principal; unpaid interest stays interest. If enabled by the terms, capitalization
  applies identically in the manager and the vault because
  there is a single ledger.
- After write-off, the accrual clock freezes. Contractual default interest, if any, is a legal claim
  tracked outside this ledger.
- Rounding: income rounds down (floor); the borrower is never charged a fraction of a unit.

## 3. Repayment allocation (waterfall)

Only destination cash allocated to a facility reduces debt:

```text
allocate(amount): fees → unpaid interest → principal → excess
```

- `excess` is borrower-refundable cash (AC-06), never applied to another facility, never NAV.
- A partial payment smaller than accrued interest reduces interest only and leaves principal and the
  remaining unpaid interest intact (AC-01: $5,000 · 10% · 1 y · $250 → principal 5,000 / interest 250 /
  legal debt 5,250).
- Third-party `repayFor` uses the same allocation and remains available during proof-service outages;
  the ledger has no dependency on evidence.
- The pipeline states never touch debt (AC-07): `source_receipt` (cash at source escrow), `start_leg`
  (in-flight conversion/bridge), `destination_receipt` (loan currency at the vault, unallocated). Only
  `repay_for` changes the facility.

## 4. Losses

| Step | Facility ledger (legal) | Vault ledger (NAV) | Borrower cash |
| --- | --- | --- | --- |
| Impairment (`impair`) | unchanged | NAV −= impairment (per facility, capped by exposure) | — |
| Write-off (`write_off`) | reserve applied via the waterfall; remaining principal/interest marked written-off; accrual frozen; **debt persists** | facility leaves the performing book; its impairment released (no double count) | reserve consumed up to debt |
| Recovery (`recover`) | waterfall on the still-outstanding debt | cash += recovery (NAV up) | excess refundable |
| Total loss + new LP (AC-09) | — | old LPs bear the loss; a new LP enters at the post-loss share price and is not diluted by it |

Write-off is not forgiveness (AC-08: $5,500 debt, $250 reserve → legal $5,250 after write-off; a later
$400 recovery → legal $4,850 and NAV +$400).

## 5. LP shares

- Share conversion uses an ERC-4626-style **virtual offset** (`+1000` virtual shares, `+1` virtual asset):
  `shares = assets × (S + 1000) / (NAV + 1)`, `assets = shares × (NAV + 1) / (S + 1000)`, floor both ways.
- The first-depositor donation attack is unprofitable. An attacker who deposits 1 unit and donates $1,000
  can redeem about $500.08; the next $2,000 depositor redeems about $1,999.83. Residual rounding is at most
  1 unit per conversion and favours the vault.
- Direct token transfers to the vault are LP-owned cash (`donate`), never a borrower repayment.
- Withdrawals are limited to available cash (AC-13); impairment lowers NAV per share immediately.
- Invariant: `Σ redeemable(shares_i) ≤ NAV + 1`.
- No fixed yield exists; realized LP return = Δ(NAV per share).

## 6. NAV and double-counting rules

```text
NAV = LP cash + Σ performing principal + Σ performing accrued interest − Σ impairment (performing facilities)
```

Excluded from NAV: borrower reserve, borrower refundable excess, source escrow balances, in-flight legs,
written-off exposure, borrower receivables (borrowing base). The same recovery right is never counted twice
across source cash / in-flight / loan receivable: it is a loan receivable until the destination allocation,
at which point cash replaces it one-for-one.

## 7. Journal entries (double-entry view)

| Event | Debit | Credit |
| --- | --- | --- |
| LP deposit | Cash | LP equity (shares) |
| Draw | Loan principal receivable | Cash |
| Accrual | Interest receivable | Interest income |
| Source escrow receipt | Collection memo (off-NAV) | — |
| Destination receipt (unallocated) | Cash | Unallocated receipts (liability until allocated) |
| Allocation | Unallocated receipts | Fees / Interest receivable / Loan principal / Borrower refundable |
| Reserve funding | Borrower cash held (off-NAV) | — |
| Impairment | Loss expense | Impairment allowance |
| Write-off | Impairment allowance / Loss expense | Loan principal + interest receivable (book); memo: legal claim remains |
| Recovery | Cash | Recovery income (or Loan principal memo) |
| Refund of excess | Borrower refundable | Cash |

## 8. R2 cases in the model

| Case | Model | Vector |
| --- | --- | --- |
| Paid receivable after native-accepted payment event | contributes 0 to the borrowing base | AC-11 (`r2`) |
| Proof-only receivable (`PROOF_READY`, not consumed) | contributes 0; ledger untouched | AC-11 (`r3`), `test_evidence_never_touches_the_ledger` |
| Non-native assertion (`NOT_REQUIRED`) | contributes 0 | AC-11 (`r4`) |
| Proof-service outage | third-party `repayFor` allocates normally | AC-12 |
| TEST_ONLY vs approved terms | `Terms.test_only` flag; DB refuses PRODUCTION facilities on TEST_ONLY terms | — |

## 9. Vectors (all pass, 15 tests)

AC-01 partial interest · AC-02 rate segments · AC-03 accrual frequency · AC-04 no capitalization · AC-05 two
borrowers · AC-06 overpayment · AC-07 pipeline states · AC-08 write-off + recovery · AC-09 total loss + new LP
· AC-10 donation · AC-11 borrowing base gates · AC-12 outage repayFor · AC-13 impairment / withdrawal cap.
Run: `python -m pytest offchain/gpu/tests/test_accounting_reference.py -q`.
