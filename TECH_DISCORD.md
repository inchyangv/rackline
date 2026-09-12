## HashCredit Technical Summary (Discord)

HashCredit is a revenue-based financing protocol for Bitcoin miners on HashKey Chain.
We prove mining payouts with Bitcoin SPV — no oracle, no bridge — and issue USDT credit lines on-chain.

It already works now:
- BTC payouts are proven with SPV (`checkpoint + header chain + merkle proof + tx output check`).
- Verified payout evidence updates borrower credit on-chain.
- Borrow/repay already runs on HashKey Chain Testnet.

Why HashKey Chain:
- Compliance-first (HashKey Group, SFC-licensed HK) — enables institutional mining pool partnerships.
- Full EVM precompile support (OP Stack) — trustless BTC address verification via ecrecover + sha256 + ripemd160.
- The protocol is modular (`IVerifierAdapter` vs `HashCreditManager` vs `LendingVault`) — new proof sources plug in without touching credit logic.

Current demo scope (already running):
- SPV verification path with checkpoints and merkle inclusion.
- Manager credit updates from verified payout evidence.
- Borrow/repay execution through vault.
- Replay protection and risk-config driven policy.
- On-chain BTC address ownership proof (claimBtcAddress).

What you can try right now:
1. Register checkpoint.
2. Link BTC wallet (BIP-137 sign → on-chain verification).
3. Build and submit SPV proof.
4. Confirm credit limit update on-chain.
5. Execute borrow/repay.

Architecture is designed for extensibility — Chainlink CCIP, ZK bridges, or any future oracle can be added via a single adapter contract.
