# HashCredit (CTC Hackathon) — PROJECT.md

## 0) One-line project definition
HashCredit is a protocol that provides a **stablecoin Revolving Credit Line (limited loan)** from Creditcoin (EVM) using **Bitcoin miners' future mining profits (hash rate-based sales)** as collateral.
The key is not “physical equipment due diligence” but to automatically open/increase credit limits by cryptographically (or in MVP, signature oracles) verifying observable Proof-of-Work based payout events on the Bitcoin chain.

---

## 1) Background and problem definition (Why)
### 1.1 Miners’ structural liquidity problem
- Miners have ASIC/infrastructure (production assets) and future cash flows (mining profits).
- However, costs (electricity/hosting/operation/maintenance) occur immediately, and profits are subject to volatility and delays.
- As a result, miners are often “forced to sell” BTC to raise operating costs, which leads to the sacrifice of long-term upside + confirmed losses in the price decline section.

### 1.2 Limitations of existing finance/DeFi alternatives
- Traditional loans (equipment collateral/corporate loans): Due diligence, collateral management, legal enforcement, slow underwriting, and collateral value plummets when the market falls.
- DeFi loans: Most are based on liquidity tokens, overcollateralized (liquidation risk), rely on BTC locking/bridging/wrapping, and do not have a credit rating layer that directly “sees” mining sales.

---

## 2) Goal (What)
### 2.1 Goal
1. Bitcoin Miner Payout is defined as a “Verifiable Revenue Event.”
2. Deterministically calculate the credit limit by accumulating verified sales events.
3. Creditcoin (EVM) provides stablecoin **loan/repayment**.
4. (Hackathon) Considering the current absence/immaturity of the Bitcoin SPV SDK for USC, complete a demo that can operate as a **hybrid oracle (MVP Relayer)**.
5. (Production) In the future, **Bitcoin SPV verification will be performed on-chain** in a “Trust-minimized” direction, or only **Verifier Adapter will be replaced** when USC’s Bitcoin proof support matures.

### 2.2 Non-goals (1st)
- Full DAO/governance, institutional-grade KYC/AML, multi-chain/multi-asset expansion, complex ML credit rating
- Liquidation based model (we call it “revenue based cap” + risk management with conservative cap/freeze)

---

## 3) Core Concept
### 3.1 “Revenue-Based Financing(RBF)” on-chain
- Borrower (miner) proves the sales event (full payout), and the protocol grants a credit limit based on this.
- Instead of depositing collateral as tokens, **sales generated from production activities** become the basis for credit.

### 3.2 What is different about HashCredit?
- Credit evaluation based on “on-chain PoW activity (=Payout)” rather than “equipment collateral”.
- Loan limit calculation, event verification, replay prevention, and risk parameters are **standardized to smart contracts**.
- Structure consistent with USC/Offchain worker pattern (only verification module can be replaced).

---

## 4) Architecture
### 4.1 Common design principles
- **Verifier Adapter Pattern:** “Payout verification method” can be replaced, “Credit Line logic” is fixed.
- **Event-sourced Credit:** Payout authentication events accumulate and limits update deterministically.
- **Idempotency/Replay protection:** The same TX proof is reflected only once.
- **Defense-in-depth:** Proof of inclusion + Verification of meaning (recipient/amount) + Verification of provenance (pool/pattern) + Risk parameters (cap/haircut).

### 4.2 Components
#### On-chain (Creditcoin EVM)
- `HashCreditManager` (Core)
- Borrower registration/status
- Reflection of payout certification
- Calculate/update limits
-borrow/repay routing
- `LendingVault` (based on a single stablecoin)
    - liquidity deposit/withdraw
    - borrow/repay
- Interest model (simple fixed APR or kink model)
- `IVerifierAdapter` + 2 types of implementations
    - `RelayerSigVerifier` (Hackathon MVP)
- `BtcSpvVerifier` (Production: Own SPV, checkpoint based)
- (Recommended) `PoolRegistry`
- Management of the source (pool/cluster/pattern) of “credit-eligible payout”
- (Recommended) `RiskConfig`
- Advance rate, caps, confirmation policy, new borrower restrictions

#### Off-chain
- (MVP) `Relayer`
- Monitor Bitcoin mempool/blocks → Detect payout → Wait for confirmations → Sign EIP-712 payload → Call `submitPayout()`
- (Production) `Proof Builder/Prover`
- (After checkpoint) header chain + merkle branch + rawTx configuration → call `submitPayoutProof()`

---

## 5) Two execution modes (important)
### 5.1 Hackathon MVP: Hybrid Oracle (Relayer Mock)
**Why you need it:** Even if the USC testnet is open, the Bitcoin SPV SDK/documentation/tools may be unavailable during the hackathon period.
**Solution:** Simulate proof including payout with a “signature oracle”, but keep on-chain interface and credit logic the same as production.

- Relayer is a trust boundary (authorized signer)
- Contracts are defended with signature verification + replay prevention + risk policy
- Only the Verifier is replaced in mainnet/production.

### 5.2 Production: Bitcoin SPV (Checkpointed Header + Merkle Inclusion)
**Key point:** Bitcoin's tx inclusion is SHA256d + Bitcoin merkle rule, so it may be difficult to combine directly with the Keccak-based Merkle description in the USC document.
Therefore, “Bitcoin proof” is designed with the assumption that we will implement it.

- Periodically register **checkpoint header** on-chain (multisig/attestor set)
- When submitting payout proof:
1) Submit a short header chain from checkpoint to target block (PrevHash link + PoW verification)
2) Verify tx inclusion with rawTx + merkle branch
3) Decode rawTx and verify vout’s recipient scriptPubKey + amount
- Proofs that cross the retarget boundary (2016 block) are initially rejected (avoided through operation)

---

## 6) Protocol operations (Flows)
### 6.1 Borrower registration
input:
- borrower EVM address
- BTC payout identifier (recommended: scriptPubKey hash format, not address string)

Essential security considerations:
- Need to prevent attacks that “register someone else’s payout address”
- Hackathon: Administrator approval + can be replaced by off-chain proof of ownership (message signing)
- Production: Consider register commit transaction (e.g. borrowerEvm commit to OP_RETURN) method

### 6.2 Payout authentication
- MVP: Relayer signed payload submission → on-chain signature verification → revenue record
- Production: Submit SPV proof → verify on-chain proof → record revenue

### 6.3 Credit Limit Calculation (Determinism)
Basic form:
- trailing revenue window W (e.g. 30 days)
- advance rate α (e.g. 0.2~0.6)
- `creditLimit = α * trailingRevenueUSD(W)`  
(In hackathons, for simplicity, payout can be calculated based on sat “without USD conversion” or a fixed BTCUSD price can be set as a config. However, from a screening/VC perspective, the “price oracle” is specified to be modularized in the future.)

### 6.4 Borrow/Repay
- `borrow(amount)` must satisfy `debt + amount <= creditLimit`.
- Reduce debt with `repay(amount)`.
- The interest model can start with a simple fixed APR (hackathon), and can be expanded to a utilization-based model in production.

### 6.5 Freeze/Offboarding (required for operation)
- When an abnormality occurs, the borrower is converted to Frozen → Additional borrowing is blocked
- The basic principle is “blocking additional loans + encouraging repayment” rather than forced liquidation.

---

## 7) Attack model and defense (screening/VC core)
### 7.1 Biggest loophole: Creating fake sales with self-transfer
If you simply acknowledge “deposit to my address” as a sale, the attacker can inflate the limit by circulating own funds, borrow stablecoins, and then default.

### 7.2 Defense Layer (Priority)
1) **Pool provenance (required)**
- Confirm as much as possible that the payout originated from a “registered pool source”
- Hackathon: Relayer signs after determining provenance (on-chain registry only provides hooks)
- Production: full cluster registry + pattern-based decision (tracking complete input UTXOs is expensive)

2) **Underwriting haircut + caps (required)**
- New borrower cap, low α (advance rate), extended period window (increased operating costs)

3) **Replay protection + confirmations (required)**
- txid/vout reflected once, confirmations policy (e.g. 6 conf)

4) **Behavior-based heuristic (optional)**
- For one-time large deposits, limit reflection is delayed/partially reflected.
- Does the payout cycle/distribution match the pool pattern?

---

## 8) Deliverables
### 8.1 Hackathon MVP delivery
- Smart contract:
- HashCreditManager + LendingVault + RelayerSigVerifier + (optional) PoolRegistry/RiskConfig
- Off-chain:
- Python Relayer (monitoring/signature/transmission)
- test:
- Foundry unit tests (registration, replay, limit update, borrow/repay)
- Demo:
- E2E demo script + minimal UI/CLI

### 8.2 Production SPV delivery (2nd)
- BtcSpvVerifier (Checkpointed header + merkle inclusion + vout parsing minimum)
- Proof builder (header/merkle/tx configuration)
- Build test vectors with actual mainnet tx samples

---

## 9) Technology stack/repo structure (recommended)
- Solidity + Foundry (Testing/Deployment)
- (Optional) Hardhat for scripts
- Python 3.11+ (Relayer/Prover)
- Docker compose (optional): Bitcoin Core, indexer, relayer

Recommended repo structure:
- `/contracts` solidity
- `/test` foundry tests
- `/script` deployment scripts
- `/offchain/relayer` python
- `/offchain/prover` python
- `/docs` additional docs
- `docs/specs/PROJECT.md`, `docs/process/TICKET.md`

---

## 10) Definition of Done
“Done” Each function must satisfy the following:
- Code + testing + minimal documentation updates
- Reproducible demo scenarios (scripts)
- Security/risk-related parameters can be controlled through config without being hard-coded in the code.
- replay/nonce/confirmations policy clearly implemented/documented

---
