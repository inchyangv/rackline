# Domain model, identifiers, units, paths, and API contract (GPU-011, v1)

Status: SPEC v1 (2026-09-14). Machine-readable form: `config/gpu/schema/domain-v1.schema.json`; sample:
`test/fixtures/gpu/domain/sample-v1.json`; validator: `script/gpu/validate_domain_fixture.py`.
Basis: PIVOT §6.1–6.2, §7–9; TICKET §0.2/§0.5/§0.9; `docs/gpu/product-term-sheet.md`;
`docs/gpu/decisions/attestcoin-first.md` (R2-D02/D05/D06/D07/D12). Field-level evidence semantics
(proof-bound vs. claimed fields, freshness checkpoints, consumption keys) are finalized by GPU-076; this
document fixes names, shapes, enums, and ownership so GPU-015/016/029/045 can build against them.

## 1. Principles

1. **One economic fact, one economic ID.** Technical observations (API rows, webhooks, chain logs, proofs)
   are separate records that *point at* an economic ID; changing an adapter, SDK, ABI, or proof bytes never
   creates a new economic fact (PIVOT §6.2, R2-D06).
2. **Money is exact.** Amounts are integer base units serialized as decimal strings, always with an asset
   reference (chain, contract, decimals). No floats, no implicit unit, no cross-asset sums.
3. **Every time value says what it means and where it came from.** `occurredAt` / `confirmedAt` /
   `observedAt` / `acceptedAt` / `provenAt` are different fields; freshness never derives from
   `acceptedAt` or `observedAt` alone (R2-D06).
4. **Five judgments are separate records**, never one boolean: native proof (`nativeStatus`), revenue
   provenance (`earningsProvenance`), unpaid receivable (`Receivable.state` + `unpaidAmount`), payment
   control (`controlGrade`), cash (`cashState`) (R2-D05).
5. **Corrections are new rows.** A correction references the original by ID and carries a signed delta or a
   reversal; original rows are never overwritten (PIVOT §8.2).
6. **Missing upstream data is `null` + provenance**, never a fabricated value; every externally sourced
   field carries a `Provenance`.
7. **Test data cannot leak into production.** Every evidence-bearing record carries `executionProfile`;
   production readers reject anything that is not `PRODUCTION` (R2-D12).

## 2. Identifier scheme

| ID | Kind | Format | Stable across |
| --- | --- | --- | --- |
| `borrowerId`, `legalEntityId`, `facilityId`, `assetId`, `controlAgreementId`, `creditDecisionId`, `recoveryCaseId`, `cashReceiptId`, `settlementId`, `repaymentAllocationId` | economic (ours) | ULID (26 chars, Crockford base32) | forever |
| `providerId` | economic (registry) | lowercase slug from the provider registry (`aethir`, `gpunet`, `mockdepin-testonly`) | forever |
| `providerAccountId` | economic (namespaced external) | `{providerId}:{externalAccountId}` | as long as the provider account exists |
| `economicEventId` | economic (namespaced external) | `{providerId}/{externalAccountId}/{eventType}/{providerEventRef}` — `eventType` ∈ `EconomicEventType`; `providerEventRef` is the provider's own stable reference (invoice/settlement/obligation id). When the provider has no stable ref, the ref is `chain:{chainKey}:{height}:{txIndex}:{logOrdinal}` of the *obligation-bearing* source event. | adapters, schema versions, proof re-submissions |
| `receivableId` | economic | ULID; `economicEventId` of the recognizing event stored on the row | forever |
| `sourceEventLocator` | technical, proof-bound | `{chainKey, height, txIndex, logOrdinal}` — `txIndex` from the native `calculateTxIndex`, `logOrdinal` = index **inside the receipt's log array** (not the RPC block-global `logIndex`) | env-specific (`chainKey` is per Creditcoin environment) |
| `sourceEventId` | technical, derived | `keccak256(envId ‖ chainKey ‖ height ‖ txIndex ‖ logOrdinal)`; exact preimage encoding fixed by GPU-076/029 | one destination environment |
| `proofQueryKey` | technical, cache | `{envId, chainKey, txHash}` — SDK `proof-by-tx` cache key; **never** a consumption key | proof service |
| `proofArtifactId` | technical | `sha256` of the canonical proof JSON (`chainKey, headerNumber, txBytes, merkleProof, continuityProof`) | bytes |
| `nativeVerificationId` | technical | destination `{chainId, txHash, logIndex}` of the app's verification/consumption tx | destination chain |
| `observationId` | technical | `{source: API|WEBHOOK|CHAIN|MANUAL, sourceRef, sha256(rawPayload)}` | — |
| `manifestHash`, `policyVersionId`, `agreementVersionId`, `schemaVersion` | version pins | `sha256:…` / semver / ULID | — |

Rules: economic IDs are never derived from verifier address, SDK version, proof bytes, or submission tx.
The same `economicEventId` observed via API, webhook, and chain is reconciled to **one** row.

## 3. Common value types

```jsonc
"AssetRef":  { "chainId": 11155111, "address": "0x…", "symbol": "USDC", "decimals": 6 }   // address null for native coin
"Money":     { "amount": "1234567", "asset": AssetRef }                                    // integer base units, string
"Valuation": { "money": Money, "inAsset": AssetRef, "amount": "…", "rateSource": "…", "rateAt": "…", "policyVersionId": "…" }
"ChainRef":  { "envId": "cc3-testnet", "chainId": 102031 }                                  // destination
"SourceChainRef": { "envId": "cc3-testnet", "chainKey": 1, "chainId": 11155111, "encoding": 1, "manifestHash": "sha256:…" }
"Timestamp": { "at": "2026-09-13T22:14:25Z", "provenance": Provenance }
"Provenance":{ "kind": "NATIVE_PROOF|PROVIDER_API|PROVIDER_STATEMENT|CHAIN_RPC|OUR_SYSTEM|MANUAL|SIMULATED",
               "ref": "…", "observedAt": "…", "schemaVersion": "…", "trust": "PROVEN|ASSERTED|OBSERVED|CLAIMED" }
```

- `Money.amount` matches `^-?[0-9]+$` (negative only in `Correction.delta`). Percentages are basis points
  (`uint16`, `10000 = 100%`). Rates in JSON are strings with explicit scale (`{"value":"1000","scaleBps":true}`).
- Decimals come from the asset registry (`ProviderRegistry` / `TokenRegistry`), never from the payload.

## 4. Entities

Ownership column: **DB** (Postgres, GPU-015/016), **API** (DTO, GPU-045), **SOL** (on-chain, GPU-029~043).
PII column marks fields that never leave the access-controlled store.

| Entity | Key fields | Owner | PII |
| --- | --- | --- | --- |
| `Borrower` | `borrowerId`, `legalEntityId`, `wallets[]{address, chainId, role, verifiedAt}`, `groupId`, `kycStatus`, `underwritingStatus`, `exposure{borrower,group}` | DB (+SOL: wallet ↔ facility binding only) | no (references only) |
| `LegalEntity` | `legalEntityId`, `jurisdiction`, `registrationRef`, `beneficialOwnersRef`, `signingAuthorityRef`, `documentsRef[]` | DB | **yes** (refs to vault store) |
| `ProviderAccount` | `providerAccountId`, `providerId`, `externalAccountId`, `borrowerId`, `roles[]` (`OPERATOR|PAYEE|ADMIN`), `authScope[]`, `credentialRef` (secret manager ref only), `controlVersion`, `lastVerifiedAt` | DB | credential ref only |
| `Asset` | `assetId`, `kind` (`AssetKind`), `sku`, `unitCount`, `identityKeys[]{scheme: GPU_UUID|SERIAL|HOST_ID|GROUP_ID|NFT_TOKEN, value, provenance}`, `ownership` (`OWNED|LEASED|UNKNOWN`), `custodian`, `location`, `parentAssetId` (MIG/vGPU/VM/container → physical) | DB | location coarse only |
| `AssetAssignment` | `assignmentId`, `assetId`, `providerAccountId`, `from`, `to` (null = current), `reason` (`ONBOARD|MOVE|RMA|OFFBOARD`), `provenance` | DB | no |
| `Encumbrance` | `encumbranceId`, `assetId` or `receivableId`, `holder`, `priority`, `kind` (`LIEN|ASSIGNMENT|LEASE|PLEDGE`), `documentRef`, `validFrom/To` | DB | doc ref only |
| `ControlAgreement` | `controlAgreementId`, `borrowerId`, `providerAccountId`, `facilityIds[]`, `controlGrade` (E0–E3), `subject[]` (`REWARD_RECEIVER|SERVICE_FEE_RECEIVER|CLAIM_DESTINATION|UNSTAKE|ACCOUNT_RECOVERY|SIGNER`), `receiver{chainId,address}`, `changeAuthority` (`BORROWER_ALONE|PROTOCOL|PARTNER|MULTI`), `agreementHash`, `agreementVersionId`, `effectiveFrom/To`, `precedence`, `lastObservedAt`, `observationProvenance` | DB + SOL (hash, version, grade, expiry) | doc ref only |
| `Facility` | `facilityId`, `borrowerId`, `vaultId`, `loanAsset` (AssetRef on destination), `state` (`FacilityState`), `approvedCap` (Money), `advanceRateBps`, `termsVersionId`, `policyVersionId`, `requiredVerification` (= `ATTESTCOIN_NATIVE`), `executionProfile`, `principal`, `unpaidInterest`, `fees`, `reservedDraws`, `rateBps`, `accrualBasis` (`ACT_365`), `maturityAt`, `usedReceivableIds[]`, `controlAgreementId` | SOL (ledger) + DB (mirror) | no |
| `CreditDecision` | `creditDecisionId`, `facilityId`, `decidedBy` (role), `policyVersionId`, `inputs{eligibleReceivableIds[], nativeVerificationIds[], controlAgreementId, provenanceSummary}`, `limit` (Money), `validUntil`, `freshnessCheckpoint` (GPU-076), `status` (`DRAFT|APPROVED|EXPIRED|REVOKED`) | DB + SOL (hash + expiry) | no |
| `Receivable` | `receivableId`, `economicEventId`, `providerAccountId`, `debtor` (payer entity), `contractRef`, `period{from,to}`, `dueAt`, `gross` (Money), `deductions[]{kind, Money}`, `net` (Money), `paidAmount`, `unpaidAmount`, `state` (`ReceivableState`), `assignment{facilityId, encumbranceId}`, `revision`, `sourceCheckpoint` (GPU-076), `evidence[]` (BusinessEvidence refs) | DB + SOL (aggregate per facility) | no |
| `Settlement` | `settlementId`, `providerAccountId`, `batchRef`, `receivableAllocations[]{receivableId, Money}`, `netPayout` (Money), `state` (`SettlementState`), `payer`, `payee`, `sourceCashReceiptId`, `legs[]` (conversion/bridge legs with `inFlight` Money), `destinationCashReceiptId`, `revision`, `corrections[]` | DB | no |
| `CashReceipt` | `cashReceiptId`, `where` (`SOURCE_ESCROW|DESTINATION_VAULT|BANK`), `locator` (`{chainId, txHash, logIndex}` or bank ref), `asset`, `amount`, `finality` (`PENDING|FINAL|REORGED`), `escrowId`, `earningsProvenance`, `sourceEventId?`, `cashState` | DB + SOL (destination receipts only) | no |
| `RepaymentAllocation` | `repaymentAllocationId`, `cashReceiptId`, `facilityId`, `settlementId?`, `fees`, `interest`, `principal`, `excess`, `txRef` (`repayFor`), `at` | SOL + DB | no |
| `RecoveryCase` | `recoveryCaseId`, `facilityId`, `trigger`, `openedAt`, `reserveUsed`, `recovered[]`, `costs[]`, `writeOff` (Money), `postWriteOffRecoveries[]`, `state` | DB + SOL (impairment/write-off amounts) | no |
| `PolicyVersion` / `TermsVersion` | id, `approvedBy`, `approvedAt`, parameters (advance, haircuts, caps, freshness, grace, default rate), `TEST_ONLY` flag | DB + SOL (hash) | no |

## 5. Evidence chain (R2 — separate records, separate keys)

```text
SourceEvent ──▶ ProofRequest ──▶ ProofArtifact ──▶ NativeVerification ──▶ EvidenceConsumption ──▶ BusinessEvidence ──▶ Receivable / CashReceipt
(observed)      (queued)          (untrusted bytes)  (precompile result)     (app-level, once per log)   (business meaning)
```

| Record | Key | Fields | Notes |
| --- | --- | --- | --- |
| `SourceEvent` | `sourceEventLocator` (+ `sourceEventId`) | `sourceChain` (SourceChainRef), `emitter`, `topic0`, `topics[]`, `data`, `txHash` (claimed), `claimedBlockTime` (claimed), `observation` (Provenance), `executionProfile` | `txHash`/time are worker claims until proven; only the locator is proof-bound |
| `ProofRequest` | `proofRequestId` (ULID) | `proofQueryKey`, `sourceEventLocator`, `state` (`OBSERVED|WAITING_ATTESTATION|PROOF_READY|SUBMITTED|NATIVE_ACCEPTED|CONSUMED|INVALID|UNSUPPORTED|EXPIRED`), attempts, backoff, `manifestHash` | durable lifecycle (GPU-079) |
| `ProofArtifact` | `proofArtifactId` | `chainKey`, `headerNumber`, `txBytes`, `merkleProof`, `continuityProof`, `serviceMeta{cached, generatedAt, host}` (untrusted), `sdkVersion`, `manifestHash` | stored as untrusted input |
| `NativeVerification` | `nativeVerificationId` | destination `{chainId, txHash, blockNumber, logIndex}`, `verifier` (app contract), `precompile`, `result` (`ACCEPTED|REJECTED`), `revertReason?`, `provenTxIndex`, `provenAt` (destination block time), `manifestHash`, `executionProfile` | only this record can set `nativeStatus=NATIVE_ACCEPTED` |
| `EvidenceConsumption` | `sourceEventId` (unique per env) | `consumerContract`, `nativeVerificationId`, `consumedAt`, `consumedBy` (role) | one consumption per source log; second attempt is `DUPLICATE` |
| `BusinessEvidence` | `businessEvidenceId` (ULID) | `kind` (`SOURCE_EVENT_NATIVE|PROVIDER_API|PROVIDER_SIGNED_STATEMENT|OUR_ANCHOR|MANUAL_DOCUMENT`), `refs{sourceEventId?, observationId?}`, `verificationMethod`, `nativeStatus`, `earningsProvenance`, `meaning` (`OBLIGATION_RECOGNIZED|ASSIGNMENT_RECOGNIZED|CORRECTION|PAYOUT|PAYMENT_CANCELLED`), `amount` (Money), `counterparties{payer,payee}`, `economicEventId`, `validUntil` (policy), `trust` | `OUR_ANCHOR` can never carry `nativeStatus=NATIVE_ACCEPTED` as *GPU revenue*; it proves only that we posted a hash |

## 6. Enumerations (fixed by this ticket; extension requires a schema version bump)

| Enum | Values |
| --- | --- |
| `executionProfile` | `LOCAL_MOCK`, `NATIVE_TESTNET`, `PRODUCTION` |
| `verificationMethod` | `ATTESTCOIN_NATIVE`, `LOCAL_MOCK`, `OFFCHAIN_ASSERTION` |
| `nativeStatus` | `NOT_REQUIRED`, `NOT_REQUESTED`, `OBSERVED`, `WAITING_ATTESTATION`, `PROOF_READY`, `SUBMITTED`, `NATIVE_ACCEPTED`, `CONSUMED`, `INVALID`, `UNSUPPORTED`, `EXPIRED` |
| `earningsProvenance` | `UNCLASSIFIED`, `PROVIDER_SETTLEMENT`, `PROVIDER_INCENTIVE`, `SELF_TRANSFER`, `THIRD_PARTY_UNKNOWN`, `REFUND_OR_REVERSAL`, `SIMULATED` |
| `controlGrade` | `E0`, `E1`, `E2`, `E3` |
| `cashState` | `NONE`, `SOURCE_ESCROW`, `IN_FLIGHT`, `DESTINATION_RECEIVED`, `ALLOCATED`, `RETURNED` |
| `environmentStatus` | `UNCONFIRMED`, `PROBED`, `UNSUPPORTED` (from GPU-075) |
| `FacilityState` | `DRAFT`, `UNDER_REVIEW`, `CONTROL_PENDING`, `ACTIVE`, `DRAW_FROZEN`, `DELINQUENT`, `DEFAULTED`, `RECOVERY`, `REPAID`, `RELEASED`, `CLOSED_WITH_LOSS` |
| `ReceivableState` | `RECOGNIZED`, `ASSIGNED`, `PARTIALLY_PAID`, `PAID`, `DISPUTED`, `CANCELLED`, `WRITTEN_OFF` |
| `SettlementState` | `ANNOUNCED`, `PAID_AT_SOURCE`, `CONVERTING`, `RECEIVED_AT_DESTINATION`, `ALLOCATED`, `REVERSED` |
| `AssetKind` | `PHYSICAL_GPU`, `MIG_PARTITION`, `VGPU`, `VM`, `CONTAINER`, `STAKING_GROUP`, `NODE_NFT` |
| `EconomicEventType` | `OBLIGATION`, `ASSIGNMENT`, `CORRECTION`, `PAYOUT`, `CANCELLATION`, `REFUND` |
| `Trust` | `PROVEN` (native), `ASSERTED` (signed by a named party), `OBSERVED` (read from an API/RPC), `CLAIMED` (worker/user input) |

Semantics: `nativeStatus=NATIVE_ACCEPTED` means only "this log occurred on this source chain". `CONSUMED`
adds "our app recorded it once". Neither implies `earningsProvenance=PROVIDER_SETTLEMENT`, an unpaid
receivable, E2, or cash. `SIMULATED` provenance is mandatory for TEST_ONLY sources (MockDePIN).

## 7. Time semantics

| Field | Meaning | Allowed provenance | Use |
| --- | --- | --- | --- |
| `occurredAt` | when the economic fact happened at the source (block time / provider period end) | PROVIDER_*, CHAIN_RPC (OBSERVED), or proof-bound height with policy-derived time | period attribution, never freshness by itself |
| `confirmedAt` | finality/attestation of the source block | CHAIN_RPC, NATIVE_PROOF (height) | attestation wait |
| `observedAt` | first seen by our system | OUR_SYSTEM | ingestion lag metrics |
| `acceptedAt` | evidence accepted into a decision | OUR_SYSTEM | audit; **never** extends validity (R2-D06) |
| `provenAt` | destination block time of the native verification tx | NATIVE_PROOF | validity window start for the *proof*, not the fact |
| `validUntil` | policy expiry of the evidence | policy | draw gating |

Official V1 encoding carries no source timestamp inside the proven bytes; a source-time claim must be
labeled `CLAIMED`/`OBSERVED` and policy uses the proven height plus a checkpoint (GPU-076).

## 8. Corrections and revisions

- `Receivable.revision` increments on any provider-side change; each change is a `Correction` row:
  `{correctionId, targetId, targetRevision, kind: REVERSAL|DELTA, delta: Money (signed), reason, provenance}`.
- Paid/cancelled/refund events reduce `unpaidAmount` and may set `state`; they never delete the receivable
  or the facility's already-drawn debt (R2-D06/D07; GPU-076 dispute handling).
- A correction against a receivable already used in a `CreditDecision` marks the decision `REVOKED` if the
  new eligible amount is below the drawn amount; existing debt is unchanged.

## 9. Ownership and privacy boundary

| Where | Holds | Never holds |
| --- | --- | --- |
| On-chain (Creditcoin) | facility ledger (principal/unpaid interest/fees), approved cap + policy hash, control agreement hash/version/grade/expiry, `sourceEventId` consumption set, destination cash receipts, repayment allocations, impairment/write-off amounts, manifest hash of the verifier binding | PII, agreements, telemetry, API secrets, provider raw payloads |
| DB (Postgres) | all entities above, raw provider payloads + hashes, observations, job/outbox tables, audit | plaintext credentials (secret-manager refs only) |
| API DTOs | scoped projections (see §11) with `schemaVersion` | credential refs, raw payloads, other borrowers' data |
| Browser | public chain state + the caller's own scoped DTOs | anything else |

## 10. Path table (TICKET §0.5 — confirmed with additions)

| Purpose | Path | Status |
| --- | --- | --- |
| v2 contracts / tests | `contracts/gpu/`, `test/gpu/` | confirmed (solc profile ≥ 0.8.28 for official imports — GPU-075 E1) |
| Python shared domain / DB / connectors | `offchain/gpu/hashcredit_gpu/`, `offchain/gpu/tests/`, `offchain/gpu/migrations/` | confirmed (GPU-015) |
| GPU API / worker | `offchain/api/hashcredit_api/gpu/`, `offchain/prover/hashcredit_prover/gpu/` | confirmed |
| Official SDK tools / proof client | `offchain/attestcoin/` | exists (GPU-075) |
| Source event contracts / native verifier | `contracts/gpu/source/`, `contracts/gpu/AttestcoinRevenueVerifier.sol` | confirmed |
| Official env manifests / fixtures | `config/attestcoin/`, `test/fixtures/gpu/attestcoin/` | exist (GPU-075) |
| **Domain schemas** | `config/gpu/schema/` | added by this ticket |
| **Domain / settlement fixtures** | `test/fixtures/gpu/domain/`, `test/fixtures/gpu/settlements/` | added / GPU-014 |
| **Repo scripts** | `script/gpu/` | added (validator); e2e scripts later (GPU-057/080) |
| Design / decisions / partners / execution | `docs/gpu/`, `docs/gpu/decisions/`, `docs/gpu/partners/`, `docs/gpu/execution/` | exist |

## 11. Product API v1 (contract only; implementation GPU-045)

Base: `/v1`. Every response: `{ "schemaVersion": "1.0", "data": …, "meta": { "executionProfile": … } }`.
Errors: `{ "error": { "code": ErrorCode, "message": str, "details": {...}, "requestId": str } }`.

| Resource | Methods | Scopes (who may call) | Notes |
| --- | --- | --- | --- |
| `/providers` | GET | any authenticated | registry: `providerId`, supported source chains (from manifest), capability flags with `unsupported` explicit |
| `/connections` | GET, POST, DELETE | borrower (own), operator | link `ProviderAccount`; credentials via secret ref; no write capability implied by a read connection |
| `/assets` | GET, POST | borrower (own), underwriter, operator | identity keys + assignments; RMA/move history |
| `/facilities` | GET, POST (draft), PATCH (state by role) | borrower (own, read), underwriter, operator, keeper (read) | ledger mirror; draws are on-chain, not via API |
| `/receivables` | GET | borrower (own), underwriter, operator | includes `unpaidAmount`, `state`, evidence refs, revision |
| `/settlements` | GET | borrower (own), operator, keeper | legs and cash state; `receivedAtDestination` only from `CashReceipt` |
| `/control-agreements` | GET, POST, PATCH | underwriter, operator; borrower read | grade/version/expiry; observation provenance |
| `/repayments` | GET | borrower (own), operator, LP (aggregate) | allocations from on-chain events |
| `/recoveries` | GET, PATCH | operator, credit | cases, reserve use, write-offs |
| `/evidence` | GET | underwriter, operator, keeper | evidence chain records by `sourceEventId` / `economicEventId` |
| `/webhooks/{providerId}` | POST | provider (signed) | signature + timestamp + replay check; never final by itself |

Roles: `borrower`, `lp`, `underwriter`, `operator`, `keeper`, `guardian`, `treasury` (GPU-013 defines
authority). Keeper can never set `payer`, `payee`, or `beneficiary` fields.

`ErrorCode`: `VALIDATION`, `UNAUTHENTICATED`, `FORBIDDEN_SCOPE`, `NOT_FOUND`, `CONFLICT_REVISION`,
`PROFILE_MISMATCH`, `UNSUPPORTED_SOURCE`, `EVIDENCE_STALE`, `EVIDENCE_INVALID`, `CONTROL_INSUFFICIENT`,
`LIMIT_EXCEEDED`, `DUPLICATE_CONSUMPTION`, `RATE_LIMITED`, `UPSTREAM_UNAVAILABLE`, `INTERNAL`.

## 12. Sample scenarios covered by `test/fixtures/gpu/domain/sample-v1.json`

1. One borrower (`brw_…`) with **two facilities** (one `ACTIVE`, one `DRAFT`) on the same vault.
2. One physical GPU (`PHYSICAL_GPU`, serial + GPU UUID) with a `MIG_PARTITION` child, **moved** from
   provider account A to account B (two `AssetAssignment` rows, first closed with reason `MOVE`).
3. One settlement **split** across two receivables (`receivableAllocations` sums to `netPayout`), with a
   source escrow receipt (`SOURCE_ESCROW`), a conversion leg (`IN_FLIGHT`), and a destination receipt
   (`DESTINATION_RECEIVED`) followed by a `RepaymentAllocation` — debt changes only on the last.
4. Evidence chain for **one source tx with two logs** → two `SourceEvent`/`EvidenceConsumption` rows
   sharing `txHash`/`txIndex`, distinct `logOrdinal`; one `ProofArtifact`; one `NativeVerification`.
5. A `NATIVE_TESTNET` evidence row that a `PRODUCTION` reader must reject (`executionProfile` mismatch).
6. `chainKey 1` meaning Sepolia on `cc3-testnet` and Ethereum mainnet on `cc3-mainnet` (two
   `SourceChainRef`s with the same `chainKey`, different `envId`/`chainId`).
7. Upstream-missing fields expressed as `null` with `Provenance.trust=CLAIMED|OBSERVED`; nothing invented.
8. A `Correction` (`DELTA` −1,000 units) against receivable revision 1 producing revision 2.

The validator checks schema conformance, allocation sums, unique `(envId, sourceEventLocator)` consumption,
and that production-profile facilities reference no non-`PRODUCTION` evidence.
