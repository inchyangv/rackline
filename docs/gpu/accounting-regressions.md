# v1 accounting / attribution regression vectors (GPU-002)

Reproductions of the known v1 (`HashCreditManager`, `LendingVault`, `BtcSpvVerifier`) defects from
PIVOT.md §2.2, pinned as executable vectors in `test/diagnostic/AccountingRegressions.t.sol`. The legacy
contracts are **not** modified (R2-D13). Each vector carries the value v1 produces today and the value the v2
ledger must produce; the constants are the acceptance expectations for the v2 tickets named below.

How to run:

| Mode | Command | Expected against v1 |
| --- | --- | --- |
| Pin (default, part of `forge test`) | `forge test --match-contract 'AccountingRegressionsTest'` | 8 passed — asserts `observed == v1` **and** `observed != correct`; fails if v1 behaviour silently changes or a defect stops reproducing |
| RED (correct expectations) | `RUN_RED_DIAGNOSTICS=true forge test --match-contract 'AccountingRegressionsTest'` | 8 failed (recorded 2026-09-14: `0 passed; 8 failed`) — becomes the green acceptance run for v2 |

A green pin run is **not** a claim that anything is fixed; a fix is proven only when the RED run is green
against the v2 contracts. Skips/xfail are not used.

Fixture: $50,000 BTC price, 50% advance rate, 30-day window, 10% fixed APR, $1,000,000 LP liquidity, 6-dp
stablecoin, `MockVerifier` (evidence is supplied verbatim), block time fixed at 1,800,000,000.

## Vectors

| ID | Defect (PIVOT §2.2) | Minimal input | v1 observed | Correct | Code | v2 owner |
| --- | --- | --- | --- | --- | --- | --- |
| AR-01 | Partial interest payment erases unpaid interest | borrow $5,000; +365 d (interest $500); repay $250 | `getCurrentDebt` = **$5,000.00**, accrued = $0 | **$5,250.00** (principal 5,000 + unpaid interest 250) | `HashCreditManager.repay` sets `lastDebtUpdateTimestamp` after any payment (`:436`) and never stores unpaid interest | GPU-034 (ledger), GPU-036 (repay) |
| AR-02 | Manager and Vault classify the same payment differently | same as AR-01 | manager principal 5,000; `vault.totalBorrowed` = **4,750** | both **5,000**; vault unpaid interest 250 | `LendingVault.repayFunds` takes principal first (`:217`); manager takes interest first (`:411`) | GPU-034, GPU-037 (vault v2) |
| AR-03 | Re-borrow capitalizes interest only in the Manager | borrow $5,000; +365 d; borrow $1,000 | manager `currentDebt` = **6,500**; vault `totalBorrowed` = 6,000 | one rule for both; v2 default: principal **6,000** + unpaid interest 500 in both (capitalization only if the facility terms say so) | `borrow` folds accrued interest into `currentDebt` (`:371`); vault adds only the new amount (`:197`) | GPU-003 (terms), GPU-034/036 |
| AR-04 | APR change re-prices the past | borrow $5,000 at 10%; +365 d; owner sets APR 20% | manager accrued = **$1,000** (whole year at 20%); vault froze **$500** at 10% | **$500** for the elapsed year; new rate applies only forward | `_calculateAccruedInterest` uses the current `borrowAPR()` for the full elapsed period (`:533`); `setFixedAPR` accrues at the old rate first (`:124`) | GPU-034 (rate segments / index) |
| AR-05 | Stale limit at borrow time | one payout → limit $10,000; warp past window + 1 d; `borrow($1,000)` | stored `creditLimit` still 10,000; **borrow succeeds** | in-window revenue is 0 → effective limit 0 → **revert** | limit is only recomputed in `submitPayout` (`:325`); `borrow` reads the stored value (`:374`) | GPU-035 (limit), GPU-036 (draw re-check), GPU-081 |
| AR-06 | Old evidence counted as fresh | payout mined 60 d ago submitted now (30-day window) | `trailingRevenueSats` = **40,000,000**, limit **$10,000** | **0 / 0** (older than the window; `lastPayoutTimestamp` kept for display only) | `_addPayoutRecord(borrower, block.timestamp, …)` records submission time (`:323`) | GPU-076 (freshness contract), GPU-031/035 |
| AR-07 | Claim signature has no domain | Alice links her BTC key; Mallory replays the same `(pubKeyX, pubKeyY, hash, v, r, s)` | `borrowerPubkeyHash[mallory] == aliceHash` (**replay succeeds**) | **revert** — the signed message must bind caller, chain id, contract, nonce, expiry | `claimBtcAddress` only checks `ecrecover(hash) == derived(pubkey)` (`BtcSpvVerifier.sol:176`) | GPU-013 (auth/consent signatures), GPU-029 (v2 interfaces); BTC path itself is legacy |
| AR-08 | Share donation / rounding (reproduced on EVM) | first LP deposits 1 base unit (1 share), donates $1,000 directly; second LP deposits $2,000 | second LP gets **1 share = $1,500** (loses $500 to the first LP); a following $1,000 deposit **reverts** (0 shares) | second LP redeemable **$2,000**; small deposits accepted | raw-balance share price with floor division and no virtual offset / minimum shares (`LendingVault.sol:145`, `:255`) | GPU-037 (vault v2 share accounting), GPU-055 (invariants) |

Notes:

- AR-01/02/03/04 share one root cause: there is no single ledger of principal / accrued interest / rate
  segments. PIVOT §2.2's headline example ($5,000 · 10% · 365 d · $250 → $5,250) is AR-01.
- The existing `test/HashCreditManager.t.sol::test_repay_interestFirst` asserts the AR-01 defect as expected
  behaviour ("Interest should reset after repay"). It is left untouched so the legacy suite keeps passing; the
  correct expectation lives in AR-01 and must be carried into the v2 suite, not into the legacy test.
- AR-05/06 are the "stale limit" and "past evidence reuse" items; under R2 they also map to the freshness
  rule (R2-D06): a draw must re-evaluate current, in-policy evidence, and acceptance time never refreshes old
  evidence.
- AR-07 is the pattern R2-D04 forbids copying into v2 auxiliary signatures (wallet auth, consent, approval):
  every signature must be domain-separated and bound to caller/chain/contract/nonce/expiry (the GPU-001 demo
  authorization already does this).
- Items from PIVOT §2.2 that are missing features rather than wrong arithmetic (no escrow/`repayFor`, global
  pause blocks repayment, NAV counts impaired debt, `setVault`/`setManager` hot-swap, 100-record payout array)
  are not vectors here; they are design requirements for GPU-029~043.
