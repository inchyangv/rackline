# Permissions, control agreements, and state transitions

This document complements `docs/gpu/domain-model.md` and defines who may act,
how those actions are authenticated, and which state
transitions are legal. Nothing here grants a partner-side right.

## 1. Actors

| Actor | Represents | Key custody | Can never |
| --- | --- | --- | --- |
| `borrower` | operator legal entity via verified wallets (EOA or smart-contract wallet) | operator's own | change payer/payee of assigned receivables, waive evidence, set its own limit |
| `registrar` | onboarding operations | operator-held hot key or multisig | approve credit, move funds, release control |
| `underwriter` | credit decision | multisig / hardware key | move funds, verify evidence, override native requirement |
| `guardian` | incident response | multisig, time-boxed | move funds, waive evidence, release collateral, resume draws alone |
| `oracle` (keeper) | proof relay + settlement observation | keeper hot key (relay gas payer) | set payer/borrower/beneficiary, create receivables, grant limits, sign anything but relay txs |
| `treasury` | vault admin, rails | multisig + timelock | grant credit, alter evidence, change control agreements |
| `servicer` | collections and reconciliation | operator-held | change waterfall order, release control before debt = 0 |
| `provider admin` | partner's own authority (external) | partner | be impersonated by our keys; partner actions are observed, never assumed |
| `lp` | vault depositor | own wallet | anything beyond deposit/withdraw/preview |

Separation rules: the relay gas payer (`oracle`) is never the revenue issuer, the treasury, or an approver.
No single actor holds two of {underwriter, treasury, guardian}. Key rotation for any role is a
recorded event with a new key epoch; old-epoch signatures are rejected after the epoch's grace window.

## 2. Authentication and signatures (auxiliary paths, never source facts)

All application signatures are EIP-712 typed data with: `domain{name, version, chainId, verifyingContract}`,
`purpose` (enum below), `subject` (ids), `nonce` (per signer, monotonically consumed), `issuedAt`,
`expiresAt`, `keyEpoch`. A signature is valid only for one `purpose` and one `verifyingContract`; replay
across chains, contracts, purposes, or callers is rejected.

| Purpose | Signer | Creates | Never creates |
| --- | --- | --- | --- |
| `WALLET_LINK` | borrower wallet | proof that the wallet is controlled by the borrower | any source fact |
| `AGREEMENT_CONSENT` | borrower authorized signer | consent hash for a `TermsVersion` / `ControlAgreement` version | legal effect by itself (recorded, reviewed) |
| `CREDIT_APPROVAL` | underwriter | `CreditDecision.status=APPROVED` for stated inputs | native acceptance, borrowing base without native evidence |
| `CONTROL_ATTESTATION` | provider admin or registrar (asserting an observation) | `ControlAgreement.observationProvenance` (ASSERTED) | E2 by itself; E2 also requires a control test and partner recognition |
| `RELAY` | oracle keeper | submission of a proof tx | verification result (only the precompile does) |
| `TREASURY_OP` | treasury multisig | vault/rail parameters via timelock | evidence or credit changes |

Smart-contract wallets authenticate with ERC-1271; a wallet may be linked to one borrower at a time;
re-linking requires the previous link to be released (no silent takeover). Nonces are per (signer,
purpose). `expiresAt − issuedAt` ≤ policy TTL (default 15 min for approvals, 5 min for wallet link).

## 3. Control agreements

`ControlAgreement` fields (domain model §4): `controlGrade`, `subject[]`, `receiver`, `changeAuthority`,
`agreementHash`, `agreementVersionId`, `effectiveFrom/To`, `precedence`, `lastObservedAt`.

| Operation | Who | Preconditions | Effect |
| --- | --- | --- | --- |
| create (grade E0/E1 draft) | registrar | borrower `AGREEMENT_CONSENT` on version | agreement exists, not usable for funding |
| attest grade E2 | underwriter, with a control-test record and partner-recognition reference | observation provenance `ASSERTED` by provider admin and control test `outcome=PASS` | grade E2, `effectiveFrom` set |
| version bump | registrar + borrower consent | active facility debt allowed; new version must not lower grade or shrink `subject[]` while debt > 0 | new `agreementVersionId`; facility records the version it was funded under |
| observe | oracle/servicer | read-only partner API/RPC | `lastObservedAt`, `controlVersion` updated; stale > policy window ⇒ draws frozen (not default) |
| revoke / expire | system (expiry) or guardian (incident) | — | grade drops to E1; draws frozen; collections continue |
| release | servicer + treasury (2 roles) | facility `debt == 0` **and** no pending settlement/refund/reversal within the reconciliation window **and** facility `REPAID` | receiver rights returned; agreement `effectiveTo` set; keys/roles returned |

Rules:
- The keeper cannot change `receiver`, `payer`, `payee`, or `subject[]`; those come from agreement versions.
- "Locked" observations older than `controlObservationMaxAge` are stale. A draw against a stale observation
  is refused even if the last observation said locked.
- An admin/guardian/underwriter/verifier key rotation never changes `controlGrade`, `requiredVerification`,
  or the facility's funded agreement version.
- Partner `support override` paths are recorded as residual risk on the agreement; they do not lower our
  grade automatically but must be listed in the PoC.

## 4. Facility state machine

States (domain model enum `FacilityState`). Two independent dimensions are tracked separately:
`Facility.state` (credit lifecycle) and `ProviderAccount.controlVersion/lastVerifiedAt` (operating account
state). An account observation never directly mutates the facility state; a policy job does.

| From | To | Trigger | Authority | Guards |
| --- | --- | --- | --- | --- |
| DRAFT | UNDER_REVIEW | onboarding complete | registrar | wallet linked; legal entity refs present |
| UNDER_REVIEW | CONTROL_PENDING | credit decision approved | underwriter (`CREDIT_APPROVAL`) | decision inputs = native-accepted evidence set + provenance + control agreement id; `requiredVerification=ATTESTCOIN_NATIVE` |
| CONTROL_PENDING | ACTIVE | control grade ≥ E2 attested and effective | underwriter + servicer | agreement version fixed on facility; reserve funded per terms |
| ACTIVE | ACTIVE (draw) | borrower `borrow(facilityId, amount)` on-chain | borrower | fresh decision (not expired/revoked), fresh control observation, `AvailableDraw ≥ amount`, vault cash, no pause on draws |
| ACTIVE | ACTIVE (repay) | `repayFor(facilityId, amount)` by anyone | any | destination receipt allocated; **never blocked by draw pause or evidence outage** |
| ACTIVE | DRAW_FROZEN | evidence stale / proof outage / control observation stale / decision revoked / guardian pause | system, guardian | collections continue |
| DRAW_FROZEN | ACTIVE | cause cleared | system (auto) or underwriter (if decision re-approved) | guardian pause needs guardian + underwriter to lift |
| ACTIVE / DRAW_FROZEN | DELINQUENT | tranche due date passed without full allocation | system | grace clock starts |
| DELINQUENT | ACTIVE | cure (allocation ≥ due) | system | |
| DELINQUENT | DEFAULTED | grace expired, or control loss confirmed, or misrepresentation found | credit committee (underwriter + guardian) | reasons recorded; dispute window respected |
| DEFAULTED | RECOVERY | recovery case opened | servicer | recovery share step-up per agreement |
| RECOVERY | REPAID | debt = 0 through recoveries | system | |
| RECOVERY | CLOSED_WITH_LOSS | write-off approved | credit committee + treasury | reserve applied first; recovery rights remain open |
| ACTIVE | REPAID | debt = 0 | system | |
| REPAID | RELEASED | release conditions (§3) | servicer + treasury | pending refund/reversal check |
| any active/recovery | (disputed evidence) | source dispute after draw | underwriter | marks collateral evidence `DISPUTED` and limits new draws; destination debt and received cash remain |

Forbidden transitions (must revert / be rejected): `RELEASED` with debt > 0; `ACTIVE` without an approved,
unexpired decision; any transition triggered by an `oracle` key; `REPAID` on the strength of a source
receipt, claimable balance, or proof alone; lowering `requiredVerification`; skipping `CONTROL_PENDING`.

## 5. Pauses (separate switches)

| Switch | Blocks | Never blocks | Who |
| --- | --- | --- | --- |
| `pauseDraws` | new draws, limit increases | repay, repayFor, allocation, recovery | guardian (lift: guardian + underwriter) |
| `pauseEvidenceIntake` | acceptance of new evidence | use of already-accepted evidence within validity; repayments | guardian |
| `pauseConversion` | conversion/bridge legs | source collection, destination allocation of already-received cash | treasury |
| `pauseRepayments` | repayFor | — | not exposed in the product path; the legacy v1 global pause is not reused |

## 6. Transition table for the required adversarial cases

| Case | Sequence | Expected outcome |
| --- | --- | --- |
| Receiver change ↔ draw race | partner receiver changed at T; our observation at T−Δ says locked; borrower draws at T+ε | draw refused if observation age > `controlObservationMaxAge`; otherwise draw may pass on the stale read → next observation flips to DRAW_FROZEN; **this residual window is the reason `controlObservationMaxAge` is short and E2 needs partner-side lock, not just observation** |
| Release ↔ late settlement race | debt hits 0; a settlement reversal arrives within the reconciliation window | release refused until window closes; reversal creates a receivable correction, possibly reopening debt |
| Support override | partner support changes receiver despite lock | observation → DRAW_FROZEN; incident; agreement residual risk realized; no automatic default |
| Stale "locked" observation | no observation for > max age | draws frozen; repayments unaffected; alert |
| Key rotation | underwriter key rotated mid-facility | old epoch approvals expire per grace; facility state unchanged; new approvals require new epoch |
| Borrowed asset ≠ received asset | destination receives token X while loan asset is Y | receipt recorded `cashState=DESTINATION_RECEIVED` but **not** allocated; treasury conversion or return; no debt reduction |
| Old release assertion | a signed `AGREEMENT_CONSENT`/release from a previous version replayed | rejected by nonce/version/expiry |
| Keeper tries to set beneficiary | relay tx includes a different payee | contract ignores caller-supplied payee; payee comes from facility/agreement state |
| Verifier/decoder upgrade | new verifier address | facility keeps `manifestHash` it was approved under; new evidence must pass the new manifest; old evidence is not re-accepted under the new one |
| Debt = 0 with pending refund | borrower owes refund to payer per correction | `REPAID` allowed, `RELEASED` blocked until refund settled or escrowed |

## 7. On-chain vs off-chain authority

- On-chain roles: `BORROWER` (per facility), `UNDERWRITER`, `GUARDIAN`, `TREASURY`, `RELAYER` (proof submit
  only), `SERVICER`. Role admin is a timelocked multisig; no role can grant itself `UNDERWRITER + TREASURY`.
- Credit decisions are anchored on-chain as `(decisionHash, validUntil, policyVersion, manifestHash)`;
  `borrow` checks the anchor, the native consumption set, and the control agreement version/expiry.
- Evidence acceptance and consumption keys are contract state in `EvidenceBook`; admin cannot
  insert a consumption without a native verification in the same tx.
- Off-chain services enforce the same guards before building txs but are never the only guard.
