# HashCredit Threat Model (SPV-Only)

## 1. System Scope

HashCredit is a revenue-based credit protocol on Creditcoin EVM.
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

### 2.5 Admin key compromise

Threat: malicious config changes or checkpoint abuse.

Controls:
- ownership transfer and operational procedures
- event logging for all sensitive actions
- recommended multisig ownership and key rotation

Residual risk: high if single-key governance remains.

### 2.6 Smart-contract logic bugs

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
