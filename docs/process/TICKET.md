# HashCredit Tickets (Current Baseline)

This file tracks actionable work for the SPV-only architecture.

## Status Legend

- `[ ]` TODO
- `[~]` IN PROGRESS
- `[x]` DONE
- `[!]` BLOCKED

## P0

### T0.1 Wallet-Only Frontend/API Write Path
- Priority: P0
- Status: [x] DONE
- Goal: remove browser token flow and server-side write endpoints from API.
- Completion summary:
  - removed API token usage from frontend state/client
  - API write endpoints removed; API now exposes only payload/proof/verification endpoints
  - added `/checkpoint/build` payload endpoint
  - claim complete converted to verify-only output

### T0.2 Frontend SPV Ops Alignment
- Priority: P0
- Status: [x] DONE
- Goal: keep proof/checkpoint flows functional after wallet-only migration.
- Completion summary:
  - `Operations` tab now builds checkpoint payload then submits `setCheckpoint` via wallet
  - `Proof` tab now builds proof via API then submits `submitPayout` via wallet
  - checkpoint ABI updated with `bits` argument

## P1

### T1.1 Documentation Convergence (SPV-Only)
- Priority: P1
- Status: [~] IN PROGRESS
- Goal: align all guides/spec/security docs with active SPV-only architecture.
- Scope:
  - remove obsolete alternate-mode instructions
  - document API as read/verify-only
  - document wallet/worker transaction boundaries

### T1.2 Regression Test Coverage for API Wallet-Only Mode
- Priority: P1
- Status: [ ] TODO
- Goal: add/adjust API tests for removed endpoints and new payload/claim semantics.
- Scope:
  - endpoint existence/non-existence checks
  - `/checkpoint/build` response contract tests
  - `/claim/complete` verify-only expectations

### T1.3 E2E Smoke Script Update
- Priority: P1
- Status: [ ] TODO
- Goal: provide repeatable script for checkpoint build -> wallet submit -> proof build -> wallet submit.

## P2

### T2.1 Operational Hardening
- Priority: P2
- Status: [ ] TODO
- Goal: expand runbooks for checkpoint cadence, reorg handling, and worker key rotation.
