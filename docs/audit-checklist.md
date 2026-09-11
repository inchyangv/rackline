# HashCredit Security Audit Checklist

This checklist is designed for auditors, security researchers, and code reviewers examining the HashCredit protocol.

## 1. Contract Overview

| Contract | Purpose | Risk Level |
|----------|---------|------------|
| `HashCreditManager` | Core borrower management, credit calculation, loan routing | Critical |
| `LendingVault` | LP deposits, fund custody, interest accrual | Critical |
| `RelayerSigVerifier` | EIP-712 signature verification (MVP) | High |
| `BtcSpvVerifier` | Bitcoin SPV proof verification (Production) | High |
| `CheckpointManager` | Trusted Bitcoin header checkpoints | High |
| `RiskConfig` | Risk parameter storage | Medium |
| `PoolRegistry` | Mining pool allowlist | Medium |
| `BitcoinLib` | Bitcoin data parsing utilities | Medium |

---

## 2. Access Control

### 2.1 Owner Functions

| Contract | Function | Risk | Verified |
|----------|----------|------|----------|
| HashCreditManager | `setVerifier(address)` | Can change verification logic | [ ] |
| HashCreditManager | `setVault(address)` | Can redirect funds | [ ] |
| HashCreditManager | `setRiskConfig(address)` | Can change credit rules | [ ] |
| HashCreditManager | `setPoolRegistry(address)` | Can bypass pool checks | [ ] |
| HashCreditManager | `registerBorrower(address, bytes32)` | Can add borrowers | [ ] |
| HashCreditManager | `freezeBorrower(address)` | Can block borrower | [ ] |
| HashCreditManager | `unfreezeBorrower(address)` | Can unblock borrower | [ ] |
| LendingVault | `setManager(address)` | Can change borrow authority | [ ] |
| LendingVault | `setFixedAPR(uint256)` | Can change interest rate | [ ] |
| RelayerSigVerifier | `setRelayerSigner(address)` | Can change trusted signer | [ ] |
| BtcSpvVerifier | `setBorrowerPubkeyHash(address, bytes20)` | Can link BTC address | [ ] |
| CheckpointManager | `setCheckpoint(...)` | Can set trusted anchor | [ ] |
| RiskConfig | `setRiskParams(RiskParams)` | Can change all risk params | [ ] |
| RiskConfig | `setBtcPrice(uint64)` | Can manipulate credit calc | [ ] |
| PoolRegistry | `addPool(bytes32, string)` | Can whitelist pool | [ ] |
| PoolRegistry | `removePool(bytes32)` | Can blacklist pool | [ ] |
| PoolRegistry | `setPermissiveMode(bool)` | Can bypass all pool checks | [ ] |

### 2.2 Manager Functions (HashCreditManager only)

| Contract | Function | Caller | Verified |
|----------|----------|--------|----------|
| LendingVault | `borrowFunds(address, uint256)` | Manager only | [ ] |
| LendingVault | `repayFunds(address, uint256)` | Manager only | [ ] |

### 2.3 Ownership Transfer

| Contract | Has `transferOwnership()` | Zero-address check | Verified |
|----------|---------------------------|-------------------|----------|
| HashCreditManager | Yes | Yes | [ ] |
| LendingVault | Yes | Yes | [ ] |
| RelayerSigVerifier | Yes | Yes | [ ] |
| BtcSpvVerifier | Yes | Yes | [ ] |
| CheckpointManager | Yes | Yes | [ ] |
| RiskConfig | Yes | Yes | [ ] |
| PoolRegistry | Yes | Yes | [ ] |

---

## 3. Replay Protection

### 3.1 Payout Replay

| Check | Contract | Implementation | Verified |
|-------|----------|----------------|----------|
| Unique key calculation | Both verifiers | `keccak256(txid, vout)` | [ ] |
| Storage before processing | RelayerSigVerifier | `_processedPayouts[key]` check before use | [ ] |
| Storage before processing | BtcSpvVerifier | `_processedPayouts[key]` check before use | [ ] |
| Manager also tracks | HashCreditManager | `processedPayouts[key]` | [ ] |
| Key marked after success | Both | Written after all validation | [ ] |

### 3.2 Signature Replay

| Check | Implementation | Verified |
|-------|----------------|----------|
| EIP-712 domain includes chainId | `DOMAIN_SEPARATOR` computed with `block.chainid` | [ ] |
| EIP-712 domain includes contract address | `address(this)` in domain | [ ] |
| Deadline enforced | `block.timestamp > deadline` reverts | [ ] |
| Borrower bound in message | `borrower` is signed field | [ ] |

---

## 4. Integer Safety

### 4.1 Overflow/Underflow

| Location | Type | Risk | Verified |
|----------|------|------|----------|
| Credit limit calculation | uint128 | Capped at `type(uint128).max` | [ ] |
| Revenue accumulation | uint128 | Can overflow with extreme values | [ ] |
| Interest calculation | uint256 | Safe with reasonable APR | [ ] |
| Share calculation | uint256 | Division by zero when `totalShares == 0` | [ ] |

### 4.2 Division

| Location | Divisor | Zero-check | Verified |
|----------|---------|------------|----------|
| `convertToShares` | `totalAssets()` | Handled (returns 1:1 when 0) | [ ] |
| `convertToAssets` | `totalShares` | Handled (returns 1:1 when 0) | [ ] |
| `utilizationRate` | `totalAssets()` | Returns 0 when denominator is 0 | [ ] |
| `_calculateCreditLimit` | `SATS_PER_BTC`, `BPS` | Constants (never 0) | [ ] |

---

## 5. External Calls

### 5.1 Call Order (Reentrancy)

| Function | External Calls | State Updates | Safe | Verified |
|----------|----------------|---------------|------|----------|
| `HashCreditManager.submitPayout` | `verifier.verifyPayout()` | After call | Check | [ ] |
| `HashCreditManager.borrow` | `vault.borrowFunds()` | Before call | Safe | [ ] |
| `HashCreditManager.repay` | `stablecoin.transferFrom()`, `vault.repayFunds()` | After transfers | Check | [ ] |
| `LendingVault.deposit` | `_asset.transferFrom()` | Before call | Safe | [ ] |
| `LendingVault.withdraw` | `_asset.transfer()` | Before call | Safe | [ ] |
| `LendingVault.borrowFunds` | `_asset.transfer()` | Before call | Safe | [ ] |
| `LendingVault.repayFunds` | `_asset.transferFrom()` | Before call | Safe | [ ] |

### 5.2 Return Value Checks

| Call | Return checked | Verified |
|------|----------------|----------|
| `IERC20.transfer()` | No (trusts ERC20) | [ ] |
| `IERC20.transferFrom()` | No (trusts ERC20) | [ ] |
| `IERC20.approve()` | No (trusts ERC20) | [ ] |

**Note:** Standard ERC20 tokens revert on failure. Non-standard tokens (USDT, etc.) may require SafeERC20.

---

## 6. Bitcoin Verification (BtcSpvVerifier)

### 6.1 Header Validation

| Check | Implementation | Verified |
|-------|----------------|----------|
| Header size = 80 bytes | `BitcoinLib.parseHeader` reverts if not 80 | [ ] |
| PrevHash links correctly | `header.prevBlockHash != prevHash` reverts | [ ] |
| PoW meets target | `BitcoinLib.verifyPoW(blockHash, bits)` | [ ] |
| Chain length within limit | `headers.length > MAX_HEADER_CHAIN` reverts | [ ] |
| Minimum confirmations | `headers.length < MIN_CONFIRMATIONS` reverts | [ ] |

### 6.2 Merkle Proof Validation

| Check | Implementation | Verified |
|-------|----------------|----------|
| Proof depth within limit | `merkleProof.length > MAX_MERKLE_DEPTH` reverts | [ ] |
| txid = sha256d(rawTx) | Computed in verifier | [ ] |
| Merkle root matches header | `verifyMerkleProof(txid, merkleRoot, proof, index)` | [ ] |
| Index used correctly | Determines left/right in each level | [ ] |

### 6.3 Transaction Parsing

| Check | Implementation | Verified |
|-------|----------------|----------|
| Tx size within limit | `rawTx.length > MAX_TX_SIZE` reverts | [ ] |
| Output index valid | `outputIndex >= outputCount` reverts | [ ] |
| Script type supported | Only P2WPKH (0) and P2PKH (1) accepted | [ ] |
| Pubkey hash matches borrower | `actualPubkeyHash != expectedPubkeyHash` reverts | [ ] |

---

## 7. Risk Parameters

### 7.1 Parameter Bounds

| Parameter | Bound | Enforced | Verified |
|-----------|-------|----------|----------|
| `advanceRateBps` | max 10,000 (100%) | Yes | [ ] |
| `btcPriceUsd` | non-zero | Yes | [ ] |
| `windowSeconds` | non-zero | Yes | [ ] |
| `largePayoutDiscountBps` | max 10,000 | Yes | [ ] |

### 7.2 Credit Limit Calculation

| Step | Implementation | Verified |
|------|----------------|----------|
| BTC value = sats * price / 1e8 | `(revenueSats * btcPriceUsd) / SATS_PER_BTC` | [ ] |
| Credit = value * rate / 10000 | `(btcValueUsd * advanceRateBps) / BPS` | [ ] |
| Decimal conversion | `/100` for 8 to 6 decimals | [ ] |
| Cap applied | `newBorrowerCap` for new borrowers | [ ] |

---

## 8. Events

### 8.1 Critical Events

| Event | Contract | Parameters | Verified |
|-------|----------|------------|----------|
| `BorrowerRegistered` | HashCreditManager | borrower, btcKey, timestamp | [ ] |
| `PayoutRecorded` | HashCreditManager | borrower, txid, vout, amount, height, newLimit | [ ] |
| `Borrowed` | HashCreditManager | borrower, amount, newDebt | [ ] |
| `Repaid` | HashCreditManager | borrower, amount, newDebt | [ ] |
| `BorrowerStatusChanged` | HashCreditManager | borrower, oldStatus, newStatus | [ ] |
| `Deposited` | LendingVault | depositor, amount, shares | [ ] |
| `Withdrawn` | LendingVault | withdrawer, amount, shares | [ ] |
| `RelayerSignerUpdated` | RelayerSigVerifier | oldSigner, newSigner | [ ] |
| `CheckpointSet` | CheckpointManager | height, hash, chainWork, timestamp | [ ] |
| `RiskParamsUpdated` | RiskConfig | all params | [ ] |

---

## 9. Error Handling

### 9.1 Custom Errors

| Error | Contract | Condition | Verified |
|-------|----------|-----------|----------|
| `InvalidAddress` | Multiple | Zero address provided | [ ] |
| `Unauthorized` | Multiple | Caller not owner/manager | [ ] |
| `BorrowerNotRegistered` | HashCreditManager | Borrower not found | [ ] |
| `BorrowerAlreadyRegistered` | HashCreditManager | Duplicate registration | [ ] |
| `BorrowerNotActive` | HashCreditManager | Borrower frozen or inactive | [ ] |
| `ExceedsCreditLimit` | HashCreditManager | Borrow exceeds limit | [ ] |
| `PayoutAlreadyProcessed` | Multiple | Replay attempt | [ ] |
| `ZeroAmount` | Multiple | Amount is zero | [ ] |
| `InvalidSignature` | RelayerSigVerifier | Signature verification failed | [ ] |
| `DeadlineExpired` | RelayerSigVerifier | Claim expired | [ ] |
| `HeaderChainTooLong` | BtcSpvVerifier | Exceeds MAX_HEADER_CHAIN | [ ] |
| `MerkleProofTooLong` | BtcSpvVerifier | Exceeds MAX_MERKLE_DEPTH | [ ] |
| `TxTooLarge` | BtcSpvVerifier | Exceeds MAX_TX_SIZE | [ ] |
| `InvalidPoW` | BtcSpvVerifier | Block hash > target | [ ] |
| `InsufficientConfirmations` | BtcSpvVerifier | Below MIN_CONFIRMATIONS | [ ] |

---

## 10. Gas and DoS

### 10.1 Loop Bounds

| Loop | Location | Bound | Verified |
|------|----------|-------|----------|
| Header chain iteration | BtcSpvVerifier | MAX_HEADER_CHAIN (144) | [ ] |
| Merkle proof iteration | BitcoinLib | MAX_MERKLE_DEPTH (20) | [ ] |
| Input skipping | BitcoinLib.parseTxOutput | Bounded by tx size | [ ] |
| Output skipping | BitcoinLib.parseTxOutput | Bounded by tx size | [ ] |

### 10.2 Storage Operations

| Operation | Type | Cost | Verified |
|-----------|------|------|----------|
| Payout recording | SSTORE (new) | ~20,000 gas | [ ] |
| Borrower state update | SSTORE (update) | ~5,000 gas | [ ] |
| Checkpoint storage | SSTORE (new) | ~20,000 gas | [ ] |

---

## 11. Testing Coverage

### 11.1 Unit Tests

| Area | Test File | Coverage | Verified |
|------|-----------|----------|----------|
| HashCreditManager | `HashCreditManager.t.sol` | Core flows | [ ] |
| LendingVault | `LendingVault.t.sol` | Deposit/withdraw/interest | [ ] |
| RelayerSigVerifier | `RelayerSigVerifier.t.sol` | Signature verification | [ ] |
| BtcSpvVerifier | `BtcSpvVerifier.t.sol` | SPV validation | [ ] |
| CheckpointManager | `CheckpointManager.t.sol` | Checkpoint management | [ ] |
| BitcoinLib | `BtcSpvVerifier.t.sol` | Parsing utilities | [ ] |
| Gas profiling | `GasProfile.t.sol` | Cost measurement | [ ] |

### 11.2 Missing Test Scenarios

- [ ] Fuzz testing for parsing functions
- [ ] Invariant testing for credit limits
- [ ] Cross-contract integration tests
- [ ] Mainnet fork tests with real Bitcoin data

---

## 12. Documentation

| Document | Location | Current | Verified |
|----------|----------|---------|----------|
| Project overview | `specs/PROJECT.md` | Yes | [ ] |
| Demo instructions | `guides/DEMO.md` | Yes | [ ] |
| Threat model | `docs/threat-model.md` | Yes | [ ] |
| Gas limits | `docs/gas-limits.md` | Yes | [ ] |
| SPV design (ADR) | `docs/adr/0001-btc-spv.md` | Yes | [ ] |
| Provenance rules | `docs/provenance.md` | Yes | [ ] |

---

## 13. Deployment Checklist

### 13.1 Pre-deployment

- [ ] All tests passing (`forge test`)
- [ ] No compiler warnings (or documented)
- [ ] Gas costs within budget
- [ ] Access control verified
- [ ] Events indexed properly

### 13.2 Deployment Order

1. Deploy `MockERC20` (or use existing stablecoin)
2. Deploy `RiskConfig` with initial params
3. Deploy `PoolRegistry` (permissive mode for MVP)
4. Deploy `RelayerSigVerifier` with signer address
5. Deploy `LendingVault` with stablecoin address
6. Deploy `HashCreditManager` with all dependencies
7. Call `vault.setManager(managerAddress)`
8. Verify all contracts on block explorer

### 13.3 Post-deployment

- [ ] Verify owner addresses
- [ ] Test with small amounts
- [ ] Monitor events
- [ ] Set up alerts

---

## 14. Findings Log

| ID | Severity | Description | Status |
|----|----------|-------------|--------|
| | | | |

---

## 15. Auditor Sign-off

| Auditor | Date | Comments |
|---------|------|----------|
| | | |

---

*Last updated: 2025-02*
