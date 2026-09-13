# Native evidence contract: proof scope, source financial events, receivable semantics

Partner-specific parts remain open until a real provider supplies source-contract facts.
This specification builds on `environment.md` (official artifacts), `domain-model.md` (records and enums),
and `accounting.md`.
Companion: `proof-to-business-mapping.md`; fixtures `test/fixtures/gpu/attestcoin/{source-events-v1.abi,
evidence-vectors-v1,canonical-id-vectors-v1}.json`.

## 1. The chain and what each stage proves

```text
ProofEnvelope ─▶ VerifiedSourceEvent ─▶ BusinessEvidence ─▶ EligibleUnpaidReceivable ─▶ (decision, draw)
 untrusted        native fact              our interpretation      policy + issuer state
```

| Stage | Record | Proves | Does **not** prove |
| --- | --- | --- | --- |
| `ProofEnvelope` | `ProofArtifact` + submission | nothing until verified | anything |
| `VerifiedSourceEvent` | `NativeVerification` + `EvidenceConsumption` + `SourceEvent` | *this log, at this locator, was emitted by this contract in a finalized block of the attested source chain* (BlockProver: inclusion + continuity) and, after our checks, `receiptStatus == 1`, emitter ∈ registry, topic/data shape | that the emitter told the truth; who legally owes what; that nothing happened later |
| `BusinessEvidence` | `BusinessEvidence` | our classification: meaning (`OBLIGATION_RECOGNIZED` …), amount, counterparties, `earningsProvenance`, `trust` | current unpaid balance; E2; cash |
| `EligibleUnpaidReceivable` | `Receivable` (state, `unpaidAmount`, revision, `sourceCheckpoint`) + policy | a receivable the policy allows in the base **now** | anything about tomorrow |

`nativeStatus=NATIVE_ACCEPTED` is a statement about a source log only.

## 2. ProofEnvelope (untrusted input; official SDK 0.18.0 shape)

```jsonc
{ "chainKey": 1, "headerNumber": 9100000, "txBytes": "0x…",         // proof-bound once verified
  "merkleProof": { "root": "0x…", "siblings": [{ "hash": "0x…", "isLeft": true }] },
  "continuityProof": { "lowerEndpointDigest": "0x…", "roots": ["0x…"] },
  "serviceMeta": { "txHash": "0x…", "txIndex": 17, "cached": true, "generatedAt": "…" }   // claimed only
}
```

- Nothing in the envelope is trusted. The only outputs of verification that count are: the precompile
  result on **exactly these bytes**, the proven `txIndex` = `calculateTxIndex(merkleProof)`, and the
  fields the official decoder reads from `txBytes` (`EvmV1Decoder`: type, `from`, `to`, `receiptStatus`,
  `receiptLogs[]{address_, topics, data}`).
- The official V1 encoding carries **no source block timestamp**. We do not invent one: `occurredAt` is
  `CLAIMED` (RPC) with provenance, and validity policy runs on the proven height + acceptance rules (§6).
- `serviceMeta.txHash`/`txIndex` are worker hints; the consumption key never uses them.

## 3. VerifiedSourceEvent locator and ID contract

| Field | Bound by | Source |
| --- | --- | --- |
| `envId` | manifest (`manifestHash`) of the verifier deployment | environment manifest |
| `chainKey` | manifest ↔ ChainInfo supported table (`chainKey`↔`chainId`↔`encoding`) | proof + manifest |
| `height` | proof (`headerNumber`); the continuity proof binds it to an attestation | native |
| `txIndex` | `calculateTxIndex(merkleProof)` computed on-chain | native |
| `logOrdinal` | zero-based index inside `receiptLogs[]` of the decoded receipt, not the RPC block-global `logIndex` | verified bytes |
| `emitter`, `topics`, `data` | decoded from verified bytes | verified bytes |
| `receiptStatus` | decoded; must be `1` | verified bytes |

**IDs**

- `sourceEventId = keccak256(abi.encode(keccak256(envId), uint64 chainKey, uint64 height, uint64 txIndex,
  uint32 logOrdinal))` is the consumption key; one consumption per ID per environment. Vectors:
  `canonical-id-vectors-v1.json` (Python, TypeScript, and Solidity agree).
- `proofQueryKey = (envId, chainKey, txHash)` is the proof-service cache key. It is never a consumption
  key: two logs in one tx share it (EV-01); a re-submission with different proof bytes shares it too.
- `economicEventId` (domain-model §2) is derived from provider/account/eventType/provider ref, **never**
  from verifier address, SDK/ABI version, proof bytes, or submission tx hash. Re-verification under a
  new verifier or manifest re-consumes nothing.
- Same `chainKey` means different chains per environment (cc3-testnet: 1 = Sepolia; cc3-mainnet: 1 =
  Ethereum); the `envId` in the id prevents cross-environment replay. `executionProfile` is carried on
  every record and production readers reject anything else.
- **Reorg policy**: destination canonical reorg ⇒ the read model rolls back consumption/evidence rows for
  orphaned verification blocks; the id contract is unchanged, so re-inclusion re-creates the same rows.
  Source-chain facts are only ever accepted at attested heights, so source reorgs below the attestation
  are impossible by construction; a dispute *after* a draw is handled in §7, not by rollback.

## 4. Source financial events (internal proposal vs external ABIs)

The event ABI for Rackline-controlled source contracts (TEST_ONLY MockDePIN and any escrow we
deploy) is `source-events-v1.abi.json`. Real partner ABIs are external and
unconfirmed; they must be recorded per partner and mapped through the same
meanings below. An external event is admissible only if its issuing authority and state change are
understood (§5).

| Meaning | Internal event | Business effect | Who may emit |
| --- | --- | --- | --- |
| `OBLIGATION_RECOGNIZED` | `ObligationRecognized(accountKey, obligationRef, issuer, payer, payee, amount, dueAt, revision)` | creates/updates a receivable at `revision` (net of issuer deductions) | issuer role; `msg.sender`-bound |
| `ASSIGNMENT_RECOGNIZED` | `ObligationAssigned(accountKey, obligationRef, facilityKey, revision)` | receivable assigned to a facility (E2 evidence input, not E2 itself) | issuer or controller |
| `CORRECTION` | `ObligationCorrected(accountKey, obligationRef, delta, revision, reason)` | signed delta; original untouched | issuer |
| `PAYOUT` | `PayoutReceived(accountKey, obligationRef, token, payer, amount, settlementSeq)` | `amount` = escrow-measured balance delta; reduces `unpaidAmount` when `obligationRef ≠ 0`, else `UNCLASSIFIED` until reconciled | escrow contract itself (never `notify(amount)`) |
| `PAYMENT_CANCELLED` | `PayoutCancelled(accountKey, obligationRef, settlementSeq, amount)` | reverses a payout | escrow/issuer |
| `CHECKPOINT` | `SourceCheckpoint(accountKey, checkpointSeq, latestRevision, openAmount, paidCumulative)` | issuer-maintained current state, used by the freshness gate (§6) | issuer |

**Payout-only providers.** If a partner only lets us prove past payouts (no natively provable obligation
or assignment), payouts are `history` and `unpaidAmount` reductions only. The first product's borrowing
base needs natively provable obligation and assignment events or an approved alternative. Without one,
the partner has no production eligibility.

## 5. Issuer authority, binding, units, duplicates

- **Authority**: an event counts only if its emitter is a registered source contract for the provider in
  the manifest/registry and the emitting role (issuer/controller/escrow) is the one the meaning requires.
  Same topics from another emitter ⇒ `EMITTER_NOT_REGISTERED`, no business evidence (EV-09).
- **State change**: obligation events must correspond to a state transition on the source contract
  (created/assigned/corrected/paid), not to a free-form log; TEST_ONLY contracts enforce this in code.
- **Binding**: `accountKey = keccak256(providerId ":" externalAccountId)` must map to a `ProviderAccount`
  of the facility's borrower; `token` must be the facility's admitted source asset; `chainKey` must be the
  facility's source chain. Mismatch ⇒ recorded raw, not attached (EV-07).
- **Units**: amounts are base units of the event's `token` on the source chain; loan-currency valuation
  is a separate `Valuation` with rate provenance (never inside the event).
- **Net vs gross**: `ObligationRecognized.amount` is net of issuer deductions; later deductions arrive as
  `CORRECTION` deltas; the receivable keeps `gross`, `deductions[]`, `net`, `paidAmount`, `unpaidAmount`.
- **Revision**: monotonic per `obligationRef`; a lower or equal revision after a higher one is ignored as
  stale (recorded, flagged `REVISION_OUT_OF_ORDER`).
- **Duplicates**: one consumption per `sourceEventId`; the same economic event observed via API, webhook,
  or another proof bytes maps to the same `economicEventId` and is reconciled, not re-recognized.
  `settlementSeq` makes payout replays impossible at the escrow level.

## 6. Freshness and omission defense

- `acceptedAt` is the first time we recorded the evidence; it never extends validity. Validity
  (`validUntil`) is `provenAt + policy window` and applies to the *proof*, not to the receivable's
  existence.
- **Checkpoint rule**: a credit decision cites a `SourceCheckpoint` for each account whose
  `latestRevision` equals the highest revision consumed for every receivable in the base, and whose
  `openAmount` reconciles (within policy tolerance) with the sum of our `unpaidAmount`s. Missing checkpoint
  ⇒ no draw (EV-10). Checkpoint shows a higher revision than we consumed ⇒ `REVISION_GAP`, no draw until
  ingested (EV-11). Checkpoint older than `checkpointMaxAge` ⇒ stale, no draw.
- **Selective disclosure**: because the checkpoint is issuer-published on-chain and revision-monotonic,
  a submitter cannot hide a later `PAYOUT`/`CORRECTION` by only submitting the older obligation proof.
- **Bounded lag / buffer**: the pilot allows no lag (`0`); any later bounded-lag or buffer policy must be
  approved and recorded in `policy_versions`.
- **Reservation**: while a draw is being executed, the receivables it relies on are `reservedDraws`
  on the facility; a correction arriving in between revokes the decision before execution.

## 7. Reorg vs dispute after execution

| Situation | Handling |
| --- | --- |
| Destination canonical reorg orphaned our verification/consumption tx | read model rollback; re-inclusion re-creates identical rows; facility limits recomputed |
| Source dispute after a draw/repay (issuer corrects or cancels) | receivable → `DISPUTED`/corrected revision; decision revoked; new draws blocked; existing destination debt, transfers, and received repayments remain; reconciliation and agreement procedure applies |
| Proof-service outage | no new facts; existing evidence valid within its window; `repayFor` unaffected |

## 8. Separation table (what each artifact may be used for)

| Artifact | May establish | May not establish |
| --- | --- | --- |
| Native-verified obligation/assignment event from a registered issuer | receivable existence, amount at revision, assignment | E2, cash, legal enforceability |
| Native-verified payout event from the escrow | payment history, `unpaidAmount` reduction, `cashState=SOURCE_ESCROW` | destination repayment, revenue provenance beyond the escrow's classification |
| Our own anchor (`OUR_ANCHOR`) | that we posted a hash | any source fact (EV-05) |
| Provider API / signed statement | `ASSERTED` facts for underwriting and reconciliation | native validity, borrowing base by itself |
| Control proof + partner recognition | `controlGrade` | receivables |
| Destination cash receipt + allocation | repayment | anything at the source |

## 9. OPEN (partner-dependent)

| ID | Question | Blocks |
| --- | --- | --- |
| EC-O01 | Which partner events are natively provable obligation/assignment events (vs payouts only)? | production admission |
| EC-O02 | Does the partner publish an on-chain checkpoint/revision, or must the checkpoint be an issuer-signed statement anchored by *them*? (our anchor does not count) | freshness gate design |
| EC-O03 | Partner event ABIs, decimals, issuer roles, escrow semantics | source integration |

## 10. Test vectors

`evidence-vectors-v1.json`: EV-01 two logs/one tx · EV-02 one receivable/many payouts · EV-03 one
payout/many receivables · EV-04 own transfer · EV-05 own anchor · EV-06 paid re-pledge · EV-07 other
account/token/chain · EV-08 source confirmed, destination cash missing · EV-09 wrong emitter · EV-10
missing checkpoint · EV-11 revision gap · EV-12 reorg vs dispute. `canonical-id-vectors-v1.json`: ids and
amounts verified across Python, TypeScript, and Solidity.
