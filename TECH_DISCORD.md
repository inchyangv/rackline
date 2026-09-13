## Rackline (formerly HashCredit) — Technical Summary (Discord)

HashCredit is now **Rackline**: we pivoted from Bitcoin hashrate to **GPU receivables**. Reason: v1 could prove mining payouts (SPV on Creditcoin) but could not collect on them — enforcement needed mining pools to withhold payouts, and no pool had a reason to. v2 lends against a cash flow you can identify, control, and verify: confirmed, unpaid settlements owed to GPU operators by DePIN compute networks, assigned to a controlled payment path.

**What v2 is (design; R2 ledger in `TICKET.md` / `docs/gpu/decisions/attestcoin-first.md`)**
- Operator onboards; confirmed unpaid settlements are assigned; the payer pays a **controlled escrow** on the source chain. Payment control is graded E0–E3 and only E2 (payer recognizes the assignment; operator cannot redirect alone, proven by a real test) gets funded.
- **Official Attestcoin native verification is the only evidence path**: `AttestcoinRevenueVerifier` → `INativeQueryVerifier` precompile `0x…0FD2` (`verifyAndEmit`) → `EvmV1Decoder` over the verified bytes → `receiptStatus == 1` → expected event from the expected emitter → `EvidenceBook` consumes it once (key includes the receipt log ordinal). No EIP-712 fallback, no admin approval, no mock verifier, no lower-advance-rate "attested" class. Unsupported payout chain = `UNSUPPORTED_SOURCE`.
- Five judgments stay separate: source event (native proof) · revenue provenance · current unpaid receivable · E2 control · actual destination cash receipt. A proof is not revenue; a past payout is not a receivable; in-flight funds are not repayment.
- Borrowing base = eligible unpaid receivables − deductions − haircuts, × advance rate; freshness bound to a source checkpoint, never to "no paid event seen".
- Debt falls only via `repayFor` after the vault actually receives loan currency. Draw pause never blocks repayment; proof outage never blocks permitted repayment or recovery.
- `LendingVault` v2: single principal / interest ledger, partial interest preserved, no retroactive APR, first-loss reserve, withdrawal queue.

**Same seam as spring:** proof ↔ credit ↔ vault separation. `BtcSpvVerifier` is retired; the debt ledger is rewritten.

**Status (2026-09-14, honest):** official Attestcoin artifacts pinned (`@gluwa/usc-sdk` 0.18.0, `@gluwa/asc-contracts` 0.2.1) and CC3 testnet probed read-only (Sepolia chainKey 1 confirmed) — `offchain/attestcoin/`, `config/attestcoin/`. **No v2 contract, worker or UI is implemented or deployed; no native proof submitted yet** (that is the G-ASC gate). The web app is Rackline-branded on the v1 contracts with every unavailable step labelled. The earlier "GPU NFT credit" draft is retired.

**Planned testnet demo (after GPU-077/078/079/080):** TEST_ONLY `MockDePINSettlement` on Sepolia pays a controlled escrow → official SDK proof → genuine native verification on CC3 testnet → receivable ledger / draw → second settlement → mock settlement rail → vault receipt → `repayFor` with no operator signature. Simulated parts labelled (`Simulated payer`, `Mock settlement`, `partnerRevenue=SIMULATED`); only the native verification is real.

**Honesty notes:** evidence is natively verified; enforcement is contractual plus payment control, never "trustless". No fixed LP yield. No partnerships claimed (Aethir / GPU.net are targets). NFT collateral, future-cash-flow and equipment finance are separate, deferred decisions.

Repo: https://github.com/inchyangv/ctc-hashcredit · Pivot write-up: `docs/hackathon/WHY_WE_PIVOTED.md` · Environment ledger: `docs/gpu/attestcoin/environment.md`
