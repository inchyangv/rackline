# Underwriting and credit policy — first product (GPU-007, DRAFT v0.1)

Status: DRAFT. Every threshold below is `TEST_ONLY` until approved and recorded in
`docs/gpu/decisions/REGISTER.md` (TS-O04…O08) with approver and date; approved values are then stored as a
`policy_versions` row with `test_only=false` (GPU-015). Basis: PIVOT §6.3, §11; term sheet §4–§7;
`attestcoin-first.md` R2-D05/D06/D08; `domain-model.md` enums. Model: `script/gpu/unit_economics.py`.

## 1. Data required before any decision (90–180 days)

| Data | Minimum | Source / provenance | Used for |
| --- | --- | --- | --- |
| Settlement statements | 90 days (180 preferred), every batch, with deductions and disputes | provider API/statement (`OBSERVED`/`ASSERTED`) | history, deduction rates, payer identity |
| Payout events on the source chain | same window | native-proven where the provider settles on a supported chain; otherwise `OBSERVED` only | reconcile statements ↔ cash; **history only** (R2-D06) |
| Utilization / job data | 90 days | provider API; never marketing dashboards | trend, concentration by customer/SKU |
| Current open receivables | full current set with revision | provider-confirmed (`ASSERTED`) + native obligation/assignment events where available | **borrowing base** |
| Rights package | ownership/lease, prior liens, existing assignments | documents (`doc://` refs), registries | eligibility, priority |
| Entity / KYC | legal entity, UBO, signing authority, sanctions | KYC vendor refs | admission |
| Control state | receiver/claim/unstake settings and change authority | partner API/RPC + GPU-009 PoC | E2 gate |

Marketing utilization, advertised FLOPS, node counts, and token price appreciation are **not** inputs to
any limit (PIVOT §6.3). Missing data → field `null` with provenance; never estimated in.

## 2. Eligibility gates (all independent; any fail ⇒ no draw)

| Gate | Field | Pass condition |
| --- | --- | --- |
| G-A Native validity | `nativeStatus` | the obligation/assignment (and later payment) events that define the receivable are `CONSUMED` under the facility's `manifestHash`; `verificationMethod=ATTESTCOIN_NATIVE` only (R2-D02). Unsupported source ⇒ `UNSUPPORTED_SOURCE`, admission off (R2-D08). |
| G-B Revenue provenance | `earningsProvenance` | `PROVIDER_SETTLEMENT`; `PROVIDER_INCENTIVE` excluded from base (§4); `SELF_TRANSFER`/`THIRD_PARTY_UNKNOWN`/`UNCLASSIFIED` excluded; `SIMULATED` allowed only in non-production profiles. |
| G-C Unpaid balance | `Receivable.unpaidAmount`, `state` | provider-confirmed current unpaid amount at the latest revision, with a fresh source checkpoint (§6); `PAID`/`CANCELLED`/`WRITTEN_OFF` contribute 0. |
| G-D Payment control | `controlGrade` | `E2` or `E3` with an effective, unexpired agreement version pinned on the facility; observation age ≤ `controlObservationMaxAge`. |
| G-E Borrower / rights | KYC, encumbrances | KYC `VERIFIED`, no conflicting senior assignment on the same receivable, asset ownership confirmed for any asset-linked receivable. |

A signed statement, an API `200`, or our own hash anchor never satisfies G-A. A lower advance rate is
never a substitute for a failed gate (R2-D03).

## 3. Eligible receivables and haircuts

```text
Net              = Gross − disputes − refunds − SLA − platform fees − senior deductions   (per receivable)
Eligible         = Net × (1 − Σ haircut_bps / 10 000)                                     (floor)
ReceivableLimit  = Eligible × advanceRate_bps / 10 000                                    (floor)
```

| Haircut | TEST_ONLY value | Trigger | Owner |
| --- | --- | --- | --- |
| Overdue bucket | 5% (1–30 d past due), 25% (31–60 d), 100% (>60 d or disputed) | `dueAt` vs. now | TS-O07 |
| Concentration | 5% when a single customer/SKU/site > 40% of eligible | provider data | TS-O07 |
| FX / token | 0% for loan-currency-denominated; for token-denominated: 1 − conservative rate, min 30% | policy rate source, `Valuation` | TS-O07 |
| Collectability | 10% baseline until 2 full settlement cycles have reconciled statement ↔ cash within tolerance | reconciliation history | TS-O07 |
| Advance rate | 50% | — | TS-O07 |

Receivables whose cash-availability date (claim/vesting/transfer delay) exceeds the tranche due date are
ineligible for that tranche (PIVOT §6.3).

## 4. Exclusions and provenance rules

- Incentive/emission rewards (`PROVIDER_INCENTIVE`) are excluded from the base; they may inform DSCR only
  after 2 cycles of reconciled cash receipt and at a 50% haircut (TEST_ONLY).
- **Paid history is never base.** A payout event proves payment; it reduces the receivable and feeds the
  borrower's track record. The same cash cannot be pledged again (R2-D06; AR-05/06).
- Self-transfers, subsidies, rebates, and loan proceeds landing in the escrow are `SELF_TRANSFER` /
  `THIRD_PARTY_UNKNOWN` and excluded.
- Receivables from customers that are related parties of the borrower are excluded unless underwriter override with reason and expiry.

## 5. Concentration limits (TEST_ONLY)

| Dimension | Limit of eligible base / of vault | Enforcement |
| --- | --- | --- |
| Single borrower | ≤ 20% of vault cash+loans | `perBorrowerCap` |
| Borrower group | ≤ 30% | `perGroupCap` |
| Single partner (network) | ≤ 60% (pilot: one partner ⇒ separate vault/loss attribution, term sheet §8) | `perProviderCap` |
| Single end-customer of the operator | ≤ 40% of a facility's eligible base | haircut + cap |
| Region / data center | ≤ 50% | `perRegionCap` |
| SKU | ≤ 70% | reporting; cap if E3 |
| Global | approved vault cap | `globalCap` |

Headroom = cap − outstanding exposure of every facility in the category − reserved draws (PIVOT §6.3).

## 6. Freshness policy (R2-D06; GPU-076 defines the mechanism)

| Item | TEST_ONLY value |
| --- | --- |
| Evidence validity (`validUntil` from `provenAt`) | 30 days for obligation/assignment events; a receivable is dropped from the base when its evidence expires |
| Source checkpoint age (provider revision / balance attestation) | ≤ 7 days at draw time; missing ⇒ draw blocked |
| Control observation age | ≤ 24 h at draw time |
| Credit decision validity | 30 days, revoked on any correction reducing eligible below drawn |
| Bounded-lag allowance for indexer catch-up | 0 in the pilot (no draw until reconciled); any allowance is a TS-O approval |

`acceptedAt` never extends validity; re-submitting an old proof does not refresh it.

## 7. Tenor, reserve, DSCR

| Item | Rule | TEST_ONLY |
| --- | --- | --- |
| Tenor per draw | ≤ expected cash date of the financed receivables + buffer | 60 days + 15 |
| Maximum tenor | hard cap | 90 days (TS-O04) |
| Reserve | borrower-owned, funded before first draw, applied first on loss | 5% of facility limit (TS-O08) |
| DSCR | expected cash available in tenor ÷ (principal + interest + fees) ≥ threshold | ≥ 1.25 (TS-O04/O05) |
| Minimum economic draw | contribution ≥ 0 in `unit-economics.md` | see model output |
| Grace | tranche due date + grace before `DELINQUENT` → `DEFAULTED` path | 10 days (TS-O10) |

## 8. Prohibited policies

- Any "attested"/self-signed evidence class, at any advance rate (R2-D03).
- Using stored limits at draw time (AR-05) or acceptance time as freshness (AR-06).
- Manual overrides without reason, approver, expiry, and cap (`policy_versions.parameters.override`).
- Mixing TEST_ONLY parameters into a `PRODUCTION` facility (enforced by DB trigger, GPU-015).
- Treating facility naming inside one vault as loss isolation.

## 9. Versioning and approval

Each parameter set is a `policy_versions` row `{policy_version_id, approved_by, approved_at, parameters,
test_only}`; facilities and decisions reference the version they were decided under. Changing a value
creates a new version; existing decisions keep theirs until re-underwritten. Approvers: credit (rates,
haircuts, caps), CEO (fees, product scope), legal (grace/default mechanics).
