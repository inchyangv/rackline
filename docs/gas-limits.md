# Gas Profiling and Limits (SPV-Only)

This document summarizes practical gas bounds for HashCredit's active SPV flow.

## Protocol Limits

| Constant | Value | Description |
|---|---:|---|
| `MAX_HEADER_CHAIN` | 144 | max headers per proof |
| `MAX_MERKLE_DEPTH` | 20 | max merkle siblings |
| `MAX_TX_SIZE` | 4096 bytes | max raw tx bytes |
| `MIN_CONFIRMATIONS` | 6 | minimum confirmations |

## Core Cost References

### BitcoinLib helpers

| Operation | Gas (approx) |
|---|---:|
| `sha256d` (80 bytes) | 1,454 |
| `parseHeader` | 2,411 |
| `bitsToTarget` | 315 |
| `extractPubkeyHash` (P2WPKH) | 6,198 |
| `extractPubkeyHash` (P2PKH) | 6,586 |
| `parseTxOutput` | 8,904 - 9,374 |

### Merkle verification

| Depth | Gas (approx) |
|---:|---:|
| 5 | 8,284 |
| 10 | 16,473 |
| 15 | 24,681 |
| 20 | 32,908 |

## SPV Proof Estimate

Approximation:

```text
total ~= base + (headers * header_cost) + (merkle_depth * merkle_cost) + tx_parse
base ~ 50,000
header_cost ~ 2,500
merkle_cost ~ 1,640
tx_parse ~ 10,000
```

Examples:

| Scenario | Headers | Merkle depth | Estimated gas |
|---|---:|---:|---:|
| small | 6 | 5 | ~83k |
| typical | 10 | 10 | ~101k |
| large | 20 | 15 | ~135k |
| max-bound | 144 | 20 | ~453k |

## Manager/Vault References

| Operation | Gas (approx) |
|---|---:|
| `registerBorrower` | 81,155 |
| `submitPayout` | 149,924 (plus verifier cost variability) |
| `borrow` | 97,184 |
| `repay` | 65,839 |
| `deposit` | 47,976 |
| `withdraw` | 30,145 |
| `setCheckpoint` | 103,871 |

## Operational Guidance

- keep proof target near checkpoint to reduce header count
- refresh checkpoints before proofs approach limit windows
- run gas profile tests periodically:

```bash
forge test --match-contract GasProfileTest --gas-report
```
