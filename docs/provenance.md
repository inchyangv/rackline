# Provenance and Self-Transfer Attack Prevention

## Overview

HashCredit uses payout-based credit scoring, which creates a potential attack vector: **self-transfer attacks** where a malicious actor could inflate their credit limit by cycling funds through their registered payout address.

This document describes the attack scenario and the defense mechanisms implemented.

## Attack Scenario: Self-Transfer Credit Inflation

### Attack Description

1. Attacker registers as a borrower with a BTC payout address
2. Attacker sends BTC to their own registered address (self-transfer)
3. Protocol records this as legitimate mining revenue
4. Credit limit increases based on the fake "revenue"
5. Attacker borrows stablecoins against the inflated limit
6. Attacker defaults, leaving the protocol with bad debt

### Attack Cost Analysis

For the attack to be profitable, the attacker must:
- Pay Bitcoin transaction fees for each self-transfer
- Have capital to lock up during the credit-building phase
- Accept the time delay before being able to borrow

If `advanceRateBps = 5000` (50%), the attacker needs to self-transfer 2x the amount they want to steal.

## Defense Layers

### Layer 1: Pool Registry (Source Verification)

**Implementation**: `PoolRegistry.sol`

The protocol maintains an allowlist of legitimate mining pool payout sources. In strict mode, only payouts originating from registered pools are accepted.

**Configuration**:
- `isPermissiveMode`: MVP allows all sources; production disables this
- `registeredPools`: Mapping of verified pool identifiers

**Effectiveness**: High for production, as legitimate mining pools have recognizable payout patterns and addresses.

### Layer 2: Minimum Payout Threshold

**Implementation**: `RiskConfig.minPayoutSats`

Small payouts below the threshold are rejected entirely. This increases the capital cost for attackers attempting many small transfers.

**Example**: With `minPayoutSats = 100,000` (0.001 BTC), an attacker must use at least this amount per payout.

### Layer 3: New Borrower Cap

**Implementation**: `RiskConfig.newBorrowerCap`

New borrowers have a hard cap on their credit limit for a window period (`windowSeconds`), regardless of reported revenue.

**Example**:
- `newBorrowerCap = 1000 * 1e6` ($1,000)
- `windowSeconds = 2592000` (30 days)

Even if an attacker submits $100,000 in payouts, their credit limit remains capped at $1,000 for the first 30 days.

### Layer 4: Minimum Payout Count for Full Credit

**Implementation**: `RiskConfig.minPayoutCountForFullCredit`

Borrowers must accumulate a minimum number of payouts before receiving full credit. Early payouts are capped at `minPayoutSats` value.

**Example**:
- `minPayoutCountForFullCredit = 3`
- First 3 payouts: Each counts only up to `minPayoutSats`, regardless of actual amount
- After 3 payouts: Full amount is credited

**Attack Impact**: An attacker must make at least 3 separate transactions, increasing time and fee costs.

### Layer 5: Large Payout Discount

**Implementation**: `RiskConfig.largePayoutThresholdSats` and `largePayoutDiscountBps`

Unusually large single payouts are only partially credited. This prevents "one-shot" attacks with large transfers.

**Example**:
- `largePayoutThresholdSats = 10,000,000` (0.1 BTC)
- `largePayoutDiscountBps = 5000` (50%)
- A 1 BTC payout only counts as 0.5 BTC for credit calculation

**Rationale**: Legitimate mining revenue tends to be consistent. Large anomalies warrant skepticism.

## Configuration Recommendations

### MVP/Hackathon
```solidity
RiskParams({
    minPayoutCountForFullCredit: 0,      // Disabled
    largePayoutThresholdSats: 0,          // Disabled
    largePayoutDiscountBps: 10_000,       // 100% (no discount)
    // Pool registry in permissive mode
})
```

### Production
```solidity
RiskParams({
    minPayoutCountForFullCredit: 3,       // Require 3 payouts
    largePayoutThresholdSats: 10_000_000, // 0.1 BTC threshold
    largePayoutDiscountBps: 5_000,        // 50% for large payouts
    // Pool registry in strict mode
})
```

## Testing the Defense

### Test Case: Self-Transfer Attack Simulation

```
Scenario: Attacker with 1 BTC attempts to maximize credit

Without protections:
  - Self-transfer 1 BTC
  - Credit limit = 1 BTC * $50,000 * 50% = $25,000
  - Profit if default: $25,000

With protections (production config):
  - Day 1: Self-transfer 1 BTC
    - Count: 1 (< minPayoutCountForFullCredit)
    - Effective: capped at minPayoutSats = 0.001 BTC
  - Day 2: Self-transfer 1 BTC
    - Count: 2 (still < 3)
    - Effective: 0.001 BTC
  - Day 3: Self-transfer 1 BTC
    - Count: 3 (now >= 3)
    - 1 BTC > 0.1 BTC threshold, apply 50% discount
    - Effective: 0.5 BTC
  - Total effective revenue: 0.002 + 0.5 = 0.502 BTC
  - Credit limit = 0.502 BTC * $50,000 * 50% = $12,550
  - But newBorrowerCap = $1,000 (if still in window)
  - Actual credit: min($12,550, $1,000) = $1,000

Attack cost: 3 BTC tied up + 3 tx fees
Maximum profit: $1,000 (but must repay or lose reputation)
```

### Result

The layered defenses make self-transfer attacks economically unviable:
- Multiple transactions required (fee cost)
- Capital lockup required (opportunity cost)
- Limited credit even with successful attack (newBorrowerCap)
- Discounted large payouts reduce efficiency

## Future Improvements

1. **UTXO Chain Analysis**: Track input UTXOs to identify self-transfers directly
2. **Pool Signature Verification**: Require pools to sign payout attestations
3. **Behavior Analysis**: ML-based detection of suspicious payout patterns
4. **Reputation Decay**: Reduce credit multiplier for dormant accounts
5. **Insurance Pool**: Protocol-level insurance against bad debt

## References

- [PROJECT.md Section 7.1](../PROJECT.md) - Attack model description
- [ADR 0001](./adr/0001-btc-spv.md) - SPV verification design
- `contracts/RiskConfig.sol` - Heuristic parameter implementation
- `contracts/PoolRegistry.sol` - Source verification
