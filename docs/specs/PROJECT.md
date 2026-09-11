# HashCredit — Project Specification (SPV-Only)

## 0. Definition

HashCredit is a Creditcoin EVM protocol that provides stablecoin revolving credit lines to Bitcoin miners using SPV-verified Bitcoin payout events as credit evidence.

## 1. Problem

Bitcoin miners face recurring operating costs while revenue timing is volatile. Existing alternatives are inefficient:
- traditional loans are slow and collateral-heavy
- DeFi lending usually requires overcollateralized liquid assets

HashCredit addresses this by turning verified Bitcoin payouts into deterministic on-chain credit inputs.

## 2. Goals

1. Represent miner payouts as verifiable revenue events.
2. Update borrower credit limits deterministically from payout history.
3. Enable borrow/repay flows in stablecoin on Creditcoin EVM.
4. Keep verification pluggable through `IVerifierAdapter` while running SPV as the active mode.

## 3. Core Principles

- Verifier adapter pattern: credit logic is independent of proof implementation.
- Event-sourced credit: payout events are append-only evidence.
- Replay safety: each payout `(txid, vout)` can be consumed once.
- Defense in depth: cryptographic checks + risk policy + operational controls.

## 4. Architecture

### 4.1 On-chain

| Contract | Role |
|---|---|
| `HashCreditManager` | borrower lifecycle, payout processing, credit limit state, borrow/repay routing |
| `LendingVault` | stablecoin pool, LP shares, debt accounting |
| `BtcSpvVerifier` | verifies Bitcoin header chain + merkle inclusion + payout output mapping |
| `CheckpointManager` | trusted checkpoint storage (height/hash/chainWork/timestamp/bits) |
| `RiskConfig` | risk parameters (advance rate, windows, caps, thresholds) |
| `PoolRegistry` | payout source eligibility policy |

### 4.2 Off-chain

| Component | Role |
|---|---|
| `offchain/api` | read/verify service: build SPV proofs, build checkpoint payloads, verify claim signatures |
| `offchain/prover` | optional worker: watch addresses, build proofs, submit on-chain payouts |

### 4.3 Frontend

- `Dashboard`: read state, borrow/repay
- `Operations`: build checkpoint payload via API, submit `setCheckpoint` via wallet
- `Proof`: build proof via API, submit `submitPayout` via wallet
- `Admin`: borrower mapping/registration via wallet

## 5. Protocol Flows

### 5.1 Borrower setup

1. Register borrower payout mapping
2. Register borrower account

### 5.2 Checkpoint flow

1. API builds checkpoint payload from Bitcoin data
2. wallet submits `CheckpointManager.setCheckpoint(...)`

### 5.3 Payout proof flow

1. API builds SPV proof bytes from txid/vout/checkpoint/target/borrower
2. wallet or worker submits `HashCreditManager.submitPayout(proof)`
3. verifier returns `PayoutEvidence`
4. manager records payout and updates credit state

### 5.4 Borrow/repay flow

- `borrow(amount)` requires debt + amount <= limit
- `repay(amount)` decreases debt according to vault logic

## 6. Risk and Security Requirements

- replay protection on `(txid, vout)`
- borrower mapping validation
- configurable confirmations and payout thresholds
- source eligibility checks through `PoolRegistry`
- emergency controls (freeze/policy updates)

## 7. Deliverables

### 7.1 Core

- contracts: manager, vault, SPV verifier, checkpoint manager, risk config, pool registry
- API for payload/proof build + claim verification
- optional worker automation for SPV submission
- frontend wallet-integrated operations

### 7.2 Quality

- unit/integration tests
- deployment/run guides
- threat model and audit checklist alignment

## 8. Repository Layout

```text
contracts/      Solidity contracts
script/         deploy scripts
test/           Foundry tests
offchain/
  api/          FastAPI (read/verify only)
  prover/       SPV worker
apps/
  web/          frontend
docs/           specs/guides/security
```

## 9. Definition of Done

A feature is done when:
- implementation is merged with tests
- affected docs are updated
- behavior is reproducible via local or deployment guide
