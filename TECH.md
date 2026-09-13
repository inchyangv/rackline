# Rackline technical design

Rackline is a receivables-backed lending system for GPU operators. Verified revenue evidence may increase borrowing capacity; only measured destination cash may reduce debt.

This document describes the implemented prototype and its public native-testnet evidence. Partner integration, real GPU revenue, and production approval remain outside the current evidence set.

## System boundaries

The product separates five independent judgments:

| Judgment | Authoritative input |
| --- | --- |
| Source event occurred | Creditcoin native BlockProver result over the exact source transaction bytes |
| Event represents GPU operating revenue | Registered emitter, issuer and provider policy |
| Receivable is currently unpaid and eligible | Revisioned source events, checkpoints, deductions and underwriting policy |
| Payment path is controlled | Versioned control agreement and independently observed control grade |
| Debt was repaid | Measured loan-currency receipt at the destination, allocated to one facility |

An SDK response, HTTP success, signature, admin action, or old payout is not native verification. A source event is not repayment. Local mocks and test-only contracts are never promoted to production evidence.

## On-chain components

| Component | Responsibility |
| --- | --- |
| `SourceEscrow` | Measures source-token receipts, emits revisioned obligation and payout events, separates unattributed deposits, and prevents duplicate settlement IDs |
| `AttestcoinRevenueVerifier` | Calls the official native verifier, decodes only verified bytes, validates receipt status/emitter/topic, and derives log-level source event IDs |
| `EvidenceBook` | Records verification provenance and consumes each technical/economic event once |
| `ReceivableBook` | Tracks recognized, assigned, corrected, paid and disputed receivables |
| `ControlRegistry` | Stores versioned payment-control agreements and validity state |
| `DebtLedger` | Accrues debt and allocates payments in the configured fee/interest/principal order |
| `GpuRiskPolicy` / `ExposureController` | Compute eligibility and reserve borrower/provider/global exposure |
| `CreditFacilityManager` | Enforces facility state, approval hashes, fresh evidence and atomic draws |
| `LendingVaultV2` | Accounts for LP cash, loan assets, impairments, borrower-owned excess, and queued withdrawals |
| `SettlementReceiver` / `RepaymentRouter` | Record destination receipts and apply measured cash without depending on the proof service |
| `RecoveryManager` | Freezes draws, tracks cure/recovery state, recognizes impairment and handles recoveries |
| `GovernanceTimelock` | Delays privileged configuration changes while preserving emergency boundaries |

The contracts use a single debt ledger. The manager, vault and repayment router do not maintain competing notions of principal or interest.

## Evidence path

```text
source transaction
  -> official proof service response (untrusted)
  -> pinned SDK encoding
  -> Creditcoin native verifier
  -> decode receipt from verified bytes
  -> validate source chain, emitter, topic and receipt success
  -> EvidenceBook consume
  -> ReceivableBook revision
  -> risk evaluation / draw reservation
```

Technical event identity includes the environment, source chain, height, transaction index and receipt log ordinal. Economic identity is separate, allowing corrections without accepting a duplicate obligation as new collateral.

The verifier is bound to a manifest hash. The manifest pins chain IDs, chain keys, encoding, native precompile, decoder source, package versions and artifact hashes. Unsupported sources fail closed.

## Credit and draw path

```text
eligible receivables
  - paid, disputed, stale or ineligible amounts
  - policy haircuts and deductions
  = eligible unpaid balance

eligible unpaid balance * advance rate
  -> capped by facility approval
  -> capped by borrower/provider/global exposure
  -> capped by lendable vault cash
  = available draw
```

Every draw re-evaluates current state. Exposure is reserved before funds move and released on failure, preventing concurrent draws from exceeding a cap. Approval, control version, policy version, manifest, asset and facility identity are bound together.

## Repayment and accounting

A repayment follows one accounting path:

```text
measured destination receipt
  -> fees
  -> unpaid interest
  -> principal
  -> borrower-refundable excess
```

For every allocation:

```text
received = feePaid + interestPaid + principalPaid + excess
```

Accounting invariants:

- Receivables support the borrowing base but are not vault assets.
- Unallocated settlement cash is in flight and does not inflate LP NAV.
- Borrower-refundable excess is not LP-owned.
- Proof outages may block new evidence but cannot block direct repayment.
- Draw pauses and repayment availability are separate controls.
- Partial interest payments preserve remaining unpaid interest.
- Rate changes accrue the previous segment before applying the new rate.
- Withdrawal requests lock shares; claims cannot exceed reserved assets.
- Impairment and recovery are explicit accounting events.

The reference accounting model lives in `offchain/gpu/hashcredit_gpu/accounting/`, with unit and invariant tests covering the Solidity implementation.

## Off-chain system

PostgreSQL stores append-only observations, proof artifacts, native-verification records, evidence consumption, receivables, cash receipts, allocations, audit entries, chain cursors, durable jobs, outbox records and transaction intents.

The workers have separate responsibilities:

- ingestion accepts signed webhooks or backfills source observations;
- the proof worker fetches and stores official proof artifacts, prepares deployment-bound calldata, and tracks native acceptance separately from business consumption;
- the chain indexer projects finalized contract logs and handles reorgs;
- reconciliation compares source cash, destination cash, ledger allocations and projected contract state;
- control monitoring records changes without granting financial authority.

Jobs are leased transactionally. Broadcast intents are idempotent, nonce-aware and bound to an allowlisted contract/method plan. Credentials are referenced through secret stores rather than returned through API DTOs.

## API and web security

The GPU API starts from `hashcredit_api.gpu.app` and does not import the legacy Bitcoin write routes. Wallet login uses an expiring EIP-712 challenge bound to wallet, chain, application domain and purpose; ERC-1271 wallets are checked through the configured RPC.

Reads are bound to a deployment ID, manifest hash and finalized canonical block. Borrowers see their own objects; staff and LP scopes are explicit. Durable commands use idempotency keys, optimistic versions, database locks and audit records. Browser-supplied input can request review but cannot fabricate native verification, underwriting approval or E2 control.

The web client obtains all deployment identity and contract addresses from `/v1/config`. Before a transaction it verifies the wallet network, deployed bytecode, asset address and token decimals, simulates the call, and waits for confirmations. The fixture demo is isolated at `/demo`.

## Profiles and current evidence

| Profile | Meaning |
| --- | --- |
| `LOCAL_MOCK` | Local contracts, fixtures and test doubles |
| `NATIVE_TESTNET` | Real public source transaction and official native verification on a Creditcoin testnet |
| `PRODUCTION` | Production configuration; still requires partner, legal, operational and financial approval |

The repository includes local tests and pinned Attestcoin environment data. TEST_ONLY source and destination deployments are recorded in manifests with contract addresses and bytecode hashes. The curated native evidence record contains four successful source-event consumptions on Creditcoin CC3 Testnet and confirms that proof-only transactions changed neither debt nor vault cash. Source revenue is simulated and partner payment control is unconfigured, so this result is not partner, production, or real-revenue evidence.

The subsequent native checkpoint and browser financial tests are linked in [README](README.md#native-testnet-evidence): LP deposit/queued and direct exit return shares to zero, and a 1 tUSD draw followed by 1.000002 tUSD measured repayment returns legal debt to zero. Source protection expiry blocks new draws but did not block direct repayment.

## Legacy isolation

The Bitcoin-SPV prototype is retained for provenance and regression coverage. Its verifier, relayer, deployment addresses and API routes do not satisfy Rackline v2 evidence requirements and are not imported by the GPU production entrypoint.
