Subject: HashCredit — Follow-up on Credit Risk Management

Hi,

Thank you for the questions. They all converge on one concern: what happens when a borrower doesn't repay? We'd like to address this directly.


1. Bad debt is inherent to unsecured credit

This is true for every unsecured lending product — credit cards, personal loans, buy-now-pay-later. No bank eliminates default risk; they bound it, price it, and build recovery mechanisms. HashCredit does the same.


2. How we assess credit

Credit limit = trailing BTC payouts (SPV-verified) x BTC/USD price x advance rate

Key constraints enforced on-chain:
- Only SPV-proven Bitcoin payouts count. No self-reported data.
- 30-day trailing window — stale revenue drops off automatically.
- 50% advance rate — borrowers access only half of verified income.
- New borrower cap ($10K hard ceiling during probation period).
- Minimum payout count required before full credit unlocks.
- Large payout discount to prevent self-transfer manipulation.
- Global vault cap bounding total protocol exposure.

Every parameter is deterministic and on-chain. When BTC price drops, limits shrink automatically.


3. KYC enables legal enforcement

Both borrowers and pools undergo KYC. On default or collusion, verified identities enable contractual claims, debt collection, and legal proceedings — the same recourse banks have for unsecured credit.


4. Why this market exists — and why enforcement works

Our target users are miners who purchase or lease hashpower from pools, not miners who own physical facilities. This is a large, underserved segment:

- Banks can't serve them. Traditional mining loans require site visits, equipment appraisals, and balance sheet audits. These miners have verifiable on-chain income but no way to convert it into creditworthiness in the traditional system.

- HashCredit fills this gap by turning SPV-verified payout history into a credit profile.

- Enforcement is actually stronger than typical unsecured lending. These miners depend on pools for hashpower. When a borrower defaults, the partnered pool can withhold or redirect future payouts toward repayment — an automated garnishment mechanism that credit cards and personal loans simply don't have.

Combined with KYC-based legal recourse, we have both technical and legal enforcement channels.


Happy to walk through specific risk scenarios or the smart contract implementation if helpful.

Best regards,
HashCredit Team
