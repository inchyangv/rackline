# Decision register (GPU pivot)

Single index of decisions that govern the GPU lending build. Each entry is either **FIXED** (with the
source of authority), **OPEN** (with the role that must decide, the material needed, and the tickets that
cannot pass their gate until it is decided), or **DECIDED** (with the date and the deciding input).
An absent approval is recorded as OPEN — never filled in as ACCEPTED.

Ledgers this register indexes (do not duplicate their text; edit them in place):
- `attestcoin-first.md` — R2 architecture decisions R2-D01…D14 (FIXED) and R2-O01…O09 (OPEN/DECIDED).
- `../product-term-sheet.md` — first-product terms (DRAFT v0.1) with TS-O01…O11.
- `../accounting-regressions.md` — AR-01…AR-08 correct-value constants (acceptance expectations).
- `settlement-rails.md` — GPU-008 ADR (DRAFT v0.1): SR-D01…D08 (FIXED baseline rails) and SR-O01…O06 (OPEN, mostly aliases of R2-O0x/TS-O02).

## 1. Product decisions — FIXED

| ID | Decision | Authority | Applies to |
| --- | --- | --- | --- |
| PD-01 | First product = short-tenor facility against confirmed, assignable, currently unpaid GPU receivables of an existing operator; funded loans require E2 control | PIVOT §1, §4.2, §5.1; R2-D10 | GPU-003, 010, 035, 081 |
| PD-02 | One partner, one settlement structure, one loan currency, restricted borrowers/LPs for the pilot; no evergreen renewal | PIVOT §5.1 | GPU-003, 020/021, 063 |
| PD-03 | Debt is reduced only by loan currency actually received at the destination and allocated to the facility (`repayFor`) | PIVOT §5.2, §10.3; R2-D07 | GPU-037, 039, 040, 081 |
| PD-04 | Paid receivables leave the borrowing base; paid history is underwriting input only; every draw re-evaluates the base and control state | PIVOT §6.3; R2-D06; AR-05/06 | GPU-035, 076, 081 |
| PD-05 | Single ledger for principal / unpaid interest / fees; partial interest payments preserve unpaid interest; rate changes never reprice the past; capitalization only if the agreement says so | PIVOT §2.2; AR-01…04 | GPU-012, 034, 036 |
| PD-06 | Draw pause and collections are separate; proof outages block new facts/draws only, never repayment or recovery | TICKET §0.3; R2-D07 | GPU-036, 039, 081 |
| PD-07 | No LP fixed/guaranteed yield; losses recognized against reserve then NAV; loss isolation needs a separate vault or attributed structure | PIVOT §2.2, §5.1 | GPU-037, 041, 063 |
| PD-08 | No testnet auto-grant credit, no public owner-key API, no permissive source admission on the production path | TICKET §0.3; GPU-001 | GPU-001 (done), 029, 062 |
| PD-09 | Excluded from the first product without a new decision: marketplace, token collateral, equipment finance (E3), future cash-flow advances, node-NFT collateral, buyer pay-later | PIVOT §1, §5.1; R2-D10/D14 | GPU-068~072 (DEFERRED) |

## 2. OPEN — product / commercial / legal (term sheet)

| ID | Decision needed | Decider (role) | Material required | Blocks |
| --- | --- | --- | --- | --- |
| TS-O01 | Legal form: secured loan with receivable assignment vs. true-sale purchase; lender of record | Legal + CEO | jurisdiction memo, partner assignment recognition (GPU-009), LP structure | GPU-010 (G1), GPU-013 roles |
| TS-O02 | Loan stablecoin on Creditcoin (issuer, contract, liquidity) — same as R2-O06 | CEO + treasury | issuer confirmation, on-chain liquidity check | GPU-006, 037, 062 |
| TS-O03 | Governing law / jurisdiction for borrower, funding entity, asset location | Legal | pilot borrower entity, DC location | GPU-010 |
| TS-O04 | Maximum tenor per draw and facility maturity | Credit | partner settlement cycle data (GPU-004/005) | GPU-007, 035 |
| TS-O05 | Interest rate (fixed APR per facility) and default rate | Credit + CEO | cost of funds, loss estimate (GPU-007) | GPU-007, 034 |
| TS-O06 | Origination / servicing fees | CEO | unit economics (GPU-007) | GPU-007 |
| TS-O07 | Advance rate and haircut schedule | Credit | receivable dispute/refund history from partner | GPU-007, 035 |
| TS-O08 | Reserve size and ownership mechanics | Credit + Legal | waterfall legal review | GPU-037, 041 |
| TS-O09 | Default rate / recovery share step-up | Credit + Legal | agreement template | GPU-041 |
| TS-O10 | Grace period and cure procedure | Credit + Legal | agreement template | GPU-013, 041 |
| TS-O11 | LP class and loss isolation structure for the pilot (separate vault vs. attributed) | CEO + Legal | funding agreement | GPU-037, 063 |

## 3. OPEN — architecture / partner (indexed from `attestcoin-first.md` §3)

| ID | Question | Status |
| --- | --- | --- |
| R2-O01 | First partner (Aethir vs GPU.net) | OPEN — GPU-004/005/008 |
| R2-O02 | Partner source chain officially supported; natively provable obligation event | OPEN — GPU-008/075/076 (CC3 testnet supports Sepolia, Ethereum mainnet only, per GPU-075 probe) |
| R2-O03 | If only past payouts are provable: hold admission vs. change product | OPEN — GPU-076/008/010 |
| R2-O04 | Freshness policy (checkpoint/reservation vs. bounded lag) | OPEN — GPU-076/007/010 |
| R2-O05 | Settlement rail; alternate vault-chain configuration | OPEN — GPU-006/040/010 |
| R2-O06 | Loan stablecoin on Creditcoin | OPEN — = TS-O02 |
| R2-O07 | Legacy `RelayerSigVerifier` retire vs. repurpose for OFFCHAIN_ASSERTION | OPEN — GPU-013/029/060 |
| R2-O08 | Hackathon-facing docs | see ledger §3 (resolution recorded there by GPU-065) |
| R2-O09 | Approved public-testnet budget for GPU-080 | OPEN — external approval |
| SR-O01…O06 | Settlement rails: loan token issuer, partner payout/obligation contracts, bridge/settlement partner, conversion venues/limits, API-only fallback decision, alternate vault chain | OPEN — `settlement-rails.md` §7 (GPU-008 DRAFT; production rail manifest cannot be created until resolved) |

## 4. Change control

- A FIXED entry changes only with a new ledger version and re-verification of dependent tickets (TICKET §0.4).
- Resolving an OPEN entry: record date, decider, input, and the tickets to re-run; update the term sheet
  status column in the same commit.
- Numbers in fixtures stay `TEST_ONLY` until the corresponding TS-O item is DECIDED and the approved value is
  recorded here with its approver.
