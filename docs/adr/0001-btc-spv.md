# ADR 0001: Bitcoin SPV Verification for HashCredit

- Status: Accepted
- Date: 2026-03-04

## Context

HashCredit requires a cryptographic, replay-safe method to prove Bitcoin miner payouts on Creditcoin EVM.
The selected production path is Bitcoin SPV verification on-chain:
- checkpoint anchor + header chain
- PoW validation
- merkle inclusion proof
- payout output parsing and borrower binding

## Decision

Adopt `BtcSpvVerifier` as the active verifier behind `IVerifierAdapter`.

`HashCreditManager` consumes only `PayoutEvidence` and remains decoupled from proof mechanics.

## Rationale

1. Bitcoin-native validation semantics are preserved.
2. Trust minimized compared to signature-oracle approaches.
3. Replay prevention and credit logic remain deterministic at manager level.
4. Future proof sources can still be added via adapter replacement.

## Design Summary

### On-chain components

- `CheckpointManager`: stores trusted header checkpoints
- `BtcSpvVerifier`: validates SPV proof and returns `PayoutEvidence`
- `HashCreditManager`: records payouts and updates credit limits

### Proof envelope (high level)

- checkpoint height
- contiguous headers from checkpoint+1 to target
- raw transaction bytes
- merkle proof siblings + tx index
- target output index + borrower address

### Core checks

1. header linkage (`prevHash` continuity)
2. PoW target checks from `bits`
3. merkle inclusion of txid in target block
4. output script extracts borrower pubkey-hash (P2WPKH/P2PKH)
5. confirmations/length bounds

## Consequences

### Positive

- stronger cryptographic assurance for payout evidence
- consistent manager/vault behavior regardless of proof source
- explicit operational boundary between API (read/verify) and wallet/worker writes

### Trade-offs

- higher implementation and gas complexity
- operational requirement for checkpoint cadence and proof construction tooling

## Operational Notes

- avoid proofs crossing difficulty retarget boundaries when unsupported
- maintain checkpoint strategy aligned with proof-length limits
- monitor worker/API health and submission failure rates

## Future Work

- evaluate USC adapter path while preserving `IVerifierAdapter`
- extend test vectors with broader real-world tx/script patterns
- formalize checkpoint authority model (multisig/attestor policy)
