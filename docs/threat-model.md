# HashCredit Threat Model (SPV-Only)

## 1. System Scope

HashCredit is a revenue-based credit protocol on HashKey Chain.
Active verification mode is Bitcoin SPV via `BtcSpvVerifier`.

### Trust Boundaries

- trusted: protocol owner/multisig, checkpoint authority, deployment keys
- semi-trusted: worker operators submitting proofs
- untrusted: borrowers, LP users, public RPC/indexer traffic

## 2. Primary Threats and Controls

### 2.1 Replay of payouts

Threat: same `(txid, vout)` processed multiple times.

Controls:
- `processedPayouts` tracking in manager
- verifier-level payout key validation
- idempotent rejection on duplicate submit

Residual risk: low.

### 2.2 Invalid SPV evidence

Threat: forged headers/merkle branch/raw tx accepted.

Controls:
- header linkage and PoW checks
- merkle inclusion verification
- output parsing and borrower pubkey-hash match
- max header/proof/tx size bounds

Residual risk: low-medium (implementation complexity risk).

### 2.3 Bitcoin reorg exposure

Threat: payout later removed by deep reorg.

Controls:
- confirmations policy
- checkpoint anchoring
- conservative advance-rate and caps
- freeze controls for incident handling

Residual risk: medium for extreme reorg scenarios.

### 2.4 Self-transfer credit inflation

Threat: borrower cycles own funds to fake revenue.

Controls:
- source eligibility via `PoolRegistry`
- payout threshold and count rules
- large payout discount
- new borrower cap

Residual risk: medium, reduced with strict provenance policy.

### 2.5 BTC address claim spoofing

Threat: attacker claims a BTC address they don't own via `claimBtcAddress`.

Controls:
- on-chain ecrecover verifies signature against provided public key coordinates
- pubkeyHash derived from compressed pubkey via sha256 + ripemd160 precompiles (same as Bitcoin Hash160)
- signature must match the exact message hash (Bitcoin double-SHA256 format)
- BTC and ETH share secp256k1 — ecrecover correctly validates BTC signatures

Residual risk: low. Requires forging a secp256k1 signature.

### 2.6 Testnet credit abuse

Threat: unauthorized credit grants via `grantTestnetCredit`.

Context: on mainnet, credit limits are driven by SPV-proven mining payouts — each `submitPayout` updates the trailing-window credit limit based on real revenue. On testnet, real mining cannot be reproduced, so `grantTestnetCredit` bootstraps a flat credit per borrower as a substitute.

Controls:
- `onlyOwner` modifier restricts access
- borrower must be registered before credit can be granted
- function intended for testnet only; production deployment should remove or disable

Residual risk: low on testnet. Function should not be deployed to mainnet.

### 2.7 Admin key compromise

Threat: malicious config changes or checkpoint abuse.

Controls:
- ownership transfer and operational procedures
- event logging for all sensitive actions
- recommended multisig ownership and key rotation

Residual risk: high if single-key governance remains.

### 2.8 Smart-contract logic bugs

Threat: logic, accounting, or access-control flaws.

Controls:
- unit/integration tests
- bounded loops and input validation
- CEI/reentrancy-safe patterns
- independent audit checklist

Residual risk: medium prior to external audits.

## 3. Incident Response

### Emergency Actions

- freeze borrower (`freezeBorrower`)
- update risk params (`RiskConfig`)
- rotate ownership/signing authorities
- update checkpoint to safe anchor

### Monitoring

- payout event anomalies
- debt-to-limit stress indicators
- checkpoint cadence and source integrity
- worker submit errors/retry bursts

## 4. Recommendations

1. use multisig for owner roles
2. enforce strict source eligibility in production
3. maintain runbooks for reorg and key incidents
4. run periodic contract + operational security reviews
