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
- Status: [x] DONE
- Goal: align all guides/spec/security docs with active SPV-only architecture.
- Completion summary:
  - removed obsolete alternate-mode instructions
  - documented API as read/verify-only
  - documented wallet/worker transaction boundaries
  - updated PROJECT.md, README.md, TECH.md, DEMO.md, guides/DEMO.md for claimBtcAddress + grantTestnetCredit
  - updated offchain/api/README.md with `/claim/extract-sig-params` endpoint
  - updated threat-model.md with BTC address claim and testnet credit sections
  - updated audit-checklist.md with new function checks
  - updated ADR 0001 with BTC address ownership verification section

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

### T1.4 On-chain BTC Address Claim (`claimBtcAddress`)
- Priority: P1
- Status: [x] DONE
- Goal: enable trustless BTC address ownership proof via on-chain signature verification.
- Completion summary:
  - `BtcSpvVerifier.claimBtcAddress()` added: ecrecover + sha256 + ripemd160 precompiles
  - offchain API `/claim/extract-sig-params` endpoint extracts on-chain params from BIP-137 signature
  - frontend Claim section updated: BTC sig → API extract → on-chain verify → register → grant credit
  - ABI updated with `claimBtcAddress` function

### T1.5 Testnet Credit Grant (`grantTestnetCredit`)
- Priority: P1
- Status: [x] DONE
- Goal: allow owner to bootstrap borrower credit limits on testnet.
- Completion summary:
  - `HashCreditManager.grantTestnetCredit(borrower, creditLimitAmount)` added (owner-only)
  - frontend auto-calls after borrower registration (1000 cUSD)
  - ABI updated with `grantTestnetCredit` function

### T1.6 ABI Sync Fix (`getBorrowerInfo`)
- Priority: P1
- Status: [x] DONE
- Goal: fix frontend ABI mismatch with contract struct.
- Completion summary:
  - added missing `lastDebtUpdateTimestamp` (uint64) field to `getBorrowerInfo` ABI output

## P2

### T2.1 Operational Hardening
- Priority: P2
- Status: [ ] TODO
- Goal: expand runbooks for checkpoint cadence, reorg handling, and worker key rotation.
