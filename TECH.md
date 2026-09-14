# Rackline technical design

Rackline is a receivables-backed lending system for GPU operators. Verified revenue evidence may increase borrowing capacity; only measured destination cash may reduce debt.

This document describes the implemented prototype and its public native-testnet evidence as of 2026-09-17. Partner integration, real GPU revenue, and production approval are outside the current evidence set. Detailed specifications live under `docs/gpu/`; this document is the map.

## 1. System boundaries

The product separates five independent judgments:

| Judgment | Authoritative input |
| --- | --- |
| Source event occurred | Creditcoin native BlockProver result over the exact source transaction bytes |
| Event represents GPU operating revenue | Registered emitter, issuer, and provider policy |
| Receivable is currently unpaid and eligible | Revisioned source events, checkpoints, deductions, and underwriting policy |
| Payment path is controlled | Versioned control agreement and independently observed control grade |
| Debt was repaid | Measured loan-currency receipt at the destination, allocated to one facility |

An SDK response, HTTP success, signature, admin action, or old payout is not native verification. A source event is not repayment. Local mocks and test-only contracts are never promoted to production evidence.

## 2. On-chain components

All contracts are in `contracts/gpu/`. Tests are in `test/gpu/`.

| Component | Responsibility |
| --- | --- |
| `ProtocolRoles`, `GovernanceTimelock`, `TreasuryTimelock` | Role registry and delayed privileged configuration; emergency boundaries stay outside the timelock |
| `ProviderRegistry`, `AccountRegistry`, `AuthorizationVerifier` | Provider/emitter/issuer registry, borrower-account linkage, EIP-712 approval verification |
| `SourceEscrow` (source chain) | Measures source-token receipts, emits revisioned obligation and payout events, separates unattributed deposits, rejects duplicate settlement IDs |
| `AttestcoinRevenueVerifier` | Calls the official native verifier, decodes only verified bytes, validates receipt status, emitter, and topic, derives log-level source event IDs |
| `EvidenceBook` | Records verification provenance and consumes each technical/economic event once |
| `ReceivableBook` | Tracks recognized, assigned, corrected, paid, and disputed receivables and their evidence validity |
| `ControlRegistry` | Stores versioned payment-control agreements, grade, and last observation |
| `DebtLedger` | Accrues debt and allocates payments in fee → interest → principal → excess order |
| `GpuRiskPolicy`, `ExposureController` | Compute eligibility and reserve borrower/provider/global exposure |
| `CreditFacilityManager` | Enforces facility state, approval hashes, fresh evidence, and atomic draws |
| `LendingVaultV2` | Accounts for LP cash, loan assets, impairments, borrower-owned excess, and queued withdrawals |
| `SettlementReceiver`, `RepaymentRouter` | Record destination receipts and apply measured cash without depending on the proof service |
| `RecoveryManager` | Freezes draws, tracks cure and recovery state, recognizes impairment, records recoveries |

There is one debt ledger. The manager, vault, and router do not keep competing notions of principal or interest.

## 3. Evidence path

```text
source transaction
  -> official proof service response (untrusted)
  -> pinned SDK encoding
  -> Creditcoin native verifier (0x…0FD2)
  -> decode receipt from verified bytes (EvmV1Decoder)
  -> validate source chain, emitter, topic, receipt success
  -> EvidenceBook consume
  -> ReceivableBook revision
  -> risk evaluation / draw reservation
```

Technical event identity is `(envId, chainKey, height, txIndex, logOrdinal)`. Economic identity is separate, so a correction can reference an earlier revision without a duplicate obligation becoming new collateral.

The verifier is bound to a manifest hash. The manifest pins chain IDs, chain keys, encoding, native precompile, decoder source, package versions, and artifact hashes. Unsupported sources fail closed. Specification: `docs/gpu/attestcoin/`.

## 4. Credit and draw path

```text
eligible receivables
  - paid, disputed, stale, or ineligible amounts
  - policy haircuts and deductions
  = eligible unpaid balance

eligible unpaid balance × advance rate
  -> capped by facility approval
  -> capped by borrower/provider/global exposure
  -> capped by lendable vault cash
  = available draw
```

Every draw re-evaluates current state. Exposure is reserved before funds move and released on failure, so concurrent draws cannot exceed a cap. Approval, control version, policy version, manifest, asset, and facility identity are bound together.

Two freshness gates apply on-chain: the receivable's `evidenceValidUntil` (refreshed by recognition, assignment, and correction events, never by a payout) and a consumed source checkpoint younger than `checkpointMaxAge` whose totals reconcile with consumed events. A stale control observation (`controlObservationMaxAge`) also blocks draws. `REPAID` is terminal; a new draw needs a new facility.

## 5. Repayment and accounting

```text
measured destination receipt
  -> fees
  -> unpaid interest
  -> principal
  -> borrower-refundable excess

received = feePaid + interestPaid + principalPaid + excess
```

Invariants:

- Receivables support the borrowing base but are not vault assets.
- Unallocated settlement cash is in flight and does not inflate LP NAV.
- Borrower-refundable excess is not LP-owned.
- Proof outages may block new evidence but never block direct repayment.
- Draw pauses and repayment availability are separate controls.
- Partial interest payments preserve remaining unpaid interest.
- Rate changes accrue the previous segment before applying the new rate.
- Withdrawal requests lock shares; claims cannot exceed reserved assets.
- Impairment and recovery are explicit accounting events.

The reference model (`offchain/gpu/hashcredit_gpu/accounting/`) and the Solidity suites reproduce the same vectors. Specification: `docs/gpu/accounting.md`.

## 6. Off-chain system

PostgreSQL stores append-only observations, proof artifacts, native-verification records, evidence consumption, receivables, cash receipts, allocations, audit entries, chain cursors, durable jobs, outbox records, and transaction intents.

| Worker | Responsibility |
| --- | --- |
| Ingestion | Accepts signed webhooks or backfills source observations |
| Proof worker | Fetches and stores official proof artifacts, prepares deployment-bound calldata, tracks native acceptance separately from business consumption |
| Chain indexer | Projects finalized contract logs and handles reorgs; replays facility, evidence, receivable and repayment read models from the canonical journal on every sync (the API merges them with reviewed ledger imports, labelled by `recordOrigin`) |
| Reconciliation | Compares source cash, destination cash, ledger allocations, and projected contract state |
| Control monitor | Records control-state changes without granting financial authority |

Jobs are leased transactionally. Broadcast intents are idempotent, nonce-aware, and bound to an allowlisted contract/method plan. Credentials are referenced through secret stores and never returned by the API. Runtime details: `offchain/gpu/RUNTIME.md`.

## 7. API and web security

The GPU API starts from `hashcredit_api.gpu.app` and does not import the legacy Bitcoin write routes. Wallet login uses an expiring EIP-712 challenge bound to wallet, chain, application domain, and purpose; ERC-1271 wallets are checked through the configured RPC.

Reads are bound to a deployment ID, manifest hash, and finalized canonical block. Borrowers see their own objects; staff and LP scopes are explicit and never inferred from deployment keys. Durable commands use idempotency keys, optimistic versions, database locks, and audit records. Browser input can request review but cannot fabricate native verification, underwriting approval, or E2 control.

The web client obtains deployment identity and contract addresses from `/v1/config`. Before a transaction it verifies wallet network, deployed bytecode, asset address, and token decimals, simulates the call, and waits for confirmations. The fixture demo at `/demo` makes no wallet, API, or RPC calls. Roles and state machine: `docs/gpu/permissions-and-states.md`.

## 8. Execution profiles

| Profile | Meaning |
| --- | --- |
| `LOCAL_MOCK` | Local contracts, fixtures, and test doubles; cannot use a public Creditcoin chain ID |
| `NATIVE_TESTNET` | Real public source transaction and official native verification on a Creditcoin testnet |
| `PRODUCTION` | Creditcoin mainnet; still requires partner, legal, operational, and financial approval |

Every evidence-bearing record carries its profile. Production readers reject anything that is not `PRODUCTION`.

## 9. Current evidence (2026-09-17)

- TEST_ONLY deployment on Creditcoin CC3 Testnet at block 5,484,231, bound by manifest to a TEST_ONLY Sepolia source escrow.
- 2026-09-14: four source-event consumptions through the official Attestcoin path; each proof-only transaction changed neither debt nor vault cash. LP browser cycle (deposit, queue, cancel, process, claim, withdraw) returning shares to zero. Borrower cycle: 1 tUSD draw followed by 1.000002 tUSD measured repayment returning legal debt to zero; source-protection expiry blocked new draws but not repayment. 25 live persona scenarios passed, including wrong-chain, bad-signature, nonce-replay, foreign-resource, and staff-scope denials.
- 2026-09-14 → 17, live QA with simulated network payers (`SIM-AETHIR` epoch rewards, `SIM-GPUNET` job invoices; our own PAYER contracts on the TEST_ONLY escrow): thirty source transitions of every escrow event kind proven and consumed, ledgers reconciling exactly on both chains; the borrowing base tracking corrections, chargebacks, overdue haircuts and cancellations to the unit; on five facilities, draws, an over-limit refusal, freeze and resume, partial repayment with accrued interest, third-party `repayFor`, delinquency and cure, full repayment to `REPAID`, and the non-payment path through `DEFAULTED`, `RECOVERY` (reserve applied through the router), impairment and write-off to `CLOSED_WITH_LOSS`. 60 scenarios plus browser checks of the non-performing states, all passing. Two fixes surfaced by the run are in `main`: chain-projected receivable and repayment history (migration `0006`) and the credit-status explanation for non-performing facilities. Catalog `docs/gpu/scenarios/live-payer-scenarios.md`, evidence `evidence/native-testnet/qa-20260915/`.

Source revenue is simulated and partner payment control is unconfigured, so none of this is partner, production, or real-revenue evidence. Links and hashes: `README.md`, `evidence/`.

## 10. Verification map

| Suite | Command | Covers |
| --- | --- | --- |
| Foundry | `forge test` | Contract units, invariants (`test/gpu/invariant/`, `test/invariant/`), Attestcoin verifier conformance, deployment wiring |
| Slither | CI job with `.slither.db.json` triage | Static analysis with reviewed findings pinned by source hash |
| Attestcoin tooling | `npm --prefix offchain/attestcoin run check && … test -- --run` | Artifact pins, ABI signature sets, manifest validation, proof-response parsing |
| Python | `pytest` in `offchain/gpu`, `offchain/api`, `offchain/prover` | Accounting and reconciliation vectors, migrations and triggers, API auth and scopes, worker lifecycle |
| Web | `npm --prefix apps/web run test:unit`, `test:e2e` | Demo store, client helpers, connected app against HTTP/EIP-1193 fixtures at desktop and mobile widths |
| Live scenarios (opt-in) | `apps/web/scripts/live-scenarios.mjs` | Deployed environment, real test-token transactions, native refresh |
| Live payer personas and credit operations (opt-in) | `apps/web/scripts/live-payer-scenarios.mjs`, `script/gpu/payer_sim.mjs` | Simulated network payers on the Sepolia escrow, proof consumption of every event kind, borrowing-base arithmetic, draws, freezes, delinquency, third-party repayment, default, recovery, impairment and write-off |

## 11. Legacy isolation

The Bitcoin-SPV prototype is retained for provenance and regression coverage. Its verifier, relayer, deployment addresses, and API routes do not satisfy Rackline v2 evidence requirements and are not imported by the GPU entrypoints.
