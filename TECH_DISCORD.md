## Rackline (formerly HashCredit) — Technical Summary (Discord)

HashCredit is now **Rackline**: we pivoted from Bitcoin hashrate to **GPU NFTs**. Reason: v1 could prove mining payouts (SPV on Creditcoin) but could not collect on them — enforcement needed mining pools to withhold payouts, and no pool had a reason to. v2 lends against an asset you can identify, route, and reclaim.

**What v2 is**
- `GpuNodeNFT` (ERC-721 on Creditcoin) = one registered GPU deployment (provider, SKU, hardware hash).
- Each NFT has a `NodeAccount` on the payout chain (ERC-6551-style escrow). The DePIN network pays *that* account.
- `AttestcoinRevenueVerifier` proves each payout on Creditcoin via the BlockProver precompile `0x0FD2` (`verifyAndEmit` + `EvmV1Decoder`, `receiptStatus == 1`, replay key `keccak(chainKey, blockHeight, txIndex)`).
- `GpuCreditManager` turns trailing verified net revenue into a facility limit; `borrow` locks the NFT; each payout is swept and repaid through `repayFor(tokenId)` — no borrower signature.
- Default: draw freeze → sweep ratio up → NFT foreclosure to the vault. Draw pause never blocks repayment.
- `LendingVault` v2: single principal/interest ledger, partial interest preserved, no retroactive APR, first-loss reserve.

**Same seam as spring:** `IVerifierAdapter` → `IRevenueVerifier`. Swapped `BtcSpvVerifier` for Attestcoin; credit logic untouched.

**Testnet demo (CC3 testnet + Sepolia):** register → mint NFT → mock network payout on Sepolia → Attestcoin proof → credit up → borrow → second payout → sweep → `repayFor` → debt down → LP pool. Simulated parts: the network (`MockDePINPayout`) and the Sepolia→Creditcoin settlement leg (keeper mock bridge). Everything else is real contracts.

**Honesty notes:** evidence is trustless; enforcement is graded E0–E3 and only E2+ (partner-recognized receiver lock) gets funded loans. No fixed LP yield. No partnerships claimed.

Repo: https://github.com/inchyangv/ctc-hashcredit · Pivot write-up: `docs/hackathon/WHY_WE_PIVOTED.md`
