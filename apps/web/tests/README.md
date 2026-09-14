# GPU browser and unit verification

From the repository root:

```sh
npm --prefix apps/web run test -- --run    # Node unit tests
npm --prefix apps/web run test:e2e         # Playwright
```

## CI suites (no network, no keys)

**Unit (`tests/*.test.mjs`).** Runs the TypeScript demo store and GPU client helpers directly: exact bigint amounts, configuration/profile rejection, wallet-login binding. No browser, network, key, or database.

**Playwright.** Starts Vite on `127.0.0.1:4173` and runs Chromium at desktop 1440px and mobile 390px. On macOS it uses the installed Google Chrome; elsewhere run `npx playwright install chromium` or set `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH`.

- `preview.spec.ts` covers the isolated demo. A sentinel rejects real wallet requests, external/API calls, and POSTs.
- `gpu.spec.ts` covers the connected application against an explicit HTTP and EIP-1193 fixture, with real ethers ABI encoding, EIP-712 signatures, transaction simulation, exact approvals, signed fixture transactions, and receipt confirmation. Coverage: onboarding, session refresh, provider requests, persisted proof requests, native-pending versus cash/debt, bound borrow and direct repay, faucet/deposit/withdraw/partial queue/cancel/claim/recovery, role/version/idempotency checks, wrong-chain and wallet changes, quote minimums, wallet rejection, simulation revert, responsive overflow, keyboard focus confinement.

Fixture balances and receipts are simulated; they are not contract, native-testnet, partner, or cash evidence. Screenshots and traces stay under the ignored `node_modules/.cache/playwright/`.

Wallet classification recognizes exactly the 23-byte [EIP-7702](https://eips.ethereum.org/EIPS/eip-7702#delegation-indicator) delegation indicator; any other non-empty account code selects server-side ERC-1271 validation. Classification never grants a role or bypasses the server's signature and allowlist check.

## Local API + PostgreSQL interoperability (opt-in)

Three terminals:

```sh
.venv-py313/bin/python apps/web/scripts/api-review-server.py 4182
VITE_GPU_API_URL=http://127.0.0.1:4182 npm --prefix apps/web run dev -- --host 127.0.0.1 --port 4273 --strictPort
node apps/web/scripts/api-review-browser.mjs
```

The server creates and migrates its own ephemeral PostgreSQL cluster and runs the real GPU API with no RPC or contract configured, so financial actions fail closed. The browser signs real login challenges with disposable public test accounts, submits real onboarding and provider requests, and verifies persistence after reload at both widths. Stopping the server removes its temporary cluster. This is LOCAL evidence only.

## Live testnet browser smoke (opt-in, real transactions)

`scripts/live-review-browser.mjs` runs real test-token transactions against a deployed environment. It is separate from CI, and its presence is not evidence that it has been run.

```sh
GPU_REVIEW_WEB_URL=… GPU_REVIEW_API_URL=… \
GPU_SMOKE_PRIVATE_KEY=<disposable test-CTC-funded key> \
GPU_ALLOW_TESTNET_TRANSACTIONS=1 \
node apps/web/scripts/live-review-browser.mjs
```

Guards: rejects non-native profiles, non-test assets, chains other than 102031, existing LP positions, native transfers, arbitrary contracts or methods, and approvals or deposits above 1 tUSD. Uses real HTTP, RPC, signatures, and two-confirmation receipts. Key and session stay in memory; output contains only public wallet, deployment, and transaction identifiers.

| Mode | Variables | Behavior |
| --- | --- | --- |
| LP (default) | as above | faucet-if-needed → 1 tUSD supply → queue/cancel → queue/fund/claim → withdraw the rest |
| LP resume | `GPU_REVIEW_RESUME_CANCELLED_REQUEST` | Resumes only an already cancelled, wallet-owned request at or below the previous 1 tUSD position; repeats no deposit |
| Borrower | `GPU_REVIEW_FLOW=borrower`, `GPU_REVIEW_FACILITY_ID`, funded borrower key | 1 tUSD borrow and a 1.001 tUSD `repayExact` cap on the API-bound facility, then checks canonical debt is zero; needs 0.001 tUSD starting balance for interest; never creates a facility or bypasses eligibility |
| Borrower repay-only | `GPU_REVIEW_RESUME_BORROWER_REPAY=1` | Repays the prior 1–1.001 tUSD debt only; rejects borrow submissions |
| Read-only | `GPU_REVIEW_READ_ONLY=1` (+ `GPU_REVIEW_EXPECT_REPAYMENT_TX`) | Blocks every submission; borrower mode checks debt 0 and, if set, a real `FINALIZED_ROUTER_EVENT` allocation with exact amounts and its activity-screen link |

RPC reads use a 12-second timeout and at most three attempts; broadcasts are never retried automatically. The helper refreshes signed sessions before expiry.

## Live persona scenarios (opt-in)

`scripts/live-scenarios.mjs` runs the catalog in [`docs/gpu/scenarios/live-user-scenarios.md`](../../../docs/gpu/scenarios/live-user-scenarios.md) against the deployed web app, API, and Creditcoin CC3 Testnet.

```sh
GPU_REVIEW_WEB_URL=https://rackline.studioliq.com \
GPU_REVIEW_API_URL=https://api-rackline.studioliq.com \
GPU_SCENARIO_KEYS=../../keys/gpu-native-testnet.json \
GPU_SCENARIO_OUT=../../evidence/native-testnet/scenarios-<date>.json \
node scripts/live-scenarios.mjs
```

Without further flags every scenario is read-only or API-only (public pages, demo isolation, manifest and code-hash binding, unauthenticated access, wrong-chain/bad-signature/nonce-replay sign-in, unknown-wallet empty state, LP parity, over-withdraw guards, blocked draws, onboarding and connection requests for a fresh disposable wallet, foreign proof requests, staff-scope denials, CORS, session lifetime, read metadata).

| Flag | Adds |
| --- | --- |
| `GPU_ALLOW_TESTNET_TRANSACTIONS=1` | The real LP cycle (delegated to `live-review-browser.mjs`) |
| `GPU_SCENARIO_NATIVE_REFRESH=1` with `GPU_SCENARIO_APPROVAL=user-<date>` | New Sepolia source transitions (payout, obligation, checkpoint) through the official Attestcoin path, consumed on Creditcoin with the keeper key; verifies on-chain eligibility and the REPAID facility's draw refusal |
| `GPU_SCENARIO_ONLY=A1,B5` | Filters by scenario ID |
| `GPU_SCENARIO_MERGE=1` | Keeps prior records of filtered-out scenarios in the same output file |

Screenshots go to the ignored `node_modules/.cache/playwright/scenarios/`.

## Recorded testnet evidence (2026-09-14)

Deployment `01K54G0000QN0QHY2GCA10HGXN` on Creditcoin chain 102031, real API and PostgreSQL, faucet test tokens only. None of it is partner-revenue or native-proof-acceptance evidence; native acceptance is verified separately.

**LP cycle**, wallet `0xee684316539c3996855AA01415555D7f5Af3Ada6`: nine successful canonical receipts (faucet, exact 1 tUSD approval, deposit, request #1, cancel #1, request #2, fund queue, claim, withdraw remaining), each with at least 39 confirmations at the independent check. A subsequent read-only sign-in at 1440px and 390px showed finalized block 5484451, LP position 0 tUSD, wallet 10,000 tUSD, nothing unfilled or claimable, no page errors or horizontal overflow. Two earlier runs stopped at a between-step lookup; on-chain state was checked before resuming the exact cancelled request, and no deposit or earlier request was repeated. Receipts and hashes: [`evidence/native-testnet/lp-browser-20260914.json`](../../../evidence/native-testnet/lp-browser-20260914.json).

**Borrower cycle**, wallet `0x42E46697957766fFad9b7f55621260f99Dc204B7`, facility `5DCNY1D03WP51EAK4V024YB60F`: [borrow 1 tUSD](https://creditcoin-testnet.blockscout.com/tx/0x7f70742f267233e7195edec63635cc71bd80167f9e896f1f225f21f485c403ee), [approve a 1.001 tUSD cap](https://creditcoin-testnet.blockscout.com/tx/0x649813a3a7e99497bf7bf56e93073f984281a1689e840921a80304bc6eb8cf75), [repay exact execution debt](https://creditcoin-testnet.blockscout.com/tx/0xa369810d67bb59695e7acc87d4163d1a1257876d6fba28635ee154dd1bc2fe78). `RepaymentRouter.Repaid` (log 13) records principal 1 tUSD, interest 0.000002 tUSD, no excess, debt 0; the unused cap was not transferred. After finalized-event cash reconciliation a read-only session verified `repaymentApplied=true`, `applicationEvidence=FINALIZED_ROUTER_EVENT`, exact allocation amounts, and the transaction link in the Activity screen at both widths. Interruptions (indexer watermark stall after the borrow, a wallet RPC failure before approval, a timeout before the browser opened) are recorded with the on-chain checks that confirmed nothing had been submitted twice: [`evidence/native-testnet/borrower-browser-20260914.json`](../../../evidence/native-testnet/borrower-browser-20260914.json).

**Persona scenarios**: 25 passed, 0 failed, across four runs. Transaction table and gate notes: [`docs/gpu/scenarios/live-user-scenarios.md`](../../../docs/gpu/scenarios/live-user-scenarios.md); evidence: [`evidence/native-testnet/scenarios-20260914.json`](../../../evidence/native-testnet/scenarios-20260914.json).

**Vercel preview**: the protected preview built from the 106-file frontend allowlist; owner-authenticated reads confirmed `/`, `/app`, `/demo`, and scoped deep links return the app, while API, missing-asset, and key paths return 404. No preview-origin API mutation or wallet transaction was sent, and the production alias was not changed.
