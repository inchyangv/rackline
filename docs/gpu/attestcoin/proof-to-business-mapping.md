# Proof → business mapping

Field-by-field mapping from the official Attestcoin artifacts (SDK 0.18.0 / `asc-contracts` 0.2.1, pinned
in `environment.md`) to the records in `domain-model.md`, with the trust class of every value. Rule of
thumb: **a value is `PROVEN` only if it is read from bytes the precompile verified or computed by the
precompile; everything the worker or the proof service says is `CLAIMED`.**

## 1. From the proof service response (`ProofResult.data`, untrusted)

| SDK field | Stored as | Trust | Used for |
| --- | --- | --- | --- |
| `chainKey` | `ProofArtifact.chainKey`; must equal manifest/facility `chainKey` | CLAIMED → checked against manifest before submit | routing |
| `headerNumber` | `ProofArtifact.headerNumber` → after native OK becomes `SourceEventLocator.height` | PROVEN after verification (continuity binds it) | locator |
| `txBytes` | `ProofArtifact.txBytesRef` (stored blob, hash) → the bytes submitted on-chain | PROVEN after verification (the precompile verified exactly these bytes) | decoding |
| `merkleProof.siblings[]` | submitted; `txIndex = calculateTxIndex(merkleProof)` on-chain | PROVEN (computed by precompile) | locator |
| `continuityProof` | submitted | PROVEN after verification | — |
| `txHash` | `SourceEvent.claimedTxHash`, `proofQueryKey` | CLAIMED | cache key, RPC cross-check |
| `txIndex` | ignored for consumption (recomputed on-chain) | CLAIMED | sanity check only |
| `cached`, `generatedAt`, host | `ProofArtifact.serviceMeta` | CLAIMED | ops metrics |

## 2. From the verified bytes (`EvmV1Decoder`, on-chain, GPU-078)

| Decoder output | Stored as | Trust | Check |
| --- | --- | --- | --- |
| `getTransactionType` | `SourceEvent.txType` | PROVEN | `isValidTransactionType`; policy may restrict to 0/1/2 |
| `decodeCommonTxFields.from` | `SourceEvent.txFrom` | PROVEN | used only for own-transfer / payer classification hints |
| `decodeCommonTxFields.to` | `SourceEvent.txTo` | PROVEN | must equal the registered emitter for direct calls; for internal calls the log emitter governs |
| `decodeReceiptFields.receiptStatus` | — | PROVEN | must be `1`, else reject before any meaning |
| `receiptLogs[i].address_` | `SourceEvent.emitter` | PROVEN | must be a registered emitter for the facility's provider/environment |
| `receiptLogs[i].topics[0]` | `SourceEvent.topic0` | PROVEN | must be one of the meanings' `topic0` (internal ABI) or a confirmed external ABI topic |
| `receiptLogs[i].topics[1..]`, `data` | decoded event args | PROVEN | typed decode per ABI; `logOrdinal = i` |

The on-chain verifier selects logs by `(emitter, topic0)` within a bounded log count; every selected log
is a separate `sourceEventId`; unrelated logs in the same receipt are ignored, not errors.

## 3. From the destination verification transaction

| Value | Stored as | Trust |
| --- | --- | --- |
| tx hash / block / log index of our app's `Verified`/`Consumed` events | `NativeVerification.destination`, `EvidenceConsumption` | PROVEN (destination chain) |
| destination block time | `NativeVerification.provenAt` | PROVEN (destination) — the *earliest* time we can attach; used for `validUntil` |
| verifier address, precompile address, manifest hash | `NativeVerification.verifier/precompile/manifestHash` | PROVEN (destination) |

## 4. Business classification (GPU-031/081, off the verified args)

| Input | Output | Notes |
| --- | --- | --- |
| meaning by `topic0` | `BusinessEvidence.meaning` | `OBLIGATION_RECOGNIZED`, `ASSIGNMENT_RECOGNIZED`, `CORRECTION`, `PAYOUT`, `PAYMENT_CANCELLED`, `CHECKPOINT` |
| `accountKey` ↔ `ProviderAccount` | `economicEventId` = `{providerId}/{externalAccountId}/{eventType}/{obligationRef or chain locator}` | mismatch → recorded raw, not attached |
| `amount`, `token` | `BusinessEvidence.amount` (`Money` with source `AssetRef`) | decimals from the token registry, never from the payload |
| `payer` vs borrower wallets / escrow / registered payer | `earningsProvenance` | borrower wallet ⇒ `SELF_TRANSFER`; registered payer ⇒ `PROVIDER_SETTLEMENT`; unknown ⇒ `THIRD_PARTY_UNKNOWN`; TEST_ONLY provider ⇒ `SIMULATED` |
| `revision` | `Receivable.revision` transitions | out-of-order ⇒ flagged, no effect |
| `SourceCheckpoint` args | `Receivable.sourceCheckpoint` / decision `freshnessCheckpoint` | freshness gate |
| emitter == our anchor contract | `kind=OUR_ANCHOR`, `verificationMethod=OFFCHAIN_ASSERTION`, `trust=ASSERTED` | never revenue |

## 5. Worked example (EV-01)

1. Worker observes tx `T` on Sepolia with two `ObligationRecognized` logs (ordinal 0: inv-A 12,000 USDC;
   ordinal 1: inv-B 9,000 USDC). Records two `SourceEvent`s (CLAIMED locator) and one `ProofRequest`
   with `proofQueryKey=(cc3-testnet, 1, T)`.
2. `waitUntilHeightAttested` → `getProof(T)` → `ProofArtifact` (sha256 of canonical JSON).
3. App tx on CC3 testnet: verifier calls `verifyAndEmit(1, 9100000, txBytes, merkle, continuity)`;
   computes `txIndex=17`; decodes receipt; selects logs by `(escrow, topic0)`; emits
   `Verified(sourceEventId_0)` and `Verified(sourceEventId_1)`; EvidenceBook consumes each once.
4. Off-chain projector (GPU-073) writes `NativeVerification` (ACCEPTED, provenTxIndex 17, provenAt =
   destination block time) and two `EvidenceConsumption`s; classifier writes two `BusinessEvidence`
   rows (`OBLIGATION_RECOGNIZED`, `PROVEN`, `SIMULATED` provenance for the TEST_ONLY provider).
5. Receivables inv-A/inv-B are created at revision 1 with `unpaidAmount = net`. They are **not** eligible
   until a `SourceCheckpoint` with `latestRevision ≥ 1` for acct-A is consumed and the policy gates
   (provenance, E2, rights) pass; then the decision may include them.
6. Later `PayoutReceived(inv-A, 4,000)` at the escrow reduces `unpaidAmount` to 8,000 and records
   `cashState=SOURCE_ESCROW`; the facility's debt is unchanged until destination allocation (`accounting.md` AC-07).
