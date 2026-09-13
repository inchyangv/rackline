# GPU browser and unit verification

From repository root:

```sh
npm --prefix apps/web run test -- --run
npm --prefix apps/web run test:e2e
```

The Node unit runner executes the actual TypeScript demo store and GPU client helpers, including exact bigint amounts, configuration/profile rejection, and wallet-login binding. It requires no browser, network, key, or database.

Playwright starts Vite on `127.0.0.1:4173` and runs Chromium at desktop 1440px and mobile 390px widths. On macOS it uses the installed Google Chrome; elsewhere run `npx playwright install chromium` or set `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH`.

`preview.spec.ts` exercises the isolated demo. A sentinel rejects real wallet requests, external/API calls, and POSTs. `gpu.spec.ts` exercises the connected application against an explicit HTTP and EIP-1193 fixture; it uses actual ethers ABI encoding, EIP-712 signatures, transaction simulation, exact approvals, signed fixture transactions, and receipt confirmation. Its balances/receipts are simulated and are not contract, native-testnet, partner, or cash evidence.

Connected coverage includes onboarding/session refresh/provider request, persisted proof requests, native pending versus cash/debt, bound borrow/direct repay, faucet/deposit/withdraw/partial queue/cancel/claim/recovery, role/version/idempotency checks, wrong chain/wallet changes, quote minimums, wallet rejection, simulation revert, responsive overflow, and keyboard focus confinement. Screenshots and failure traces stay beneath ignored `node_modules/.cache/playwright/test-results/`.

Wallet classification recognizes exactly the 23-byte delegation indicator defined by [EIP-7702](https://eips.ethereum.org/EIPS/eip-7702#delegation-indicator); other nonempty account code selects server-side ERC-1271 validation. Classification never grants a role or bypasses the server's signature/allowlist check.

## Actual API/PostgreSQL interoperability

Run these in three terminals:

```sh
.venv-py313/bin/python apps/web/scripts/api-review-server.py 4182
VITE_GPU_API_URL=http://127.0.0.1:4182 npm --prefix apps/web run dev -- --host 127.0.0.1 --port 4273 --strictPort
node apps/web/scripts/api-review-browser.mjs
```

The server creates and migrates its own ephemeral PostgreSQL cluster and runs the real GPU API. No RPC or contract is configured; financial actions fail closed. The browser signs real login challenges with public disposable test accounts, submits real HTTP onboarding and provider requests, and verifies PostgreSQL persistence after page reload on desktop and mobile. Stop the server to remove only its temporary database cluster. This remains **LOCAL** evidence and never claims native verification or actual GPU revenue.

For deployed contract/API smoke evidence, use the release execution record. A live wallet or credential is never required for CI.

`scripts/live-review-browser.mjs` is an opt-in **real testnet transaction** browser smoke, separate from CI. Set `GPU_REVIEW_WEB_URL`, `GPU_REVIEW_API_URL`, a disposable test-CTC-funded wallet in `GPU_SMOKE_PRIVATE_KEY`, and `GPU_ALLOW_TESTNET_TRANSACTIONS=1`, then run `node apps/web/scripts/live-review-browser.mjs`. It rejects non-native profiles, non-test assets, chains other than 102031, existing LP positions, native transfers, arbitrary contracts/methods, and approvals/deposits above 1 tUSD. It uses actual HTTP, RPC, signatures and two-confirmation receipts for faucet-if-needed → 1 tUSD supply → queue/cancel → queue/fund/claim → remaining direct withdrawal. The key and API session stay in memory. Output contains only public wallet/deployment IDs and transaction hashes. This script's availability is not evidence that the live smoke has been run.

For an explicitly prepared, zero-debt test borrower, set `GPU_REVIEW_FLOW=borrower` and `GPU_REVIEW_FACILITY_ID` with that borrower's funded test wallet. This mode allows only a 1 tUSD borrow and a 1.001 tUSD `repayExact` cap to the API-bound facility, then checks canonical debt is zero. A 0.001 tUSD starting balance is required for interest. It never creates a facility or bypasses eligibility. A stopped LP smoke can resume only with `GPU_REVIEW_RESUME_CANCELLED_REQUEST` identifying its already cancelled, wallet-owned request and no more than the previous 1 tUSD test position; prior deposits/requests are not repeated. The helper refreshes signed sessions before expiry, and screenshots remain in ignored cache storage.

## 2026-09-14 implementation verification

This matrix records frontend implementation evidence for GPU-046–052. All fixtures and the disposable database harness are **LOCAL** evidence, even when testing native-required configuration. They do not establish native acceptance, reviewed partner revenue, credit approval, or real destination cash.

| Flow | Evidence and boundary |
| --- | --- |
| Generated API/contract bindings, exact amounts | Four generated Solidity ABIs and 47 OpenAPI schemas; drift check passes. Bigint parsing, domain and deployment rejection covered by unit tests. |
| Wallet authentication | Real EIP-712 signatures; wrong-chain switch, account/chain session invalidation, ERC-1271 server-validation rejection, delegated-EOA selection and scoped screens verified at both widths. Session tokens are memory-only. |
| Borrower onboarding / provider connection | Actual API + migrated PostgreSQL: HTTP 201 onboarding, refreshed borrower session, HTTP 202 pending review, and persisted request after reload at 1440px and 390px. This does not approve identity or payment control. |
| Source proof / activity | Account-bound request survives reload in the browser fixture; pending/artifact/native/receivable eligibility and destination-cash application remain separate. |
| LP deposit / withdrawal | Exact approval, frozen preview/minimum, confirmation-gated refresh, direct withdrawal, partial queue funding, cancel, one-time claim and epoch recovery verified with ABI-valid wallet fixtures. Test faucet is explicitly test-only. |
| Borrow / repay | Bound bytes32 facility context, draw eligibility and pause checks, manager draw, exact repayment during proof outage, confirmed-only refresh. No ID guessing or source-paid debt reduction. |
| Transaction failure | Wallet rejection and simulation revert preserve balances; chain/account change drops the session; expired quotes and wrong deployment are rejected. |
| Operations | Role/scope, reason, expected version and idempotency included; UI has no manual native-verification override or financial signing key. |
| Responsive / accessibility | All six connected pages at both widths, no horizontal overflow or uncaught errors, dialog focus confinement, reviewed desktop/mobile screenshots. |
| Isolated demo | Six flows at both widths; network/wallet sentinel proves no API calls, wallet transactions or real funds. |

Latest full local checks: 29 unit tests, 52 browser tests (40 connected + 12 isolated demo), production build and lint passed. Generated drift check passed before the final router-repayment DTO extension and must pass again with that schema. Wallet coverage also includes first-time testnet registration, a repayment cap above displayed debt without excess transfer, preserving login while configuration outages pause new submissions, and explicit finalized-block/stale-debt labels while repayment remains separate from draw eligibility. The actual API/PostgreSQL harness additionally passed both viewport flows, including the real proof-history endpoint after API restart. Integration found and corrected an unconfigured-asset render crash, registration-reference constraint mismatch, and mobile lazy-navigation test timing; no native success was inferred from these fixes.

## Actual testnet LP browser evidence

On 2026-09-14 the connected browser used the real API/PostgreSQL and Creditcoin chain 102031 deployment `01K54G0000QN0QHY2GCA10HGXN`, with wallet `0xee684316539c3996855AA01415555D7f5Af3Ada6`. These are real **test-token** transactions, not partner-revenue or native-proof-acceptance claims.

| Browser action | Confirmed transaction |
| --- | --- |
| Test faucet | [444f277c…](https://creditcoin-testnet.blockscout.com/tx/0x444f277cf8c2db087a853e9d4dec91e52f61ac85636337a0df9b87a1b5916240) |
| Exact 1 tUSD approval | [a1139d1d…](https://creditcoin-testnet.blockscout.com/tx/0xa1139d1d6f939ad72194ceb0d7b424725ccbc663aa993215894aeccac128a8d9) |
| 1 tUSD deposit | [fc21ec54…](https://creditcoin-testnet.blockscout.com/tx/0xfc21ec540e1e40441d111b9335eb8e5bb4d0e3c44e3d2b0afacc85763bbc3cf6) |
| Request withdrawal #1 | [e0d4c120…](https://creditcoin-testnet.blockscout.com/tx/0xe0d4c12083c9278617634318b3daa6199bf6366bcda778dcb12b253894de9a66) |
| Cancel request #1 | [8fc710b1…](https://creditcoin-testnet.blockscout.com/tx/0x8fc710b113c088a313a800b35a20ba9ad44356df2bda28bd62cf9878c5281717) |
| Request withdrawal #2 | [b48f18e0…](https://creditcoin-testnet.blockscout.com/tx/0xb48f18e040f95aa29759ec484d7efbe980f2dc742454c7f42e2676e19c8af137) |
| Fund the queue | [93817b78…](https://creditcoin-testnet.blockscout.com/tx/0x93817b78b42840e8e193ac0e9151dfbefd86a7a63ff678c89c758e033d6a232f) |
| Claim funded cash | [58607208…](https://creditcoin-testnet.blockscout.com/tx/0x586072082ead746cf13264c14c75f5929129661ad5faff495c6903561144bdeb) |
| Withdraw remaining shares | [658233c9…](https://creditcoin-testnet.blockscout.com/tx/0x658233c98f54da8f8d9863a8a6136f79d0769abc8c2a3e24500b0ab4aab7cbc4) |

The first two automation runs stopped at a between-step Refresh lookup; confirmed on-chain state was checked before resuming the exact cancelled/pending request. No deposit or earlier request was repeated. The final resumed run passed and a subsequent **read-only** sign-in passed at both 1440px and 390px: finalized block 5484451, LP position **0 tUSD**, wallet **10,000 tUSD**, no unfilled or claimable amount, no uncaught page errors or horizontal overflow. Screenshots `native-lp-1440.png` and `native-lp-390.png` are in ignored `node_modules/.cache/playwright/`. The chain's six-block indexing finality is distinct from the two confirmations shown for transaction inclusion. Partial funding/loss recovery remain separately covered by LOCAL contract/browser tests, not this live LP cycle.

Public receipt and final-state checks are in [LP browser evidence](../../../evidence/native-testnet/lp-browser-20260914.json). All nine receipts were successful and canonical with at least 39 confirmations at the independent check.

## Actual testnet borrower browser evidence

The same deployment's borrower wallet `0x42E46697957766fFad9b7f55621260f99Dc204B7` completed facility `5DCNY1D03WP51EAK4V024YB60F`: [borrow 1 tUSD](https://creditcoin-testnet.blockscout.com/tx/0x7f70742f267233e7195edec63635cc71bd80167f9e896f1f225f21f485c403ee), [approve a 1.001 tUSD cap](https://creditcoin-testnet.blockscout.com/tx/0x649813a3a7e99497bf7bf56e93073f984281a1689e840921a80304bc6eb8cf75), and [repay exact execution debt](https://creditcoin-testnet.blockscout.com/tx/0xa369810d67bb59695e7acc87d4163d1a1257876d6fba28635ee154dd1bc2fe78). `RepaymentRouter.Repaid` log 13 records principal 1 tUSD, interest 0.000002 tUSD, no excess, and debt 0. The unused cap was not transferred. Actual API canonical debt 0 and the Repaid facility screen passed at desktop/mobile widths, with no uncaught browser errors or horizontal overflow.

The initial run stopped after successful borrowing because the indexer watermark stalled. A repayment-only resume encountered a wallet RPC failure before approval; on-chain nonce/allowance checks confirmed nothing had been submitted. Another attempt timed out before opening the browser. The final run used the updated API and bounded read-only RPC retries, then completed without repeating the borrow. Public [borrower browser evidence](../../../evidence/native-testnet/borrower-browser-20260914.json) records all three successful canonical receipts, final debt/token balance, and these interruptions. This remains test-token evidence; partner revenue is simulated and native-proof acceptance is verified separately.

For safe investigation, `GPU_REVIEW_RESUME_BORROWER_REPAY=1` permits only repayment of the prior 1–1.001 tUSD debt and rejects manager borrow submissions. `GPU_REVIEW_READ_ONLY=1` blocks every transaction submission; borrower mode checks debt 0. Adding `GPU_REVIEW_EXPECT_REPAYMENT_TX` additionally requires a real API `FINALIZED_ROUTER_EVENT` allocation with the expected exact amounts and verifies its activity-screen link. RPC reads use a 12-second timeout and at most three attempts; broadcasts are never automatically retried.
