# HashCredit Security Audit Checklist (SPV-Only)

## 1) Contract Inventory

- `HashCreditManager`
- `LendingVault`
- `BtcSpvVerifier`
- `CheckpointManager`
- `RiskConfig`
- `PoolRegistry`
- `BitcoinLib`

## 2) Access Control

### Owner/admin functions validated

- [ ] manager dependency setters (`setVerifier`, `setVault`, `setRiskConfig`, `setPoolRegistry`)
- [ ] borrower state controls (`registerBorrower`, `freezeBorrower`, `unfreezeBorrower`)
- [ ] vault manager assignment and APR controls
- [ ] verifier mapping setters (`setBorrowerPubkeyHash`)
- [ ] on-chain BTC address claim (`claimBtcAddress`) — ecrecover + pubkey derivation + Hash160
- [ ] testnet credit grant (`grantTestnetCredit`) — owner-only, borrower must be registered
- [ ] checkpoint updates (`setCheckpoint`)
- [ ] risk parameter updates
- [ ] pool registry mutations and mode toggles

### Ownership safety

- [ ] all ownable contracts support safe ownership transfer
- [ ] zero-address protections are present
- [ ] owner powers match documented trust model

## 3) Replay and State Safety

- [ ] payout key is deterministic: `keccak256(txid, vout)`
- [ ] duplicate payout reverts in verifier and/or manager
- [ ] manager records payout once after full validation
- [ ] borrower status gates payout and borrow flows correctly

## 4) SPV Verification Correctness

### Header chain checks

- [ ] each header is 80 bytes
- [ ] prev-hash linkage is enforced
- [ ] PoW target from `bits` is checked per header
- [ ] chain/proof length bounds enforced
- [ ] confirmations requirement enforced

### Merkle proof checks

- [ ] txid computed as Bitcoin SHA256d(rawTx)
- [ ] merkle path index logic is correct
- [ ] computed root equals target header merkle root
- [ ] proof depth bounds enforced

### Transaction/output checks

- [ ] tx size bounds enforced
- [ ] output index bounds enforced
- [ ] supported script types are strictly parsed
- [ ] extracted pubkey-hash equals registered borrower mapping

## 5) Economic / Risk Controls

- [ ] advance rate and cap bounds validated
- [ ] new borrower cap logic enforced
- [ ] payout threshold/count/discount rules behave as documented
- [ ] BTC price update permissions and constraints validated
- [ ] borrow checks always enforce debt <= credit limit

## 6) External Calls and Reentrancy

- [ ] external call order follows CEI expectations
- [ ] no unsafe external calls before critical state updates
- [ ] token transfer assumptions are documented (or SafeERC20 used)
- [ ] manager-vault cross-calls cannot bypass authorization

## 7) Events and Observability

- [ ] critical state transitions emit events
- [ ] payout processing emits borrower/amount/key context
- [ ] admin parameter changes are evented
- [ ] event fields are sufficient for operational monitoring

## 8) Tests and Verification Depth

- [ ] unit tests cover happy paths and reverts
- [ ] fuzz tests for parsing/limits where practical
- [ ] integration tests for manager-verifier-vault flow
- [ ] gas profile confirms proof bounds are operable

## 9) Deployment and Ops

- [ ] deployment order/runbook documented
- [ ] multisig ownership plan documented
- [ ] worker key rotation and secret handling documented
- [ ] incident response runbook tested (freeze/param update)

## 10) Findings Log

| ID | Severity | Area | Summary | Status |
|---|---|---|---|---|
|   |   |   |   |   |
