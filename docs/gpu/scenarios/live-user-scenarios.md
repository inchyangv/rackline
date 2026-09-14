# Live user scenarios (TEST_ONLY deployment)

Persona-driven scenarios executed against the deployed Rackline environment:
web `https://rackline.studioliq.com`, API `https://api-rackline.studioliq.com`,
Creditcoin CC3 Testnet `102031`, deployment `01K54G0000QN0QHY2GCA10HGXN`.

Runner: `apps/web/scripts/live-scenarios.mjs`. Evidence: `evidence/native-testnet/scenarios-<date>.json`.
Every scenario records its checks, public identifiers, and transaction hashes. The runner
never logs keys or session tokens. Real transactions use faucet test tokens only.

These scenarios verify the deployed technical path. They do not claim partner GPU revenue,
production readiness, or that native proof acceptance is anything other than the
TEST_ONLY simulated source (`partnerRevenue=SIMULATED`).

## Personas

| Persona | Wallet | What they can do |
| --- | --- | --- |
| Visitor | none | Read public pages, run the fixture demo, hit public API endpoints |
| Unknown wallet | fresh random key, no gas | Sign in, see empty state, register a borrower profile |
| LP | `0xee68…Ada6` (disposable, funded) | Supply, queue, cancel, process, claim, withdraw |
| Borrower | `0x42E4…04B7` (facility `5DCNY1D03WP51EAK4V024YB60F`) | Borrow within eligibility, repay, read history |
| Operator (keeper) | `0x0013…B233` | Consume native source evidence on Creditcoin; no API staff role |
| Attacker / misuse | any | Wrong chain, bad signature, nonce replay, foreign resources |

## Scenario matrix

| ID | Persona | Scenario | Expected result | Real tx |
| --- | --- | --- | --- | --- |
| A1 | Visitor | Public pages `/`, `/app`, `/demo` render at 1440/390 | 200 HTML, no page errors, no horizontal overflow | no |
| A2 | Visitor | Fixture demo is isolated | `/demo` sends no request to the API or RPC origins | no |
| A3 | Visitor | Public API binding equals the committed manifest | `/ready` FRESH; `/v1/config` deployment/manifest/contracts match `config/gpu/deployments/cc3-testnet.json`; on-chain code hashes match | no |
| A4 | Visitor | Unauthenticated and garbage-token access | `/v1/me`, `/v1/lp`, `/v1/facilities`, `/v1/operations`, `POST /v1/onboarding` → 401 | no |
| B1 | Misuse | Wallet on Ethereum mainnet | Switch prompt; rejected switch shows an error and issues no challenge; accepted switch asks to connect again; then sign-in works | no |
| B2 | Misuse | Challenge signed by a different key | verify rejected, no session | no |
| B3 | Misuse | Nonce replay | first verify 200, identical second verify rejected | no |
| B4 | Misuse | Unknown nonce | verify rejected | no |
| B5 | Unknown wallet | First sign-in | roles `[]`, no borrower, empty facility state, LP position 0, both widths clean | no |
| C1 | LP | Read-only position parity | API `/v1/lp` equals chain (`balanceOf`, vault shares, NAV); UI shows the same position; prior withdrawal rows present | no |
| C2 | LP | Full liquidity cycle | faucet-if-needed → 1 tUSD supply → queue → cancel → queue → process → claim → withdraw rest; all receipts status 1; final shares 0 | yes (8–9) |
| C3 | LP | Over-withdraw guard | With zero shares the Withdraw/queue buttons are disabled; a static `withdraw` call reverts | no |
| D1 | Borrower | Read-only history | debt 0, facility REPAID, `Repaid` allocation `FINALIZED_ROUTER_EVENT` 1.000002 = 1 + 0.000002, activity link shown | no |
| D2 | Borrower | Draw blocked when source protection expired | `drawBlockedReason=NO_ELIGIBLE_DRAW`, on-chain `eligibleUnpaid=0`, Borrow disabled, static `borrow` reverts, repay stays available | no |
| D3 | Operator | New source transitions are proven and consumed | Sepolia `settle` (1 source tUSD by the registered payer) plus `recognizeObligation` + `assignObligation` of a new 10 tUSD obligation → official proofs → Creditcoin consumption; original `paid` +1 (a payout never renews evidence validity), a new ASSIGNED receivable with fresh validity, proof-only receipts, destination debt still 0 | yes (3 Sepolia + 3 CC3) |
| D3b | Operator | Native checkpoint refresh through the official Attestcoin path | Sepolia `reserveCheckpoint` → official proof → Creditcoin consumption; proof-only receipt (0 debt/vault mutations); consumed revision equals consumed events; on-chain `eligibleUnpaid > 0` while the checkpoint is fresh; API canonical block passes the consumption | yes (Sepolia + CC3) |
| D4 | Borrower | Re-draw on a REPAID facility | Facility state REPAID is terminal (`isTransitionAllowed(REPAID, ACTIVE) = false`); eligible receivables exist yet `availableDraw = 0`; static `borrow` reverts; API reports REPAID + blocked; UI Borrow/Repay disabled; no wallet transaction | no |
| D5 | Operator | Open an additional facility | `OpenGpuFacility.s.sol` (11 CC3 txs: agreement, book registration, `openFacility`, binding, enrolment, observation, review transitions, underwriter authorization anchor, ACTIVE); imported into the API DB with `bootstrap_native --facility-name`; a new 20 tUSD Sepolia obligation assigned to it is proven and consumed | yes (11 CC3 + 2 Sepolia + 2 CC3) |
| D6 | Borrower | Real draw and repayment on the new facility | control observation refreshed → checkpoint proven and consumed → browser borrow 1 tUSD → repay with 1.001 cap; `Repaid` log principal 1, excess 0; debt 0 on chain and in the API | yes (Sepolia + 2 CC3 + 3 wallet) |
| E1 | Unknown wallet | Borrower onboarding via the app | `POST /v1/onboarding` 201; identical replay returns the same borrower; different payload with the same key → 409; `/v1/me` shows borrower role after reconnect | no |
| E2 | New borrower | Provider connection request | `POST /v1/connections` 202 PENDING_REVIEW; visible after reload; duplicate account returns the same application | no |
| E3 | New borrower | Proof request for a foreign provider account | 404, and `/v1/proofs` stays empty | no |
| F1 | LP / borrower | Staff scopes are denied | `/v1/operations` 403, `/v1/recoveries` 403, action POST 403, another borrower's facility 403/404 | no |
| F2 | Keeper / underwriter / treasury | Staff roles are not inferred from deployment keys | `/v1/me` roles `[]` for each | no |
| G1 | Any | CORS policy | allowed origin echoed, foreign origin not echoed | no |
| G2 | Any | Session lifetime | `expiresAt − now ≤ 3600 s` | no |
| G3 | Any | Read metadata consistency | every authenticated read carries the deployment id / manifest hash; canonical block is within 60 blocks of the RPC head | no |

### Ordering and gates

- D2 runs before D3/D3b (they restore on-chain eligibility); D4 runs after D3b while the checkpoint is still fresh, so the REPAID gate is observed with live evidence. D1 is a read-only view of the completed borrow → repay cycle of 2026-09-14.
- `REPAID` is terminal. `CreditFacilityManager` moves a facility to `REPAID` when debt reaches zero and allows only `REPAID → RELEASED`. A second live draw needs a newly opened and approved facility (`SetupGpuFacility` for a new facility ID plus API bootstrap), which this suite does not perform. The control observation (`ControlRegistry.lastObservedAt`) is also older than `controlObservationMaxAge` (15 minutes) and would need a fresh operator observation before any draw.
- Two independent freshness gates control eligibility, and both were exercised: `ReceivableBook.eligibleUnpaid` requires the receivable's `evidenceValidUntil` (six hours after its last consumed recognition, assignment, or correction event; a payout does not refresh it) to be in the future, **and** a consumed checkpoint younger than `checkpointMaxAge` (15 minutes) whose revision and paid totals reconcile with consumed events. The first checkpoint-only refresh of the day was consumed and audited but left `eligibleUnpaid=0` because receivable evidence had expired at 09:33 UTC; D3 therefore recognises and assigns a new obligation before D3b refreshes the checkpoint.
- `GPU_SCENARIO_MERGE=1` lets a partial rerun (`GPU_SCENARIO_ONLY=D3,D3b,D4`) keep earlier records.

## Execution record — 2026-09-14

Consolidated evidence: [`evidence/native-testnet/scenarios-20260914.json`](../../../evidence/native-testnet/scenarios-20260914.json)
— 25 scenarios PASS, 0 FAIL, 0 SKIPPED across four runs (09:32, 10:03, 10:28, 10:57 UTC; partial reruns merged with `GPU_SCENARIO_MERGE=1`).
Two earlier checkpoint-only refreshes (Creditcoin blocks 5,485,888 and 5,486,100) were consumed and audited
proof-only but left `eligibleUnpaid = 0`; they are retained under `history` in the evidence file.

| Step | Chain | Transaction | Note |
| --- | --- | --- | --- |
| C2 approve | Creditcoin | [0xcb5cbc61…](https://creditcoin-testnet.blockscout.com/tx/0xcb5cbc61f6cd1e4e2d5470e899c87b4a50253715c34ede8c68497b6e4e3bd1a8) | block 5485798 |
| C2 deposit | Creditcoin | [0xeaf67a5d…](https://creditcoin-testnet.blockscout.com/tx/0xeaf67a5d2cc4ffba3efd448857cff254433204a808d0f7cde63c88474d81cc8d) | block 5485800 |
| C2 requestWithdrawal | Creditcoin | [0x68968e27…](https://creditcoin-testnet.blockscout.com/tx/0x68968e2768111accaba7f1cac22c7f927ed6beeefa1cc8f9118dcd62ba22c67b) | block 5485807 |
| C2 cancelWithdrawal | Creditcoin | [0xeafa872d…](https://creditcoin-testnet.blockscout.com/tx/0xeafa872d93a0f32875188905e0d699bee54f00289315611a4521f92a88959e6a) | block 5485814 |
| C2 requestWithdrawal | Creditcoin | [0x7281044f…](https://creditcoin-testnet.blockscout.com/tx/0x7281044f7f333cf164ed0478149d1576fa04508af3404b345ca22c4962b258d5) | block 5485822 |
| C2 processWithdrawals | Creditcoin | [0x17715bb9…](https://creditcoin-testnet.blockscout.com/tx/0x17715bb9850384e0d51e9f5ba2b30c72754c55e194c561e6572d2debddc9d05a) | block 5485830 |
| C2 claimWithdrawal | Creditcoin | [0x0e2a4d35…](https://creditcoin-testnet.blockscout.com/tx/0x0e2a4d3596f081dc9db11784dd3228bfa1e8a9a66101aa494b6490d8c37d1538) | block 5485837 |
| C2 withdraw | Creditcoin | [0x580dac37…](https://creditcoin-testnet.blockscout.com/tx/0x580dac3744cf02033111462702b2724309fb2a1aa9c0d6e6f217a87b8e9a470a) | block 5485845 |
| D3 settle 1 source tUSD | Sepolia | [0x06f26351…](https://sepolia.etherscan.io/tx/0x06f26351f1eb5e80348e6e657b0e41f47d0278453b901a69fcb4e83666173d43) | block 11702313 |
| D3 recognizeObligation | Sepolia | [0x92133b45…](https://sepolia.etherscan.io/tx/0x92133b4501b1134f4485edbfadbfec0c4d39b3f9f4a188b0fa7157eef5258222) | new 10 source tUSD obligation |
| D3 assignObligation | Sepolia | [0x00a0fed5…](https://sepolia.etherscan.io/tx/0x00a0fed57e54f4606e2213685c17dee5dc7e316f3b784ef00dd5b865dee72a6f) | assigned to the facility |
| D3 consume settle | Creditcoin | [0xcbf33138…](https://creditcoin-testnet.blockscout.com/tx/0xcbf3313880a1b1fe4871338e54719f94d507377336bc3e89034d249a4af12186) | block 5486052, proof-only audit PASSED |
| D3 consume recognizeObligation | Creditcoin | [0x3fb0e581…](https://creditcoin-testnet.blockscout.com/tx/0x3fb0e5816d7d9f23fea8a6304e8f982d3d802ed4ab4789236eb886da9430f0f2) | block 5486058, proof-only audit PASSED |
| D3 consume assignObligation | Creditcoin | [0x40d4a776…](https://creditcoin-testnet.blockscout.com/tx/0x40d4a77628ac61ebf1243280b6dbdf0af33fe478e6c75b2e3c1c801e63a56b3d) | block 5486064, proof-only audit PASSED |
| D3b reserveCheckpoint | Sepolia | [0x5631af3e…](https://sepolia.etherscan.io/tx/0x5631af3e72d93722b02a35ae70d89529969c7b2e88e0699c20e5f66fb7f18ded) | seq 7 |
| D3b consume reserveCheckpoint | Creditcoin | [0xd3e0afe3…](https://creditcoin-testnet.blockscout.com/tx/0xd3e0afe343241e83d95914d62bbe3a6b5059fdd6228af7fd89f706fc26ffb854) | block 5486166, eligibleUnpaid 10000000 at age 588 s |

Every real transaction used faucet test tokens. `partnerRevenue` remains `SIMULATED`; nothing here is
partner revenue, a production launch, or a live lending pool.
