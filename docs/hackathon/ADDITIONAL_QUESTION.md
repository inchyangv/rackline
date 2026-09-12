# Answers

## Premise: Bad debt is inherent to all unsecured lending

All three questions converge on the same issue: **"What happens when repayment doesn't occur?"** This is not unique to HashCredit. Unsecured credit lending, by definition, has no collateral to seize upon default — bad debt is a structural inevitability. Traditional finance does not eliminate this risk; it manages it.

How banks manage unsecured credit risk:
1. **Income verification** — pay stubs, tax returns to confirm repayment capacity
2. **Limit controls** — credit scoring, DTI ratios to prevent over-lending
3. **Auto-debit repayment** — scheduled transfers from the borrower's account
4. **KYC + legal enforcement** — verified identity enables debt collection and legal proceedings
5. **Loan loss provisions** — reserves set aside from revenue to absorb expected losses

HashCredit applies the same framework to mining revenue.

| Traditional Credit | HashCredit | Status |
|---|---|---|
| Income verification (pay stubs) | SPV-proven BTC payouts | **Live** |
| Credit score / DTI limits | Trailing revenue x advance rate + caps | **Live** |
| Auto-debit repayment | Payout-linked auto-repayment | **Mainnet roadmap** |
| KYC + debt collection | Borrower/pool KYC + legal recourse | **Mainnet roadmap** |
| Loan loss provisions (BIS) | On-chain reserve + Coverage Pool | **Mainnet roadmap** |

---

## Q1. What prevents a mining pool from simply not enforcing repayment or colluding with the miner?

In traditional banking, borrowers can conceal income or collude with employers to fabricate pay stubs. Banks mitigate this through income verification procedures and KYC-based legal accountability. HashCredit follows the same principle.

**Currently live:**
- **Income verification:** Only payouts recorded on the Bitcoin blockchain and verified via SPV proof are accepted as credit evidence. Self-reported or fabricated data cannot pass.
- **Limit controls:** A 50% advance rate, new-borrower cap, large-payout discount, and minimum payout threshold collectively bound the maximum loss from any single bad actor — just as banks assign lower limits to new customers.
- **Approved pool system:** PoolRegistry restricts accepted payout sources to approved partner pools only.

**Mainnet roadmap — KYC-based legal enforcement:**
Both borrowers and pools undergo KYC. If a pool fails to enforce repayment or colludes with a miner, verified identities enable contractual claims and debt collection — the same recourse a bank has when an unsecured borrower defaults.

On-chain logic alone cannot prevent collusion, but neither can traditional finance. The key is designing a system where the cost of collusion (legal liability + capped exposure) exceeds the benefit.

---

## Q2. How do you handle miners switching pools or splitting hashrate across multiple pools?

In traditional banking, when a borrower's income stream stops, further lending is blocked and existing debt enters delinquency management. HashCredit works the same way.

**Currently live — payout-address-based tracking:**

HashCredit tracks **SPV-verified payouts to a registered BTC address**, not hashrate directly.

- **Switching between approved pools:** As long as the same payout address is used, payouts from any approved pool are attributed to the same borrower. Tracking continues seamlessly.
- **Multiple approved pools simultaneously:** All payouts aggregate into a single credit history within the trailing revenue window.
- **Moving to an unapproved pool or changing address:** The protocol can no longer capture that revenue, so payouts stop arriving and the credit limit naturally declines via the trailing window.

**Mainnet roadmap — auto-detection + legal recourse:**
- If a borrower with outstanding debt receives no payouts for a defined period, an **automatic freeze** is triggered — blocking further borrowing.
- KYC information then enables debt collection proceedings.

---

## Q3. How does your protocol adjust credit limits when BTC price drops sharply, or do you have any mechanism equivalent to liquidation or risk buffering?

Traditional unsecured lending also uses **income-based limit adjustments + loan loss provisions** rather than collateral liquidation. HashCredit follows the same model.

**Currently live — automatic limit reduction:**

Credit limit = trailing BTC payouts x BTC/USD price x advance rate. When prices fall, USD-denominated mining revenue drops and the credit limit automatically decreases, blocking new exposure. Additional safeguards include new-borrower caps, a global vault cap, and emergency pause/freeze controls.

**Mainnet roadmap — automated repayment + two-layer loss absorption:**

*Payout-linked auto-repayment (= auto-debit):*
When a payout is submitted for a borrower with outstanding debt, a configurable portion is automatically applied toward repayment — the same concept as a bank auto-debiting monthly installments from a borrower's account.

*Two-layer loss absorption — vault reserve + Coverage Pool:*

In traditional finance, banks set aside loan loss provisions from revenue and, when those are exhausted, absorb remaining losses from capital. In DeFi, Aave uses Umbrella (formerly Safety Module) — a separate staking pool where participants earn rewards in exchange for bearing slashing risk when bad debt occurs. HashCredit combines both approaches.

**Layer 1 — Vault reserve (loan loss provision):**
- A configurable share (e.g., 20%) of LendingVault interest revenue is automatically set aside as `reserveBalance`
- When a borrower has no payouts for a defined period and debt exceeds the credit limit, the loan is recorded as a deficit
- `eliminateDeficit()` draws from the reserve first

**Layer 2 — Coverage Pool (on-chain insurance):**
- A separate ERC-4626 vault where coverage providers deposit stablecoins
- Depositors earn a premium from a share of borrower interest revenue — analogous to Aave Umbrella stakers earning rewards
- When a deficit exceeds the vault reserve, Coverage Pool assets are slashed to cover the remainder
- LPs (senior) are protected by two layers; Coverage Pool depositors (junior) earn higher yield in exchange for bearing first-loss risk

**Loss absorption waterfall:** deficit occurs → (1) vault reserve → (2) Coverage Pool slashing → (3) LP loss as last resort

The key difference from Aave is that Aave's primary defense is collateral liquidation, with bad debt being a rare edge case. HashCredit has no collateral, so the **Coverage Pool serves as a thicker, more critical protection layer**. Reserve balances, Coverage Pool size, and deficit status are all publicly visible on-chain — making this more transparent than traditional bank loan loss provisions.
