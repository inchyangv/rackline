# Provenance and Self-Transfer Defense

## Overview

HashCredit uses payout-based credit. Without provenance controls, a borrower could attempt self-transfer loops to inflate credit.

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
