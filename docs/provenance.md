# Provenance and Self-Transfer Defense

> **Legacy v1 (Bitcoin SPV) document — not the v2 design.** Rackline v2 (GPU receivables credit, R2, 2026-09-14) uses only official Attestcoin native verification and a rebuilt debt ledger; see `TECH.md`, `PIVOT.md`, `docs/gpu/decisions/attestcoin-first.md`. Kept unchanged as the record of the v1 contracts that remain deployed on testnet. Do not reuse the BTC identity / SPV / relayer design as a GPU evidence path (R2-D03).

## Overview

Rackline (formerly HashCredit) uses payout-based credit. Without provenance controls, a borrower could attempt self-transfer loops to inflate credit.

## Attack Pattern

1. borrower registers payout mapping
2. borrower sends own BTC to mapped address
3. payout is treated as revenue
4. credit limit increases
5. borrower borrows and defaults

## Defense Layers

### 1) Source Eligibility (`PoolRegistry`)

- maintain allowlist/pattern policy for acceptable payout sources
- reject non-eligible sources in strict operation

### 2) Risk Thresholds (`RiskConfig`)

- `minPayoutSats` blocks dust-level noise
- `minPayoutCountForFullCredit` delays full trust for new accounts
- `largePayoutThresholdSats` + `largePayoutDiscountBps` discount anomalies
- `newBorrowerCap` limits initial exposure

### 3) Replay and Confirmation Rules

- each `(txid, vout)` consumed once
- confirmations policy enforced by verifier/proof requirements

## Recommended Production Profile

- strict source eligibility enabled
- conservative advance rate
- non-zero `minPayoutCountForFullCredit`
- non-zero large payout discount
- calibrated `newBorrowerCap`

## Operational Checks

- monitor payout distribution anomalies per borrower
- monitor sudden single-payout spikes
- review freeze/unfreeze actions and rationale

## References

- `contracts/PoolRegistry.sol`
- `contracts/RiskConfig.sol`
- `contracts/HashCreditManager.sol`
- `docs/threat-model.md`
