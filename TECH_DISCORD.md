## HashCredit Technical Summary (Discord)

USC was not live yet, so we built the full BTC-proof credit stack using the same architecture pattern USC would use.

It already works now:
- BTC payouts are proven with SPV (`checkpoint + header chain + merkle proof + tx output check`).
- Verified payout evidence updates borrower credit on-chain.
- Borrow/repay already runs on Creditcoin testnet.

Why this matters:
- The protocol is modular (`verifier adapter` vs `credit manager` vs `vault asset`).
- USC integration is a plug-in step (token/vault or settlement adapter), not a redesign.

In short: we implemented the USC-shaped architecture now, proved it end-to-end with real BTC proof flow, and left a clean path to attach USC by wiring adapters.
