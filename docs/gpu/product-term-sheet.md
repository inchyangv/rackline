# First product term sheet — confirmed GPU receivables facility (DRAFT v0.1)

Status: **DRAFT** (GPU-003, 2026-09-14). Nothing here is ACCEPTED. Every number marked `TEST_ONLY` is an
illustration for tests and fixtures, not an offered or approved commercial term. Items marked `OPEN` need a
named decision recorded in `docs/gpu/decisions/REGISTER.md` before the pilot (G1, GPU-010).
Governing decisions: `docs/gpu/decisions/attestcoin-first.md` (R2-D01…D14). Product basis: PIVOT §1, §4–§6, §11.

## 1. Product in one paragraph

A **short-tenor working-capital facility** for an existing GPU operator, sized against its **confirmed,
assignable, currently unpaid receivables** from one DePIN compute network, secured by **E2 payment control**
over the settlement path, funded from a stablecoin lending vault on **Creditcoin**, with source-chain facts
verified only through the **official Attestcoin native path**. Repayment happens when settlement cash actually
arrives in the controlled path and is allocated to the facility — never on a proof, statement, or claim.

## 2. Boundary — what this product is not

| Excluded (separate decision required) | Why | Owner |
| --- | --- | --- |
| GPU rental / compute marketplace | different borrower, revenue, and collection mechanics (PIVOT §1) | R2-D10 |
| Token-collateral loans (ATH / $GPU / CTC / ATC) | price/liquidity risk, not receivable finance; CTC/ATC are never the loan currency (R2-D01) | R2-D10, GPU-072 |
| Equipment purchase finance / resale | needs E3 (lien, custodian, removal restriction) (PIVOT §4.2, §5.1) | GPU-070 |
| Future cash-flow / trailing-payout advances | first product finances existing confirmed receivables only (R2-D06) | GPU-072 |
| Node-NFT collateral | demo construct, not a right (R2-D14) | GPU-072 |
| Customers of the network (pay-later for compute buyers) | different debtor | — |
| New nodes with only incentive-token income; operators with only projected utilization; "data-access" collateral | PIVOT §5.1 exclusions | — |

## 3. Parties and roles

| Role | Who (pilot) | Notes |
| --- | --- | --- |
| Borrower | Legal entity operating GPUs on the selected network with ≥ 90–180 days settlement history (PIVOT §11) | KYC, beneficial owner, signing authority, prior liens verified (GPU-010) |
| Payer / issuer of receivables | The network's settlement entity (Aethir **or** GPU.net — one, OPEN R2-O01) | Must recognize the assignment / payment control (E2) — GPU-009 |
| Lender of record | `OPEN TS-O01` — Rackline entity vs. vault participants as lenders vs. receivable purchase | Legal form decides who owns the receivable |
| Funding | `LendingVault` (stablecoin LPs) on Creditcoin | Pilot: restricted LP set, no public solicitation (§0.4) |
| Servicer / operator | Rackline | Underwriting, control setup, settlement reconciliation, collections |
| Underwriter / guardian / treasury / oracle keeper | Separate keys and roles (GPU-013) | No role can waive the native-evidence requirement (R2-D02) |

## 4. Facility terms

| Term | Draft | Status |
| --- | --- | --- |
| Loan currency | One stablecoin on Creditcoin (pilot: `OPEN TS-O02`; testnet fixtures use a TEST_ONLY mUSDT) | OPEN R2-O06 |
| Execution / ledger chain | Creditcoin (R2-D01) | FIXED |
| Legal form | Loan secured by assignment of receivables **or** true-sale receivable purchase — `OPEN TS-O01` | OPEN |
| Jurisdiction / governing law | `OPEN TS-O03` (borrower entity + asset location + funding entity) | OPEN |
| Use of proceeds | Power, hosting, operating costs; liquidity during the settlement wait | DRAFT |
| Facility type | Revolving up to `FacilityLimit`, each draw a dated tranche | DRAFT |
| Tenor per draw | ≤ the receivable's expected cash date + buffer; hard maximum `OPEN TS-O04` (TEST_ONLY fixture: 90 days) | OPEN |
| Facility maturity | Fixed date; **no automatic evergreen renewal** (PIVOT §5.1) | DRAFT |
| Interest | Fixed APR per facility, simple daily accrual (`actual/365`), interest accrues on principal only; **no capitalization** of unpaid interest unless the agreement says so (GPU-012) | DRAFT; rate `OPEN TS-O05` (TEST_ONLY fixture: 10%) |
| Fees | Origination and servicing fees `OPEN TS-O06`; only fees actually receivable count as revenue (PIVOT §11) | OPEN |
| Advance rate | Applied to `EligibleReceivables` (§5); `OPEN TS-O07` (TEST_ONLY fixture: 50%) | OPEN |
| Approved cap per facility | Underwriter-approved, versioned (`approvedCap`) | DRAFT |
| Concentration caps | Borrower / group / partner / region / global headroom (PIVOT §6.3) | values OPEN (GPU-007) |
| Minimum payment | Each settlement allocates the agreed share; if no settlement arrives by the tranche due date the tranche is delinquent (§7) | DRAFT |
| Prepayment | Allowed any time via `repayFor`; interest to date only | DRAFT |
| Reserve | Borrower-owned cash reserve held apart from LP cash; size `OPEN TS-O08`; first-loss use only per agreement | OPEN |
| Payment control | E2 required before the first draw: payer recognizes assignment; borrower cannot change receiver / claim destination / unstake path alone while debt is open (PIVOT §4.2) | FIXED requirement; partner mechanics GPU-009 |
| Evidence | Official Attestcoin native proof of the payer's obligation / assignment / payment events on a supported source chain; provenance, unpaid balance, control, and cash verified separately (R2-D05) | FIXED |
| Freshness | Draw only against evidence inside policy validity and a source checkpoint / bounded-lag policy (R2-D06, GPU-076) | policy OPEN (GPU-007) |

## 5. Borrowing base (from PIVOT §6.3)

```text
EligibleReceivables = recognized, currently unpaid receivables (payer-confirmed, assigned to the facility)
                    − disputes / refunds / SLA / senior deductions
                    − overdue, concentration, FX, and collectability haircuts
ReceivableLimit     = EligibleReceivables × advanceRate
FacilityLimit       = min(ReceivableLimit, approvedCap)
FacilityRoom        = FacilityLimit − (principal + unpaid interest + fees) − reserved draws
AvailableDraw       = max(0, min(FacilityRoom, each concentration headroom, vault lendable cash))
```

Rules:
- Paid receivables leave the base the moment the payment event is recognized; paid history is used for
  underwriting only, never re-pledged (R2-D06, AR-05/06 in `docs/gpu/accounting-regressions.md`).
- Every draw re-evaluates the formula with current evidence and control state; a stored limit is never used
  (AR-05).
- Token-denominated receivables are valued at a conservative loan-currency rate with a claim/vesting delay
  check against the tranche due date (PIVOT §6.3).

## 6. Cash flow and waterfall

```text
Payer settlement → Source escrow (E2 path)
                 → [approved conversion / settlement rail, GPU-040]
                 → Destination repayment account / Vault receives loan currency
                 → allocation to facility (settlementId) → repayFor: fees → unpaid interest → principal
                 → remainder per agreement (borrower operating costs / reserve / borrower)
```

- Only the amount received in loan currency at the destination and allocated to the facility reduces debt
  (R2-D07). Escrow receipt, claimable balances, and in-flight legs are tracked as `cashState`, not repayment.
- The normal waterfall may leave an agreed operating-cost portion with the borrower; on default the recovery
  share rises per the agreement (PIVOT §5.2). Order is contractual, not hard-coded (GPU-037/039).
- Excess receipts are never applied to another borrower's debt; refunds owed are borrower cash, not LP cash.
- Third-party direct `repayFor` is always accepted, also during proof-service outages (R2-D07).

Worked example (TEST_ONLY numbers, reconciled with PIVOT §6.3): eligible unpaid receivables $20,000,
advance 50% → $10,000; approved cap $8,000 → FacilityLimit $8,000; outstanding principal + interest $3,000;
reserved draws $1,000 → FacilityRoom **$4,000**; group headroom $2,000 → AvailableDraw **$2,000**.
A later $6,000 settlement arriving at the destination with a 60% repayment share allocates $3,600 →
fees $0 → unpaid interest (say $50) → principal $3,550; the $6,000 receivable leaves the base.

## 7. Delinquency, cure, default, loss

State machine (PIVOT §5.3): `Draft → UnderReview → ControlPending → Active → Repaid → Released`;
recovery branch `Active → DrawFrozen → Delinquent → Defaulted → Recovery → ClosedWithLoss`.

| Trigger | Automatic effect | Human decision |
| --- | --- | --- |
| Proof service outage / evidence stale | new draws blocked; collections continue; **no default** | — |
| Missed tranche due date | `Delinquent`, draws frozen, default-rate `OPEN TS-O09` after grace `OPEN TS-O10` | cure plan |
| Control loss detected (receiver changed etc.) | draws frozen; incident scoped; collections continue | cure / dispute / default (GPU-013) |
| Default | recovery share up; reserve applied per agreement; then agreed operating intervention / collateral steps | legal / credit |
| Loss | write-off against reserve then LP NAV; recovery record stays open (GPU-039/041) | credit committee |

Utilization drops are a renewal signal, not a default. Observation gaps alone never trigger enforcement.

## 8. LP / vault terms (pilot)

- Stablecoin vault; **no fixed or guaranteed yield** (README's legacy "8%" is a borrow APR, not an LP rate).
- Restricted LP set during the pilot; no public solicitation before G4 (GPU-063).
- Loss isolation per partner/program requires a separate vault or loss-attributed structure — naming
  facilities inside one pooled vault does not isolate losses (PIVOT §5.1). `OPEN TS-O11`.
- Withdrawals limited to available cash; impaired principal / unpaid interest are not NAV assets once
  recognized as impaired (GPU-037/041).

## 9. Conditions precedent to the first draw (checklist, all must be evidenced)

1. Partner capability confirmed and source chain officially supported (GPU-004/005/008; R2-D08).
2. E2 control experiment passed on an approved account (GPU-009) and agreement signed.
3. Native evidence pipeline green on a public testnet (G-ASC, GPU-080) and on the partner source (G3, GPU-056).
4. Accounting reference model and invariants green (GPU-012/055; RED diagnostics green on v2).
5. Underwriting memo, rights check, KYC, sanctions, jurisdictional review (GPU-010).
6. Funding agreement with named LPs and loss-bearing rules; reserve funded.
7. Operational runbook: dashboards, alerts, pause/collection separation, legal escalation (GPU-044/059).

## 10. Term ↔ PIVOT / ticket map

| Term | PIVOT | Implementing tickets |
| --- | --- | --- |
| Product boundary | §1, §5.1 | GPU-003 (this), GPU-072 (deferred) |
| Roles / control grades | §4.1–4.3, §11 | GPU-009, GPU-013, GPU-038 |
| Borrowing base | §6.3 | GPU-035, GPU-076, GPU-081 |
| Cash flow / waterfall | §5.2, §10.3 | GPU-037, GPU-039, GPU-040 |
| Accounting | §2.2, §6.2 | GPU-012, GPU-034, GPU-036 |
| Delinquency / default / loss | §5.3 | GPU-013, GPU-039, GPU-041 |
| LP terms | §5.1, §12.2 | GPU-037, GPU-063 |
| Legal / jurisdiction | §11 | GPU-010 |
