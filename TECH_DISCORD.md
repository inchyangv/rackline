## HashCredit Technical Summary (Discord)

USC testnet exists, but USC mainnet was not live when we built this flow.  
So we built the full BTC-proof credit stack using the same architecture pattern USC would use.

It already works now:
- BTC payouts are proven with SPV (`checkpoint + header chain + merkle proof + tx output check`).
- Verified payout evidence updates borrower credit on-chain.
- Borrow/repay already runs on Creditcoin testnet.

Why this matters:
- The protocol is modular (`verifier adapter` vs `credit manager` vs `vault asset`).
- USC integration is a wiring/deployment step (token/vault or settlement adapter), not a redesign.

Current demo scope (already running):
- SPV verification path with checkpoints and merkle inclusion.
- Manager credit updates from verified payout evidence.
- Borrow/repay execution through vault.
- Replay protection and risk-config driven policy.
- API ops flow for checkpointing, borrower mapping, and proof submit.

What you can try right now:
1. Register checkpoint.
2. Register borrower pubkey-hash + borrower.
3. Build and submit SPV proof.
4. Confirm credit limit update on-chain.
5. Execute borrow/repay.

In short: we implemented the USC-shaped architecture now, proved it end-to-end with real BTC proof flow, and left a clean path to attach USC by wiring adapters.
