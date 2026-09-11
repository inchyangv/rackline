# USC Adapter Design (HashCredit)

## Goal

Add a USC-backed verifier adapter without changing `HashCreditManager` credit logic.

## Current Active Path

- Active verifier: `BtcSpvVerifier`
- Input proof: Bitcoin SPV proof bytes
- Output: `PayoutEvidence` via `IVerifierAdapter`

## Target USC Path

- New adapter: `UscVerifierAdapter`
- Adapter input: USC query/proof envelope (`bytes`)
- Adapter output: same `PayoutEvidence` structure

## Compatibility Contract

The adapter must satisfy:
- `verifyPayout(bytes proof) -> PayoutEvidence`
- deterministic mapping of:
  - `borrower`
  - `txid` (`bytes32`, internal order)
  - `vout`
  - `amountSats`
  - `blockHeight`
  - `blockTimestamp`

Replay protection remains in `HashCreditManager` (`processedPayouts`).

## Off-chain Requirements

1. Worker to build USC proof envelope
2. Stable ABI schema for adapter proof bytes
3. Consistent txid endianness with existing SPV tooling

## Open Items

- USC precompile method signatures and return schema
- payload size/gas bounds vs current SPV proof sizes
- operational trust model for USC source proofs

## Implementation Checklist

1. Define USC proof envelope ABI
2. Implement `UscVerifierAdapter`
3. Add Foundry tests for valid/invalid mappings
4. Add off-chain worker integration
5. switch manager verifier via `setVerifier`
6. run smoke tests against unchanged manager/vault flows
