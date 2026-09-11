# HashCredit Threat Model

This document outlines the security threats facing the HashCredit protocol and the mitigations implemented to address them.

## 1. Overview

HashCredit is a revenue-based financing protocol for Bitcoin miners on Creditcoin EVM. The core trust assumptions vary between MVP (Relayer Oracle) and Production (SPV) modes:

| Component | MVP Trust Model | Production Trust Model |
|-----------|-----------------|------------------------|
| Payout Verification | Trusted relayer | Bitcoin PoW + SPV |
| Checkpoint | N/A | Owner/multisig |
| Credit Calculation | On-chain deterministic | On-chain deterministic |
| Price Oracle | Admin-configured | Admin-configured |

## 2. Threat Categories

### 2.1 Oracle Compromise (MVP Only)

**Threat:** Malicious or compromised relayer signs fraudulent payout claims.

**Impact:**
- Attacker inflates credit limit with fake payouts
- Borrows stablecoins beyond legitimate entitlement
- Defaults, causing LP losses

**Mitigations:**
| Control | Description | Status |
|---------|-------------|--------|
| Single authorized signer | Only owner-configured relayer can sign | Implemented |
| Signature verification | EIP-712 typed data signatures | Implemented |
| Deadline enforcement | Claims expire after set period | Implemented |
| Key rotation capability | Owner can change relayer address | Implemented |
| Rate limiting (off-chain) | Relayer should limit claim frequency | Operational |

**Residual Risk:** High for MVP. Relayer compromise is single point of failure.

**Production Mitigation:** Replace with SPV proof verification (BtcSpvVerifier).

---

### 2.2 Replay Attacks

**Threat:** Same Bitcoin payout claimed multiple times to inflate credit.

**Scenarios:**
1. Same payout submitted twice to same contract
2. Payout replayed across chain forks
3. Payout replayed to different borrower accounts

**Mitigations:**
| Control | Description | Status |
|---------|-------------|--------|
| Unique payout key | `keccak256(txid, vout)` stored on first use | Implemented |
| Dual-layer protection | Both verifier and manager track processed payouts | Implemented |
| Chain ID in signatures | EIP-712 domain includes chainId | Implemented |
| Borrower binding | Payout tied to specific borrower in signed message | Implemented |

**Residual Risk:** Low. Multiple layers of replay protection.

---

### 2.3 Bitcoin Reorg Attacks

**Threat:** Bitcoin transaction confirmed, payout claimed, then reorged away.

**Attack Flow:**
1. Attacker sends BTC payout (gets 6 confirmations)
2. Submits proof, receives credit limit increase
3. Borrows stablecoins
4. Bitcoin chain reorgs, removing the payout transaction
5. Attacker keeps borrowed funds without legitimate payout

**Mitigations:**
| Control | Description | Status |
|---------|-------------|--------|
| Confirmation requirement | MIN_CONFIRMATIONS = 6 blocks | Implemented |
| Checkpoint anchor | SPV proofs anchor to trusted checkpoint | Implemented |
| Header chain verification | PoW checked for all headers | Implemented |
| Conservative advance rate | Only 50% of revenue credited | Configurable |
| Trailing window | Credit based on recent history, not single events | Implemented |

**Residual Risk:** Medium. 6-block reorg is rare but possible in extreme cases.

**Recommendations:**
- Consider 10+ confirmations for high-value payouts
- Monitor Bitcoin network for unusual activity
- Implement emergency pause if large reorg detected

---

### 2.4 Self-Transfer (Fake Revenue) Attacks

**Threat:** Borrower sends BTC to themselves to fake mining revenue.

**Attack Flow:**
1. Attacker controls BTC and registers as borrower
2. Sends BTC from address A to registered payout address B
3. Claims this as "mining payout"
4. Receives credit limit increase
5. Borrows and defaults

**Mitigations:**
| Control | Description | Status |
|---------|-------------|--------|
| Pool Registry | Whitelist known mining pool payout patterns | Implemented |
| Permissive mode bypass | MVP accepts all sources (operational risk) | Configurable |
| Payout heuristics | Large payouts discounted via `largePayoutDiscountBps` | Implemented |
| Minimum payout count | Full credit only after `minPayoutCountForFullCredit` payouts | Implemented |
| New borrower cap | `newBorrowerCap` limits exposure to new accounts | Implemented |
| Trailing window | Sustained fake revenue expensive to maintain | Implemented |

**Residual Risk:** Medium-High in MVP (permissive mode). Lower in production with strict pool validation.

**Recommendations:**
- Transition to strict pool registry mode post-MVP
- Implement input UTXO analysis for provenance
- Consider off-chain KYC/verification for large credit lines

---

### 2.5 Key Loss / Compromise

**Threat:** Loss or compromise of protocol admin keys.

**Affected Keys:**
| Key | Impact of Compromise | Impact of Loss |
|-----|---------------------|----------------|
| Protocol Owner | Full admin control, can drain via parameter manipulation | Cannot update configs, frozen protocol |
| Relayer Signer (MVP) | Can sign fraudulent payouts | Cannot verify new payouts |
| Checkpoint Signer | Can insert malicious checkpoint | Cannot advance checkpoints |

**Mitigations:**
| Control | Description | Status |
|---------|-------------|--------|
| Ownership transfer | All contracts support `transferOwnership()` | Implemented |
| No direct fund access | Owner cannot directly withdraw LP funds | Implemented |
| Parameter bounds | `advanceRateBps` capped at 10,000 (100%) | Implemented |
| Event logging | All admin actions emit events | Implemented |

**Residual Risk:** High for single-key ownership.

**Recommendations:**
- Migrate to multisig ownership (Gnosis Safe)
- Implement timelock for sensitive operations
- Establish key recovery procedures

---

### 2.6 Smart Contract Vulnerabilities

**Threat:** Bugs in contract code leading to fund loss.

**Attack Vectors:**
| Vector | Mitigation | Status |
|--------|------------|--------|
| Reentrancy | No external calls before state updates | Applied |
| Integer overflow | Solidity 0.8.x automatic checks | Applied |
| Access control bypass | `onlyOwner`, `onlyManager` modifiers | Applied |
| Flash loan attacks | No oracle price dependency in single tx | Not applicable |
| Front-running | No MEV-sensitive operations | Applied |

**Residual Risk:** Medium. Formal audit recommended.

---

### 2.7 Price Oracle Manipulation

**Threat:** BTC/USD price manipulation to inflate credit limits.

**Current Model:**
- `btcPriceUsd` set by admin via `RiskConfig.setBtcPrice()`
- No on-chain price feed dependency

**Mitigations:**
| Control | Description | Status |
|---------|-------------|--------|
| Admin-only price updates | Only owner can set price | Implemented |
| No atomic price dependency | Price manipulation requires admin compromise | Implemented |
| Event logging | Price changes emit `BtcPriceUpdated` event | Implemented |

**Residual Risk:** Low for external attackers. Medium for admin compromise.

**Future Consideration:** Integrate Chainlink or similar oracle with sanity bounds.

---

### 2.8 Liquidity Provider (LP) Risks

**Threat:** LP fund losses due to borrower defaults.

**Risk Factors:**
- Undercollateralized lending (by design)
- Revenue can decrease (market conditions)
- Borrower can abandon operations

**Mitigations:**
| Control | Description | Status |
|---------|-------------|--------|
| Advance rate < 100% | Default 50%, configurable | Implemented |
| Global cap | `globalCap` limits total exposure | Implemented |
| Borrower freeze | Admin can freeze risky borrowers | Implemented |
| Interest accrual | Borrowers pay interest on outstanding debt | Implemented |
| No forced liquidation | Protocol designed for gradual wind-down | By design |

**Residual Risk:** Inherent to the business model. LPs accept default risk.

---

## 3. Security Architecture

### 3.1 Trust Boundaries

```
┌─────────────────────────────────────────────────────────────────┐
│                     TRUSTED ZONE                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │ Protocol     │  │ Relayer      │  │ Checkpoint           │   │
│  │ Owner        │  │ Signer (MVP) │  │ Signers (Production) │   │
│  └──────────────┘  └──────────────┘  └──────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   SMART CONTRACTS                               │
│  ┌────────────────────┐  ┌────────────────┐  ┌──────────────┐   │
│  │ HashCreditManager  │──│ IVerifierAdapter│──│ LendingVault │   │
│  └────────────────────┘  └────────────────┘  └──────────────┘   │
│           │                     │                    │          │
│  ┌────────────────────┐  ┌────────────────┐  ┌──────────────┐   │
│  │ RiskConfig         │  │ PoolRegistry   │  │ Checkpoint   │   │
│  │                    │  │                │  │ Manager      │   │
│  └────────────────────┘  └────────────────┘  └──────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   UNTRUSTED ZONE                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │ Borrowers    │  │ LPs          │  │ Proof Submitters     │   │
│  └──────────────┘  └──────────────┘  └──────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Defense in Depth

| Layer | Controls |
|-------|----------|
| L1: Input Validation | Proof size limits, address validation, amount bounds |
| L2: Cryptographic | Signature verification, hash verification, PoW validation |
| L3: State Protection | Replay prevention, nonce tracking, status checks |
| L4: Economic | Advance rate, caps, windows, heuristics |
| L5: Operational | Freeze capability, parameter updates, monitoring |

---

## 4. Incident Response

### 4.1 Emergency Actions

| Action | Method | Effect |
|--------|--------|--------|
| Freeze borrower | `freezeBorrower(address)` | Block new borrows, allow repay |
| Change relayer | `setRelayerSigner(address)` | Invalidate old signer |
| Update checkpoint | `setCheckpoint(...)` | Anchor to safe block |
| Pause (if implemented) | N/A | Halt all operations |

### 4.2 Monitoring Recommendations

- Track `PayoutRecorded` events for unusual patterns
- Monitor `BtcPriceUpdated` for unauthorized changes
- Alert on `BorrowerStatusChanged` events
- Track total debt vs credit limits
- Monitor Bitcoin network for reorg events

---

## 5. Recommendations Summary

### 5.1 Critical (Pre-Production)
- [ ] External security audit
- [ ] Multisig for owner keys
- [ ] Formal verification of critical paths

### 5.2 High Priority
- [ ] Timelock for admin operations
- [ ] Emergency pause mechanism
- [ ] On-chain monitoring/alerts

### 5.3 Medium Priority
- [ ] Strict pool registry mode
- [ ] Input UTXO provenance analysis
- [ ] Chainlink price oracle integration

---

## 6. Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2025-02 | Initial threat model document |
