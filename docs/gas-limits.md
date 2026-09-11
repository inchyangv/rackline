# Gas Profiling and Limits Documentation

This document describes the gas consumption characteristics and enforced limits for the HashCredit protocol smart contracts.

## 1. Protocol Limits

### 1.1 BtcSpvVerifier Limits

| Constant | Value | Description |
|----------|-------|-------------|
| `MAX_HEADER_CHAIN` | 144 | Maximum number of headers in SPV proof chain (~1 day of blocks) |
| `MAX_MERKLE_DEPTH` | 20 | Maximum Merkle proof depth (supports up to ~1M transactions per block) |
| `MAX_TX_SIZE` | 4,096 bytes | Maximum raw Bitcoin transaction size |
| `MIN_CONFIRMATIONS` | 6 | Minimum block confirmations required |

### 1.2 Rationale for Limits

**Header Chain Limit (144):**
- 144 blocks corresponds to approximately 1 day of Bitcoin blocks
- Prevents excessive gas costs from long header chain verification
- Operational guidance: submit proofs before transactions age beyond checkpoint + 144 blocks

**Merkle Depth Limit (20):**
- Supports blocks with up to 2^20 (~1 million) transactions
- Bitcoin's largest blocks historically contain ~10,000 transactions
- Provides ample headroom for future block size increases

**Transaction Size Limit (4,096 bytes):**
- Standard Bitcoin transactions are typically 200-500 bytes
- Large multisig or complex transactions rarely exceed 2,000 bytes
- 4KB limit prevents gas griefing while allowing legitimate transactions

## 2. Gas Consumption Profile

### 2.1 BitcoinLib Low-Level Operations

| Operation | Gas Cost | Notes |
|-----------|----------|-------|
| `sha256d` (80 bytes) | ~1,454 | Double SHA256 hash |
| `parseHeader` | ~2,411 | Parse 80-byte Bitcoin header |
| `bitsToTarget` | ~315 | Convert difficulty bits to target |
| `extractPubkeyHash` (P2WPKH) | ~6,198 | Extract pubkey hash from SegWit script |
| `extractPubkeyHash` (P2PKH) | ~6,586 | Extract pubkey hash from legacy script |
| `parseTxOutput` (minimal) | ~8,904 | Parse single output from simple transaction |
| `parseTxOutput` (multi-output) | ~9,374 | Parse output at index 1 from multi-output tx |

### 2.2 Merkle Proof Verification

| Proof Depth | Gas Cost | Use Case |
|-------------|----------|----------|
| 1 | ~1,747 | Block with 2 transactions |
| 5 | ~8,284 | Block with up to 32 transactions |
| 10 | ~16,473 | Block with up to 1,024 transactions |
| 15 | ~24,681 | Block with up to 32,768 transactions |
| 20 (max) | ~32,908 | Block with up to 1,048,576 transactions |

**Formula:** Gas cost scales approximately linearly with depth at ~1,640 gas per level.

### 2.3 Verifier Operations

| Operation | Gas Cost | Notes |
|-----------|----------|-------|
| `RelayerSigVerifier.verifyPayout` | ~35,272 | EIP-712 signature verification + storage write |

**Note:** Full `BtcSpvVerifier.verifyPayout` gas depends on:
- Header chain length: ~2,500 gas per header (parse + hash + PoW check)
- Merkle proof depth: ~1,640 gas per level
- Transaction parsing: ~8,000-10,000 gas

Estimated worst-case (144 headers, 20-depth proof): ~400,000 gas

### 2.4 HashCreditManager Operations

| Operation | Gas Cost | Notes |
|-----------|----------|-------|
| `registerBorrower` | ~81,155 | Create new borrower record |
| `submitPayout` | ~149,924 | Verify + record payout + update credit |
| `borrow` | ~97,184 | Check limits + route to vault |
| `repay` | ~65,839 | Transfer tokens + update state |

### 2.5 LendingVault Operations

| Operation | Gas Cost | Notes |
|-----------|----------|-------|
| `deposit` | ~47,976 | LP deposits stablecoin for shares |
| `withdraw` | ~30,145 | LP redeems shares for stablecoin |

### 2.6 CheckpointManager Operations

| Operation | Gas Cost | Notes |
|-----------|----------|-------|
| `setCheckpoint` | ~103,871 | Admin sets new trusted checkpoint |
| `getCheckpoint` | ~14,507 | Read checkpoint data |

## 3. Gas Estimation for SPV Proofs

### 3.1 Formula

```
Total Gas = Base Cost + (Headers * Header Cost) + (Merkle Depth * Merkle Cost) + Tx Parse Cost

Where:
- Base Cost: ~50,000 gas (storage operations, basic checks)
- Header Cost: ~2,500 gas per header
- Merkle Cost: ~1,640 gas per level
- Tx Parse Cost: ~10,000 gas
```

### 3.2 Examples

| Scenario | Headers | Merkle Depth | Estimated Gas |
|----------|---------|--------------|---------------|
| Minimum (6 conf, small block) | 6 | 5 | ~83,200 |
| Typical (10 conf, normal block) | 10 | 10 | ~101,400 |
| Large block (20 conf) | 20 | 15 | ~134,600 |
| Maximum (144 headers, max depth) | 144 | 20 | ~452,800 |

### 3.3 Gas Limit Recommendations

| Network | Block Gas Limit | Max Recommended Proof |
|---------|-----------------|----------------------|
| Ethereum Mainnet | 30M | 144 headers, 20 depth |
| Creditcoin | TBD | 144 headers, 20 depth |

All protocol limits are well within typical EVM gas limits.

## 4. Error Codes for Limit Violations

| Error | Triggered When |
|-------|---------------|
| `HeaderChainTooLong` | `headers.length > MAX_HEADER_CHAIN (144)` |
| `MerkleProofTooLong` | `merkleProof.length > MAX_MERKLE_DEPTH (20)` |
| `TxTooLarge` | `rawTx.length > MAX_TX_SIZE (4096)` |
| `InsufficientConfirmations` | `headers.length < MIN_CONFIRMATIONS (6)` |

## 5. Optimization Recommendations

### 5.1 For Proof Submitters
- Submit proofs shortly after minimum confirmations (6 blocks)
- Avoid letting transactions age beyond checkpoint + 100 blocks
- Monitor gas prices for optimal submission timing

### 5.2 For Protocol Operators
- Set checkpoints at reasonable intervals (~2016 blocks / 2 weeks)
- Avoid crossing difficulty retarget boundaries if possible
- Monitor average proof gas costs for network health

### 5.3 For Borrowers
- Batch multiple payouts before claiming credit if gas is expensive
- Repay loans when gas is low to minimize transaction costs

## 6. Running Gas Profile Tests

To measure gas consumption on your environment:

```bash
# Run all gas profile tests
forge test --match-contract GasProfileTest -vv

# Run with gas report
forge test --match-contract GasProfileTest --gas-report
```

Test file location: `test/GasProfile.t.sol`
