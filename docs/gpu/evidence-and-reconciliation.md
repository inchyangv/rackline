# Evidence and settlement reconciliation — golden fixtures (GPU-014, v1)

Status: SPEC v1 (2026-09-14). Reference reconciler: `offchain/gpu/hashcredit_gpu/reconciliation/reference.py`.
Golden fixtures: `test/fixtures/gpu/settlements/s-01…s-05.json` (executed by
`offchain/gpu/tests/test_settlement_fixtures.py`). Basis: PIVOT §6.2, §8.2–8.3, §10.3;
`domain-model.md` (ids), `accounting.md` (AC-07 pipeline), `attestcoin/evidence-contract.md` (EV vectors).
The production reconciler (GPU-024) and the ledger DB (GPU-016) must reproduce these fixtures exactly.

## 1. Identifiers and how they link

```text
observationId ─┐
observationId ─┼──▶ economicEventId ──▶ receivable lifecycle (account|obligationRef, revision)
observationId ─┘         │                       │
 (API / WEBHOOK /        │                       ▼
  STATEMENT / CHAIN)     │            settlementId ──▶ legs ──▶ destination receipt ──▶ repaymentAllocationId
                         │
        CHAIN only: sourceEventId (consumption key) · proofQueryKey (cache) · proofArtifactId (bytes)
```

| ID | Role | Merge key? |
| --- | --- | --- |
| `observationId` (`source`, `ref`, `sha256(raw)`) | one sighting | no |
| `economicEventId` (`provider/account/eventType/providerRef`) | one economic fact | **yes** |
| `sourceEventId` (env, chainKey, height, on-chain txIndex, receipt log ordinal) | one consumed source log | no — uniqueness key for consumption |
| `proofQueryKey` (env, chainKey, txHash) | proof cache | no |
| `proofArtifactId` (sha256 of proof JSON) | bytes provenance | no |
| `settlementId` | one payer batch | groups payouts, legs, destination receipts, allocations |
| `repaymentAllocationId` | one allocation to one facility | no |

Adapter or schema version changes, verifier replacement, different proof bytes, or re-submission never
create a new `economicEventId` (S-01: three observations → one event; `test_ids_are_not_merge_keys`).
The same provider reference on another account or chain is a different economic event (namespaced).

## 2. Lifecycle: earned → settled → paid, one revenue line

| Stage | Event | Effect on the receivable | Cash | Facility debt |
| --- | --- | --- | --- | --- |
| earned | `OBLIGATION` (rev n) | create / update `net` at revision | — | — |
| assigned | `ASSIGNMENT` | `assignedFacility` (E2 input) | — | — |
| corrected | `CORRECTION` (delta, rev n+1) | `net += delta`; decision revoked if used and shrinking | — | — |
| settled at source | `PAYOUT` (settlementId) | `paid += amount` (only when attributable and `PROVIDER_SETTLEMENT`) | `SOURCE_ESCROW` | **unchanged** |
| reversed | `CANCELLATION` | `paid −= amount` | negative escrow line, `REFUND_OR_REVERSAL` | unchanged |
| converting | `LEG` | — | escrow → `IN_FLIGHT` (may change asset) | unchanged |
| paid at destination | `DESTINATION_RECEIPT` | — | `IN_FLIGHT` → `DESTINATION` | unchanged |
| applied | `ALLOCATION` (loan asset only, ≤ received) | — | — | **reduced** (excess over debt not applied) |

Corrections reference the original revision (`targetEconomicEventId`, `revision = current + 1`); the
original row is never overwritten. Out-of-order revisions are recorded as `REVISION_OUT_OF_ORDER` and not
applied (S-03).

## 3. Trust and conflicts

- Trust of an economic event = strongest observation: `PROVEN` (consumed native log) > `ASSERTED`
  (signed statement) > `OBSERVED` (API/RPC read) > `CLAIMED`. A native verification that nobody
  consumed (public `verify` front-run) is `OBSERVED`, never `PROVEN` (S-04 `inv-E`).
- Two observations of one event with different amounts → `AMOUNT_CONFLICT`; nothing is silently picked.
- Only `PROVEN` + assigned + not paid/cancelled receivables count as eligible unpaid (summary field
  `eligibleUnpaid`).

## 4. Rejections encoded in the fixtures

| Code | Situation | Fixture |
| --- | --- | --- |
| `LOCATOR_TAMPERED` | caller-claimed height/txIndex/logOrdinal ≠ proven | S-04 `inv-F` |
| `DUPLICATE_CONSUMPTION` | same `sourceEventId` consumed twice | S-04 `c10` |
| `OWN_ANCHOR_INELIGIBLE` | our statement-hash anchor; consumed but never a business fact | S-04 `c7` |
| `EMITTER_NOT_REGISTERED` | same topics from an unregistered contract | (EV-09; reconciler code path) |
| `ACCOUNT_MISMATCH` | assignment for a facility of another account | S-04 `c4` |
| `PAID_REPLEDGE` | assignment of a fully paid receivable | S-04 `c3` |
| `TOKEN_MISMATCH` | payout in a token other than the receivable's | (EV-07; code path) |
| `AMOUNT_CONFLICT` | conflicting observations | S-03 `api:inv-C:dup` |
| `REVISION_OUT_OF_ORDER` | correction skipping a revision | S-03 `c4` |
| `CORRECTION_TARGET_MISSING` | delta against unknown obligation | code path |
| `ALLOCATION_EXCEEDS_RECEIPT` | allocations of a settlement > destination receipts | S-05 `a3` |
| `LOAN_ASSET_MISMATCH` | allocation in a non-loan asset | S-05 `a1` |
| `CANCEL_EXCEEDS_PAID` | reversal larger than paid | code path |

Unknown-origin cash (payout with no attributable obligation) is `UNCLASSIFIED` cash, never a receivable
(S-04 `settle-5`); borrower self-transfers are `SELF_TRANSFER` (S-04 `settle-6`).

## 5. Currency difference source ↔ destination

Receivables and source payouts are in the source asset (`usdc:11155111`); facility debt and allocations
are in the loan asset (`musdt:102031`). A `LEG` converts escrow cash into in-flight loan currency; the
receivable's `unpaid` decreases by the **source** amount at source payout, the facility's debt decreases
by the **destination** amount at allocation (S-02: 6,000 USDC paid at source → 3,600 mUSDT allocated →
debt 5,000 → 1,400; escrow keeps 2,400 USDC). Never both.

## 6. Totals the fixtures pin (summary fields)

`economicEvents`, per-receivable `{net, paid, unpaid, state, revision, trust, assigned}`, `eligibleUnpaid`,
`sourceEscrow`, `inFlight`, `destinationReceived`, `unclassifiedCash`, `facilityDebt`, `allocations`
(`amount`, `applied`, `excess`), `consumedSourceEvents`, `exceptions`, `decisionsRevoked`. Invariants checked
after every fixture: Σ allocations of a settlement ≤ its source amount; consumed ids unique.

## 7. Fixture index

| Fixture | Covers |
| --- | --- |
| S-01 | duplicate API + statement + chain observations → one PROVEN event; assignment; source payout reduces unpaid, not debt |
| S-02 | two logs in one tx (ordinal 0/1); one payout across two receivables; conversion leg; destination receipt; allocation reduces debt in loan currency |
| S-03 | correction after decision use → decision revoked; out-of-order revision; conflicting amounts |
| S-04 | paid re-pledge; other account; unclassified cash; self transfer; own anchor; unconsumed verify (front-run); tampered locator; duplicate consumption |
| S-05 | allocation > receipt; non-loan-asset allocation; excess above debt not applied |
